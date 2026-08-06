import {
  createCipheriv, createDecipheriv, randomBytes, scryptSync, timingSafeEqual,
} from 'node:crypto';
import { BIP32Factory } from 'bip32';
import * as bitcoin from 'bitcoinjs-lib';
import { ECPairFactory } from 'ecpair';
import * as ecc from 'tiny-secp256k1';
import { mnemonicToSeed, mnemonicToEntropy } from './bip39.js';

bitcoin.initEccLib(ecc);
const bip32 = BIP32Factory(ecc);
const ECPair = ECPairFactory(ecc);
const VAULT_VERSION = 3;
const SCRYPT = Object.freeze({ N: 131072, r: 8, p: 1, maxmem: 192 * 1024 * 1024 });
const BACKUP_VERSION = 2;
const VAULT_FORMAT = 'entropysilo-vault';
const LEGACY_VAULT_FORMAT = 'rpiwallet-vault';
const BACKUP_FORMAT = 'entropysilo-backup';
const LEGACY_BACKUP_FORMAT = 'rpiwallet-backup';
const SLIP132_PUBLIC = Object.freeze({
  bitcoin: Object.freeze({ 44: 0x0488b21e, 49: 0x049d7cb2, 84: 0x04b24746, 86: 0x0488b21e }),
  testnet: Object.freeze({ 44: 0x043587cf, 49: 0x044a5262, 84: 0x045f1cf6, 86: 0x043587cf }),
});

function asBuffer(value) { return Buffer.from(value); }
function toXOnly(publicKey) { return asBuffer(publicKey).subarray(1, 33); }

export function networkFor(name = 'bitcoin') {
  if (name === 'bitcoin' || name === 'mainnet') return bitcoin.networks.bitcoin;
  if (name === 'testnet' || name === 'signet') return bitcoin.networks.testnet;
  throw new Error('Obsługiwane sieci: bitcoin, testnet, signet.');
}

function vaultAad(version, metadata, format = VAULT_FORMAT) {
  const header = format === LEGACY_VAULT_FORMAT ? `RPiWalletVault/v${version}` : `EntropySiloVault/v${version}`;
  return Buffer.from(version >= 2 ? `${header}\0${JSON.stringify(metadata ?? {})}` : header, 'utf8');
}

export function encryptVault(payload, passphrase, metadata = {}) {
  if (!/^\d{12}$/u.test(String(passphrase))) throw new Error('PIN musi mieć dokładnie 12 cyfr (brak secure elementu uniemożliwia bezpieczny krótki PIN).');
  const salt = randomBytes(32);
  const nonce = randomBytes(12);
  const key = scryptSync(String(passphrase).normalize('NFKD'), salt, 32, SCRYPT);
  const cipher = createCipheriv('aes-256-gcm', key, nonce);
  cipher.setAAD(vaultAad(VAULT_VERSION, metadata));
  const ciphertext = Buffer.concat([cipher.update(JSON.stringify(payload), 'utf8'), cipher.final()]);
  const tag = cipher.getAuthTag();
  key.fill(0);
  return {
    format: VAULT_FORMAT, version: VAULT_VERSION,
    kdf: { name: 'scrypt', N: SCRYPT.N, r: SCRYPT.r, p: SCRYPT.p, salt: salt.toString('base64') },
    cipher: { name: 'aes-256-gcm', nonce: nonce.toString('base64'), tag: tag.toString('base64') },
    ciphertext: ciphertext.toString('base64'), metadata,
  };
}

