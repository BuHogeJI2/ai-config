#!/usr/bin/env node
import { execFileSync, spawnSync } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

// Codex reviews headless: `codex exec` in a read-only sandbox, with no approvals and no integrations, so
// nobody talks to the reviewer. Each round blocks until Codex answers; later rounds resume its thread.

const MODELS = { default: 'gpt-5.6-sol', astra: 'gpt-6-astra' };
const EFFORT = 'high';
const MAX_ROUNDS = 3;
const DEFAULT_TIMEOUT_SEC = 45 * 60;
const META_VERSION = 5;
const TAG = '[codex-review]';

const EXIT = { done: 0, error: 1, timeout: 2 };

// --ignore-user-config drops config.toml, which also leaves the project untrusted, so its .codex/ layer
// (config, hooks, rules) is ignored. App-managed plugins and the account's app tools are not in
// config.toml; only the feature switches turn them off. --ignore-rules drops rules that allow commands
// outside the sandbox, such as peer-chat.py.
export const ISOLATION = [
  '-c', 'approval_policy="never"',
  '--ignore-user-config',
  '--ignore-rules',
  '-c', 'features.apps=false',
  '-c', 'features.plugins=false',
  '-c', 'features.remote_plugin=false',
  '-c', 'features.hooks=false',
];

function usage() {
  console.error(`usage:
  codex-review.mjs init [--astra]
  codex-review.mjs send <dir> <round> [--timeout <sec>]
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

export function reviewBase(store) {
  if (store && fs.existsSync(path.join(store, '.tmp'))) return path.join(store, '.tmp', 'codex-reviews');
  return path.join(os.homedir(), '.claude', 'codex-reviews');
}

function readMeta(dir) {
  const file = path.join(dir, 'meta.json');
  if (!fs.existsSync(file)) fail(`no meta.json in ${dir}; run init first`);
  let meta;
  try {
    meta = JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (error) {
    fail(`invalid ${file}: ${error.message}`);
  }
  if (meta.version !== META_VERSION) {
    fail('this review was started by an older version of the skill; run init for a new review');
  }
  return meta;
}

function writeMeta(dir, meta) {
  fs.writeFileSync(path.join(dir, 'meta.json'), JSON.stringify(meta, null, 2) + '\n');
}

const roundFile = (dir, round) => path.join(dir, `round-${round}.md`);
const answerFile = (dir, round) => path.join(dir, `answer-${round}.md`);

// A `running` round whose helper is gone (killed, or the machine slept) may still have a Codex process
// behind it; a second run of the same round could race it, so it is never started again.
export function sendRefusal(meta, round, answerExists) {
  const current = meta.rounds[round];
  if (current?.state === 'running') {
    return `round ${round} was started and never finished; if no send for it is still running, run init for a new review`;
  }
  if (current) return `round ${round} is already ${current.state}`;
  if (round > 1 && meta.rounds[round - 1]?.state !== 'answered') {
    return `round ${round - 1} has no recorded answer yet`;
  }
  if (answerExists) return `answer-${round}.md already exists; a stale answer would be taken for this round`;
  return null;
}

export function codexArgs(meta, round, outputFile) {
  const common = [...ISOLATION, '-m', meta.model, '-c', `model_reasoning_effort=${meta.effort}`, '--skip-git-repo-check', '--json', '-o', outputFile, '-'];
  return round === 1
    ? ['exec', '-C', meta.cwd, '-s', 'read-only', ...common]
    : ['exec', 'resume', meta.threadId, '-c', 'sandbox_mode="read-only"', ...common];
}

export function threadIdFrom(stdout) {
  for (const line of stdout.split('\n')) {
    let event;
    try {
      event = JSON.parse(line);
    } catch {
      continue;
    }
    if (event?.type === 'thread.started' && event.thread_id) return event.thread_id;
  }
  return null;
}

function composeMessage(dir, round) {
  const file = roundFile(dir, round);
  if (!fs.existsSync(file)) fail(`missing ${file}`);
  const header = `${TAG} round ${round}`;
  let body = fs.readFileSync(file, 'utf8').trim();
  if (!body.startsWith(header)) body = `${header}\n\n${body}`;
  const message = body + '\n';
  fs.writeFileSync(file, message);
  return message;
}

function readReply(file) {
  try {
    return fs.readFileSync(file, 'utf8').trim();
  } catch {
    return '';
  }
}

function send(dir, meta, round, timeoutSec) {
  if (round > 1 && !meta.threadId) fail('no codex thread yet; send round 1 first');
  const message = composeMessage(dir, round);
  // Each attempt reads only the file it named, so output left by a failed attempt is never taken as the
  // answer of a later one.
  const lastMessage = path.join(dir, `answer-${round}.${randomBytes(4).toString('hex')}.raw.md`);

  meta.rounds[round] = { state: 'running', startedAt: Date.now() };
  writeMeta(dir, meta);
  const retryable = (text, code) => {
    delete meta.rounds[round];
    writeMeta(dir, meta);
    fail(text, code);
  };

  const run = spawnSync('codex', codexArgs(meta, round, lastMessage), {
    cwd: meta.cwd,
    input: message,
    encoding: 'utf8',
    maxBuffer: 256 * 1024 * 1024,
    timeout: timeoutSec * 1000,
  });
  if (run.error?.code === 'ETIMEDOUT' || run.signal) {
    retryable(`codex exec was still running after ${timeoutSec}s and was stopped; run send again or raise --timeout`, EXIT.timeout);
  }
  if (run.error) retryable(`could not run codex: ${run.error.message}`);
  if (run.status !== 0) retryable(`codex exec failed (exit ${run.status}):\n${run.stderr}`);

  const threadId = round === 1 ? threadIdFrom(run.stdout) : meta.threadId;
  if (!threadId) retryable('codex exec output has no thread id; the round did not start a review');
  const reply = readReply(lastMessage);
  if (!reply) retryable(`codex exec finished without an answer; stderr:\n${run.stderr}`);
  fs.rmSync(lastMessage);

  meta.threadId = threadId;
  fs.writeFileSync(answerFile(dir, round), reply + '\n');
  meta.rounds[round] = { state: 'answered', startedAt: meta.rounds[round].startedAt };
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
    if (args.some((arg) => arg !== '--astra')) usage();
    const target = reviewTarget() ?? process.cwd();
    const dir = path.join(reviewBase(storageRoot()), `${timestamp()}-${randomBytes(4).toString('hex')}`);
    fs.mkdirSync(dir, { recursive: true, mode: 0o700 });

    const meta = {
      version: META_VERSION,
      model: args.includes('--astra') ? MODELS.astra : MODELS.default,
      effort: EFFORT,
      cwd: target,
      threadId: null,
      rounds: {},
    };
    writeMeta(dir, meta);
    console.log(JSON.stringify({ dir, model: meta.model, brief: roundFile(dir, 1) }, null, 2));
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
    return send(dir, meta, round, timeoutSec);
  }

  if (command === 'status') {
    const [dir] = args;
    if (!dir) usage();
    const meta = readMeta(dir);
    console.log(JSON.stringify({ model: meta.model, threadId: meta.threadId, rounds: meta.rounds }, null, 2));
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
