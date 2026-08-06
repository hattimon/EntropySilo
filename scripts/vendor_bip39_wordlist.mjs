#!/usr/bin/env node
import { writeFile, mkdir } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { wordlist } from '@scure/bip39/wordlists/english.js';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const output = resolve(root, 'apps/data/bip39-english.json');
if (wordlist.length !== 2048) throw new Error(`Expected 2048 words, got ${wordlist.length}`);
await mkdir(dirname(output), { recursive: true });
await writeFile(output, `${JSON.stringify(wordlist, null, 2)}\n`, { mode: 0o644 });
console.log(`Vendored ${wordlist.length} BIP-39 words to ${output}`);
