import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import {
  buildGuidance,
  clearFailedExecRound,
  parseJsonReply,
  reviewBase,
  rootFromCommonDir,
  sendRefusal,
} from './claude-review.mjs';

const HELPER = fileURLToPath(new URL('./claude-review.mjs', import.meta.url));

const FAKE_CLAUDE = `#!/usr/bin/env node
import fs from 'node:fs';
const argv = process.argv.slice(2);
const stdin = fs.readFileSync(0, 'utf8');
fs.appendFileSync(process.env.FAKE_LOG, JSON.stringify({ argv, stdin, claudecode: process.env.CLAUDECODE ?? null }) + '\\n');
const result = (fields) => console.log(JSON.stringify({ type: 'result', subtype: 'success', is_error: false, result: 'Answer', permission_denials: [], ...fields }));
const mode = process.env.FAKE_CLAUDE;
if (mode === 'ok') result({});
if (mode === 'denied') result({ permission_denials: [{ tool_name: 'Read', tool_use_id: 't', tool_input: {} }] });
if (mode === 'is-error') result({ is_error: true, result: 'Not logged in' });
if (mode === 'max-turns') result({ subtype: 'error_max_turns', result: '' });
if (mode === 'empty') result({ result: '  ' });
if (mode === 'not-json') console.log('garbage');
if (mode === 'fail') { console.error('network down'); process.exit(2); }
if (mode === 'sleep') await new Promise((resolve) => setTimeout(resolve, 5000));
`;

const FAKE_PEER_CHAT = `#!/bin/sh
echo called >> "$FAKE_PEER_LOG"
`;

function world(t) {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'claude-review-test-')));
  t.after(() => {
    unlock(root);
    fs.rmSync(root, { recursive: true, force: true });
  });
  const bin = path.join(root, 'bin');
  const home = path.join(root, 'home');
  const repo = path.join(root, 'repo');
  for (const dir of [bin, home, repo]) fs.mkdirSync(dir);
  fs.writeFileSync(path.join(bin, 'claude'), FAKE_CLAUDE, { mode: 0o755 });
  fs.writeFileSync(path.join(bin, 'peer-chat.py'), FAKE_PEER_CHAT, { mode: 0o755 });
  spawnSync('git', ['init', '-q'], { cwd: repo });
  const log = path.join(root, 'claude.log');
  const peerLog = path.join(root, 'peer-chat.log');

  const run = (args, mode = 'ok') =>
    spawnSync(process.execPath, [HELPER, ...args], {
      cwd: repo,
      encoding: 'utf8',
      env: {
        ...process.env,
        PATH: `${bin}${path.delimiter}${process.env.PATH}`,
        HOME: home,
        CODEX_HOME: path.join(home, '.codex'),
        CLAUDE_CONFIG_DIR: path.join(home, '.claude'),
        CLAUDECODE: '1',
        AGTERM_ENABLED: '1',
        AGTERM_WINDOW_ID: 'window',
        FAKE_CLAUDE: mode,
        FAKE_LOG: log,
        FAKE_PEER_LOG: peerLog,
      },
    });
  const calls = () =>
    fs.existsSync(log) ? fs.readFileSync(log, 'utf8').trim().split('\n').map((line) => JSON.parse(line)) : [];
  const init = () => {
    const result = run(['init']);
    assert.equal(result.status, 0, result.stderr);
    const { dir } = JSON.parse(result.stdout);
    fs.writeFileSync(path.join(dir, 'round-1.md'), 'Review this.\n');
    return dir;
  };
  const meta = (dir) => JSON.parse(fs.readFileSync(path.join(dir, 'meta.json'), 'utf8'));
  const write = (file, text) => {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, text);
  };
  return { root, home, repo, run, calls, init, meta, write, peerCalled: () => fs.existsSync(peerLog) };
}

const flagValue = (argv, flag) => argv[argv.indexOf(flag) + 1];

