import { loadState, saveState } from '../lib/store.js';
import { sendMessage, telegram } from '../lib/telegram.js';

function promptFor(schedule) {
  const prompts = {
    '37 21 * * *': {
      text: '<b>08:37 — утренний контроль.</b>\nВес после туалета до еды/питья. Затем отметим алкоголь накануне, аппетит, сон и самочувствие.',
      keyboard: { inline_keyboard: [[{ text: '⚖️ Ввести вес', callback_data: 'menu:weight' }, { text: '🩺 Самочувствие', callback_data: 'menu:symptoms' }], [{ text: '🍺 Алкоголь', callback_data: 'menu:alcohol' }]] }
    },
    '45 1 * * *': {
      text: '<b>12:45 — контроль перед обедом.</b>\nЗапиши, что собираешься есть. Отдельно отметь орлистат, если принимаешь.',
      keyboard: { inline_keyboard: [[{ text: '🍽 Обед', callback_data: 'menu:meal' }, { text: '💊 Орлистат', callback_data: 'menu:orlistat' }]] }
    },
    '30 5 * * *': {
      text: '<b>16:30 — дневной контроль.</b>\nВода, активность и что уже съел. Если намечается алкоголь — лучше отметить заранее.',
      keyboard: { inline_keyboard: [[{ text: '💧 Вода', callback_data: 'menu:water' }, { text: '🚶 Активность', callback_data: 'menu:activity' }], [{ text: '🍺 Алкоголь', callback_data: 'menu:alcohol' }]] }
    },
    '30 9 * * *': {
      awaitingType: 'evening_checkin',
      text: '<b>20:30 — вечерний дневник.</b>\nОтветь одним сообщением по пунктам:\n1) что и примерно сколько съел за день;\n2) был ли алкоголь и сколько;\n3) сколько Листаты Мини 60 мг принял и с какими приёмами пищи;\n4) сколько воды выпил;\n5) была ли ходьба, зарядка, тренировка или сколько примерно шагов;\n6) насколько голоден вечером по шкале 0–10;\n7) были ли тошнота, боль в животе, рвота, изжога, запор или диарея.\n\nПосле ответа дам короткий разбор и один конкретный план на завтра. Компенсационного голодания не будет.',
      keyboard: { inline_keyboard: [[{ text: '📊 Что уже записано', callback_data: 'menu:today' }, { text: '🌙 Ответить позже', callback_data: 'menu:evening' }]] }
    },
    '20 21 * * 0': {
      text: '<b>Понедельник — недельный контроль.</b>\nВес, талия, алкоголь за неделю, Семавик, Листата и средняя активность. Начни с веса.',
      keyboard: { inline_keyboard: [[{ text: '⚖️ Ввести вес', callback_data: 'menu:weight' }, { text: '💉 Семавик', callback_data: 'menu:semavik' }], [{ text: '📊 Сегодня', callback_data: 'menu:today' }]] }
    }
  };
  return prompts[schedule] || prompts['30 9 * * *'];
}

export default async function handler(req, res) {
  try {
    const proto = req.headers['x-forwarded-proto'] || 'https';
    const productionHost = process.env.VERCEL_PROJECT_PRODUCTION_URL || req.headers.host;
    if (productionHost) {
      const base = /^https?:\/\//i.test(productionHost) ? productionHost : proto + '://' + productionHost;
      const webhook = base.replace(/\/$/, '') + '/api/telegram';
      await telegram('setWebhook', {
        url: webhook,
        allowed_updates: ['message', 'callback_query'],
        drop_pending_updates: false
      });
      const info = await telegram('getWebhookInfo');
      if (!info || info.url !== webhook) throw new Error('Webhook verification failed');
    }

    const schedule = String(req.headers['x-vercel-cron-schedule'] || '');
    const state = await loadState();
    if (!state.chatId) return res.status(200).json({ ok: true, skipped: 'no-chat' });

    const p = promptFor(schedule);
    if (p.awaitingType) {
      state.awaiting = { type: p.awaitingType, meta: {}, at: new Date().toISOString() };
      await saveState(state);
    }
    await sendMessage(state.chatId, p.text, p.keyboard);
    return res.status(200).json({ ok: true, schedule });
  } catch (error) {
    console.error(error);
    return res.status(500).json({ ok: false, error: String(error?.message || error) });
  }
}
