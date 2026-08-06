import test from 'node:test';
import assert from 'node:assert/strict';
import { bip32, bip85Entropy } from '../apps/bip85.js';

test('official BIP-85 general test vector 1', () => {
  const root = bip32.fromBase58('xprv9s21ZrQH143K2LBWUUQRFXhucrQqBpKdRRxNVq2zBqsx8HVqFk2uYo8kmbaLLHRdqtQpUm98uKfu3vca1LqdGhUtyoFnCNkfmXRyPXLjbKb');
  const entropy = bip85Entropy(root, "m/83696968'/0'/0'");
  assert.equal(entropy.toString('hex'), 'efecfbccffea313214232d29e71563d941229afb4338c21f9517c41aaa0d16f00b83d2a09ef747e7a64e8e2bd5a14869e693da66ce94ac2da570ab7ee48618f7');
});