export function decryptVault(document, passphrase) {
  const current = document?.format === VAULT_FORMAT && document?.version === VAULT_VERSION;
  const legacy = document?.format === LEGACY_VAULT_FORMAT && [1, 2].includes(document?.version);
  if (!current && !legacy) throw new Error('Nieobsługiwany format skarbca.');
  const kdf = document.kdf ?? {};
  if (kdf.name !== 'scrypt' || kdf.N !== SCRYPT.N || kdf.r !== SCRYPT.r || kdf.p !== SCRYPT.p) {
    throw new Error('Niebezpieczne albo nieobsługiwane parametry KDF.');
  }
  const salt = Buffer.from(kdf.salt, 'base64');
  const nonce = Buffer.from(document.cipher?.nonce ?? '', 'base64');
  const tag = Buffer.from(document.cipher?.tag ?? '', 'base64');
  if (salt.length !== 32 || nonce.length !== 12 || tag.length !== 16) throw new Error('Uszkodzony nagłówek skarbca.');
  const key = scryptSync(String(passphrase).normalize('NFKD'), salt, 32, SCRYPT);
  try {
    const decipher = createDecipheriv('aes-256-gcm', key, nonce);
    decipher.setAAD(vaultAad(document.version, document.metadata, document.format));
    decipher.setAuthTag(tag);
    const clear = Buffer.concat([decipher.update(Buffer.from(document.ciphertext, 'base64')), decipher.final()]);
    const parsed = JSON.parse(clear.toString('utf8'));
    clear.fill(0);
    const validPayload = typeof parsed.mnemonic === 'string'
      || typeof parsed.recoveryCode === 'string'
      || typeof parsed.wif === 'string'
      || (parsed.legacyInput && typeof parsed.legacyInput.password === 'string' && typeof parsed.legacyInput.number === 'string');
    if (!validPayload) throw new Error('Skarbiec nie zawiera obsługiwanego sekretu.');
    if (typeof parsed.mnemonic === 'string') mnemonicToEntropy(parsed.mnemonic);
    return parsed;
  } catch {
    throw new Error('Nieprawidłowe hasło albo uszkodzony skarbiec.');
  } finally { key.fill(0); }
}

export function encryptBackup(payload, passphrase) {
  const normalized = String(passphrase).normalize('NFKD');
  if (normalized.length < 12) throw new Error('Hasło backupu musi mieć co najmniej 12 znaków.');
  const salt = randomBytes(32); const nonce = randomBytes(12);
  const key = scryptSync(normalized, salt, 32, SCRYPT);
  const header = Buffer.from(`EntropySiloBackup/v${BACKUP_VERSION}`, 'utf8');
  const cipher = createCipheriv('aes-256-gcm', key, nonce); cipher.setAAD(header);
  const ciphertext = Buffer.concat([cipher.update(JSON.stringify(payload), 'utf8'), cipher.final()]);
  const tag = cipher.getAuthTag(); key.fill(0);
  return {
    format: BACKUP_FORMAT, version: BACKUP_VERSION,
    kdf: { name: 'scrypt', N: SCRYPT.N, r: SCRYPT.r, p: SCRYPT.p, salt: salt.toString('base64') },
    cipher: { name: 'aes-256-gcm', nonce: nonce.toString('base64'), tag: tag.toString('base64') },
    ciphertext: ciphertext.toString('base64'),
  };
}

export function decryptBackup(document, passphrase) {
  const current = document?.format === BACKUP_FORMAT && document?.version === BACKUP_VERSION;
  const legacy = document?.format === LEGACY_BACKUP_FORMAT && document?.version === 1;
  if (!current && !legacy) throw new Error('Nieobsługiwany format backupu.');
  const kdf = document.kdf ?? {};
  if (kdf.name !== 'scrypt' || kdf.N !== SCRYPT.N || kdf.r !== SCRYPT.r || kdf.p !== SCRYPT.p) throw new Error('Nieprawidłowe parametry KDF backupu.');
  const salt = Buffer.from(kdf.salt ?? '', 'base64');
  const nonce = Buffer.from(document.cipher?.nonce ?? '', 'base64');
  const tag = Buffer.from(document.cipher?.tag ?? '', 'base64');
  if (salt.length !== 32 || nonce.length !== 12 || tag.length !== 16) throw new Error('Uszkodzony nagłówek backupu.');
  const key = scryptSync(String(passphrase).normalize('NFKD'), salt, 32, SCRYPT);
  try {
    const aad = legacy ? 'RPiWalletBackup/v1' : `EntropySiloBackup/v${BACKUP_VERSION}`;
    const decipher = createDecipheriv('aes-256-gcm', key, nonce); decipher.setAAD(Buffer.from(aad, 'utf8')); decipher.setAuthTag(tag);
    const clear = Buffer.concat([decipher.update(Buffer.from(document.ciphertext ?? '', 'base64')), decipher.final()]);
    const payload = JSON.parse(clear.toString('utf8')); clear.fill(0); return payload;
  } catch { throw new Error('Błędne hasło albo uszkodzony backup.'); }
  finally { key.fill(0); }
}

