import { createHmac } from 'node:crypto';
import { BIP32Factory } from 'bip32';
import * as ecc from 'tiny-secp256k1';
import { entropyToMnemonic, mnemonicToSeed } from './bip39.js';

const bip32 = BIP32Factory(ecc);
const PURPOSE = 83696968;

export function bip85Entropy(root, path) {
  const child = root.derivePath(path);
  if (!child.privateKey) throw new Error('BIP-85 wymaga prywatnego klucza root.');
  return createHmac('sha512', 'bip-entropy-from-k').update(Buffer.from(child.privateKey)).digest();
}

export function deriveBip85Mnemonic({ mnemonic, bip39Passphrase = '', index = 0, words = 24 }) {
  if (!Number.isSafeInteger(Number(index)) || Number(index) < 0 || Number(index) > 0x7fffffff) throw new Error('Indeks BIP-85 poza zakresem 0..2147483647.');
  if (Number(words) !== 24) throw new Error('EntropySilo tworzy potomne mnemoniki BIP-85 wyłącznie 24-wyrazowe.');
  const seed = mnemonicToSeed(mnemonic, bip39Passphrase);
  const root = bip32.fromSeed(seed); seed.fill(0);
  const path = `m/${PURPOSE}'/39'/0'/24'/${Number(index)}'`;
  const entropy = bip85Entropy(root, path);
  const result = entropyToMnemonic(entropy.subarray(0, 32));
  entropy.fill(0);
  return { ...result, path, index: Number(index), words: 24 };
}

export { bip32 };
