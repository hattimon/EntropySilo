import test from 'node:test';
import assert from 'node:assert/strict';
import { createCipheriv, randomBytes, scryptSync } from 'node:crypto';
import * as bitcoin from 'bitcoinjs-lib';
import { addressTypesFromWif, decryptBackup, decryptVault, deriveAddress, deriveAddressTypes, encryptBackup, encryptVault, inspectPsbt, privateKeyHexToWif, signPsbt } from '../apps/wallet-core.js';

const mnemonic = 'abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about';
const legacyKdf = Object.freeze({ N: 131072, r: 8, p: 1, maxmem: 192 * 1024 * 1024 });

function encryptLegacyDocument(payload, passphrase, { format, version, aad, metadata }) {
  const salt = randomBytes(32);
  const nonce = randomBytes(12);
  const key = scryptSync(String(passphrase).normalize('NFKD'), salt, 32, legacyKdf);
  const cipher = createCipheriv('aes-256-gcm', key, nonce);
  cipher.setAAD(Buffer.from(aad, 'utf8'));
  const ciphertext = Buffer.concat([cipher.update(JSON.stringify(payload), 'utf8'), cipher.final()]);
  const tag = cipher.getAuthTag();
  key.fill(0);
  return {
    format, version,
    kdf: { name: 'scrypt', N: legacyKdf.N, r: legacyKdf.r, p: legacyKdf.p, salt: salt.toString('base64') },
    cipher: { name: 'aes-256-gcm', nonce: nonce.toString('base64'), tag: tag.toString('base64') },
    ciphertext: ciphertext.toString('base64'),
    ...(metadata ? { metadata } : {}),
  };
}

test('vault encrypt/decrypt and wrong password', () => {
  const document = encryptVault({ mnemonic }, '123456789012', { name: 'root', source: 'generated-cards' });
  assert.equal(document.format, 'entropysilo-vault');
  assert.equal(document.version, 3);
  assert.equal(decryptVault(document, '123456789012').mnemonic, mnemonic);
  assert.throws(() => decryptVault(document, '000000000000'), /Nieprawidłowe hasło/);
  const tampered = structuredClone(document); tampered.metadata.source = 'imported-wif';
  assert.throws(() => decryptVault(tampered, '123456789012'), /Nieprawidłowe hasło albo uszkodzony/u);
});

