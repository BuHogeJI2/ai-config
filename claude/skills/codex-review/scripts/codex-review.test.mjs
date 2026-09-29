import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import { ISOLATION, reviewBase, sendRefusal } from './codex-review.mjs';

const HELPER = fileURLToPath(new URL('./codex-review.mjs', import.meta.url));

const FAKE_CODEX = `#!/usr/bin/env node
import fs from 'node:fs';
const argv = process.argv.slice(2);
const stdin = fs.readFileSync(0, 'utf8');
fs.appendFileSync(process.env.FAKE_LOG, JSON.stringify({ argv, stdin }) + '\\n');
const output = argv[argv.indexOf('-o') + 1];
const mode = process.env.FAKE_CODEX;
const thread = () => console.log(JSON.stringify({ type: 'thread.started', thread_id: 'thread-1' }));
if (mode === 'ok') { fs.writeFileSync(output, 'Answer ' + argv[0] + '\\n'); thread(); }
if (mode === 'fail') { console.error('boom'); process.exit(3); }
if (mode === 'empty') { fs.writeFileSync(output, '  \\n'); thread(); }
if (mode === 'no-output') thread();
if (mode === 'no-thread') fs.writeFileSync(output, 'Answer\\n');
if (mode === 'write-then-fail') { fs.writeFileSync(output, 'Stale answer\\n'); thread(); process.exit(1); }
if (mode === 'sleep') await new Promise((resolve) => setTimeout(resolve, 5000));
`;

const FAKE_PEER_CHAT = `#!/bin/sh
echo called >> "$FAKE_PEER_LOG"
`;

