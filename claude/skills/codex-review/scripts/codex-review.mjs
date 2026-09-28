#!/usr/bin/env node
import { execFileSync, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

// How a review runs (see SKILL.md "How it runs"):
//   agterm — the user already runs Codex in the other pane. Each round is a file; peer-chat.py types a
//            one-line pointer to it into Codex's composer. Codex writes answer-N.md and sends a pointer
//            back, which arrives here as a new "Chat from Codex:" prompt. Nothing blocks or polls.
//   exec   — headless `codex exec`, read-only sandbox, blocking; used outside agterm or with --exec.

const MODELS = { default: 'gpt-5.6-sol', astra: 'gpt-6-astra' };
const EFFORT = 'high';
const MAX_ROUNDS = 3;
const DEFAULT_TIMEOUT_SEC = 45 * 60;
const PEER_CHAT = process.env.PEER_CHAT || 'peer-chat.py';
const TAG = '[codex-review]';

const EXIT = { done: 0, error: 1, timeout: 2, needsUser: 3 };

function usage() {
  console.error(`usage:
  codex-review.mjs init [--astra] [--exec]
  codex-review.mjs send <dir> <round> [--timeout <sec>]
  codex-review.mjs answer <dir> <round>
  codex-review.mjs status <dir>`);
  process.exit(EXIT.error);
}

function fail(message, code = EXIT.error) {
  console.error(`codex-review: ${message}`);
  process.exit(code);
}

function git(args) {
  try {
    return execFileSync('git', args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim() || null;
  } catch {
    return null;
  }
}

// What gets reviewed: the checkout we are actually in. From a linked worktree the common dir points at
// the MAIN checkout, which would send the review to the wrong code.
const reviewTarget = () => git(['rev-parse', '--show-toplevel']);

// Where review folders live: the main repo, so one `.tmp/codex-reviews` is shared with every linked
// worktree and survives a worktree being deleted (the same choice the backlog skill makes).
function storageRoot() {
  const common = git(['rev-parse', '--path-format=absolute', '--git-common-dir']);
  if (!common) return null;
  return path.basename(common) === '.git' ? path.dirname(common) : common;
}

function timestamp() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
}

// agterm reviews always live in $TMPDIR: the reviewing Codex writes answer-N.md into the folder, and
// its workspace-write sandbox allows $TMPDIR, but not a repo it was not started in (a linked worktree's
// main checkout, or another project). macOS cleans $TMPDIR, so agterm reviews are not kept for long.
export function reviewBase(store, mode) {
  if (mode === 'agterm') return path.join(os.tmpdir(), 'agterm-peer-reviews', 'codex-reviews');
  if (store && fs.existsSync(path.join(store, '.tmp'))) return path.join(store, '.tmp', 'codex-reviews');
  return path.join(os.homedir(), '.claude', 'codex-reviews');
}

// Codex strips AGTERM_SESSION_ID from its tool environment, so any agterm variable counts; the real
// check of the other pane is peer-chat.py's, at send time.
export const insideAgterm = (env) =>
  Boolean(env.AGTERM_SESSION_ID || env.AGTERM_WINDOW_ID || env.AGTERM_ENABLED === '1');

function readMeta(dir) {
  const file = path.join(dir, 'meta.json');
  if (!fs.existsSync(file)) fail(`no meta.json in ${dir}; run init first`);
  return JSON.parse(fs.readFileSync(file, 'utf8'));
}

function writeMeta(dir, meta) {
  fs.writeFileSync(path.join(dir, 'meta.json'), JSON.stringify(meta, null, 2) + '\n');
}

const roundFile = (dir, round) => path.join(dir, `round-${round}.md`);
const answerFile = (dir, round) => path.join(dir, `answer-${round}.md`);

// `sending` covers the window in which peer-chat.py may have typed into Codex without confirming it.
// A round is never sent twice from any state: a blind re-send could make Codex review it twice.
export function sendRefusal(meta, round, answerExists) {
  const current = meta.rounds[round];
  if (current?.state === 'sending') {
    return `round ${round} delivery is unknown; read the Codex pane before doing anything, never re-send blind`;
  }
  if (current) return `round ${round} is already ${current.state}`;
  if (round > 1 && meta.rounds[round - 1]?.state !== 'answered') {
    return `round ${round - 1} has no recorded answer yet`;
  }
  if (answerExists) return `answer-${round}.md already exists; a stale answer would be taken for this round`;
  return null;
}

const AFTER_TYPING = /do not resend|submit withheld|; composer (cleared|cleanup)/;

// A round is cleared for a re-send only on positive evidence that nothing was typed. In the pinned
// peer-chat.py every handled failure after typing started names an AFTER_TYPING marker, so a handled
// `peer-chat: ` error without one (wrong pane, no split, busy composer) is a pre-write refusal. A
// signal, a traceback or missing output proves nothing and stays unknown.
export function deliveryOutcome(run) {
  if (run.error) return ['ENOENT', 'EACCES'].includes(run.error.code) ? 'unsent' : 'unknown';
  if (run.status === 0) return 'sent';
  const text = (run.stderr ?? '').trim();
  if (/delivery was confirmed/.test(text)) return 'sent';
  if (run.signal || run.status === null || !text) return 'unknown';
  if (text.includes('Traceback (most recent call last)') || AFTER_TYPING.test(text)) return 'unknown';
  if (run.status === 130) return /nothing was typed/.test(text) ? 'unsent' : 'unknown';
  const lastLine = text.split('\n').at(-1);
  return run.status === 1 && lastLine.startsWith('peer-chat: ') ? 'unsent' : 'unknown';
}

function replyInstructions(dir, round) {
  return `

## Reply instructions

This review runs through peer-chat: you are in the other pane of the user's agterm split.

1. Stay read-only. The only files you may create are the answer file below and the one-shot message
   files peer-chat.py needs to send your reply.
2. Write your full answer, in the answer format above, to this exact path. It must not exist yet; if it
   does, stop and say so in your pane instead of overwriting it.
   ${answerFile(dir, round)}
3. Then send exactly this one line back with peer-chat.py, as your peer-chat skill describes:
   ${TAG} answer ${round} ready: ${answerFile(dir, round)}
4. Send nothing else through peer-chat for this review round.
`;
}

function composeMessage(dir, meta, round) {
  const file = roundFile(dir, round);
  if (!fs.existsSync(file)) fail(`missing ${file}`);
  const header = `${TAG} round ${round}`;
  let body = fs.readFileSync(file, 'utf8').trim();
  if (!body.startsWith(header)) body = `${header}\n\n${body}`;
  if (meta.mode === 'agterm' && !body.includes('## Reply instructions')) body += replyInstructions(dir, round);
  const message = body.trimEnd() + '\n';
  fs.writeFileSync(file, message);
  return message;
}

// The answer is written by another agent into a folder it can reach, so it is checked before it is
// trusted: a regular file, right where the round said, and written after the round went out.
export function answerProblem(dir, round, sentAt) {
  const file = answerFile(dir, round);
  let stat;
  try {
    stat = fs.lstatSync(file);
  } catch {
    return `${file} does not exist yet`;
  }
  if (!stat.isFile()) return `${file} is not a regular file`;
  if (stat.size === 0) return `${file} is empty`;
  if (stat.mtimeMs + 1000 < sentAt) return `${file} is older than round ${round}`;
  return null;
}

function sendAgterm(dir, meta, round) {
  const pointer = `${TAG} round ${round}: read ${roundFile(dir, round)} and follow its reply instructions`;
  meta.rounds[round] = { state: 'sending', sentAt: Date.now() };
  writeMeta(dir, meta);

  // --queue (Tab): tested live on codex-cli 0.157.0 — an idle Codex starts it at once, a busy one
  // runs it as its own turn after the current one, instead of steering unrelated work.
  const run = spawnSync(PEER_CHAT, ['--to', 'codex', '--queue', '--stdin'], { input: pointer, encoding: 'utf8' });
  const reason = run.error
    ? `could not run ${PEER_CHAT}: ${run.error.message}`
    : (run.stderr || run.stdout || `exit ${run.status ?? run.signal}`).trim();
  const outcome = deliveryOutcome(run);
  if (outcome === 'sent') {
    meta.rounds[round].state = 'sent';
    writeMeta(dir, meta);
    console.log(`round ${round} sent to Codex; its answer arrives as a "Chat from Codex:" prompt`);
    return;
  }
  if (outcome === 'unsent') {
    delete meta.rounds[round];
    writeMeta(dir, meta);
    fail(`nothing was sent: ${reason}`, EXIT.needsUser);
  }
  fail(`delivery of round ${round} is unknown — read the Codex pane, do not re-send:\n${reason}`);
}

function sendExec(dir, meta, round, message, timeoutSec) {
  const lastMessage = path.join(dir, `answer-${round}.raw.md`);
  const common = ['-c', `model_reasoning_effort=${meta.effort}`, '--skip-git-repo-check', '--json', '-o', lastMessage];
  if (round > 1 && !meta.threadId) fail('no codex thread yet; send round 1 first');
  const args =
    round === 1
      ? ['exec', '-C', meta.cwd, '-s', 'read-only', '-m', meta.model, ...common, '-']
      : ['exec', 'resume', meta.threadId, '-c', 'sandbox_mode="read-only"', '-m', meta.model, ...common, '-'];

  meta.rounds[round] = { state: 'sending', sentAt: Date.now() };
  writeMeta(dir, meta);
  const run = spawnSync('codex', args, {
    cwd: meta.cwd,
    input: message,
    encoding: 'utf8',
    maxBuffer: 256 * 1024 * 1024,
    timeout: timeoutSec * 1000,
  });
  // A headless run owns its whole turn, so a failed one left nothing behind and may run again.
  const retryable = (text, code) => {
    delete meta.rounds[round];
    writeMeta(dir, meta);
    fail(text, code);
  };
  if (run.error?.code === 'ETIMEDOUT' || run.signal) {
    retryable(`codex exec was still running after ${timeoutSec}s and was stopped; run send again or raise --timeout`, EXIT.timeout);
  }
  if (run.status !== 0) retryable(`codex exec failed (exit ${run.status}):\n${run.stderr}`);

  if (round === 1) {
    const started = run.stdout
      .split('\n')
      .map((line) => {
        try {
          return JSON.parse(line);
        } catch {
          return null;
        }
      })
      .find((event) => event?.type === 'thread.started');
    if (!started) retryable('could not find the codex thread id in exec output');
    meta.threadId = started.thread_id;
  }
  const reply = fs.readFileSync(lastMessage, 'utf8').trim();
  fs.rmSync(lastMessage);
  fs.writeFileSync(answerFile(dir, round), reply + '\n');
  meta.rounds[round].state = 'answered';
  writeMeta(dir, meta);
  console.log(`answer saved: ${answerFile(dir, round)}\n`);
  console.log(reply);
}

function parseTimeout(args) {
  const i = args.indexOf('--timeout');
  if (i === -1) return DEFAULT_TIMEOUT_SEC;
  const seconds = Number(args[i + 1]);
  if (!Number.isFinite(seconds) || seconds <= 0) fail('--timeout takes a positive number of seconds');
  return seconds;
}

function parseRound(value) {
  const round = Number(value);
  if (!Number.isInteger(round) || round < 1 || round > MAX_ROUNDS) fail(`round must be an integer from 1 through ${MAX_ROUNDS}`);
  return round;
}

export function main(argv = process.argv.slice(2)) {
  const [command, ...args] = argv;

  if (command === 'init') {
    if (args.some((arg) => arg !== '--astra' && arg !== '--exec')) usage();
    const mode = !args.includes('--exec') && insideAgterm(process.env) ? 'agterm' : 'exec';
    const target = reviewTarget() ?? process.cwd();
    const dir = path.join(reviewBase(storageRoot(), mode), timestamp());
    fs.mkdirSync(dir, { recursive: true, mode: 0o700 });

    const meta = {
      version: 4,
      mode,
      model: mode === 'exec' && args.includes('--astra') ? MODELS.astra : MODELS.default,
      effort: EFFORT,
      cwd: target,
      threadId: null,
      rounds: {},
    };
    writeMeta(dir, meta);
    const why =
      mode === 'exec'
        ? args.includes('--exec')
          ? '--exec was given'
          : 'not running inside agterm'
        : null;
    console.log(
      JSON.stringify(
        {
          dir,
          mode,
          model: mode === 'exec' ? meta.model : 'whatever runs in the other pane',
          brief: roundFile(dir, 1),
          why,
        },
        null,
        2,
      ),
    );
    return;
  }

  if (command === 'send') {
    const [dir, roundArg] = args;
    if (!dir || !roundArg) usage();
    const round = parseRound(roundArg);
    const timeoutSec = parseTimeout(args);
    const meta = readMeta(dir);
    const refusal = sendRefusal(meta, round, fs.existsSync(answerFile(dir, round)));
    if (refusal) fail(refusal);
    const message = composeMessage(dir, meta, round);
    return meta.mode === 'exec' ? sendExec(dir, meta, round, message, timeoutSec) : sendAgterm(dir, meta, round);
  }

  if (command === 'answer') {
    const [dir, roundArg] = args;
    if (!dir || !roundArg) usage();
    const round = parseRound(roundArg);
    const meta = readMeta(dir);
    const current = meta.rounds[round];
    if (!current) fail(`round ${round} was never sent`);
    if (current.state === 'answered') fail(`round ${round} is already answered`);
    const problem = answerProblem(dir, round, current.sentAt);
    if (problem) fail(problem);
    // A reply can only come from a round Codex received, so an unknown delivery is settled by it.
    current.state = 'answered';
    writeMeta(dir, meta);
    console.log(fs.readFileSync(answerFile(dir, round), 'utf8'));
    return;
  }

  if (command === 'status') {
    const [dir] = args;
    if (!dir) usage();
    const meta = readMeta(dir);
    console.log(JSON.stringify({ mode: meta.mode, rounds: meta.rounds }, null, 2));
    return;
  }

  usage();
}

// import.meta.url is the resolved real path, so resolve argv[1] too; otherwise a call through a
// linked folder (the installed skill) silently skips main().
if (process.argv[1] && import.meta.url === pathToFileURL(fs.realpathSync(process.argv[1])).href) {
  try {
    main();
  } catch (err) {
    fail(err.stack || String(err));
  }
}
