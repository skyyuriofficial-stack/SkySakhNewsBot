import { mkdir, copyFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const out = resolve('ocr-data');
await mkdir(out, { recursive: true });

for (const lang of ['rus', 'eng']) {
  const src = resolve('node_modules', '@tesseract.js-data', lang, '4.0.0_best_int', lang + '.traineddata.gz');
  const dst = resolve(out, lang + '.traineddata.gz');
  await copyFile(src, dst);
  console.log('prepared OCR data:', lang);
}