function purposePath(purpose, account, networkName) {
  const supported = new Set([44, 49, 84, 86]);
  if (!supported.has(Number(purpose))) throw new Error('Obsługiwane standardy: BIP44, BIP49, BIP84, BIP86.');
  if (!Number.isSafeInteger(account) || account < 0 || account > 1000) throw new Error('Nieprawidłowy numer konta.');
  const coin = networkName === 'bitcoin' || networkName === 'mainnet' ? 0 : 1;
  return `m/${purpose}'/${coin}'/${account}'`;
}

function watchOnlyExtendedPublicKey(accountNode, purpose, networkName) {
  const family = networkName === 'bitcoin' || networkName === 'mainnet' ? 'bitcoin' : 'testnet';
  const networkObject = networkFor(networkName);
  const publicVersion = SLIP132_PUBLIC[family][Number(purpose)];
  const slip132Network = { ...networkObject, bip32: { ...networkObject.bip32, public: publicVersion } };
  return bip32.fromPublicKey(asBuffer(accountNode.publicKey), asBuffer(accountNode.chainCode), slip132Network).toBase58();
}

const ADDRESS_TYPES = Object.freeze({
  44: Object.freeze({ label: 'Legacy', technical: 'P2PKH', bip: 'BIP44' }),
  49: Object.freeze({ label: 'Nested SegWit', technical: 'P2SH-P2WPKH', bip: 'BIP49' }),
  84: Object.freeze({ label: 'Native SegWit', technical: 'P2WPKH', bip: 'BIP84' }),
  86: Object.freeze({ label: 'Taproot', technical: 'P2TR', bip: 'BIP86' }),
});

function deriveAddressFromRoot({ root, purpose = 84, account = 0, change = 0, index = 0, network = 'bitcoin' }) {
  if (![0, 1].includes(Number(change))) throw new Error('change musi wynosić 0 albo 1.');
  if (!Number.isSafeInteger(Number(index)) || Number(index) < 0 || Number(index) > 1000000) throw new Error('Nieprawidłowy indeks adresu.');
  const networkObject = networkFor(network);
  const accountPath = purposePath(Number(purpose), Number(account), network);
  const accountNode = root.derivePath(accountPath);
  const path = `${accountPath}/${Number(change)}/${Number(index)}`;
  const child = root.derivePath(path);
  const pubkey = asBuffer(child.publicKey);
  let payment;
  if (Number(purpose) === 44) payment = bitcoin.payments.p2pkh({ pubkey, network: networkObject });
  if (Number(purpose) === 49) payment = bitcoin.payments.p2sh({ redeem: bitcoin.payments.p2wpkh({ pubkey, network: networkObject }), network: networkObject });
  if (Number(purpose) === 84) payment = bitcoin.payments.p2wpkh({ pubkey, network: networkObject });
  if (Number(purpose) === 86) payment = bitcoin.payments.p2tr({ internalPubkey: toXOnly(pubkey), network: networkObject });
  const fingerprint = asBuffer(root.fingerprint).toString('hex');
  const accountXpub = accountNode.neutered().toBase58();
  const watchOnlyKey = watchOnlyExtendedPublicKey(accountNode, purpose, network);
  const origin = accountPath.slice(2).replaceAll("'", 'h');
  const descriptorFunction = Number(purpose) === 44 ? 'pkh' : Number(purpose) === 49 ? 'sh(wpkh' : Number(purpose) === 84 ? 'wpkh' : 'tr';
  let descriptor = `${descriptorFunction}([${fingerprint}/${origin}]${accountXpub}/${Number(change)}/*)`;
  if (Number(purpose) === 49) descriptor += ')';
  const watchOnlyExpression = `[${fingerprint}/${origin}]${watchOnlyKey}`;
  const type = ADDRESS_TYPES[Number(purpose)];
  return {
    network, purpose: Number(purpose), account: Number(account), change: Number(change), index: Number(index),
    path, address: payment.address, publicKey: pubkey.toString('hex'), accountXpub, watchOnlyKey,
    masterFingerprint: fingerprint, watchOnlyExpression, descriptor, ...type,
  };
}