function world(t) {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'codex-review-test-')));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const bin = path.join(root, 'bin');
  const home = path.join(root, 'home');
  const repo = path.join(root, 'repo');
  for (const dir of [bin, home, repo]) fs.mkdirSync(dir);
  fs.writeFileSync(path.join(bin, 'codex'), FAKE_CODEX, { mode: 0o755 });
  fs.writeFileSync(path.join(bin, 'peer-chat.py'), FAKE_PEER_CHAT, { mode: 0o755 });
  spawnSync('git', ['init', '-q'], { cwd: repo });
  const log = path.join(root, 'codex.log');
  const peerLog = path.join(root, 'peer-chat.log');

  const run = (args, mode = 'ok') =>
    spawnSync(process.execPath, [HELPER, ...args], {
      cwd: repo,
      encoding: 'utf8',
      env: {
        ...process.env,
        PATH: `${bin}${path.delimiter}${process.env.PATH}`,
        HOME: home,
        AGTERM_ENABLED: '1',
        AGTERM_SESSION_ID: 'session',
        FAKE_CODEX: mode,
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
  return { root, home, repo, run, calls, init, meta, peerCalled: () => fs.existsSync(peerLog) };
}

const withRound = (dir, round, text = 'Follow-up.\n') => fs.writeFileSync(path.join(dir, `round-${round}.md`), text);
const rawFiles = (dir) => fs.readdirSync(dir).filter((name) => name.endsWith('.raw.md'));

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

test('reviewBase uses the main checkout .tmp when there is one, else the Claude home', (t) => {
  const repo = fs.mkdtempSync(path.join(os.tmpdir(), 'codex-review-repo-'));
  t.after(() => fs.rmSync(repo, { recursive: true, force: true }));
  assert.equal(reviewBase(repo), path.join(os.homedir(), '.claude', 'codex-reviews'));
  assert.equal(reviewBase(null), path.join(os.homedir(), '.claude', 'codex-reviews'));
  fs.mkdirSync(path.join(repo, '.tmp'));
  assert.equal(reviewBase(repo), path.join(repo, '.tmp', 'codex-reviews'));
});

test('init has no pane mode and gives each review its own folder', (t) => {
  const w = world(t);
  assert.equal(w.run(['init', '--exec']).status, 1);
  const first = w.init();
  const second = w.init();
  assert.notEqual(first, second);
  assert.equal(path.dirname(first), path.join(w.home, '.claude', 'codex-reviews'));
  assert.match(path.basename(first), /^\d{4}-\d{2}-\d{2}-\d{6}-[0-9a-f]{8}$/);
  assert.equal(w.meta(first).version, 5);
});

test('round 1 runs codex exec read-only and isolated, feeds the brief on stdin, and saves the answer', (t) => {
  const w = world(t);
  const dir = w.init();
  const result = w.run(['send', dir, '1']);
  assert.equal(result.status, 0, result.stderr);

  const [call] = w.calls();
  assert.deepEqual(call.argv.slice(0, 5), ['exec', '-C', w.repo, '-s', 'read-only']);
  assert.deepEqual(call.argv.slice(5, 5 + ISOLATION.length), ISOLATION);
  assert.ok(call.argv.includes('--json'));
  assert.equal(call.argv.at(-1), '-');
  assert.equal(call.stdin, '[codex-review] round 1\n\nReview this.\n');

  assert.equal(fs.readFileSync(path.join(dir, 'answer-1.md'), 'utf8'), 'Answer exec\n');
  assert.match(result.stdout, /Answer exec/);
  assert.equal(w.meta(dir).threadId, 'thread-1');
  assert.equal(w.meta(dir).rounds[1].state, 'answered');
  assert.deepEqual(rawFiles(dir), []);
  assert.equal(w.peerCalled(), false);
});

test('later rounds resume the thread with the same isolation', (t) => {
  const w = world(t);
  const dir = w.init();
  assert.equal(w.run(['send', dir, '1']).status, 0);
  withRound(dir, 2);
  const result = w.run(['send', dir, '2']);
  assert.equal(result.status, 0, result.stderr);

  const call = w.calls()[1];
  assert.deepEqual(call.argv.slice(0, 5), ['exec', 'resume', 'thread-1', '-c', 'sandbox_mode="read-only"']);
  assert.deepEqual(call.argv.slice(5, 5 + ISOLATION.length), ISOLATION);
  assert.equal(fs.readFileSync(path.join(dir, 'answer-2.md'), 'utf8'), 'Answer exec\n');
  assert.equal(w.peerCalled(), false);
});

test('a failed or answerless run fails, clears the round and can run again', (t) => {
  const w = world(t);
  const dir = w.init();
  const cases = [
    ['fail', /exit 3[\s\S]*boom/],
    ['empty', /without an answer/],
    ['no-output', /without an answer/],
    ['no-thread', /no thread id/],
  ];
  for (const [mode, message] of cases) {
    const result = w.run(['send', dir, '1'], mode);
    assert.equal(result.status, 1, mode);
    assert.match(result.stderr, message, mode);
    assert.deepEqual(w.meta(dir).rounds, {}, mode);
    assert.equal(w.meta(dir).threadId, null, mode);
    assert.equal(fs.existsSync(path.join(dir, 'answer-1.md')), false, mode);
  }
  assert.equal(w.run(['send', dir, '1']).status, 0);
});

test('output left by a failed attempt is never taken as the answer of a retry', (t) => {
  const w = world(t);
  const dir = w.init();
  assert.equal(w.run(['send', dir, '1'], 'write-then-fail').status, 1);
  const retry = w.run(['send', dir, '1'], 'no-output');
  assert.equal(retry.status, 1);
  assert.match(retry.stderr, /without an answer/);
  assert.equal(fs.existsSync(path.join(dir, 'answer-1.md')), false);
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

test('the helper runs when called through a linked folder whose path has spaces', () => {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'codex review link '));
  try {
    const linked = path.join(temp, 'linked scripts');
    fs.symlinkSync(path.dirname(HELPER), linked);
    const review = path.join(temp, 'review dir');
    fs.mkdirSync(review);
    const meta = { version: 5, model: 'm', threadId: null, rounds: { 1: { state: 'answered' } } };
    const metaText = JSON.stringify(meta, null, 2) + '\n';
    fs.writeFileSync(path.join(review, 'meta.json'), metaText);

    const result = spawnSync(process.execPath, [path.join(linked, 'codex-review.mjs'), 'status', review], {
      encoding: 'utf8',
    });

    assert.equal(result.status, 0, result.stderr);
    assert.deepEqual(JSON.parse(result.stdout), { model: 'm', threadId: null, rounds: meta.rounds });
    assert.equal(fs.readFileSync(path.join(review, 'meta.json'), 'utf8'), metaText);
  } finally {
    fs.rmSync(temp, { recursive: true, force: true });
  }
});