function unlock(dir) {
  try {
    fs.chmodSync(dir, 0o755);
    for (const name of fs.readdirSync(dir)) {
      const full = path.join(dir, name);
      const stat = fs.lstatSync(full);
      if (stat.isDirectory()) unlock(full);
      else if (stat.isFile()) fs.chmodSync(full, 0o644);
    }
  } catch {}
}

test('sendRefusal allows the first round of a fresh review', () => {
  assert.equal(sendRefusal({ rounds: {} }, 1, false), null);
});

test('sendRefusal never runs a round twice', () => {
  assert.match(sendRefusal({ rounds: { 1: { state: 'running' } } }, 1, false), /never finished/);
  assert.match(sendRefusal({ rounds: { 1: { state: 'answered' } } }, 1, false), /already answered/);
});

test('sendRefusal keeps rounds in order', () => {
  assert.match(sendRefusal({ rounds: { 1: { state: 'running' } } }, 2, false), /round 1 has no recorded answer/);
  assert.equal(sendRefusal({ rounds: { 1: { state: 'answered' } } }, 2, false), null);
});

test('sendRefusal refuses when a stale answer file is already there', () => {
  assert.match(sendRefusal({ rounds: {} }, 1, true), /already exists/);
});

test('reviewBase uses the main checkout .tmp when there is one, else the Codex home', (t) => {
  const repo = fs.mkdtempSync(path.join(os.tmpdir(), 'claude-review-repo-'));
  t.after(() => fs.rmSync(repo, { recursive: true, force: true }));
  assert.equal(reviewBase(repo, { CODEX_HOME: '/codex' }), path.join('/codex', 'claude-reviews'));
  assert.equal(reviewBase(null, {}), path.join(os.homedir(), '.codex', 'claude-reviews'));
  fs.mkdirSync(path.join(repo, '.tmp'));
  assert.equal(reviewBase(repo, { CODEX_HOME: '/codex' }), path.join(repo, '.tmp', 'claude-reviews'));
});

test('clearFailedExecRound gives a retried round 1 a fresh Claude session id', () => {
  const meta = { claudeSessionId: 'first', rounds: { 1: { state: 'running' } } };
  clearFailedExecRound(meta, 1);
  assert.deepEqual(meta.rounds, {});
  assert.match(meta.claudeSessionId, /^[0-9a-f-]{36}$/);
});

test('clearFailedExecRound keeps the session of a later round, which resumes it', () => {
  const meta = { claudeSessionId: 'first', rounds: { 1: { state: 'answered' }, 2: { state: 'running' } } };
  clearFailedExecRound(meta, 2);
  assert.deepEqual(meta.rounds, { 1: { state: 'answered' } });
  assert.equal(meta.claudeSessionId, 'first');
});

test('rootFromCommonDir maps a normal .git directory to its checkout', () => {
  assert.equal(rootFromCommonDir('/repo/.git'), '/repo');
  assert.equal(rootFromCommonDir('/repo/shared-git-dir'), '/repo/shared-git-dir');
});

test('parseJsonReply accepts only a successful result with text', () => {
  const reply = (fields) => JSON.stringify({ subtype: 'success', is_error: false, result: ' No findings\n', ...fields });
  assert.equal(parseJsonReply(reply({})), 'No findings');
  assert.throws(() => parseJsonReply(reply({ is_error: true, result: 'Not logged in' })), /reported an error: Not logged in/);
  assert.throws(() => parseJsonReply(reply({ subtype: 'error_max_turns' })), /did not finish the review/);
  assert.throws(() => parseJsonReply(reply({ result: '' })), /non-empty result/);
  assert.throws(() => parseJsonReply('garbage'));
});

test('parseJsonReply keeps denied tool calls visible in the answer', () => {
  const text = JSON.stringify({ subtype: 'success', is_error: false, result: 'Answer', permission_denials: [{}, {}] });
  assert.equal(parseJsonReply(text), 'Note: the reviewer was denied 2 tool calls; the review may be incomplete.\n\nAnswer');
});

