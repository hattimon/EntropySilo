#!/usr/bin/env node
import { link, mkdir, readFile, readdir, rename, unlink, writeFile } from 'node:fs/promises';
import { basename, join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { generateMnemonic } from './bip39.js';
import { mnemonicToEntropy } from './bip39.js';
import { generateFromCards } from './card-entropy.js';
import { deriveBip85Mnemonic } from './bip85.js';
import {
  addressTypesFromWif, decryptVault, deriveAddress, deriveAddressTypes, encryptVault,
  decryptBackup, encryptBackup, inspectPsbt, privateKeyHexToWif, signPsbt, signPsbtWithWif,
} from './wallet-core.js';

const vaultDirectory = resolve(process.env.ENTROPYSILO_VAULT_DIR ?? '/var/lib/entropysilo/vaults');

async function readInput() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(Buffer.from(chunk));
  const value = Buffer.concat(chunks).toString('utf8').trim();
  return value ? JSON.parse(value) : {};
}
function safeName(value) {
  const name = String(value ?? '').trim();
  if (!/^[a-zA-Z0-9_-]{1,32}$/u.test(name)) throw new Error('Nazwa: 1-32 znaków a-z, A-Z, 0-9, _ lub -.');
  return name;
}
function vaultPath(name) { return join(vaultDirectory, `${safeName(name)}.vault.json`); }
async function readVaultDocument(name) { return JSON.parse(await readFile(vaultPath(name), 'utf8')); }
async function loadVault(name, passphrase) {
  const document = await readVaultDocument(name);
  return resolveSecret(decryptVault(document, passphrase));
}
async function loadVaultRaw(name, passphrase) {
  const document = await readVaultDocument(name);
  return decryptVault(document, passphrase);
}
async function saveVault(name, document) {
  await mkdir(vaultDirectory, { recursive: true, mode: 0o700 });
  const destination = vaultPath(name); const temporary = `${destination}.new-${process.pid}`;
  try {
    await writeFile(temporary, `${JSON.stringify(document, null, 2)}\n`, { mode: 0o600, flag: 'wx' });
    await link(temporary, destination); // Atomic no-replace: link fails if destination exists.
  } catch (error) {
    if (error.code === 'EEXIST') throw new Error(`Portfel ${safeName(name)} już istnieje.`);
    throw error;
  } finally {
    try { await unlink(temporary); } catch (error) { if (error.code !== 'ENOENT') throw error; }
  }
}
async function replaceVaultDocument(name, document) {
  const destination = vaultPath(name); const temporary = `${destination}.new`;
  try { await unlink(temporary); } catch (error) { if (error.code !== 'ENOENT') throw error; }
  await writeFile(temporary, `${JSON.stringify(document, null, 2)}\n`, { mode: 0o600, flag: 'wx' });
  await rename(temporary, destination);
}
async function updateMetadata(name, passphrase, patch) {
  const normalizedName = safeName(name);
  const oldDocument = await readVaultDocument(normalizedName);
  const payload = decryptVault(oldDocument, passphrase);
  const metadata = { ...(oldDocument.metadata ?? {}), name: normalizedName, ...patch, updatedAt: new Date().toISOString() };
  await replaceVaultDocument(normalizedName, encryptVault(payload, passphrase, metadata));
  return metadata;
}
function publicMetadata(name, document) {
  const metadata = document?.metadata ?? {};
  return {
    name,
    source: metadata.source ?? 'unknown',
    wordCount: metadata.wordCount ?? null,
    parent: metadata.parent ?? null,
    bip85Index: metadata.bip85Index ?? null,
    bip85Path: metadata.bip85Path ?? null,
    hidden: metadata.hidden === true,
    restorable: metadata.restorable === true,
    bip85Root: metadata.bip85Root === true,
    createdAt: metadata.createdAt ?? null,
  };
}
function resolveSecret(payload) {
  if (typeof payload.mnemonic === 'string') return payload;
  if (typeof payload.wif === 'string') return payload;
  if (typeof payload.recoveryCode === 'string') {
    const decoded = runSwd('swd-decode-json', payload.recoveryCode);
    return { ...payload, mnemonic: mnemonicToEntropy(decoded.mnemonic).mnemonic };
  }
  if (payload.legacyInput) {
    const generated = runSwd('swd-legacy-24-json', JSON.stringify(payload.legacyInput));
    return { ...payload, mnemonic: mnemonicToEntropy(generated.mnemonic).mnemonic };
  }
  throw new Error('Nieobsługiwany sekret w skarbcu.');
}
function swdPayload(mnemonic, createdAt = new Date().toISOString()) {
  const encoded = runSwd('swd-encode-json', mnemonicToEntropy(mnemonic).mnemonic);
  return { recoveryCode: encoded.paperCode, format: encoded.format, wordCount: encoded.wordCount, createdAt };
}
function effectiveSecret(payload, input) {
  if (input.bip85Index === undefined || input.bip85Index === null || input.bip85Index === '') return payload;
  const child = deriveBip85Mnemonic({ mnemonic: payload.mnemonic, bip39Passphrase: String(input.bip39Passphrase ?? ''), index: Number(input.bip85Index), words: 24 });
  return { ...payload, mnemonic: child.mnemonic, bip85Path: child.path };
}
function signingPassphrase(input) {
  return input.bip85Index === undefined || input.bip85Index === null || input.bip85Index === ''
    ? String(input.bip39Passphrase ?? '')
    : String(input.childBip39Passphrase ?? '');
}
async function createRecoveredVault({ name, pin, mnemonic, secretPayload, metadata = {} }) {
  const normalizedName = safeName(name);
  const payload = secretPayload ?? swdPayload(mnemonic);
  const finalMetadata = { name: normalizedName, createdAt: payload.createdAt, recovered: true, ...metadata };
  const document = encryptVault(payload, pin, finalMetadata);
  await saveVault(normalizedName, document);
  const resolved = resolveSecret(payload);
  return { name: normalizedName, firstAddress: deriveAddress({ mnemonic: resolved.mnemonic, purpose: 44, network: 'bitcoin' }) };
}
function runSwd(wrapper, secretInput) {
  const directory = process.env.ENTROPYSILO_SWD_BIN ?? '/usr/local/bin';
  const result = spawnSync(join(directory, wrapper), { input: String(secretInput), encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'], timeout: 120000 });
  if (result.status !== 0) throw new Error((result.stderr || `SWD zakończył się kodem ${result.status}`).trim());
  return JSON.parse(result.stdout);
}

async function main() {
  const command = process.argv[2];
  const input = await readInput();
  if (command === 'create') {
    const name = safeName(input.name);
    const method = input.generation ?? 'system';
    if (!['system', 'cards'].includes(method)) throw new Error('Generowanie: system albo cards. Import używa osobnego polecenia recover.');
    const generatedData = method === 'cards' ? generateFromCards(input.cards ?? {}) : generateMnemonic(24);
    const mnemonic = generatedData.mnemonic;
    const payload = swdPayload(mnemonic);
    const metadata = {
      name, createdAt: payload.createdAt, source: method === 'cards' ? 'generated-cards' : 'generated-csprng',
      wordCount: 24, hidden: false, restorable: false,
    };
    const document = encryptVault(payload, input.passphrase, metadata);
    await saveVault(name, document);
    const firstAddress = deriveAddress({ mnemonic, purpose: 84, network: input.network ?? 'bitcoin' });
    // The GUI needs the mnemonic once for the paper backup. Do not return redundant
    // copies such as raw entropy or the reversible SWD recovery code.
    console.log(JSON.stringify({ name, generated: true, generation: method, mnemonic, firstAddress }, null, 2));
    return;
  }
  if (command === 'recover') {
    const name = safeName(input.name);
    const mnemonic = mnemonicToEntropy(input.mnemonic).mnemonic;
    const payload = swdPayload(mnemonic);
    const metadata = {
      name, createdAt: payload.createdAt, recovered: true, source: 'imported-bip39',
      wordCount: mnemonic.split(' ').length, hidden: false, restorable: false,
    };
    const document = encryptVault(payload, input.passphrase, metadata);
    await saveVault(name, document);
    const firstAddress = deriveAddress({ mnemonic, purpose: 84, network: input.network ?? 'bitcoin' });
    console.log(JSON.stringify({ name, recovered: true, firstAddress }, null, 2));
    return;
  }
  if (command === 'recover-swd') {
    const name = safeName(input.name);
    const decoded = runSwd('swd-decode-json', input.recoveryCode);
    const mnemonic = mnemonicToEntropy(decoded.mnemonic).mnemonic;
    const payload = { recoveryCode: String(input.recoveryCode).trim(), format: decoded.format, wordCount: decoded.wordCount, createdAt: new Date().toISOString() };
    const metadata = {
      name, createdAt: payload.createdAt, recovered: true, source: `imported-${decoded.format}`,
      wordCount: decoded.wordCount, hidden: false, restorable: false,
    };
    const document = encryptVault(payload, input.passphrase, metadata);
    await saveVault(name, document);
    console.log(JSON.stringify({ name, recovered: true, source: decoded.format, firstAddress: deriveAddress({ mnemonic, purpose: 84, network: input.network ?? 'bitcoin' }) }, null, 2));
    return;
  }
  if (command === 'recover-wif') {
    const name = safeName(input.name); const network = input.network ?? 'bitcoin';
    const types = addressTypesFromWif({ wif: input.wif, network });
    const payload = { wif: String(input.wif).trim(), network, createdAt: new Date().toISOString() };
    const metadata = {
      name, createdAt: payload.createdAt, recovered: true, source: 'imported-wif',
      wordCount: null, hidden: false, restorable: false,
    };
    const document = encryptVault(payload, input.passphrase, metadata);
    await saveVault(name, document);
    console.log(JSON.stringify({ name, recovered: true, source: 'wif', types }, null, 2)); return;
  }
  if (command === 'recover-private-key') {
    const name = safeName(input.name); const network = input.network ?? 'bitcoin';
    const wif = privateKeyHexToWif({ privateKeyHex: input.privateKeyHex, network });
    const types = addressTypesFromWif({ wif, network });
    const payload = { wif, network, createdAt: new Date().toISOString() };
    const metadata = { name, createdAt: payload.createdAt, recovered: true, source: 'imported-private-key', wordCount: null, hidden: false, restorable: false };
    const document = encryptVault(payload, input.passphrase, metadata);
    await saveVault(name, document);
    console.log(JSON.stringify({ name, recovered: true, source: 'private-key', types }, null, 2)); return;
  }
  if (command === 'legacy-create') {
    const wordCount = Number(input.wordCount ?? 24);
    if (![12, 24].includes(wordCount)) throw new Error('Wallet Decoder legacy obsługuje 12 albo 24 słowa.');
    const generated = runSwd('swd-legacy-24-json', JSON.stringify({ password: input.password, number: input.number, wordCount }));
    const legacyInput = { password: String(input.password), number: String(input.number), wordCount };
    const created = await createRecoveredVault({ name: input.name, pin: input.pin, secretPayload: { legacyInput, createdAt: new Date().toISOString() }, metadata: { source: 'legacy-manual-password-number', wordCount, hidden: false, restorable: false } });
    console.log(JSON.stringify({ ...created, legacyAddress: generated.address, source: 'manual-password-number' }, null, 2));
    return;
  }
  if (command === 'legacy-from-wallet') {
    const source = await loadVault(input.sourceName, input.sourcePin);
    const format = input.format === 'swd1' ? 'swd1' : 'swd2';
    const encoded = runSwd(format === 'swd1' ? 'swd-encode-v1-json' : 'swd-encode-json', source.mnemonic);
    const generated = runSwd('swd-legacy-24-json', JSON.stringify({ password: encoded.password, number: encoded.number, wordCount: 24 }));
    const legacyInput = { password: encoded.password, number: String(encoded.number), wordCount: 24 };
    const created = await createRecoveredVault({ name: input.name, pin: input.pin, secretPayload: { legacyInput, createdAt: new Date().toISOString() }, metadata: { source: `legacy-from-${format}`, parent: safeName(input.sourceName), wordCount: 24, hidden: false, restorable: true } });
    console.log(JSON.stringify({ ...created, legacyAddress: generated.address, source: format }, null, 2));
    return;
  }
  if (command === 'change-pin') {
    const oldDocument = await readVaultDocument(input.name);
    const payload = decryptVault(oldDocument, input.oldPin);
    const metadata = { ...(oldDocument.metadata ?? {}), name: safeName(input.name), changedAt: new Date().toISOString() };
    const document = encryptVault(payload, input.newPin, metadata);
    await replaceVaultDocument(input.name, document);
    console.log(JSON.stringify({ changed: true, name: safeName(input.name) })); return;
  }
  if (command === 'factory-reset') {
    if (input.confirm !== 'FACTORY RESET') throw new Error('Reset wymaga dokładnego potwierdzenia FACTORY RESET.');
    await loadVaultRaw(input.name, input.passphrase);
    const files = await readdir(vaultDirectory);
    for (const filename of files) {
      if (/^[a-zA-Z0-9_-]{1,32}\.vault\.json(?:\.new(?:-[0-9]+)?)?$/u.test(filename)) await unlink(join(vaultDirectory, filename));
    }
    const settings = resolve(process.env.HOME ?? '/var/lib/entropysilo', 'settings.json');
    try { await unlink(settings); } catch (error) { if (error.code !== 'ENOENT') throw error; }
    console.log(JSON.stringify({ reset: true }));
    return;
  }
  if (command === 'list') {
    await mkdir(vaultDirectory, { recursive: true, mode: 0o700 });
    const names = (await readdir(vaultDirectory)).filter((name) => name.endsWith('.vault.json')).map((name) => basename(name, '.vault.json')).sort();
    console.log(JSON.stringify({ wallets: names })); return;
  }
  if (command === 'catalog') {
    await mkdir(vaultDirectory, { recursive: true, mode: 0o700 });
    const names = (await readdir(vaultDirectory)).filter((name) => name.endsWith('.vault.json')).map((name) => basename(name, '.vault.json')).sort();
    const wallets = [];
    for (const name of names) {
      try {
        const item = publicMetadata(name, await readVaultDocument(name));
        if (input.includeHidden === true || !item.hidden) wallets.push(item);
      } catch { wallets.push({ name, source: 'damaged-metadata', wordCount: null, hidden: false }); }
    }
    console.log(JSON.stringify({ wallets })); return;
  }
  if (command === 'backup-export') {
    await mkdir(vaultDirectory, { recursive: true, mode: 0o700 });
    const names = (await readdir(vaultDirectory)).filter((name) => name.endsWith('.vault.json')).map((name) => basename(name, '.vault.json')).sort();
    if (names.length === 0) throw new Error('Brak portfeli do backupu.');
    const wallets = [];
    for (const name of names) wallets.push({ name, document: await readVaultDocument(name) });
    const payload = { format: 'entropysilo-backup-payload', version: 2, createdAt: new Date().toISOString(), wallets };
    console.log(JSON.stringify(encryptBackup(payload, input.backupPassphrase))); return;
  }
  if (command === 'backup-import') {
    const payload = decryptBackup(input.backup, input.backupPassphrase);
    const currentPayload = payload?.format === 'entropysilo-backup-payload' && payload?.version === 2;
    const legacyPayload = payload?.format === 'rpiwallet-backup-payload' && payload?.version === 1;
    if ((!currentPayload && !legacyPayload) || !Array.isArray(payload.wallets) || payload.wallets.length < 1 || payload.wallets.length > 100) throw new Error('Nieprawidłowa zawartość backupu.');
    await mkdir(vaultDirectory, { recursive: true, mode: 0o700 });
    const checked = [];
    for (const item of payload.wallets) {
      const name = safeName(item?.name); const document = item?.document;
      const currentVault = document?.format === 'entropysilo-vault' && document?.version === 3;
      const legacyVault = document?.format === 'rpiwallet-vault' && [1, 2].includes(document?.version);
      if ((!currentVault && !legacyVault) || typeof document?.ciphertext !== 'string') throw new Error(`Backup zawiera uszkodzony skarbiec: ${name}.`);
      try { await readFile(vaultPath(name)); throw new Error(`Portfel ${name} już istnieje.`); }
      catch (error) { if (error.code !== 'ENOENT') throw error; }
      checked.push({ name, document });
    }
    for (const item of checked) await saveVault(item.name, item.document);
    console.log(JSON.stringify({ restored: checked.map((item) => item.name), count: checked.length })); return;
  }
  if (command === 'set-hidden') {
    const metadata = await updateMetadata(input.name, input.passphrase, { hidden: input.hidden === true });
    console.log(JSON.stringify({ updated: true, metadata })); return;
  }
  if (command === 'delete-wallet') {
    const name = safeName(input.name);
    await loadVaultRaw(name, input.passphrase);
    if (input.confirm !== `DELETE ${name}`) throw new Error(`Usunięcie wymaga potwierdzenia DELETE ${name}.`);
    await unlink(vaultPath(name));
    console.log(JSON.stringify({ deleted: true, name })); return;
  }
  if (command === 'bip85-create') {
    const parentName = safeName(input.parentName);
    const parent = await loadVault(parentName, input.parentPin);
    const child = deriveBip85Mnemonic({
      mnemonic: parent.mnemonic, bip39Passphrase: String(input.parentBip39Passphrase ?? ''),
      index: Number(input.index), words: 24,
    });
    const name = safeName(input.name);
    const payload = swdPayload(child.mnemonic);
    const metadata = {
      name, createdAt: payload.createdAt, source: 'bip85-child', parent: parentName,
      bip85Index: child.index, bip85Path: child.path, wordCount: 24, hidden: false, restorable: true,
    };
    const document = encryptVault(payload, input.pin, metadata);
    await saveVault(name, document);
    await updateMetadata(parentName, input.parentPin, { bip85Root: true });
    console.log(JSON.stringify({
      name, parent: parentName, bip85Index: child.index, bip85Path: child.path,
      firstAddress: deriveAddress({ mnemonic: child.mnemonic, purpose: 84, network: input.network ?? 'bitcoin' }),
    }, null, 2)); return;
  }
  if (command === 'verify') {
    await loadVaultRaw(input.name, input.passphrase);
    console.log(JSON.stringify({ unlocked: true, name: safeName(input.name) })); return;
  }
  if (command === 'address') {
    const loaded = await loadVault(input.name, input.passphrase);
    if (loaded.wif) {
      const types = addressTypesFromWif({ wif: loaded.wif, network: input.network ?? loaded.network ?? 'bitcoin' });
      const result = types.find((item) => item.purpose === Number(input.purpose ?? 84));
      console.log(JSON.stringify(result, null, 2)); return;
    }
    const payload = effectiveSecret(loaded, input);
    console.log(JSON.stringify(deriveAddress({ ...payload, ...input, mnemonic: payload.mnemonic, bip39Passphrase: signingPassphrase(input) }), null, 2)); return;
  }
  if (command === 'address-types') {
    const loaded = await loadVault(input.name, input.passphrase);
    if (loaded.wif) {
      console.log(JSON.stringify({ types: addressTypesFromWif({ wif: loaded.wif, network: input.network ?? loaded.network ?? 'bitcoin' }) }, null, 2)); return;
    }
    const payload = effectiveSecret(loaded, input);
    const types = deriveAddressTypes({ ...payload, ...input, mnemonic: payload.mnemonic, bip39Passphrase: signingPassphrase(input) });
    console.log(JSON.stringify({ types }, null, 2)); return;
  }
  if (command === 'addresses') {
    const payload = effectiveSecret(await loadVault(input.name, input.passphrase), input);
    const start = Number(input.start ?? 0); const count = Number(input.count ?? 10);
    if (!Number.isSafeInteger(start) || start < 0 || !Number.isSafeInteger(count) || count < 1 || count > 50) throw new Error('Zakres adresów jest nieprawidłowy.');
    const addresses = Array.from({ length: count }, (_, offset) => deriveAddress({
      ...input, mnemonic: payload.mnemonic, bip39Passphrase: signingPassphrase(input), index: start + offset,
    }));
    console.log(JSON.stringify({ addresses, accountXpub: addresses[0].accountXpub, masterFingerprint: addresses[0].masterFingerprint }, null, 2)); return;
  }
  if (command === 'inspect') {
    console.log(JSON.stringify(inspectPsbt(input.psbt, input.network), null, 2)); return;
  }
  if (command === 'sign') {
    if (input.confirm !== true) throw new Error('Podpis wymaga confirm:true po sprawdzeniu wszystkich wyjść i opłaty.');
    const loaded = await loadVault(input.name, input.passphrase);
    if (loaded.wif) {
      console.log(JSON.stringify(signPsbtWithWif({ ...input, ...loaded, network: input.network ?? loaded.network }), null, 2)); return;
    }
    const payload = effectiveSecret(loaded, input);
    console.log(JSON.stringify(signPsbt({ ...input, ...payload, bip39Passphrase: signingPassphrase(input) }), null, 2)); return;
  }
  throw new Error('Użycie: wallet-cli.js create|list|address|inspect|sign (JSON przez stdin).');
}

main().catch((error) => { console.error(JSON.stringify({ error: error.message })); process.exitCode = 1; });
