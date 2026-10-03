const API = (token) => 'https://api.telegram.org/bot' + token;

export async function telegram(method, payload = {}) {
  const token = process.env.TELEGRAM_BOT_TOKEN;
  if (!token) throw new Error('TELEGRAM_BOT_TOKEN is not configured');
  const response = await fetch(API(token) + '/' + method, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload)
  });
  const data = await response.json();
  if (!data.ok) throw new Error('Telegram ' + method + ' failed: ' + JSON.stringify(data));
  return data.result;
}

export function sendMessage(chatId, text, replyMarkup) {
  const payload = { chat_id: chatId, text, parse_mode: 'HTML', disable_web_page_preview: true };
  if (replyMarkup) payload.reply_markup = replyMarkup;
  return telegram('sendMessage', payload);
}

export function answerCallback(callbackQueryId, text = '') {
  return telegram('answerCallbackQuery', { callback_query_id: callbackQueryId, text });
}

export async function ensureWebhook(webhookUrl) {
  const expected = String(webhookUrl || '').replace(/\/$/, '');
  if (!expected) return { ok: false, repaired: false, reason: 'missing-webhook-url' };

  const info = await telegram('getWebhookInfo');
  const current = String(info?.url || '').replace(/\/$/, '');
  const pending = Number(info?.pending_update_count || 0);
  const hasRecentError = Boolean(info?.last_error_message) && pending > 0;

  if (current !== expected || hasRecentError) {
    await telegram('setWebhook', {
      url: expected,
      allowed_updates: ['message', 'callback_query'],
      drop_pending_updates: false
    });
    const refreshed = await telegram('getWebhookInfo');
    const refreshedUrl = String(refreshed?.url || '').replace(/\/$/, '');
    return {
      ok: refreshedUrl === expected,
      repaired: true,
      url: refreshedUrl,
      pending_update_count: Number(refreshed?.pending_update_count || 0),
      last_error_message: refreshed?.last_error_message || null
    };
  }

  return {
    ok: true,
    repaired: false,
    url: current,
    pending_update_count: pending,
    last_error_message: info?.last_error_message || null
  };
}

export async function downloadTelegramFile(fileId) {
  const token = process.env.TELEGRAM_BOT_TOKEN;
  if (!token) throw new Error('TELEGRAM_BOT_TOKEN is not configured');
  const info = await telegram('getFile', { file_id: fileId });
  if (!info?.file_path) throw new Error('Telegram file_path missing');
  const response = await fetch('https://api.telegram.org/file/bot' + token + '/' + info.file_path);
  if (!response.ok) throw new Error('Telegram file download failed: HTTP ' + response.status);
  const bytes = new Uint8Array(await response.arrayBuffer());
  return {
    bytes,
    filePath: info.file_path,
    mimeType: info.file_path.toLowerCase().endsWith('.png') ? 'image/png' : 'image/jpeg'
  };
}

export function menuKeyboard() {
  return { inline_keyboard: [
    [{ text: '⚖️ Вес', callback_data: 'menu:weight' }, { text: '🍽 Еда', callback_data: 'menu:meal' }],
    [{ text: '🍺 Алкоголь', callback_data: 'menu:alcohol' }, { text: '💉 Семавик', callback_data: 'menu:semavik' }],
    [{ text: '💊 Листата 60 мг', callback_data: 'menu:orlistat' }, { text: '💧 Вода', callback_data: 'menu:water' }],
    [{ text: '🚶 Активность', callback_data: 'menu:activity' }, { text: '🩺 Самочувствие', callback_data: 'menu:symptoms' }],
    [{ text: '🧠 Совет / вопрос', callback_data: 'menu:advice' }, { text: '🌙 Итог дня', callback_data: 'menu:evening' }],
    [{ text: '📊 Сегодня', callback_data: 'menu:today' }]
  ]};
}