test('init has no pane mode and gives each review its own folder', (t) => {
  const w = world(t);
  assert.equal(w.run(['init', '--exec']).status, 1);
  const first = w.init();
  const second = w.init();
  assert.notEqual(first, second);
  assert.equal(path.dirname(first), path.join(w.home, '.codex', 'claude-reviews'));
  assert.equal(w.meta(first).version, 5);
});

test('round 1 runs Claude with read tools only, fenced and isolated, and saves the answer', (t) => {
  const w = world(t);
  const dir = w.init();
  const result = w.run(['send', dir, '1']);
  assert.equal(result.status, 0, result.stderr);

  const [call] = w.calls();
  assert.equal(flagValue(call.argv, '--tools'), 'Read,Glob,Grep');
  assert.equal(flagValue(call.argv, '--add-dir'), dir);
  assert.equal(flagValue(call.argv, '--permission-mode'), 'plan');
  assert.equal(flagValue(call.argv, '--permission-prompts'), 'none');
  assert.equal(flagValue(call.argv, '--session-id'), w.meta(dir).claudeSessionId);
  for (const flag of ['-p', '--restricted', '--disable-slash-commands', '--strict-mcp-config', '--no-chrome']) {
    assert.ok(call.argv.includes(flag), flag);
  }
  assert.ok(!call.argv.join(' ').includes('Bash'));
  assert.equal(call.claudecode, null);
  assert.equal(
    call.stdin,
    `[claude-review] round 1\n\nBefore anything else, read ${path.join(dir, 'guidance.md')}: it holds your instructions for this review.\n\nReview this.\n`,
  );

  assert.equal(fs.readFileSync(path.join(dir, 'answer-1.md'), 'utf8'), 'Answer\n');
  assert.equal(w.meta(dir).rounds[1].state, 'answered');
  assert.equal(w.peerCalled(), false);
});

test('later rounds resume the session with the same flags and no new guidance', (t) => {
  const w = world(t);
  const dir = w.init();
  assert.equal(w.run(['send', dir, '1']).status, 0);
  fs.writeFileSync(path.join(dir, 'guidance.md'), 'kept\n');
  fs.writeFileSync(path.join(dir, 'round-2.md'), 'Follow-up.\n');
  const result = w.run(['send', dir, '2']);
  assert.equal(result.status, 0, result.stderr);

  const call = w.calls()[1];
  assert.equal(flagValue(call.argv, '--resume'), w.meta(dir).claudeSessionId);
  assert.ok(!call.argv.includes('--session-id'));
  assert.ok(call.argv.includes('--restricted'));
  assert.equal(call.stdin, '[claude-review] round 2\n\nFollow-up.\n');
  assert.equal(fs.readFileSync(path.join(dir, 'guidance.md'), 'utf8'), 'kept\n');
});

test('a failed or unusable result fails, clears the round and can run again', (t) => {
  const w = world(t);
  const dir = w.init();
  const cases = [
    ['fail', /exited 2[\s\S]*network down[\s\S]*not logged in/],
    ['is-error', /reported an error: Not logged in/],
    ['max-turns', /did not finish the review/],
    ['empty', /non-empty result/],
    ['not-json', /raw output saved/],
  ];
  for (const [mode, message] of cases) {
    const before = w.meta(dir).claudeSessionId;
    const result = w.run(['send', dir, '1'], mode);
    assert.equal(result.status, 1, mode);
    assert.match(result.stderr, message, mode);
    assert.deepEqual(w.meta(dir).rounds, {}, mode);
    assert.notEqual(w.meta(dir).claudeSessionId, before, mode);
    assert.equal(fs.existsSync(path.join(dir, 'answer-1.md')), false, mode);
  }
  assert.equal(w.run(['send', dir, '1']).status, 0);
  assert.equal(fs.existsSync(path.join(dir, 'answer-1.raw.json')), false);
});

test('a result with denied tool calls is saved with a note', (t) => {
  const w = world(t);
  const dir = w.init();
  assert.equal(w.run(['send', dir, '1'], 'denied').status, 0);
  assert.match(fs.readFileSync(path.join(dir, 'answer-1.md'), 'utf8'), /^Note: the reviewer was denied 1 tool call;/);
});