export function deriveAddress({ mnemonic, bip39Passphrase = '', purpose = 84, account = 0, change = 0, index = 0, network = 'bitcoin' }) {
  const networkObject = networkFor(network);
  const seed = mnemonicToSeed(mnemonic, bip39Passphrase);
  const root = bip32.fromSeed(seed, networkObject);
  seed.fill(0);
  return deriveAddressFromRoot({ root, purpose, account, change, index, network });
}

export function deriveAddressTypes({ mnemonic, bip39Passphrase = '', account = 0, change = 0, index = 0, network = 'bitcoin' }) {
  const networkObject = networkFor(network);
  const seed = mnemonicToSeed(mnemonic, bip39Passphrase);
  const root = bip32.fromSeed(seed, networkObject);
  seed.fill(0);
  return [84, 49, 86, 44].map((purpose) => deriveAddressFromRoot({ root, purpose, account, change, index, network }));
}

export function addressTypesFromWif({ wif, network = 'bitcoin' }) {
  const networkObject = networkFor(network);
  let keyPair;
  try { keyPair = ECPair.fromWIF(String(wif).trim(), networkObject); }
  catch { throw new Error('Nieprawidłowy klucz prywatny WIF dla wybranej sieci.'); }
  if (!keyPair.compressed) throw new Error('Obsługiwane są wyłącznie skompresowane klucze WIF.');
  const pubkey = asBuffer(keyPair.publicKey);
  const payments = {
    44: bitcoin.payments.p2pkh({ pubkey, network: networkObject }),
    49: bitcoin.payments.p2sh({ redeem: bitcoin.payments.p2wpkh({ pubkey, network: networkObject }), network: networkObject }),
    84: bitcoin.payments.p2wpkh({ pubkey, network: networkObject }),
    86: bitcoin.payments.p2tr({ internalPubkey: toXOnly(pubkey), network: networkObject }),
  };
  return [84, 49, 86, 44].map((purpose) => ({
    network, purpose, account: null, change: null, index: null, path: 'single-key/WIF',
    address: payments[purpose].address, publicKey: pubkey.toString('hex'), accountXpub: null, watchOnlyKey: null,
    masterFingerprint: null, descriptor: null, ...ADDRESS_TYPES[purpose],
  }));
}

export function privateKeyHexToWif({ privateKeyHex, network = 'bitcoin' }) {
  const normalized = String(privateKeyHex ?? '').trim();
  if (!/^[0-9a-f]{64}$/iu.test(normalized)) throw new Error('Surowy klucz prywatny musi mieć dokładnie 64 znaki hex.');
  const privateKey = Buffer.from(normalized, 'hex');
  try { return ECPair.fromPrivateKey(privateKey, { compressed: true, network: networkFor(network) }).toWIF(); }
  catch { throw new Error('Surowy klucz prywatny jest poza zakresem secp256k1.'); }
  finally { privateKey.fill(0); }
}

function inputValue(input, transactionInput) {
  if (input.witnessUtxo) return BigInt(input.witnessUtxo.value);
  if (input.nonWitnessUtxo) {
    const transaction = bitcoin.Transaction.fromBuffer(asBuffer(input.nonWitnessUtxo));
    return BigInt(transaction.outs[transactionInput.index]?.value ?? 0);
  }
  return null;
}

