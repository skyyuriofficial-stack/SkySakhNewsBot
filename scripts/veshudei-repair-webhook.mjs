const token = process.env.TELEGRAM_BOT_TOKEN;
const env = process.env.VERCEL_ENV;
const productionHost = process.env.VERCEL_PROJECT_PRODUCTION_URL;

if (env !== 'production' || !token || !productionHost) {
  console.log('veshudei webhook repair skipped');
  process.exit(0);
}

const base = productionHost.startsWith('http://') || productionHost.startsWith('https://')
  ? productionHost
  : 'https://' + productionHost;
const webhook = base.replace(/\/$/, '') + '/api/telegram';

try {
  const response = await fetch('https://api.telegram.org/bot' + token + '/setWebhook', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      url: webhook,
      allowed_updates: ['message', 'callback_query'],
      drop_pending_updates: false
    })
  });
  const data = await response.json();
  if (!data.ok) console.warn('veshudei webhook repair rejected:', data.description || 'unknown');
  else console.log('veshudei webhook repaired for production');
} catch (error) {
  console.warn('veshudei webhook repair failed:', error && error.message ? error.message : String(error));
}

process.exit(0);