test('a run past the timeout is stopped with exit 2 and can run again', (t) => {
  const w = world(t);
  const dir = w.init();
  const result = w.run(['send', dir, '1', '--timeout', '1'], 'sleep');
  assert.equal(result.status, 2);
  assert.match(result.stderr, /still running after 1s/);
  assert.deepEqual(w.meta(dir).rounds, {});
});

test('a review started by the old helper is refused', (t) => {
  const w = world(t);
  const dir = w.init();
  fs.writeFileSync(path.join(dir, 'meta.json'), JSON.stringify({ version: 4, mode: 'agterm', rounds: {} }));
  const result = w.run(['send', dir, '1']);
  assert.equal(result.status, 1);
  assert.match(result.stderr, /older version of the skill; run init/);
  assert.deepEqual(w.calls(), []);
});

test('guidance.md copies user sources before project ones, with scope, path and frontmatter', (t) => {
  const w = world(t);
  const claudeHome = path.join(w.home, '.claude');
  w.write(path.join(claudeHome, 'CLAUDE.md'), 'User rule.\n');
  w.write(path.join(claudeHome, 'rules', 'b.md'), 'User rule b.\n');
  w.write(path.join(claudeHome, 'rules', 'nested', 'a.md'), 'Nested user rule.\n');
  w.write(path.join(w.repo, 'CLAUDE.md'), 'Project rule.\n');
  w.write(path.join(w.repo, 'CLAUDE.local.md'), 'Local rule.\n');
  w.write(path.join(w.repo, '.claude', 'rules', 'area', 'api.md'), '---\npaths:\n  - "src/api/**"\n---\nAPI rule.\n');

  const { text, unreadable } = buildGuidance(claudeHome, w.repo);
  assert.deepEqual(unreadable, []);
  const headings = text.split('\n').filter((line) => line.startsWith('## '));
  assert.deepEqual(headings, [
    `## user: ${path.join(claudeHome, 'CLAUDE.md')}`,
    `## user: ${path.join(claudeHome, 'rules', 'b.md')}`,
    `## user: ${path.join(claudeHome, 'rules', 'nested', 'a.md')}`,
    `## project: ${path.join(w.repo, 'CLAUDE.md')}`,
    `## project: ${path.join(w.repo, 'CLAUDE.local.md')}`,
    `## project: ${path.join(w.repo, '.claude', 'rules', 'area', 'api.md')}`,
  ]);
  assert.match(text, /---\npaths:\n {2}- "src\/api\/\*\*"\n---\nAPI rule\./);
  assert.match(text, /applies only to files matching those paths/);
});

