import { get } from '@vercel/blob';
import { telegram } from '../lib/telegram.js';
import { providerConfigured } from '../lib/provider-secret.js';

export default async function handler(req, res) {
  let blobOperational = false;
  let bot = null;
  let webhook = null;
  let openRouterPrivate = false;

  try {
    const result = await get('veshudei/healthcheck.json', { access: 'private', useCache: false });
    blobOperational = Boolean(result && result.statusCode === 200);
  } catch (_) {
    blobOperational = false;
  }

  try {
    openRouterPrivate = await providerConfigured();
  } catch (_) {
    openRouterPrivate = false;
  }

  try {
    const me = await telegram('getMe');
    bot = { id: me?.id || null, username: me?.username || null };
    const info = await telegram('getWebhookInfo');
    webhook = {
      url: info?.url || '',
      pending_update_count: info?.pending_update_count ?? null,
      last_error_date: info?.last_error_date ?? null,
      last_error_message: info?.last_error_message || null,
      max_connections: info?.max_connections ?? null,
      allowed_updates: info?.allowed_updates || null
    };
  } catch (error) {
    webhook = { error: String(error?.message || error) };
  }

  return res.status(200).json({
    ok: true,
    service: '@veshudei_bot',
    telegramTokenConfigured: Boolean(process.env.TELEGRAM_BOT_TOKEN),
    aiProviders: {
      openrouter: openRouterPrivate,
      openai: Boolean(process.env.OPENAI_API_KEY),
      vercelGateway: Boolean(process.env.AI_GATEWAY_API_KEY || process.env.ENABLE_VERCEL_AI_GATEWAY === '1')
    },
    photoRecognitionReady: Boolean(openRouterPrivate || process.env.OPENAI_API_KEY),
    blobOperational,
    productionUrl: process.env.VERCEL_PROJECT_PRODUCTION_URL || null,
    bot,
    webhook,
    time: new Date().toISOString()
  });
}