export function inspectPsbt(psbtText, network = 'bitcoin') {
  const networkObject = networkFor(network);
  const trimmed = String(psbtText).trim();
  const psbt = /^[0-9a-f]+$/iu.test(trimmed) ? bitcoin.Psbt.fromHex(trimmed, { network: networkObject }) : bitcoin.Psbt.fromBase64(trimmed, { network: networkObject });
  if (psbt.inputCount > 256 || psbt.txOutputs.length > 256) {
    throw new Error('PSBT przekracza limit 256 wejść albo 256 wyjść.');
  }
  const outputs = psbt.txOutputs.map((output, index) => {
    let address = '(skrypt niestandardowy)';
    try { address = bitcoin.address.fromOutputScript(output.script, networkObject); } catch {}
    return { index, address, valueSats: output.value.toString() };
  });
  const values = psbt.data.inputs.map((input, index) => inputValue(input, psbt.txInputs[index]));
  const totalIn = values.every((value) => value !== null) ? values.reduce((sum, value) => sum + value, 0n) : null;
  const totalOut = psbt.txOutputs.reduce((sum, output) => sum + BigInt(output.value), 0n);
  const fee = totalIn === null ? null : totalIn - totalOut;
  if (fee !== null && fee < 0n) throw new Error('PSBT ma ujemną opłatę — odrzucono.');
  return {
    inputCount: psbt.inputCount,
    outputs,
    totalInputSats: totalIn?.toString() ?? null,
    totalOutputSats: totalOut.toString(),
    feeSats: fee?.toString() ?? null,
    warning: totalIn === null ? 'Nie wszystkie kwoty wejściowe są dostępne; nie można zweryfikować opłaty.' : null,
  };
}

function sameFingerprint(left, right) {
  const a = asBuffer(left); const b = asBuffer(right);
  return a.length === b.length && timingSafeEqual(a, b);
}

function missingFingerprint(value) {
  const fingerprint = asBuffer(value);
  return fingerprint.length === 4 && fingerprint.every((byte) => byte === 0);
}

function standardSigningPath(path, networkName, selectedAccount = null) {
  const match = /^m\/(44|49|84|86)'\/(0|1)'\/(\d{1,4})'\/([01])\/(\d{1,7})$/u.exec(String(path));
  if (!match) return false;
  const expectedCoin = networkName === 'bitcoin' || networkName === 'mainnet' ? '0' : '1';
  if (match[2] !== expectedCoin || Number(match[3]) > 1000 || Number(match[5]) > 1000000) return false;
  return selectedAccount === null || selectedAccount === undefined || selectedAccount === '' || Number(match[3]) === Number(selectedAccount);
}

function tweakSigner(node, networkObject) {
  if (!node.privateKey) throw new Error('Brak klucza prywatnego dla Taproot.');
  let privateKey = asBuffer(node.privateKey);
  if (node.publicKey[0] === 3) privateKey = asBuffer(ecc.privateNegate(privateKey));
  const tweak = bitcoin.crypto.taggedHash('TapTweak', toXOnly(node.publicKey));
  const tweaked = ecc.privateAdd(privateKey, tweak);
  privateKey.fill(0);
  if (!tweaked) throw new Error('Nie udało się utworzyć klucza Taproot.');
  return ECPair.fromPrivateKey(asBuffer(tweaked), { network: networkObject });
}

