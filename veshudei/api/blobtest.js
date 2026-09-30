import { get, put } from '@vercel/blob';

export default async function handler(req, res) {
  try {
    const pathname = 'veshudei/healthcheck.json';
    const payload = JSON.stringify({ ok: true, ts: new Date().toISOString() });
    await put(pathname, payload, {
      access: 'private',
      allowOverwrite: true,
      addRandomSuffix: false,
      contentType: 'application/json',
      cacheControlMaxAge: 0
    });
    const result = await get(pathname, { access: 'private', useCache: false });
    if (!result || result.statusCode !== 200) throw new Error('Blob readback failed');
    const body = await new Response(result.stream).text();
    return res.status(200).json({ ok: true, write: true, read: true, body: JSON.parse(body) });
  } catch (error) {
    return res.status(500).json({ ok: false, error: String(error?.message || error) });
  }
}
