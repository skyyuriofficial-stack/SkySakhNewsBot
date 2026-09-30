import { get } from '@vercel/blob';

export default async function handler(req, res) {
  let blobOperational = false;
  try {
    const result = await get('veshudei/healthcheck.json', { access: 'private', useCache: false });
    blobOperational = Boolean(result && result.statusCode === 200);
  } catch (_) {
    blobOperational = false;
  }
  return res.status(200).json({
    ok: true,
    service: '@veshudei_bot',
    telegramTokenConfigured: Boolean(process.env.TELEGRAM_BOT_TOKEN),
    blobOperational,
    time: new Date().toISOString()
  });
}
