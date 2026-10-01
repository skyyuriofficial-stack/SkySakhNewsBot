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

export function menuKeyboard() {
  return { inline_keyboard: [
    [{ text: '⚖️ Вес', callback_data: 'menu:weight' }, { text: '🍽 Еда', callback_data: 'menu:meal' }],
    [{ text: '🍺 Алкоголь', callback_data: 'menu:alcohol' }, { text: '💉 Семавик', callback_data: 'menu:semavik' }],
    [{ text: '💊 Орлистат', callback_data: 'menu:orlistat' }, { text: '💧 Вода', callback_data: 'menu:water' }],
    [{ text: '🚶 Активность', callback_data: 'menu:activity' }, { text: '🩺 Самочувствие', callback_data: 'menu:symptoms' }],
    [{ text: '🧠 Совет / вопрос', callback_data: 'menu:advice' }, { text: '🌙 Итог дня', callback_data: 'menu:evening' }],
    [{ text: '📊 Сегодня', callback_data: 'menu:today' }]
  ]};
}
