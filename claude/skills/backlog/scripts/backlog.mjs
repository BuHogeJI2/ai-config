#!/usr/bin/env node
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const RANK = { high: 0, medium: 1, low: 2 };

function mainRepoRoot() {
  // In a worktree, --git-common-dir points at the main repo's .git, so a
  // .tmp backlog survives the worktree being deleted.
  const common = execFileSync('git', ['rev-parse', '--path-format=absolute', '--git-common-dir'], {
    encoding: 'utf8',
  }).trim();
  return path.basename(common) === '.git' ? path.dirname(common) : common;
}

function backlogDir() {
  const sharedRoot = mainRepoRoot();
  const checkoutRoot = execFileSync('git', ['rev-parse', '--show-toplevel'], {
    encoding: 'utf8',
  }).trim();
  const temporary = path.join(sharedRoot, '.tmp', 'backlog');
  const documented = path.join(checkoutRoot, 'docs', 'backlog');
  const hasTemporary = directoryExists(temporary);
  const hasDocumented = directoryExists(documented);

  if (hasTemporary && hasDocumented) {
    throw new Error(`Conflicting backlog directories: ${temporary} and ${documented}. Choose one before continuing.`);
  }
  if (hasTemporary) return temporary;
  if (hasDocumented) return documented;
  return directoryExists(path.join(sharedRoot, '.tmp')) ? temporary : documented;
}

function directoryExists(dir) {
  if (!fs.existsSync(dir)) return false;
  if (!fs.statSync(dir).isDirectory()) throw new Error(`Expected a directory: ${dir}`);
  return true;
}

function resolvedDir() {
  return path.join(backlogDir(), 'resolved');
}

function itemFile(slug) {
  if (typeof slug !== 'string' || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug)) {
    throw new Error('Expected a kebab-case item slug (lowercase letters and digits).');
  }
  const file = path.join(backlogDir(), `${slug}.md`);
  if (!fs.existsSync(file)) throw new Error(`No such item: ${slug}`);
  return file;
}

