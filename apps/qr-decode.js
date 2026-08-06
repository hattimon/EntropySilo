#!/usr/bin/env node
import jsQR from 'jsqr';
import { PNG } from 'pngjs';
import jpeg from 'jpeg-js';

const chunks = [];
for await (const chunk of process.stdin) chunks.push(Buffer.from(chunk));

try {
  const input = JSON.parse(Buffer.concat(chunks).toString('utf8'));
  let width; let height; let rgba;
  if (input.format === 'rgb') {
    width = Number(input.width); height = Number(input.height);
    const rgb = Buffer.from(String(input.dataBase64 ?? ''), 'base64');
    if (!Number.isSafeInteger(width) || !Number.isSafeInteger(height) || width < 64 || height < 64 || width * height > 16_000_000 || rgb.length !== width * height * 3) throw new Error('Nieprawidłowa klatka RGB.');
    rgba = Buffer.allocUnsafe(width * height * 4);
    for (let source = 0, target = 0; source < rgb.length; source += 3, target += 4) {
      rgba[target] = rgb[source]; rgba[target + 1] = rgb[source + 1]; rgba[target + 2] = rgb[source + 2]; rgba[target + 3] = 255;
    }
    rgb.fill(0);
  } else {
    const encoded = Buffer.from(String(input.dataBase64 ?? ''), 'base64');
    if (encoded.length < 16 || encoded.length > 16 * 1024 * 1024) throw new Error('Nieprawidłowy rozmiar obrazu QR.');
    const decoded = input.format === 'png' ? PNG.sync.read(encoded, { checkCRC: true })
      : input.format === 'jpg' || input.format === 'jpeg' ? jpeg.decode(encoded, { useTArray: true, formatAsRGBA: true })
        : (() => { throw new Error('Obsługiwany jest tylko PNG albo JPEG.'); })();
    width = decoded.width; height = decoded.height; rgba = Buffer.from(decoded.data);
    encoded.fill(0);
    if (width < 64 || height < 64 || width * height > 16_000_000) throw new Error('Nieprawidłowe wymiary obrazu QR.');
  }
  const result = jsQR(new Uint8ClampedArray(rgba.buffer, rgba.byteOffset, rgba.byteLength), width, height, { inversionAttempts: 'attemptBoth' });
  rgba.fill(0);
  if (!result?.data) throw new Error('Nie znaleziono kodu QR na obrazie.');
  if (result.data.length > 2 * 1024 * 1024) throw new Error('Dane QR są zbyt duże.');
  console.log(JSON.stringify({ data: result.data, width, height }));
} catch (error) {
  console.error(JSON.stringify({ error: error.message }));
  process.exitCode = 1;
}