export function signPsbt({ mnemonic, bip39Passphrase = '', psbt: psbtText, network = 'bitcoin', account = null, finalize = true }) {
  const networkObject = networkFor(network);
  if (account !== null && account !== undefined && account !== '' && (!Number.isSafeInteger(Number(account)) || Number(account) < 0 || Number(account) > 1000)) {
    throw new Error('Nieprawidłowy numer konta.');
  }
  const summary = inspectPsbt(psbtText, network);
  const trimmed = String(psbtText).trim();
  const psbt = /^[0-9a-f]+$/iu.test(trimmed) ? bitcoin.Psbt.fromHex(trimmed, { network: networkObject }) : bitcoin.Psbt.fromBase64(trimmed, { network: networkObject });
  const seed = mnemonicToSeed(mnemonic, bip39Passphrase);
  const root = bip32.fromSeed(seed, networkObject);
  seed.fill(0);
  const fingerprint = asBuffer(root.fingerprint);
  const signedInputs = [];
  const compatibilityWarnings = [];

  psbt.data.inputs.forEach((input, inputIndex) => {
    for (const derivation of input.bip32Derivation ?? []) {
      const fingerprintMatches = sameFingerprint(derivation.masterFingerprint, fingerprint);
      const fingerprintMissing = missingFingerprint(derivation.masterFingerprint);
      if (!fingerprintMatches && !fingerprintMissing) continue;
      if (!standardSigningPath(derivation.path, network, account)) continue;
      const child = root.derivePath(derivation.path);
      if (!asBuffer(child.publicKey).equals(asBuffer(derivation.pubkey))) {
        if (fingerprintMatches) throw new Error(`Wejście ${inputIndex}: public key nie zgadza się ze ścieżką.`);
        continue;
      }
      psbt.signInput(inputIndex, child);
      signedInputs.push(inputIndex);
      if (fingerprintMissing) compatibilityWarnings.push(`Wejście ${inputIndex}: brak fingerprintu w PSBT; własność potwierdzono przez pełną ścieżkę i klucz publiczny.`);
    }
    for (const derivation of input.tapBip32Derivation ?? []) {
      const fingerprintMatches = sameFingerprint(derivation.masterFingerprint, fingerprint);
      const fingerprintMissing = missingFingerprint(derivation.masterFingerprint);
      if (!fingerprintMatches && !fingerprintMissing) continue;
      if (!standardSigningPath(derivation.path, network, account)) continue;
      if ((derivation.leafHashes ?? []).length > 0) throw new Error('Taproot script-path nie jest obecnie obsługiwany.');
      const child = root.derivePath(derivation.path);
      if (!toXOnly(child.publicKey).equals(asBuffer(derivation.pubkey))) {
        if (fingerprintMatches) throw new Error(`Wejście ${inputIndex}: klucz Taproot nie zgadza się ze ścieżką.`);
        continue;
      }
      psbt.signInput(inputIndex, tweakSigner(child, networkObject));
      signedInputs.push(inputIndex);
      if (fingerprintMissing) compatibilityWarnings.push(`Wejście ${inputIndex}: brak fingerprintu w PSBT; własność potwierdzono przez pełną ścieżkę i klucz publiczny.`);
    }
  });
  if (signedInputs.length === 0) throw new Error('PSBT nie zawiera wejść należących do tego portfela albo brakuje danych BIP32 derivation.');
  const result = { summary, signedInputs: [...new Set(signedInputs)], compatibilityWarnings: [...new Set(compatibilityWarnings)], psbtBase64: psbt.toBase64(), finalized: false, transactionHex: null, transactionId: null };
  if (finalize) {
    try {
      psbt.finalizeAllInputs();
      const transaction = psbt.extractTransaction();
      result.finalized = true;
      result.psbtBase64 = psbt.toBase64();
      result.transactionHex = transaction.toHex();
      result.transactionId = transaction.getId();
    } catch (error) {
      result.finalizeWarning = `Pozostawiono częściowo podpisany PSBT: ${error.message}`;
    }
  }
  return result;
}

export function signPsbtWithWif({ wif, psbt: psbtText, network = 'bitcoin', finalize = true }) {
  const networkObject = networkFor(network);
  const summary = inspectPsbt(psbtText, network);
  const trimmed = String(psbtText).trim();
  const psbt = /^[0-9a-f]+$/iu.test(trimmed) ? bitcoin.Psbt.fromHex(trimmed, { network: networkObject }) : bitcoin.Psbt.fromBase64(trimmed, { network: networkObject });
  let keyPair;
  try { keyPair = ECPair.fromWIF(String(wif).trim(), networkObject); }
  catch { throw new Error('Nieprawidłowy klucz prywatny WIF dla wybranej sieci.'); }
  if (!keyPair.compressed) throw new Error('Obsługiwane są wyłącznie skompresowane klucze WIF.');
  const signedInputs = [];
  psbt.data.inputs.forEach((input, inputIndex) => {
    try {
      if (input.tapInternalKey) psbt.signInput(inputIndex, tweakSigner(keyPair, networkObject));
      else psbt.signInput(inputIndex, keyPair);
      signedInputs.push(inputIndex);
    } catch {}
  });
  if (signedInputs.length === 0) throw new Error('PSBT nie zawiera wejść należących do zaimportowanego klucza WIF.');
  const result = { summary, signedInputs, psbtBase64: psbt.toBase64(), finalized: false, transactionHex: null, transactionId: null };
  if (finalize) {
    try {
      psbt.finalizeAllInputs();
      const transaction = psbt.extractTransaction();
      result.finalized = true; result.psbtBase64 = psbt.toBase64();
      result.transactionHex = transaction.toHex(); result.transactionId = transaction.getId();
    } catch (error) { result.finalizeWarning = `Pozostawiono częściowo podpisany PSBT: ${error.message}`; }
  }
  return result;
}
