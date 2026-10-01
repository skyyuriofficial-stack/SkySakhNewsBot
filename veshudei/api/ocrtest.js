import { mkdir, readFile, writeFile, access } from 'node:fs/promises';
import { join } from 'node:path';

export const config = { maxDuration: 60 };

const RUS_DATA = new URL('../ocr-data/rus.traineddata.gz', import.meta.url);

async function langPath() {
  const dir = '/tmp/veshudei-tessdata';
  await mkdir(dir, { recursive: true });
  const dst = join(dir, 'rus.traineddata.gz');
  try { await access(dst); } catch (_) { await writeFile(dst, await readFile(RUS_DATA)); }
  return dir;
}

export default async function handler(req, res) {
  let worker = null;
  const stage = String(req.query?.stage || 'recognize');
  const started = Date.now();
  try {
    const lp = await langPath();
    if (stage === 'files') {
      const data = await readFile(RUS_DATA);
      return res.status(200).json({ ok: true, stage, bytes: data.length, ms: Date.now() - started });
    }

    const { createWorker } = await import('tesseract.js');
    worker = await createWorker('rus', 1, { langPath: lp, gzip: true, cacheMethod: 'none' });
    if (stage === 'worker') {
      return res.status(200).json({ ok: true, stage, ms: Date.now() - started });
    }

    const sharpMod = await import('sharp');
    const sharp = sharpMod.default || sharpMod;
    const svg = Buffer.from('<svg width="1000" height="300" xmlns="http://www.w3.org/2000/svg"><rect width="100%" height="100%" fill="white"/><text x="40" y="110" font-size="54" font-family="Arial" fill="black">Салат Боул 310 г</text><text x="40" y="210" font-size="46" font-family="Arial" fill="black">Жиры 8,7 г 159 ккал</text></svg>');
    const png = await sharp(svg).png().toBuffer();
    const result = await worker.recognize(png);
    return res.status(200).json({ ok: true, stage, text: String(result?.data?.text || '').trim(), ms: Date.now() - started });
  } catch (error) {
    return res.status(200).json({ ok: false, stage, error: String(error?.message || error), ms: Date.now() - started });
  } finally {
    try { if (worker) await worker.terminate(); } catch (_) {}
  }
}
