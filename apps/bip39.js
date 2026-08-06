import { createHash, pbkdf2Sync, randomBytes } from 'node:crypto';
import english from './data/bip39-english.json' with { type: 'json' };

const VALID_ENTROPY_BYTES = new Set([16, 20, 24, 28, 32]);
const VALID_WORD_COUNTS = new Set([12, 15, 18, 21, 24]);

function normalizeMnemonic(value) {
  return String(value).normalize('NFKD').trim().toLowerCase().split(/\s+/u).join(' ');
}

function bytesToBits(bytes) {
  return [...bytes].map((byte) => byte.toString(2).padStart(8, '0')).join('');
}

function bitsToBytes(bits) {
  const output = Buffer.alloc(bits.length / 8);
  for (let index = 0; index < output.length; index += 1) {
    output[index] = Number.parseInt(bits.slice(index * 8, index * 8 + 8), 2);
  }
  return output;
}

export function entropyToMnemonic(entropyInput) {
  const entropy = Buffer.from(entropyInput);
  if (!VALID_ENTROPY_BYTES.has(entropy.length)) {
    throw new Error('Entropia BIP-39 musi mieć 128, 160, 192, 224 albo 256 bitów.');
  }
  const entropyBits = bytesToBits(entropy);
  const checksumLength = entropy.length * 8 / 32;
  const checksumBits = bytesToBits(createHash('sha256').update(entropy).digest()).slice(0, checksumLength);
  const combined = entropyBits + checksumBits;
  const words = [];
  for (let offset = 0; offset < combined.length; offset += 11) {
    words.push(english[Number.parseInt(combined.slice(offset, offset + 11), 2)]);
  }
  return { mnemonic: words.join(' '), entropyHex: entropy.toString('hex'), checksumBits };
}

export function generateMnemonic(wordCount = 24) {
  if (Number(wordCount) !== 24) throw new Error('Nowe portfele są generowane wyłącznie z pełnych 256 bitów (24 słowa).');
  return entropyToMnemonic(randomBytes(32));
}

export function mnemonicToEntropy(mnemonicInput) {
  const mnemonic = normalizeMnemonic(mnemonicInput);
  const words = mnemonic.split(' ');
  if (!VALID_WORD_COUNTS.has(words.length)) throw new Error('Nieprawidłowa liczba słów BIP-39.');
  const indexes = words.map((word) => {
    const index = english.indexOf(word);
    if (index < 0) throw new Error(`Słowo nie występuje na angielskiej liście BIP-39: ${word}`);
    return index;
  });
  const allBits = indexes.map((index) => index.toString(2).padStart(11, '0')).join('');
  const entropyLength = Math.floor(allBits.length * 32 / 33);
  const checksumLength = allBits.length - entropyLength;
  const entropy = bitsToBytes(allBits.slice(0, entropyLength));
  const expected = bytesToBits(createHash('sha256').update(entropy).digest()).slice(0, checksumLength);
  if (allBits.slice(entropyLength) !== expected) throw new Error('Suma kontrolna mnemonika BIP-39 jest błędna.');
  return { mnemonic, entropy, entropyHex: entropy.toString('hex'), checksumBits: expected };
}

export function validateMnemonic(mnemonic) {
  try { mnemonicToEntropy(mnemonic); return true; } catch { return false; }
}

export function mnemonicToSeed(mnemonicInput, passphrase = '') {
  const { mnemonic } = mnemonicToEntropy(mnemonicInput);
  return pbkdf2Sync(
    Buffer.from(mnemonic.normalize('NFKD'), 'utf8'),
    Buffer.from(`mnemonic${String(passphrase).normalize('NFKD')}`, 'utf8'),
    2048,
    64,
    'sha512',
  );
}

export { normalizeMnemonic };
