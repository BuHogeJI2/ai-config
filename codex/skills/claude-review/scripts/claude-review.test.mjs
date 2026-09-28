import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import {
  answerProblem,
  clearFailedExecRound,
  insideAgterm,
  messageName,
  parseJsonReply,
  pointerMessage,
  reviewBase,
  rootFromCommonDir,
  sendRefusal,
  spawnTimedOut,
} from './claude-review.mjs';

const meta = (rounds) => ({ rounds });

test('sendRefusal allows the first round of a fresh review', () => {
  assert.equal(sendRefusal(meta({}), 1, false), null);
});

test('sendRefusal never sends a round twice', () => {
  assert.match(sendRefusal(meta({ 1: { state: 'sending' } }), 1, false), /sent or unsent/);
  assert.match(sendRefusal(meta({ 1: { state: 'sent' } }), 1, false), /already sent/);
  assert.match(sendRefusal(meta({ 1: { state: 'answered' } }), 1, false), /already answered/);
});

test('sendRefusal keeps rounds in order', () => {
  assert.match(sendRefusal(meta({ 1: { state: 'sent' } }), 2, false), /round 1 has no recorded answer/);
  assert.equal(sendRefusal(meta({ 1: { state: 'answered' } }), 2, false), null);
});

test('sendRefusal refuses when a stale answer file is already there', () => {
  assert.match(sendRefusal(meta({}), 1, true), /already exists/);
});

test('answerProblem accepts only a fresh regular answer file', (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'claude-review-test-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const file = path.join(dir, 'answer-1.md');

  assert.match(answerProblem(dir, 1, Date.now()), /does not exist/);

  fs.writeFileSync(file, '');
  assert.match(answerProblem(dir, 1, Date.now()), /empty/);

  fs.writeFileSync(file, 'No findings\n');
  assert.equal(answerProblem(dir, 1, Date.now() - 5000), null);

  const old = new Date(Date.now() - 60_000);
  fs.utimesSync(file, old, old);
  assert.match(answerProblem(dir, 1, Date.now()), /older than round 1/);

  fs.rmSync(file);
  fs.symlinkSync('/etc/hosts', file);
  assert.match(answerProblem(dir, 1, 0), /not a regular file/);
});

test('reviewBase always keeps agterm reviews in $TMPDIR, where both agents can write', (t) => {
  const repo = fs.mkdtempSync(path.join(os.tmpdir(), 'claude-review-repo-'));
  t.after(() => fs.rmSync(repo, { recursive: true, force: true }));
  const shared = path.join(os.tmpdir(), 'agterm-peer-reviews', 'claude-reviews');

  assert.equal(reviewBase(repo, 'agterm'), shared);
  assert.equal(reviewBase(repo, 'exec'), path.join(os.homedir(), '.codex', 'claude-reviews'));

  fs.mkdirSync(path.join(repo, '.tmp'));
  assert.equal(reviewBase(repo, 'agterm'), shared);
  assert.equal(reviewBase(repo, 'exec'), path.join(repo, '.tmp', 'claude-reviews'));
});

test('clearFailedExecRound gives a retried round 1 a fresh Claude session id', () => {
  const meta = { claudeSessionId: 'first', rounds: { 1: { state: 'sending' } } };
  clearFailedExecRound(meta, 1);
  assert.deepEqual(meta.rounds, {});
  assert.notEqual(meta.claudeSessionId, 'first');
  assert.match(meta.claudeSessionId, /^[0-9a-f-]{36}$/);
});

test('clearFailedExecRound keeps the session of a later round, which resumes it', () => {
  const meta = { claudeSessionId: 'first', rounds: { 1: { state: 'answered' }, 2: { state: 'sending' } } };
  clearFailedExecRound(meta, 2);
  assert.deepEqual(meta.rounds, { 1: { state: 'answered' } });
  assert.equal(meta.claudeSessionId, 'first');
});

test('insideAgterm accepts any agterm variable, since Codex strips the session id', () => {
  assert.equal(insideAgterm({ AGTERM_WINDOW_ID: 'w' }), true);
  assert.equal(insideAgterm({ AGTERM_ENABLED: '1' }), true);
  assert.equal(insideAgterm({ AGTERM_SESSION_ID: 's' }), true);
  assert.equal(insideAgterm({}), false);
});

test('pointerMessage names only the round file', () => {
  assert.equal(
    pointerMessage('/r/claude-reviews/x', 2),
    '[claude-review] round 2: read /r/claude-reviews/x/round-2.md and follow its reply instructions',
  );
});

test('messageName matches what peer-chat.py accepts', () => {
  assert.match(messageName(1), /^peer-chat-[a-z0-9][a-z0-9-]{2,48}\.txt$/);
});

test('rootFromCommonDir maps a normal .git directory to its checkout', () => {
  assert.equal(rootFromCommonDir('/repo/.git'), '/repo');
  assert.equal(rootFromCommonDir('/repo/shared-git-dir'), '/repo/shared-git-dir');
});

test('parseJsonReply extracts the Claude result', () => {
  assert.equal(parseJsonReply(JSON.stringify({ result: ' No findings\n' })), 'No findings');
});

test('parseJsonReply rejects missing results', () => {
  assert.throws(() => parseJsonReply('{"result":""}'), /non-empty result/);
});

test('spawnTimedOut recognizes Node spawn timeout errors', () => {
  assert.equal(spawnTimedOut({ error: { code: 'ETIMEDOUT' } }), true);
  assert.equal(spawnTimedOut({ status: 1 }), false);
});

test('the helper runs when called through a linked folder', () => {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'claude-review-link-'));
  try {
    const helper = fileURLToPath(new URL('./claude-review.mjs', import.meta.url));
    fs.symlinkSync(path.dirname(helper), path.join(temp, 'linked'));
    const result = spawnSync(process.execPath, [path.join(temp, 'linked', 'claude-review.mjs')], { encoding: 'utf8' });
    assert.equal(result.status, 1);
    assert.match(result.stdout + result.stderr, /usage:/);
  } finally {
    fs.rmSync(temp, { recursive: true, force: true });
  }
});
