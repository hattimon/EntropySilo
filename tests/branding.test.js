import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

async function source(path) {
  return readFile(new URL(`../${path}`, import.meta.url), 'utf8');
}

test('EntropySilo is the active runtime identity and English is the default language', async () => {
  const [gui, uiUnit, liveUnit, usbHelper] = await Promise.all([
    source('apps/wallet_gui.py'),
    source('systemd/wallet-ui.service'),
    source('systemd/wallet-ui-live.service'),
    source('apps/entropysilo-usb'),
  ]);

  assert.match(gui, /"language": "en"/u);
  assert.match(gui, /English \(default\)/u);
  assert.match(gui, /ENTROPYSILO_PRIVILEGED_SOCKET/u);
  assert.match(uiUnit, /\/opt\/entropysilo/u);
  assert.match(liveUnit, /xserver-entropysilo\.service/u);
  assert.match(usbHelper, /MOUNT_DIR\/EntropySilo/u);

  for (const activeSource of [gui, uiUnit, liveUnit, usbHelper]) {
    assert.doesNotMatch(activeSource, /\/opt\/rpiwallet|\/var\/lib\/rpiwallet|\/run\/rpiwallet|\/RPiWallet|RPIWALLET_/u);
  }
});

test('new backups use .eswb while legacy .rpwb restore remains explicitly supported', async () => {
  const [usbHelper, core] = await Promise.all([
    source('apps/entropysilo-usb'),
    source('apps/wallet-core.js'),
  ]);
  assert.match(usbHelper, /backup\.eswb/u);
  assert.match(usbHelper, /\(eswb\|rpwb\)/u);
  assert.match(core, /LEGACY_BACKUP_FORMAT = 'rpiwallet-backup'/u);
  assert.match(core, /BACKUP_FORMAT = 'entropysilo-backup'/u);
});
