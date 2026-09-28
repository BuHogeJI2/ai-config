import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const helper = fileURLToPath(new URL('./backlog.mjs', import.meta.url));

function repository(t) {
  const root = fs.mkdtempSync(path.join(fs.realpathSync(os.tmpdir()), 'backlog-test-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const repo = path.join(root, 'repo');
  fs.mkdirSync(repo);
  execFileSync('git', ['init', '--quiet', repo]);
  return { root, repo };
}

function run(cwd, ...args) {
  return execFileSync(process.execPath, [helper, ...args], { cwd, encoding: 'utf8' }).trim();
}

function item(directory, slug, fields = {}) {
  fs.mkdirSync(directory, { recursive: true });
  const metadata = { priority: 'medium', created: '2026-01-01', ...fields };
  const text = `---\n${Object.entries(metadata).map(([key, value]) => `${key}: ${value}`).join('\n')}\n---\n\n# ${slug}\n\nEvidence for ${slug}.\n`;
  fs.writeFileSync(path.join(directory, `${slug}.md`), text);
  return text;
}

function worktree(root, repo) {
  const checkout = path.join(root, 'linked');
  execFileSync('git', ['worktree', 'add', '--quiet', '--orphan', '-b', 'linked', checkout], { cwd: repo });
  return checkout;
}

test('read operations select docs without creating directories', (t) => {
  const { repo } = repository(t);
  const nested = path.join(repo, 'source');
  fs.mkdirSync(nested);
  assert.equal(run(nested, 'path'), path.join(repo, 'docs', 'backlog'));
  assert.match(run(nested, 'list'), /Backlog is empty/);
  assert.deepEqual(JSON.parse(run(nested, 'list', '--json')), []);
  assert.equal(fs.existsSync(path.join(repo, 'docs')), false);
  assert.equal(fs.existsSync(path.join(repo, '.tmp')), false);
});

test('existing .tmp selects temporary storage without creating backlog', (t) => {
  const { repo } = repository(t);
  fs.mkdirSync(path.join(repo, '.tmp'));
  assert.equal(run(repo, 'path'), path.join(repo, '.tmp', 'backlog'));
  assert.deepEqual(JSON.parse(run(repo, 'list', '--json')), []);
  assert.equal(fs.existsSync(path.join(repo, '.tmp', 'backlog')), false);
  assert.equal(fs.existsSync(path.join(repo, 'docs')), false);
});

test('existing docs backlog remains selected when .tmp appears', (t) => {
  const { repo } = repository(t);
  const directory = path.join(repo, 'docs', 'backlog');
  const text = item(directory, 'existing');
  fs.mkdirSync(path.join(repo, '.tmp'));
  assert.equal(run(repo, 'path'), directory);
  assert.equal(run(repo, 'show', 'existing'), text.trim());
  assert.deepEqual(JSON.parse(run(repo, 'list', '--json')).map((entry) => entry.slug), ['existing']);
});

test('an archive-only docs backlog remains selected', (t) => {
  const { repo } = repository(t);
  const directory = path.join(repo, 'docs', 'backlog');
  item(path.join(directory, 'resolved'), 'previous');
  fs.mkdirSync(path.join(repo, '.tmp'));
  assert.equal(run(repo, 'path'), directory);
  assert.deepEqual(JSON.parse(run(repo, 'list', '--json')), []);
});

test('conflicting storage blocks every operation without changing items', (t) => {
  const { repo } = repository(t);
  const temporary = path.join(repo, '.tmp', 'backlog');
  const documented = path.join(repo, 'docs', 'backlog');
  const first = item(temporary, 'existing');
  const second = item(documented, 'existing');
  for (const args of [['path'], ['list'], ['list', '--json'], ['show', 'existing'], ['resolve', 'existing']]) {
    const result = spawnSync(process.execPath, [helper, ...args], { cwd: repo, encoding: 'utf8' });
    assert.equal(result.status, 1);
    assert.match(result.stderr, /Conflicting backlog directories/);
    assert.equal(result.stdout, '');
  }
  assert.equal(fs.readFileSync(path.join(temporary, 'existing.md'), 'utf8'), first);
  assert.equal(fs.readFileSync(path.join(documented, 'existing.md'), 'utf8'), second);
  assert.equal(fs.existsSync(path.join(temporary, 'resolved')), false);
  assert.equal(fs.existsSync(path.join(documented, 'resolved')), false);
});

test('a file named .tmp is reported instead of used as a directory', (t) => {
  const { repo } = repository(t);
  fs.writeFileSync(path.join(repo, '.tmp'), 'existing file');
  const result = spawnSync(process.execPath, [helper, 'path'], { cwd: repo, encoding: 'utf8' });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /Expected a directory/);
});

test('linked worktrees share temporary storage from the main repository', (t) => {
  const { root, repo } = repository(t);
  const checkout = worktree(root, repo);
  fs.mkdirSync(path.join(repo, '.tmp'));
  const directory = path.join(repo, '.tmp', 'backlog');
  assert.equal(run(checkout, 'path'), directory);
  const text = item(directory, 'shared');
  assert.equal(run(checkout, 'show', 'shared'), text.trim());
  assert.equal(run(repo, 'show', 'shared'), text.trim());
});

test('docs storage belongs to the current checkout and survives .tmp appearing', (t) => {
  const { root, repo } = repository(t);
  const checkout = worktree(root, repo);
  const mainDocs = path.join(repo, 'docs', 'backlog');
  const checkoutDocs = path.join(checkout, 'docs', 'backlog');
  item(mainDocs, 'main-only');
  assert.equal(run(checkout, 'path'), checkoutDocs);
  item(checkoutDocs, 'checkout-only');
  fs.mkdirSync(path.join(repo, '.tmp'));
  assert.equal(run(checkout, 'path'), checkoutDocs);
  assert.deepEqual(JSON.parse(run(checkout, 'list', '--json')).map((entry) => entry.slug), ['checkout-only']);
  assert.deepEqual(JSON.parse(run(repo, 'list', '--json')).map((entry) => entry.slug), ['main-only']);
});

test('items sort by priority and then oldest first, with where optional', (t) => {
  const { repo } = repository(t);
  const directory = path.join(repo, 'docs', 'backlog');
  item(directory, 'medium-new', { created: '2026-09-01' });
  item(directory, 'low-old', { priority: 'low', created: '2020-01-01' });
  item(directory, 'medium-old', { created: '2025-01-01' });
  item(directory, 'high-new', { priority: 'high', created: '2026-09-28' });
  const items = JSON.parse(run(repo, 'list', '--json'));
  const expected = ['high-new', 'medium-old', 'medium-new', 'low-old'];
  assert.deepEqual(items.map((entry) => entry.slug), expected);
  assert.deepEqual(items.map((entry) => entry.where), [[], [], [], []]);
  const output = run(repo, 'list');
  for (let index = 1; index < expected.length; index++) {
    assert.ok(output.indexOf(expected[index - 1]) < output.indexOf(expected[index]));
  }
});

for (const location of ['docs', '.tmp']) {
  test(`resolution in ${location} preserves archives and unblocks dependencies`, (t) => {
    const { repo } = repository(t);
    const directory = path.join(repo, location, 'backlog');
    const text = item(directory, 'prerequisite');
    item(directory, 'dependent', { after: '[prerequisite]' });
    item(directory, 'unknown', { after: '[missing]' });
    assert.match(run(repo, 'list'), /warning: unknown lists unknown after: missing/);
    assert.equal(JSON.parse(run(repo, 'list', '--json')).find((entry) => entry.slug === 'dependent').blockedBy, 'after prerequisite');
    assert.match(run(repo, 'resolve', 'prerequisite'), /Unblocked: dependent/);
    assert.equal(fs.existsSync(path.join(directory, 'prerequisite.md')), false);
    assert.equal(fs.readFileSync(path.join(directory, 'resolved', 'prerequisite.md'), 'utf8'), text);
    assert.equal(JSON.parse(run(repo, 'list', '--json')).find((entry) => entry.slug === 'dependent').blockedBy, null);

    const recurrence = item(directory, 'prerequisite', { created: '2026-09-28' });
    const result = spawnSync(process.execPath, [helper, 'resolve', 'prerequisite'], { cwd: repo, encoding: 'utf8' });
    assert.equal(result.status, 1);
    assert.match(result.stderr, /Resolved item already exists/);
    assert.equal(fs.readFileSync(path.join(directory, 'prerequisite.md'), 'utf8'), recurrence);
    assert.equal(fs.readFileSync(path.join(directory, 'resolved', 'prerequisite.md'), 'utf8'), text);
  });
}
