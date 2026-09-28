#!/usr/bin/env node
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const RANK = { high: 0, medium: 1, low: 2 };

function mainRepoRoot() {
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

function directoryExists(directory) {
  if (!fs.existsSync(directory)) return false;
  if (!fs.statSync(directory).isDirectory()) throw new Error(`Expected a directory: ${directory}`);
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
      const field = /^([A-Za-z_]+):\s*(.*)$/.exec(line);
      if (!field) continue;
      const raw = field[2].trim();
      fields[field[1]] = raw.startsWith('[')
        ? raw.slice(1, -1).split(',').map((value) => value.trim().replace(/^['"]|['"]$/g, '')).filter(Boolean)
        : raw.replace(/^['"]|['"]$/g, '');
    }
  }
  const body = match ? text.slice(match[0].length) : text;
  const heading = /^#\s+(.+)$/m.exec(body);
  return { fields, title: heading ? heading[1].trim() : null };
}

function slugsIn(directory) {
  if (!fs.existsSync(directory)) return new Set();
  return new Set(
    fs.readdirSync(directory).filter((file) => file.endsWith('.md')).map((file) => file.replace(/\.md$/, '')),
  );
}

function readItems() {
  const directory = backlogDir();
  if (!fs.existsSync(directory)) return [];
  const done = slugsIn(resolvedDir());
  const open = slugsIn(directory);

  const items = fs
    .readdirSync(directory)
    .filter((file) => file.endsWith('.md'))
    .map((file) => {
      const text = fs.readFileSync(path.join(directory, file), 'utf8');
      const { fields, title } = parseFrontmatter(text);
      const slug = file.replace(/\.md$/, '');
      return {
        slug,
        file: path.join(directory, file),
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
    item.pendingAfter = item.after.filter((slug) => !done.has(slug));
    item.unknownAfter = item.after.filter((slug) => !done.has(slug) && !open.has(slug));
    const reasons = [];
    if (item.blocked) reasons.push(item.blocked);
    if (item.pendingAfter.length) reasons.push(`after ${item.pendingAfter.join(', ')}`);
    item.blockedBy = reasons.length ? reasons.join('; ') : null;
  }

  return items.sort(
    (first, second) =>
      (RANK[first.priority] ?? 3) - (RANK[second.priority] ?? 3) || first.created.localeCompare(second.created),
  );
}

function pad(value, width) {
  return String(value).padEnd(width);
}

function printTable(rows, width, lastColumn) {
  for (const item of rows) {
    console.log(
      `${pad(item.priority, 9)}${pad(item.created || '—', 12)}${pad(item.slug, width + 2)}${lastColumn(item)}`,
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

  const open = items.filter((item) => !item.blockedBy);
  const blocked = items.filter((item) => item.blockedBy);
  const width = Math.max(...items.map((item) => item.slug.length), 4);

  console.log(`${pad('PRIORITY', 9)}${pad('CREATED', 12)}${pad('SLUG', width + 2)}TITLE`);
  if (open.length) printTable(open, width, (item) => item.title);
  else console.log('(every item is blocked)');

  if (blocked.length) {
    console.log('\nBLOCKED — not startable yet');
    console.log(`${pad('PRIORITY', 9)}${pad('CREATED', 12)}${pad('SLUG', width + 2)}BLOCKED BY`);
    printTable(blocked, width, (item) => item.blockedBy);
  }

  console.log(`\n${items.length} item(s), ${blocked.length} blocked, in ${backlogDir()}`);

  const typos = items.filter((item) => item.unknownAfter.length);
  for (const item of typos) {
    console.log(`warning: ${item.slug} lists unknown after: ${item.unknownAfter.join(', ')}`);
  }
}

function show(slug) {
  process.stdout.write(fs.readFileSync(itemFile(slug), 'utf8'));
}

function resolve(slug) {
  const file = itemFile(slug);
  const destination = resolvedDir();
  fs.mkdirSync(destination, { recursive: true });
  const target = path.join(destination, `${slug}.md`);
  try {
    fs.linkSync(file, target);
  } catch (error) {
    if (error.code === 'EEXIST') throw new Error(`Resolved item already exists: ${slug}`);
    throw error;
  }
  fs.unlinkSync(file);
  console.log(`Resolved: ${slug} -> ${target}`);

  const freed = readItems().filter((item) => item.after.includes(slug) && !item.blockedBy);
  for (const item of freed) console.log(`Unblocked: ${item.slug} (${item.priority}) — ${item.title}`);
}

const [command, argument] = process.argv.slice(2);
try {
  if (command === 'list' || command === undefined) list(argument === '--json');
  else if (command === 'show') show(argument);
  else if (command === 'resolve') resolve(argument);
  else if (command === 'path') console.log(backlogDir());
  else {
    console.error('usage: backlog.mjs [list [--json] | show <slug> | resolve <slug> | path]');
    process.exit(2);
  }
} catch (error) {
  console.error(String(error.message ?? error));
  process.exit(1);
}
