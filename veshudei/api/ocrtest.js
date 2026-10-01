export const config = { maxDuration: 30 };

export default async function handler(req, res) {
  let worker = null;
  try {
    const sharpMod = await import('sharp');
    const sharp = sharpMod.default || sharpMod;
    const { createWorker } = await import('tesseract.js');

    const svg = Buffer.from('<svg width="1000" height="300" xmlns="http://www.w3.org/2000/svg"><rect width="100%" height="100%" fill="white"/><text x="40" y="110" font-size="54" font-family="Arial" fill="black">Салат Боул 310 г</text><text x="40" y="210" font-size="46" font-family="Arial" fill="black">Жиры 8,7 г  159 ккал</text></svg>');
    const png = await sharp(svg).png().toBuffer();

    worker = await createWorker('rus+eng');
    const result = await worker.recognize(png);
    const text = String(result?.data?.text || '').trim();
    return res.status(200).json({ ok: true, text });
  } catch (error) {
    return res.status(200).json({ ok: false, error: String(error?.message || error) });
  } finally {
    try { if (worker) await worker.terminate(); } catch (_) {}
  }
}
