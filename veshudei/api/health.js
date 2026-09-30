export default async function handler(req, res) {
  return res.status(200).json({
    ok: true,
    service: '@veshudei_bot',
    telegramTokenConfigured: Boolean(process.env.TELEGRAM_BOT_TOKEN),
    blobConfigured: Boolean(process.env.BLOB_READ_WRITE_TOKEN || process.env.VERCEL_OIDC_TOKEN),
    time: new Date().toISOString()
  });
}
