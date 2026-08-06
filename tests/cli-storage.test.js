import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

const cli = resolve('apps/wallet-cli.js');
const request = {
  name: 'duplicate_guard',
  passphrase: '123456789012',
  wif: 'KwDiBf89QgGbjEhKnhXJuH7LrciVrZi3qYjgd9M7rFU73sVHnoWn',
  network: 'bitcoin',
};

test('creating a wallet never overwrites an existing vault with the same name', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'entropysilo-cli-'));
  const env = { ...process.env, ENTROPYSILO_VAULT_DIR: directory };
  try {
    const first = spawnSync(process.execPath, [cli, 'recover-wif'], {
      input: JSON.stringify(request), encoding: 'utf8', env,
    });
    assert.equal(first.status, 0, first.stderr);
    const path = join(directory, 'duplicate_guard.vault.json');
    const original = await readFile(path, 'utf8');
    const second = spawnSync(process.execPath, [cli, 'recover-wif'], {
      input: JSON.stringify(request),
      encoding: 'utf8', env,
    });
    assert.notEqual(second.status, 0);
    assert.match(second.stderr, /już istnieje/u);
    assert.equal(await readFile(path, 'utf8'), original);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