test('guidance.md includes a project rule even without a project CLAUDE.md', (t) => {
  const w = world(t);
  w.write(path.join(w.repo, '.claude', 'rules', 'security.md'), 'Security rule.\n');
  const { text } = buildGuidance(path.join(w.home, '.claude'), w.repo);
  assert.match(text, /## project: .*security\.md\n\nSecurity rule\./);
});

test('guidance.md skips missing sources and lists unreadable ones', (t) => {
  const w = world(t);
  const claudeHome = path.join(w.home, '.claude');
  const secret = path.join(claudeHome, 'rules', 'locked.md');
  w.write(secret, 'Locked.\n');
  fs.chmodSync(secret, 0o000);
  const { text, unreadable } = buildGuidance(claudeHome, w.repo);
  assert.equal(unreadable.length, 1);
  assert.match(unreadable[0], /locked\.md/);
  assert.match(text, /could not be read, so this copy is incomplete:\n- .*locked\.md/);
  assert.match(text, /No instruction files were found/);
  assert.ok(!text.includes('CLAUDE.local.md'));
});

test('guidance.md lists locked rule folders instead of treating them as missing', (t) => {
  const w = world(t);
  const claudeHome = path.join(w.home, '.claude');
  w.write(path.join(claudeHome, 'rules', 'ok.md'), 'Readable rule.\n');
  w.write(path.join(claudeHome, 'rules', 'nested', 'hidden.md'), 'Hidden rule.\n');
  w.write(path.join(w.repo, '.claude', 'rules', 'project.md'), 'Project rule.\n');
  fs.chmodSync(path.join(claudeHome, 'rules', 'nested'), 0o000);
  fs.chmodSync(path.join(w.repo, '.claude', 'rules'), 0o000);

  const { text, unreadable } = buildGuidance(claudeHome, w.repo);
  assert.equal(unreadable.length, 2);
  assert.match(unreadable[0], /rules[/\\]nested \(EACCES\)/);
  assert.match(unreadable[1], /\.claude[/\\]rules \(EACCES\)/);
  assert.match(text, /could not be read, so this copy is incomplete/);
  assert.match(text, /Readable rule\./);
  assert.ok(!text.includes('No instruction files were found'));
});

test('guidance.md reports a FIFO source instead of hanging', (t) => {
  const w = world(t);
  const claudeHome = path.join(w.home, '.claude');
  fs.mkdirSync(path.join(claudeHome, 'rules'), { recursive: true });
  for (const fifo of [path.join(claudeHome, 'rules', 'pipe.md'), path.join(w.repo, 'CLAUDE.md')]) {
    assert.equal(spawnSync('mkfifo', [fifo]).status, 0);
  }
  const { unreadable } = buildGuidance(claudeHome, w.repo);
  assert.deepEqual(unreadable, [
    `${path.join(claudeHome, 'rules', 'pipe.md')} (not a regular file)`,
    `${path.join(w.repo, 'CLAUDE.md')} (not a regular file)`,
  ]);
});

test('guidance.md reads a rule through a symlink to a regular file', (t) => {
  const w = world(t);
  const claudeHome = path.join(w.home, '.claude');
  w.write(path.join(w.root, 'shared.md'), 'Shared rule.\n');
  fs.mkdirSync(path.join(claudeHome, 'rules'), { recursive: true });
  fs.symlinkSync(path.join(w.root, 'shared.md'), path.join(claudeHome, 'rules', 'shared.md'));
  const { text, unreadable } = buildGuidance(claudeHome, w.repo);
  assert.deepEqual(unreadable, []);
  assert.match(text, /Shared rule\./);
});

test('send writes guidance.md before every round-1 attempt and warns about unreadable sources', (t) => {
  const w = world(t);
  const dir = w.init();
  const rule = path.join(w.home, '.claude', 'rules', 'shared.md');
  w.write(rule, 'First version.\n');
  assert.equal(w.run(['send', dir, '1'], 'fail').status, 1);
  assert.match(fs.readFileSync(path.join(dir, 'guidance.md'), 'utf8'), /First version\./);

  w.write(rule, 'Second version.\n');
  fs.chmodSync(path.join(w.home, '.claude', 'rules'), 0o755);
  w.write(path.join(w.home, '.claude', 'rules', 'locked.md'), 'Locked.\n');
  fs.chmodSync(path.join(w.home, '.claude', 'rules', 'locked.md'), 0o000);
  const result = w.run(['send', dir, '1']);
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stderr, /warning: could not read .*locked\.md/);
  const guidance = fs.readFileSync(path.join(dir, 'guidance.md'), 'utf8');
  assert.match(guidance, /Second version\./);
  assert.equal(w.calls()[1].stdin.match(/Before anything else/g).length, 1);
});

test('the helper runs when called through a linked folder', () => {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'claude-review-link-'));
  try {
    fs.symlinkSync(path.dirname(HELPER), path.join(temp, 'linked'));
    const result = spawnSync(process.execPath, [path.join(temp, 'linked', 'claude-review.mjs')], { encoding: 'utf8' });
    assert.equal(result.status, 1);
    assert.match(result.stdout + result.stderr, /usage:/);
  } finally {
    fs.rmSync(temp, { recursive: true, force: true });
  }
});
