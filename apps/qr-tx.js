#!/usr/bin/env node
import { mkdir, readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import QRCode from 'qrcode';
import { createHash } from 'node:crypto';

async function stdin() { const chunks = []; for await (const chunk of process.stdin) chunks.push(Buffer.from(chunk)); return Buffer.concat(chunks).toString('utf8').trim(); }
const args = process.argv.slice(2);
const fileIndex = args.indexOf('--file');
const outputIndex = args.indexOf('--output');
const data = fileIndex >= 0 ? (await readFile(args[fileIndex + 1], 'utf8')).trim() : await stdin();
if (!data) throw new Error('Brak danych QR.');
const output = resolve(outputIndex >= 0 ? args[outputIndex + 1] : '/tmp/entropysilo-qr');
const chunkSize = 700;
const chunks = data.length <= 1000 ? [data] : Array.from({ length: Math.ceil(data.length / chunkSize) }, (_, i) => data.slice(i * chunkSize, (i + 1) * chunkSize));
const id = createHash('sha256').update(data).digest('hex').slice(0, 8);
await mkdir(output, { recursive: true, mode: 0o700 });
const files = [];
for (let index = 0; index < chunks.length; index += 1) {
  const payload = chunks.length === 1 ? chunks[index] : `RPW1:${id}:${index + 1}:${chunks.length}:${chunks[index]}`;
  const filename = resolve(output, `qr-${String(index + 1).padStart(3, '0')}.png`);
  await QRCode.toFile(filename, payload, { errorCorrectionLevel: 'M', margin: 2, width: 420, color: { dark: '#000000', light: '#ffffff' } });
  files.push(filename);
}
if (args.includes('--terminal')) console.log(await QRCode.toString(data, { type: 'utf8', errorCorrectionLevel: 'M', small: true }));
console.log(JSON.stringify({ id, multipart: files.length > 1, frameCount: files.length, files }));
