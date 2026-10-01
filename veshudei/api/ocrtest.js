import { mkdir, readFile, writeFile, access } from 'node:fs/promises';
import { join } from 'node:path';

export const config = { maxDuration: 30 };

const OCR_DATA = {
  rus: new URL('../ocr-data/rus.traineddata.gz', import.meta.url),
  eng: new URL('../ocr-data/eng.traineddata.gz', import.meta.url)
};

async function langPath() {
  const dir = '/tmp/veshudei-tessdata';
  await mkdir(dir, { recursive: true });
  for (const lang of ['rus','eng']) {
    const dst = join(dir, lang + '.traineddata.gz');
    try { await access(dst); continue; } catch (_) {}
    await writeFile(dst, await readFile(OCR_DATA[lang]));
  }
  return dir;
}

export default async function handler(req, res) {
  let worker = null;
  try {
    const sharpMod = await import('sharp');
    const sharp = sharpMod.default || sharpMod;
    const { createWorker } = await import('tesseract.js');

    const svg = Buffer.from('<svg width="1000" height="300" xmlns="http://www.w3.org/2000/svg"><rect width="100%" height="100%" fill="white"/><text x="40" y="110" font-size="54" font-family="Arial" fill="black">Салат Боул 310 г</text><text x="40" y="210" font-size="46" font-family="Arial" fill="black">Жиры 8,7 г 159 ккал</text></svg>');
    const png = await sharp(svg).png().toBuffer();

    worker = await createWorker(['rus','eng'], 1, {
      langPath: await langPath(),
      gzip: true,
      cacheMethod: 'none'
    });
    const result = await worker.recognize(png);
    const text = String(result?.data?.text || '').trim();
    return res.status(200).json({ ok: true, text });
  } catch (error) {
    return res.status(200).json({ ok: false, error: String(error?.message || error) });
  } finally {
    try { if (worker) await worker.terminate(); } catch (_) {}
  }
}
