#!/usr/bin/env node
import { execFileSync, spawnSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

// Claude reviews headless: `claude -p` with only Read, Glob and Grep, fenced to the checkout and the review
// folder, with no settings, hooks, MCP servers or skills, so nobody talks to the reviewer. Each round
// blocks until Claude answers; later rounds resume its session.

const MODELS = { default: 'opus', fable: 'fable' };
const EFFORT = 'high';
const MAX_ROUNDS = 3;
const DEFAULT_TIMEOUT_SEC = 45 * 60;
const META_VERSION = 5;
const TAG = '[claude-review]';
const EXIT = { done: 0, error: 1, timeout: 2 };

function usage() {
  console.error(`usage:
  claude-review.mjs init [--fable]
  claude-review.mjs send <dir> <round> [--timeout <sec>]
  claude-review.mjs status <dir>`);
  process.exit(EXIT.error);
}

function fail(message, code = EXIT.error) {
  console.error(`claude-review: ${message}`);
  process.exit(code);
}

function git(args) {
  try {
    return execFileSync('git', args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim() || null;
  } catch {
    return null;
  }
}

export function rootFromCommonDir(common) {
  return path.basename(common) === '.git' ? path.dirname(common) : common;
}

function reviewStorageRoot() {
  const common = git(['rev-parse', '--path-format=absolute', '--git-common-dir']);
  return common ? rootFromCommonDir(common) : null;
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

export function reviewBase(root, env = process.env) {
  if (root && fs.existsSync(path.join(root, '.tmp'))) return path.join(root, '.tmp', 'claude-reviews');
  return path.join(env.CODEX_HOME || path.join(os.homedir(), '.codex'), 'claude-reviews');
}

// Claude refuses a --session-id whose transcript already exists, and a failed first run may have
// written one; a retried round 1 therefore starts under a fresh id.
export function clearFailedExecRound(meta, round) {
  delete meta.rounds[round];
  if (round === 1) meta.claudeSessionId = randomUUID();
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
  fs.writeFileSync(path.join(dir, 'meta.json'), `${JSON.stringify(meta, null, 2)}\n`);
}

const roundFile = (dir, round) => path.join(dir, `round-${round}.md`);
const answerFile = (dir, round) => path.join(dir, `answer-${round}.md`);
const guidanceFile = (dir) => path.join(dir, 'guidance.md');

// A `running` round whose helper is gone (killed, or the machine slept) may still have a Claude process
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

// --restricted ignores every settings file (so every hook) and fences the file tools to the checkout and
// --add-dir, but it also drops CLAUDE.md and the rules files; guidance.md carries those instead.
export function claudeArgs(meta, round, dir) {
  const common = [
    '-p',
    '--output-format', 'json',
    '--model', meta.model,
    '--effort', meta.effort,
    '--tools', 'Read,Glob,Grep',
    '--restricted',
    '--add-dir', dir,
    '--permission-mode', 'plan',
    '--permission-prompts', 'none',
    '--disable-slash-commands',
    '--strict-mcp-config',
    '--no-chrome',
  ];
  return round === 1 ? [...common, '--session-id', meta.claudeSessionId] : [...common, '--resume', meta.claudeSessionId];
}

// Every `.md` entry under root, sorted. A missing root is fine; any other failure to list a folder or to
// stat an entry is recorded in `unreadable`, so a partial copy never looks complete.
function markdownFiles(root, unreadable) {
  const found = [];
  const seen = new Set();
  const walk = (dir) => {
    let entries;
    try {
      const real = fs.realpathSync(dir);
      if (seen.has(real)) return;
      seen.add(real);
      entries = fs.readdirSync(dir);
    } catch (error) {
      if (!(dir === root && error.code === 'ENOENT')) unreadable.push(`${dir} (${error.code || error.message})`);
      return;
    }
    for (const name of entries) {
      const full = path.join(dir, name);
      let stat;
      try {
        stat = fs.statSync(full);
      } catch (error) {
        unreadable.push(`${full} (${error.code || error.message})`);
        continue;
      }
      if (stat.isDirectory()) walk(full);
      else if (name.endsWith('.md')) found.push(full);
    }
  };
  walk(root);
  return found.sort();
}

export function guidanceSources(claudeHome, target, unreadable = []) {
  return [
    { scope: 'user', file: path.join(claudeHome, 'CLAUDE.md') },
    ...markdownFiles(path.join(claudeHome, 'rules'), unreadable).map((file) => ({ scope: 'user', file })),
    { scope: 'project', file: path.join(target, 'CLAUDE.md') },
    { scope: 'project', file: path.join(target, '.claude', 'CLAUDE.md') },
    { scope: 'project', file: path.join(target, 'CLAUDE.local.md') },
    ...markdownFiles(path.join(target, '.claude', 'rules'), unreadable).map((file) => ({ scope: 'project', file })),
  ];
}

// Opened non-blocking and checked with fstat, so a FIFO or device named like a rule is reported instead of
// hanging the helper before Claude even starts. A symlink to a regular file is read normally.
function readSource(file) {
  let fd;
  try {
    fd = fs.openSync(file, fs.constants.O_RDONLY | fs.constants.O_NONBLOCK);
  } catch (error) {
    return error.code === 'ENOENT' ? { missing: true } : { error: error.code || error.message };
  }
  try {
    if (!fs.fstatSync(fd).isFile()) return { error: 'not a regular file' };
    return { text: fs.readFileSync(fd, 'utf8') };
  } catch (error) {
    return { error: error.code || error.message };
  } finally {
    fs.closeSync(fd);
  }
}

const GUIDANCE_PREAMBLE = `# Your instructions for this review

This session cannot load instruction files by itself, so they are copied here, user scope first and
project scope after, as Claude Code would load them. Follow them as your own instructions.

- A rule whose frontmatter has \`paths:\` applies only to files matching those paths.
- Where a project source conflicts with a user source, the project source wins.
- Not copied: CLAUDE.md files in subdirectories (read the ones in directories you review), CLAUDE.md files
  above the repository root, and \`@path\` imports inside these files (not expanded). The project
  AGENTS.md, if any, is in your working directory.
`;

// Returns the text of guidance.md and the sources that exist but could not be read.
export function buildGuidance(claudeHome, target) {
  const sections = [];
  const unreadable = [];
  for (const { scope, file } of guidanceSources(claudeHome, target, unreadable)) {
    const source = readSource(file);
    if (source.missing) continue;
    if (source.error) unreadable.push(`${file} (${source.error})`);
    else sections.push(`## ${scope}: ${file}\n\n${source.text.trimEnd()}\n`);
  }
  let text = GUIDANCE_PREAMBLE;
  if (unreadable.length) text += `\nThese sources exist but could not be read, so this copy is incomplete:\n${unreadable.map((f) => `- ${f}`).join('\n')}\n`;
  text += sections.length ? `\n${sections.join('\n')}` : '\nNo instruction files were found.\n';
  return { text, unreadable };
}

function writeGuidance(dir, meta, env) {
  const claudeHome = env.CLAUDE_CONFIG_DIR || path.join(os.homedir(), '.claude');
  const { text, unreadable } = buildGuidance(claudeHome, meta.cwd);
  fs.writeFileSync(guidanceFile(dir), text);
  for (const source of unreadable) console.error(`claude-review: warning: could not read ${source}; guidance.md is incomplete`);
}

function composeMessage(dir, round) {
  const file = roundFile(dir, round);
  if (!fs.existsSync(file)) fail(`missing ${file}`);
  const header = `${TAG} round ${round}`;
  const readFirst = `Before anything else, read ${guidanceFile(dir)}: it holds your instructions for this review.`;
  let body = fs.readFileSync(file, 'utf8').trim();
  if (body.startsWith(header)) body = body.slice(header.length).trim();
  if (round === 1 && body.startsWith(readFirst)) body = body.slice(readFirst.length).trim();
  const lines = round === 1 ? [header, readFirst, body] : [header, body];
  const message = `${lines.join('\n\n')}\n`;
  fs.writeFileSync(file, message);
  return message;
}

// A result is an answer only when Claude says it succeeded and returned text; anything else is a failure,
// never "No findings". Denied tool calls do not fail the round, but the answer says the review may be partial.
export function parseJsonReply(text) {
  const parsed = JSON.parse(text);
  if (parsed.is_error === true) throw new Error(`Claude reported an error: ${parsed.result || parsed.subtype || 'no detail'}`);
  if (parsed.subtype !== 'success') throw new Error(`Claude did not finish the review (subtype ${parsed.subtype})`);
  if (typeof parsed.result !== 'string' || !parsed.result.trim()) {
    throw new Error('Claude JSON response did not contain a non-empty result');
  }
  const denied = Array.isArray(parsed.permission_denials) ? parsed.permission_denials.length : 0;
  const note = denied ? `Note: the reviewer was denied ${denied} tool call${denied === 1 ? '' : 's'}; the review may be incomplete.\n\n` : '';
  return `${note}${parsed.result.trim()}`;
}

function claudeEnvironment() {
  const env = { ...process.env };
  delete env.CLAUDECODE;
  return env;
}

const ACCESS_HINT =
  'If Claude is not logged in or cannot reach the network (a sandbox can block both), fix that and run send again; from Codex, run send with sandbox escalation.';

function send(dir, meta, round, timeoutSec) {
  if (round === 1) writeGuidance(dir, meta, process.env);
  const message = composeMessage(dir, round);
  const rawFile = path.join(dir, `answer-${round}.raw.json`);

  meta.rounds[round] = { state: 'running', startedAt: Date.now() };
  writeMeta(dir, meta);
  const retryable = (text, code) => {
    clearFailedExecRound(meta, round);
    writeMeta(dir, meta);
    fail(text, code);
  };

  const run = spawnSync('claude', claudeArgs(meta, round, dir), {
    cwd: meta.cwd,
    env: claudeEnvironment(),
    input: message,
    encoding: 'utf8',
    maxBuffer: 256 * 1024 * 1024,
    timeout: timeoutSec * 1000,
  });

  if (run.error?.code === 'ETIMEDOUT' || run.signal) {
    fs.writeFileSync(rawFile, run.stdout || '');
    retryable(`Claude was still running after ${timeoutSec}s and was stopped; partial output saved to ${rawFile}`, EXIT.timeout);
  }
  if (run.error) retryable(`could not run Claude: ${run.error.message}`);
  if (run.status !== 0) {
    fs.writeFileSync(rawFile, run.stdout || '');
    retryable(`Claude exited ${run.status}:\n${(run.stderr || run.stdout).trim()}\n${ACCESS_HINT}`);
  }

  let reply;
  try {
    reply = parseJsonReply(run.stdout);
  } catch (error) {
    fs.writeFileSync(rawFile, run.stdout);
    retryable(`${error.message}; raw output saved to ${rawFile}\n${ACCESS_HINT}`);
  }
  fs.rmSync(rawFile, { force: true });
  fs.writeFileSync(answerFile(dir, round), `${reply}\n`);
  meta.rounds[round] = { state: 'answered', startedAt: meta.rounds[round].startedAt };
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

export function main(argv = process.argv.slice(2)) {
  const [command, ...args] = argv;

  if (command === 'init') {
    if (args.some((arg) => arg !== '--fable')) usage();
    const root = git(['rev-parse', '--show-toplevel']) ?? process.cwd();
    const dir = path.join(reviewBase(reviewStorageRoot() ?? root), `${timestamp()}-${randomUUID().slice(0, 8)}`);
    fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
    const meta = {
      version: META_VERSION,
      model: args.includes('--fable') ? MODELS.fable : MODELS.default,
      effort: EFFORT,
      cwd: root,
      claudeSessionId: randomUUID(),
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
    const timeoutSec = parseTimeout(args); // before anything runs, so a bad value costs nothing
    const meta = readMeta(dir);
    const refusal = sendRefusal(meta, round, fs.existsSync(answerFile(dir, round)));
    if (refusal) fail(refusal);
    return send(dir, meta, round, timeoutSec);
  }

  if (command === 'status') {
    const [dir] = args;
    if (!dir) usage();
    const meta = readMeta(dir);
    console.log(JSON.stringify({ model: meta.model, rounds: meta.rounds }, null, 2));
    return;
  }

  usage();
}

// import.meta.url is the resolved real path, so resolve argv[1] too; otherwise a call through a
// linked folder (the installed skill) silently skips main().
if (process.argv[1] && import.meta.url === pathToFileURL(fs.realpathSync(process.argv[1])).href) {
  try {
    main();
  } catch (error) {
    fail(error.stack || String(error));
  }
}
