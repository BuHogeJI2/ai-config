#!/usr/bin/env node
import { execFileSync, spawnSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

// How a review runs (see SKILL.md):
//   agterm — the user already runs Claude in the other pane. Each round is a file; Codex sends a
//            one-line pointer to it with peer-chat.py. Claude writes answer-N.md and sends a pointer
//            back, which arrives in Codex's pane as a new "Chat from Claude:" prompt.
//            Codex's sandbox blocks the agterm socket, so this helper never sends: it prepares the
//            message file, and Codex runs the one rule-allowed peer-chat.py command itself.
//   exec   — headless `claude -p` in plan mode, blocking; used outside agterm or with --exec.

const MODELS = { default: 'opus', fable: 'fable' };
const EFFORT = 'high';
const MAX_ROUNDS = 3;
const DEFAULT_TIMEOUT_SEC = 45 * 60;
const PEER_CHAT = process.env.PEER_CHAT || 'peer-chat.py';
const TAG = '[claude-review]';
const EXIT = { done: 0, error: 1, timeout: 2, needsUser: 3 };

function usage() {
  console.error(`usage:
  claude-review.mjs init [--fable] [--exec]
  claude-review.mjs send <dir> <round> [--timeout <sec>]
  claude-review.mjs sent <dir> <round>
  claude-review.mjs unsent <dir> <round>
  claude-review.mjs answer <dir> <round>
  claude-review.mjs status <dir>`);
  process.exit(EXIT.error);
}

function fail(message, code = EXIT.error) {
  console.error(`claude-review: ${message}`);
  process.exit(code);
}

function repoRoot() {
  try {
    return execFileSync('git', ['rev-parse', '--show-toplevel'], {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim();
  } catch {
    return null;
  }
}

export function rootFromCommonDir(common) {
  return path.basename(common) === '.git' ? path.dirname(common) : common;
}

function reviewStorageRoot() {
  try {
    const common = execFileSync('git', ['rev-parse', '--path-format=absolute', '--git-common-dir'], {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim();
    return rootFromCommonDir(common);
  } catch {
    return null;
  }
}

function timestamp() {
  const date = new Date();
  const pad = (value) => String(value).padStart(2, '0');
  return [
    date.getFullYear(),
    pad(date.getMonth() + 1),
    pad(date.getDate()),
    `${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`,
  ].join('-');
}

// agterm reviews always live in $TMPDIR: this Codex's sandbox writes the round files and the reviewing
// Claude writes answer-N.md, and a repo .tmp may be outside the sandbox (a linked worktree's main
// checkout) or outside the reviewer's start directory. macOS cleans $TMPDIR, so they are not kept long.
export function reviewBase(root, mode) {
  if (mode === 'agterm') return path.join(os.tmpdir(), 'agterm-peer-reviews', 'claude-reviews');
  if (root && fs.existsSync(path.join(root, '.tmp'))) return path.join(root, '.tmp', 'claude-reviews');
  return path.join(os.homedir(), '.codex', 'claude-reviews');
}

// Claude refuses a --session-id whose transcript already exists, and a failed first run may have
// written one; a retried round 1 therefore starts under a fresh id.
export function clearFailedExecRound(meta, round) {
  delete meta.rounds[round];
  if (round === 1) meta.claudeSessionId = randomUUID();
}

// Codex strips AGTERM_SESSION_ID from its tool environment, so any agterm variable counts; the real
// check of the other pane is peer-chat.py's, at send time.
export const insideAgterm = (env) =>
  Boolean(env.AGTERM_SESSION_ID || env.AGTERM_WINDOW_ID || env.AGTERM_ENABLED === '1');

function readMeta(dir) {
  const file = path.join(dir, 'meta.json');
  if (!fs.existsSync(file)) fail(`no meta.json in ${dir}; run init first`);
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (error) {
    fail(`invalid ${file}: ${error.message}`);
  }
}

function writeMeta(dir, meta) {
  fs.writeFileSync(path.join(dir, 'meta.json'), `${JSON.stringify(meta, null, 2)}\n`);
}

const roundFile = (dir, round) => path.join(dir, `round-${round}.md`);
const answerFile = (dir, round) => path.join(dir, `answer-${round}.md`);

// `sending` covers the window in which peer-chat.py may have typed into Claude without confirming it.
// A round is never sent twice from any state: a blind re-send could make Claude review it twice.
export function sendRefusal(meta, round, answerExists) {
  const current = meta.rounds[round];
  if (current?.state === 'sending') {
    return `round ${round} is being sent or its delivery is unknown; run sent or unsent for it first`;
  }
  if (current) return `round ${round} is already ${current.state}`;
  if (round > 1 && meta.rounds[round - 1]?.state !== 'answered') {
    return `round ${round - 1} has no recorded answer yet`;
  }
  if (answerExists) return `answer-${round}.md already exists; a stale answer would be taken for this round`;
  return null;
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

export function pointerMessage(dir, round) {
  return `${TAG} round ${round}: read ${roundFile(dir, round)} and follow its reply instructions`;
}

// peer-chat.py accepts only `peer-chat-<a-z0-9->.txt` names for its private spool.
export const messageName = (round) => `peer-chat-claude-review-${round}-${randomUUID().slice(0, 8)}.txt`;

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
  const message = `${body.trimEnd()}\n`;
  fs.writeFileSync(file, message);
  return message;
}

// The prepared file keeps the mode peer-chat.py gave it; writeFileSync truncates in place.
function prepareAgterm(dir, meta, round) {
  const name = messageName(round);
  const run = spawnSync(PEER_CHAT, ['--prepare-message', name], { encoding: 'utf8' });
  if (run.error) fail(`could not run ${PEER_CHAT}: ${run.error.message}`);
  if (run.status !== 0) fail(`${PEER_CHAT} --prepare-message failed: ${(run.stderr || run.stdout).trim()}`);
  let prepared;
  try {
    prepared = JSON.parse(run.stdout).messageFile;
  } catch {
    fail(`unexpected ${PEER_CHAT} --prepare-message output: ${run.stdout.trim()}`);
  }
  fs.writeFileSync(prepared, pointerMessage(dir, round));

  meta.rounds[round] = { state: 'sending', sentAt: Date.now() };
  writeMeta(dir, meta);
  console.log(JSON.stringify({ round, command: `${PEER_CHAT} --to claude --message-file ${name}` }, null, 2));
}

function claudeEnvironment() {
  const env = { ...process.env };
  delete env.CLAUDECODE;
  return env;
}

export function spawnTimedOut(run) {
  return run.error?.code === 'ETIMEDOUT';
}

export function parseJsonReply(text) {
  const parsed = JSON.parse(text);
  if (typeof parsed.result !== 'string' || !parsed.result.trim()) {
    throw new Error('Claude JSON response did not contain a non-empty result');
  }
  return parsed.result.trim();
}

function sendExec(dir, meta, round, message, timeoutSec) {
  const rawFile = path.join(dir, `answer-${round}.raw.json`);
  const common = [
    '-p',
    '--output-format', 'json',
    '--model', meta.model,
    '--effort', meta.effort,
    '--permission-mode', 'plan',
    '--permission-prompts', 'none',
    '--no-chrome',
    '--strict-mcp-config',
  ];
  const args = round === 1
    ? [...common, '--session-id', meta.claudeSessionId]
    : [...common, '--resume', meta.claudeSessionId];

  meta.rounds[round] = { state: 'sending', sentAt: Date.now() };
  writeMeta(dir, meta);
  // A headless run owns its whole turn, so a failed one can run again.
  const retryable = (text, code) => {
    clearFailedExecRound(meta, round);
    writeMeta(dir, meta);
    fail(text, code);
  };
  const run = spawnSync('claude', args, {
    cwd: meta.cwd,
    env: claudeEnvironment(),
    input: message,
    encoding: 'utf8',
    maxBuffer: 256 * 1024 * 1024,
    timeout: timeoutSec * 1000,
  });

  if (spawnTimedOut(run)) {
    fs.writeFileSync(rawFile, run.stdout || '');
    retryable(`Claude exceeded the ${timeoutSec}s exec timeout and was stopped; partial output saved to ${rawFile}`, EXIT.timeout);
  }
  if (run.error) retryable(`could not run Claude: ${run.error.message}`);
  if (run.status !== 0) {
    fs.writeFileSync(rawFile, run.stdout || '');
    retryable(`Claude exited ${run.status}:\n${run.stderr || run.stdout}`);
  }

  let reply;
  try {
    reply = parseJsonReply(run.stdout);
  } catch (error) {
    fs.writeFileSync(rawFile, run.stdout);
    retryable(`${error.message}; raw output saved to ${rawFile}`);
  }
  fs.writeFileSync(answerFile(dir, round), `${reply}\n`);
  meta.rounds[round].state = 'answered';
  writeMeta(dir, meta);
  console.log(`answer saved: ${answerFile(dir, round)}\n`);
  console.log(reply);
}

function parseTimeout(args) {
  const index = args.indexOf('--timeout');
  if (index === -1) return DEFAULT_TIMEOUT_SEC;
  const value = Number(args[index + 1]);
  if (!Number.isFinite(value) || value <= 0) fail('--timeout must be a positive number of seconds');
  return value;
}

function parseRound(value) {
  const round = Number(value);
  if (!Number.isInteger(round) || round < 1 || round > MAX_ROUNDS) {
    fail(`round must be an integer from 1 through ${MAX_ROUNDS}`);
  }
  return round;
}

function agtermRound(args) {
  const [dir, roundArg] = args;
  if (!dir || !roundArg) usage();
  const round = parseRound(roundArg);
  const meta = readMeta(dir);
  if (meta.mode !== 'agterm') fail('this command is only for agterm mode');
  return { dir, round, meta, current: meta.rounds[round] };
}

export async function main(argv = process.argv.slice(2)) {
  const [command, ...args] = argv;

  if (command === 'init') {
    if (args.some((arg) => arg !== '--fable' && arg !== '--exec')) usage();
    const mode = !args.includes('--exec') && insideAgterm(process.env) ? 'agterm' : 'exec';
    const root = repoRoot() ?? process.cwd();
    const dir = path.join(reviewBase(reviewStorageRoot() ?? root, mode), `${timestamp()}-${randomUUID().slice(0, 8)}`);
    fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
    const meta = {
      version: 4,
      mode,
      model: args.includes('--fable') ? MODELS.fable : MODELS.default,
      effort: EFFORT,
      cwd: root,
      claudeSessionId: mode === 'exec' ? randomUUID() : null,
      rounds: {},
    };
    writeMeta(dir, meta);
    console.log(JSON.stringify({
      dir,
      mode,
      model: mode === 'exec' ? meta.model : 'whatever runs in the other pane',
      brief: roundFile(dir, 1),
      why: mode === 'agterm' ? null : args.includes('--exec') ? '--exec was given' : 'not running inside agterm',
    }, null, 2));
    return;
  }

  if (command === 'send') {
    const [dir, roundArg] = args;
    if (!dir || !roundArg) usage();
    const round = parseRound(roundArg);
    const timeoutSec = parseTimeout(args); // before anything runs, so a bad value costs nothing
    const meta = readMeta(dir);
    const refusal = sendRefusal(meta, round, fs.existsSync(answerFile(dir, round)));
    if (refusal) fail(refusal);
    const message = composeMessage(dir, meta, round);
    if (meta.mode === 'exec') return sendExec(dir, meta, round, message, timeoutSec);
    return prepareAgterm(dir, meta, round);
  }

  if (command === 'sent' || command === 'unsent') {
    const { dir, round, meta, current } = agtermRound(args);
    if (current?.state !== 'sending') fail(`round ${round} is not being sent`);
    if (command === 'sent') current.state = 'sent';
    else delete meta.rounds[round];
    writeMeta(dir, meta);
    console.log(command === 'sent' ? `round ${round} recorded as sent` : `round ${round} cleared; it can be sent again`);
    return;
  }

  if (command === 'answer') {
    const { dir, round, meta, current } = agtermRound(args);
    if (!current) fail(`round ${round} was never sent`);
    if (current.state === 'answered') fail(`round ${round} is already answered`);
    const problem = answerProblem(dir, round, current.sentAt);
    if (problem) fail(problem);
    // A reply can only come from a round Claude received, so an unknown delivery is settled by it.
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
  main().catch((error) => fail(error.stack || String(error)));
}