test('known BIP84 first address', () => {
  const result = deriveAddress({ mnemonic, purpose: 84, network: 'bitcoin' });
  const accountOne = deriveAddress({ mnemonic, purpose: 84, account: 1, network: 'bitcoin' });
  assert.equal(result.path, "m/84'/0'/0'/0/0");
  assert.equal(result.address, 'bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu');
  assert.match(result.accountXpub, /^xpub/u);
  assert.match(result.watchOnlyKey, /^zpub/u);
  assert.match(result.watchOnlyExpression, /^\[[0-9a-f]{8}\/84h\/0h\/0h\]zpub/u);
  assert.match(result.descriptor, /^wpkh\(\[[0-9a-f]{8}\/84h\/0h\/0h\]xpub/u);
  assert.equal(accountOne.path, "m/84'/0'/1'/0/0");
  assert.match(accountOne.descriptor, /^wpkh\(\[[0-9a-f]{8}\/84h\/0h\/1h\]xpub/u);
  assert.notEqual(accountOne.address, result.address);
});

test('four clearly labelled public address standards', () => {
  const types = deriveAddressTypes({ mnemonic, network: 'bitcoin' });
  assert.deepEqual(types.map((item) => item.purpose), [84, 49, 86, 44]);
  assert.deepEqual(types.map((item) => item.label), ['Native SegWit', 'Nested SegWit', 'Taproot', 'Legacy']);
  assert.equal(types[0].path, "m/84'/0'/0'/0/0");
  assert.match(types[0].descriptor, /^wpkh\(\[/u);
  assert.match(types[1].descriptor, /^sh\(wpkh\(\[/u);
  assert.match(types[2].descriptor, /^tr\(\[/u);
  assert.match(types[3].descriptor, /^pkh\(\[/u);
  assert.deepEqual(types.map((item) => item.watchOnlyKey.slice(0, 4)), ['zpub', 'ypub', 'xpub', 'xpub']);
});

test('raw private key is normalized to compressed WIF with four public address types', () => {
  const wif = privateKeyHexToWif({ privateKeyHex: '01'.padStart(64, '0'), network: 'bitcoin' });
  assert.equal(wif, 'KwDiBf89QgGbjEhKnhXJuH7LrciVrZi3qYjgd9M7rFU73sVHnoWn');
  const types = addressTypesFromWif({ wif, network: 'bitcoin' });
  assert.deepEqual(types.map((item) => item.purpose), [84, 49, 86, 44]);
  assert.equal(types[0].path, 'single-key/WIF');
});

test('encrypted wallet backup authenticates password and payload', () => {
  const payload = { format: 'entropysilo-backup-payload', version: 2, wallets: [{ name: 'wallet1' }] };
  const backup = encryptBackup(payload, 'correct horse battery staple');
  assert.equal(backup.format, 'entropysilo-backup');
  assert.equal(backup.version, 2);
  assert.deepEqual(decryptBackup(backup, 'correct horse battery staple'), payload);
  assert.throws(() => decryptBackup(backup, 'incorrect password'), /Błędne hasło/u);
});

test('legacy RPiWallet vault and backup remain readable after the EntropySilo rename', () => {
  const passphrase = 'correct horse battery staple';
  const metadata = { name: 'legacy', source: 'imported-mnemonic' };
  const legacyVault = encryptLegacyDocument(
    { mnemonic }, passphrase,
    {
      format: 'rpiwallet-vault', version: 2, metadata,
      aad: `RPiWalletVault/v2\0${JSON.stringify(metadata)}`,
    },
  );
  assert.equal(decryptVault(legacyVault, passphrase).mnemonic, mnemonic);

  const payload = { format: 'rpiwallet-backup-payload', version: 1, wallets: [{ name: 'legacy' }] };
  const legacyBackup = encryptLegacyDocument(
    payload, passphrase,
    { format: 'rpiwallet-backup', version: 1, aad: 'RPiWalletBackup/v1' },
  );
  assert.deepEqual(decryptBackup(legacyBackup, passphrase), payload);
});

test('BIP84 PSBT is inspected, signed and finalized with the derived wallet key', () => {
  const input = deriveAddress({ mnemonic, purpose: 84, index: 0, network: 'bitcoin' });
  const destination = deriveAddress({ mnemonic, purpose: 84, index: 1, network: 'bitcoin' });
  const psbt = new bitcoin.Psbt({ network: bitcoin.networks.bitcoin });
  psbt.addInput({
    hash: Buffer.alloc(32, 7), index: 0,
    witnessUtxo: { script: bitcoin.address.toOutputScript(input.address), value: 10_000n },
    bip32Derivation: [{
      masterFingerprint: Buffer.from(input.masterFingerprint, 'hex'),
      path: input.path,
      pubkey: Buffer.from(input.publicKey, 'hex'),
    }],
  });
  psbt.addOutput({ address: destination.address, value: 9_000n });
  const encoded = psbt.toBase64();
  const summary = inspectPsbt(encoded, 'bitcoin');
  assert.equal(summary.feeSats, '1000');
  assert.equal(summary.outputs[0].address, destination.address);
  const signed = signPsbt({ mnemonic, psbt: encoded, network: 'bitcoin', account: 0, finalize: true });
  assert.equal(signed.finalized, true);
  assert.deepEqual(signed.signedInputs, [0]);
  assert.match(signed.transactionHex, /^[0-9a-f]+$/u);
});

test('BlueWallet PSBT with zero fingerprint signs only after public-key verification', () => {
  const input = deriveAddress({ mnemonic, purpose: 84, index: 1, network: 'bitcoin' });
  const destination = deriveAddress({ mnemonic, purpose: 84, index: 2, network: 'bitcoin' });
  const psbt = new bitcoin.Psbt({ network: bitcoin.networks.bitcoin });
  psbt.addInput({
    hash: Buffer.alloc(32, 8), index: 0,
    witnessUtxo: { script: bitcoin.address.toOutputScript(input.address), value: 10_000n },
    bip32Derivation: [{
      masterFingerprint: Buffer.alloc(4),
      path: input.path,
      pubkey: Buffer.from(input.publicKey, 'hex'),
    }],
  });
  psbt.addOutput({ address: destination.address, value: 9_000n });
  const encoded = psbt.toBase64();
  const signed = signPsbt({ mnemonic, psbt: encoded, network: 'bitcoin', finalize: true });
  assert.equal(signed.finalized, true);
  assert.deepEqual(signed.signedInputs, [0]);
  assert.equal(signed.compatibilityWarnings.length, 1);
  assert.throws(() => signPsbt({ mnemonic, psbt: encoded, network: 'bitcoin', account: 1 }), /PSBT nie zawiera/u);
  assert.throws(
    () => signPsbt({ mnemonic: 'legal winner thank year wave sausage worth useful legal winner thank yellow', psbt: encoded, network: 'bitcoin' }),
    /PSBT nie zawiera/u,
  );
});

test('selected HD account 1 signs account 1 and rejects account 0', () => {
  const input = deriveAddress({ mnemonic, purpose: 84, account: 1, index: 0, network: 'bitcoin' });
  const destination = deriveAddress({ mnemonic, purpose: 84, account: 1, index: 1, network: 'bitcoin' });
  const psbt = new bitcoin.Psbt({ network: bitcoin.networks.bitcoin });
  psbt.addInput({
    hash: Buffer.alloc(32, 9), index: 0,
    witnessUtxo: { script: bitcoin.address.toOutputScript(input.address), value: 10_000n },
    bip32Derivation: [{ masterFingerprint: Buffer.alloc(4), path: input.path, pubkey: Buffer.from(input.publicKey, 'hex') }],
  });
  psbt.addOutput({ address: destination.address, value: 9_000n });
  const encoded = psbt.toBase64();
  assert.equal(signPsbt({ mnemonic, psbt: encoded, network: 'bitcoin', account: 1 }).finalized, true);
  assert.throws(() => signPsbt({ mnemonic, psbt: encoded, network: 'bitcoin', account: 0 }), /PSBT nie zawiera/u);
});

test('oversized PSBT is rejected before expensive inspection or signing', () => {
  const psbt = new bitcoin.Psbt({ network: bitcoin.networks.bitcoin });
  for (let index = 0; index < 257; index += 1) {
    const hash = Buffer.alloc(32, 0);
    hash.writeUInt32LE(index, 0);
    psbt.addInput({ hash, index: 0 });
  }
  psbt.addOutput({ script: Buffer.from([bitcoin.opcodes.OP_RETURN]), value: 0n });
  assert.throws(() => inspectPsbt(psbt.toBase64(), 'bitcoin'), /limit 256/u);
});
