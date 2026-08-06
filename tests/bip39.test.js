import test from 'node:test';
import assert from 'node:assert/strict';
import { entropyToMnemonic, mnemonicToEntropy, mnemonicToSeed } from '../apps/bip39.js';

test('official BIP-39 vector: zero entropy', () => {
  const entropy = Buffer.alloc(16);
  const expected = 'abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about';
  assert.equal(entropyToMnemonic(entropy).mnemonic, expected);
  assert.equal(mnemonicToEntropy(expected).entropyHex, entropy.toString('hex'));
  assert.equal(
    mnemonicToSeed(expected, 'TREZOR').toString('hex'),
    'c55257c360c07c72029aebc1b53c05ed0362ada38ead3e3e9efa3708e53495531f09a6987599d18264c1e1c92f2cf141630c7a3c4ab7c81b2f001698e7463b04',
  );
});

test('256-bit round trip', () => {
  const entropy = Buffer.from('8080808080808080808080808080808080808080808080808080808080808080', 'hex');
  const encoded = entropyToMnemonic(entropy);
  assert.equal(encoded.mnemonic.split(' ').length, 24);
  assert.equal(mnemonicToEntropy(encoded.mnemonic).entropyHex, entropy.toString('hex'));
});
