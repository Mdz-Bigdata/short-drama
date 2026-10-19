#!/usr/bin/env node
/**
 * Interface translation coverage.
 *
 *   node scripts/i18n-coverage.mjs           report keys missing per language and untranslated files
 *   node scripts/i18n-coverage.mjs --keys    print every key (one JSON string per line)
 *   node scripts/i18n-coverage.mjs --check   exit 1 when a used key has no English or Vietnamese entry
 *
 * Keys are the Chinese text passed to t() / tr(), plus the labels of constant option lists that
 * components translate where they display them (DYNAMIC_SOURCES below).
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

const ROOT = new URL('..', import.meta.url).pathname;
const SRC = join(ROOT, 'src');
const CJK = /[㐀-鿿豈-﫿]/;

// Constant lists whose string properties are translated at their display sites.
const DYNAMIC_SOURCES = [
  ['src/features/workbench/AgentStageTabs.tsx', ['label']],
  ['src/features/workbench/chatCommands.ts', ['label', 'description']],
  ['src/features/workbench/creationOptions.ts', ['label']],
  ['src/types.ts', ['label', 'hint']],
];

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) walk(path, out);
    else if (/\.(tsx?|mts)$/.test(name) && !/\.test\./.test(name) && !path.includes(`${join('src', 'i18n')}`)) out.push(path);
  }
  return out;
}

function unescape(text) {
  return text.replace(/\\(.)/g, '$1');
}

const files = walk(SRC);
const keys = new Set();
const keyUse = /\b(?:t|tr)\(\s*'((?:[^'\\\n]|\\.)*)'/g;
for (const file of files) {
  const text = readFileSync(file, 'utf8');
  for (const match of text.matchAll(keyUse)) if (CJK.test(match[1])) keys.add(unescape(match[1]));
}
for (const [file, props] of DYNAMIC_SOURCES) {
  const text = readFileSync(join(ROOT, file), 'utf8');
  for (const prop of props) {
    for (const match of text.matchAll(new RegExp(`\\b${prop}:\\s*'((?:[^'\\\\\\n]|\\\\.)*)'`, 'g'))) {
      if (CJK.test(match[1])) keys.add(unescape(match[1]));
    }
  }
}

function dictionary(name) {
  const text = readFileSync(join(SRC, 'i18n', `${name}.ts`), 'utf8');
  const entries = new Set();
  for (const match of text.matchAll(/^\s*'((?:[^'\\\n]|\\.)*)'\s*:/gm)) entries.add(unescape(match[1]));
  return entries;
}

const sorted = [...keys].sort();
if (process.argv.includes('--keys')) {
  for (const key of sorted) console.log(JSON.stringify(key));
  process.exit(0);
}

const missing = Object.fromEntries(['en', 'vi'].map(name => {
  const entries = dictionary(name);
  return [name, sorted.filter(key => !entries.has(key))];
}));

// Lines that still carry Chinese outside t()/tr(), comments and console output: work left to do.
const untranslated = files.map(file => {
  const lines = readFileSync(file, 'utf8').split('\n').filter(line => {
    const code = line.replace(/\b(?:t|tr)\(\s*'(?:[^'\\]|\\.)*'/g, '').replace(/\/\/.*$|\/\*.*?\*\/|\{\/\*.*?\*\/\}/g, '');
    return CJK.test(code) && !/^\s*\*/.test(line) && !/console\.(log|warn|error|info)/.test(line);
  });
  return [relative(ROOT, file), lines.length];
}).filter(([, count]) => count > 0).sort((a, b) => b[1] - a[1]);

console.log(`keys in use: ${sorted.length}`);
for (const [name, list] of Object.entries(missing)) console.log(`missing in ${name}: ${list.length}`);
console.log(`files with untranslated Chinese: ${untranslated.length} (lines: ${untranslated.reduce((sum, [, n]) => sum + n, 0)})`);
for (const [file, count] of untranslated.slice(0, 15)) console.log(`  ${String(count).padStart(4)}  ${file}`);
if (process.argv.includes('--check') && (missing.en.length || missing.vi.length)) {
  for (const [name, list] of Object.entries(missing)) for (const key of list.slice(0, 20)) console.error(`[${name}] ${key}`);
  process.exit(1);
}
