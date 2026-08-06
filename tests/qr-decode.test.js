import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import QRCode from 'qrcode';

test('static PNG transaction QR round-trips without a temporary file', async () => {
  const payload = 'cHNidP8BAAoCAAAAAQ==';
  const png = await QRCode.toBuffer(payload, { type: 'png', width: 420, margin: 3, errorCorrectionLevel: 'M' });
  const result = spawnSync(process.execPath, ['apps/qr-decode.js'], {
    input: JSON.stringify({ format: 'png', dataBase64: png.toString('base64') }), encoding: 'utf8',
  });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(JSON.parse(result.stdout).data, payload);
});

test('QR decoder rejects unsupported data', () => {
  const result = spawnSync(process.execPath, ['apps/qr-decode.js'], {
    input: JSON.stringify({ format: 'exe', dataBase64: Buffer.alloc(64).toString('base64') }), encoding: 'utf8',
  });
  assert.notEqual(result.status, 0);
  assert.match(JSON.parse(result.stderr).error, /PNG albo JPEG/u);
});
