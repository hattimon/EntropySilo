#!/usr/bin/env node
import { generateMnemonic } from './bip39.js';

const wordCount = 24;
const result = generateMnemonic(24);
if (process.argv.includes('--json')) console.log(JSON.stringify(result));
else {
  console.log(`MNEMONIC (${wordCount} słowa; pokaż tylko raz):`);
  console.log(result.mnemonic);
  console.log(`\nEntropia: ${result.entropyHex}`);
  console.log(`Checksum: ${result.checksumBits}`);
}
