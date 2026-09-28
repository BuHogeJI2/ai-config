import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import { answerProblem, deliveryOutcome, insideAgterm, reviewBase, sendRefusal } from './codex-review.mjs';

const meta = (rounds) => ({ rounds });

test('sendRefusal allows the first round of a fresh review', () => {
  assert.equal(sendRefusal(meta({}), 1, false), null);
});

test('sendRefusal never sends a round twice', () => {
  assert.match(sendRefusal(meta({ 1: { state: 'sending' } }), 1, false), /never re-send blind/);
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

const failed = (stderr, status = 1, extra = {}) => ({ status, signal: null, stderr, ...extra });

test('deliveryOutcome clears a round only on a handled pre-write refusal', () => {
  const refusals = [
    "peer-chat: codex target pane is not running 'codex'; for a wrapper, pass --target-command NAME",
    'peer-chat: attempt 1/5 blocked; retrying in 10s: busy\npeer-chat: target composer prompt is not recognisable; nothing was typed after 5 attempts',
  ];
  for (const text of refusals) assert.equal(deliveryOutcome(failed(text)), 'unsent', text);
  assert.equal(deliveryOutcome(failed('peer-chat: interrupted: nothing was typed', 130)), 'unsent');
  assert.equal(deliveryOutcome({ error: { code: 'ENOENT' } }), 'unsent');
});

test('deliveryOutcome keeps every after-typing or unexplained failure unknown', () => {
  const afterTyping = [
    'peer-chat: message chunk 1/1 was typed but the target composer did not confirm it; submit withheld; composer cleanup failed',
    'peer-chat: target composer changed before submit; submit withheld; composer cleared',
    'peer-chat: target did not confirm submission; delivery is ambiguous; do not resend',
  ];
  for (const text of afterTyping) assert.equal(deliveryOutcome(failed(text)), 'unknown', text);
  assert.equal(deliveryOutcome(failed('peer-chat: interrupted: submission confirmation was interrupted', 130)), 'unknown');
  assert.equal(deliveryOutcome(failed('')), 'unknown');
  assert.equal(deliveryOutcome(failed('', null, { signal: 'SIGKILL' })), 'unknown');
  assert.equal(deliveryOutcome(failed('Traceback (most recent call last):\n  File "x"\nTypeError: boom')), 'unknown');
  assert.equal(deliveryOutcome({ error: { code: 'ETIMEDOUT' } }), 'unknown');
});

test('deliveryOutcome trusts a confirmed delivery', () => {
  assert.equal(deliveryOutcome({ status: 0, signal: null, stderr: '' }), 'sent');
  assert.equal(deliveryOutcome(failed('peer-chat: delivery was confirmed; do not resend; success report failed: x')), 'sent');
});

test('answerProblem accepts only a fresh regular answer file', (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'codex-review-test-'));
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

test('reviewBase always keeps agterm reviews in $TMPDIR, where the Codex sandbox can write', (t) => {
  const repo = fs.mkdtempSync(path.join(os.tmpdir(), 'codex-review-repo-'));
  t.after(() => fs.rmSync(repo, { recursive: true, force: true }));
  const shared = path.join(os.tmpdir(), 'agterm-peer-reviews', 'codex-reviews');

  assert.equal(reviewBase(repo, 'agterm'), shared);
  assert.equal(reviewBase(repo, 'exec'), path.join(os.homedir(), '.claude', 'codex-reviews'));
  assert.equal(reviewBase(null, 'exec'), path.join(os.homedir(), '.claude', 'codex-reviews'));

  fs.mkdirSync(path.join(repo, '.tmp'));
  assert.equal(reviewBase(repo, 'agterm'), shared);
  assert.equal(reviewBase(repo, 'exec'), path.join(repo, '.tmp', 'codex-reviews'));
});

test('insideAgterm accepts any agterm variable', () => {
  assert.equal(insideAgterm({ AGTERM_SESSION_ID: 's' }), true);
  assert.equal(insideAgterm({ AGTERM_ENABLED: '1' }), true);
  assert.equal(insideAgterm({}), false);
});

test('the helper runs when called through a linked folder whose path has spaces', () => {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'codex review link '));
  try {
    const helper = fileURLToPath(new URL('./codex-review.mjs', import.meta.url));
    const linked = path.join(temp, 'linked scripts');
    fs.symlinkSync(path.dirname(helper), linked);
    const review = path.join(temp, 'review dir');
    fs.mkdirSync(review);
    const metaText = JSON.stringify({ mode: 'agterm', rounds: { 1: { state: 'sent' } } }, null, 2) + '\n';
    fs.writeFileSync(path.join(review, 'meta.json'), metaText);

    const result = spawnSync(process.execPath, [path.join(linked, 'codex-review.mjs'), 'status', review], {
      encoding: 'utf8',
    });

    assert.equal(result.status, 0, result.stderr);
    assert.deepEqual(JSON.parse(result.stdout), { mode: 'agterm', rounds: { 1: { state: 'sent' } } });
    assert.equal(fs.readFileSync(path.join(review, 'meta.json'), 'utf8'), metaText);
  } finally {
    fs.rmSync(temp, { recursive: true, force: true });
  }
});