function parseFrontmatter(text) {
  const match = /^---\n([\s\S]*?)\n---\n/.exec(text);
  const fields = {};
  if (match) {
    for (const line of match[1].split('\n')) {
      const kv = /^([A-Za-z_]+):\s*(.*)$/.exec(line);
      if (!kv) continue;
      const raw = kv[2].trim();
      fields[kv[1]] = raw.startsWith('[')
        ? raw.slice(1, -1).split(',').map((s) => s.trim().replace(/^['"]|['"]$/g, '')).filter(Boolean)
        : raw.replace(/^['"]|['"]$/g, '');
    }
  }
  const body = match ? text.slice(match[0].length) : text;
  const heading = /^#\s+(.+)$/m.exec(body);
  return { fields, title: heading ? heading[1].trim() : null };
}

function slugsIn(dir) {
  if (!fs.existsSync(dir)) return new Set();
  return new Set(
    fs.readdirSync(dir).filter((f) => f.endsWith('.md')).map((f) => f.replace(/\.md$/, '')),
  );
}

function readItems() {
  const dir = backlogDir();
  if (!fs.existsSync(dir)) return [];
  const done = slugsIn(resolvedDir());
  const open = slugsIn(dir);

  const items = fs
    .readdirSync(dir)
    .filter((f) => f.endsWith('.md'))
    .map((file) => {
      const text = fs.readFileSync(path.join(dir, file), 'utf8');
      const { fields, title } = parseFrontmatter(text);
      const slug = file.replace(/\.md$/, '');
      return {
        slug,
        file: path.join(dir, file),
        priority: fields.priority ?? 'unset',
        created: fields.created ?? '',
        where: [].concat(fields.where ?? []),
        related: [].concat(fields.related ?? []),
        after: [].concat(fields.after ?? []),
        blocked: typeof fields.blocked === 'string' ? fields.blocked : '',
        title: title ?? slug,
        lines: text.trimEnd().split('\n').length,
      };
    });

  for (const item of items) {
    // An `after:` slug stops blocking only once it is proven resolved. An
    // unknown slug keeps blocking and is reported — it is usually a typo.
    item.pendingAfter = item.after.filter((s) => !done.has(s));
    item.unknownAfter = item.after.filter((s) => !done.has(s) && !open.has(s));
    const reasons = [];
    if (item.blocked) reasons.push(item.blocked);
    if (item.pendingAfter.length) reasons.push(`after ${item.pendingAfter.join(', ')}`);
    item.blockedBy = reasons.length ? reasons.join('; ') : null;
  }

  return items.sort(
    (a, b) =>
      (RANK[a.priority] ?? 3) - (RANK[b.priority] ?? 3) || a.created.localeCompare(b.created),
  );
}

function pad(s, n) {
  return String(s).padEnd(n);
}

function printTable(rows, width, lastColumn) {
  for (const i of rows) {
    console.log(
      `${pad(i.priority, 9)}${pad(i.created || '—', 12)}${pad(i.slug, width + 2)}${lastColumn(i)}`,
    );
  }
}

function list(json) {
  const items = readItems();
  if (json) {
    process.stdout.write(JSON.stringify(items, null, 2) + '\n');
    return;
  }
  if (items.length === 0) {
    console.log(`Backlog is empty (${backlogDir()})`);
    return;
  }

  const open = items.filter((i) => !i.blockedBy);
  const blocked = items.filter((i) => i.blockedBy);
  const w = Math.max(...items.map((i) => i.slug.length), 4);

  console.log(`${pad('PRIORITY', 9)}${pad('CREATED', 12)}${pad('SLUG', w + 2)}TITLE`);
  if (open.length) printTable(open, w, (i) => i.title);
  else console.log('(every item is blocked)');

  if (blocked.length) {
    console.log(`\nBLOCKED — not startable yet`);
    console.log(`${pad('PRIORITY', 9)}${pad('CREATED', 12)}${pad('SLUG', w + 2)}BLOCKED BY`);
    printTable(blocked, w, (i) => i.blockedBy);
  }

  console.log(
    `\n${items.length} item(s), ${blocked.length} blocked, in ${backlogDir()}`,
  );

  const typos = items.filter((i) => i.unknownAfter.length);
  for (const i of typos) {
    console.log(`warning: ${i.slug} lists unknown after: ${i.unknownAfter.join(', ')}`);
  }
}

function show(slug) {
  process.stdout.write(fs.readFileSync(itemFile(slug), 'utf8'));
}

function resolve(slug) {
  const file = itemFile(slug);
  const dest = resolvedDir();
  fs.mkdirSync(dest, { recursive: true });
  const target = path.join(dest, `${slug}.md`);
  // linkSync fails on an existing target, where renameSync would silently
  // overwrite an archived item that resolved dependencies still point at.
  try {
    fs.linkSync(file, target);
  } catch (err) {
    if (err.code === 'EEXIST') throw new Error(`Resolved item already exists: ${slug}`);
    throw err;
  }
  fs.unlinkSync(file);
  console.log(`Resolved: ${slug} -> ${target}`);

  const freed = readItems().filter((i) => i.after.includes(slug) && !i.blockedBy);
  for (const i of freed) console.log(`Unblocked: ${i.slug} (${i.priority}) — ${i.title}`);
}

const [cmd, arg] = process.argv.slice(2);
try {
  if (cmd === 'list' || cmd === undefined) list(arg === '--json');
  else if (cmd === 'show') show(arg);
  else if (cmd === 'resolve') resolve(arg);
  else if (cmd === 'path') console.log(backlogDir());
  else {
    console.error('usage: backlog.mjs [list [--json] | show <slug> | resolve <slug> | path]');
    process.exit(2);
  }
} catch (err) {
  console.error(String(err.message ?? err));
  process.exit(1);
}
