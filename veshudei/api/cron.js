import { loadState } from '../lib/store.js';
import { sendMessage, telegram } from '../lib/telegram.js';

function promptFor(schedule) {
  const prompts = {
    '45 6 * * *': {
      repairOnly: true,
      text: '',
      keyboard: null
    },
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
      text: '<b>20:30 — итог дня.</b>\nЗакрой дневник: еда, алкоголь, лекарства, активность и самочувствие.',
      keyboard: { inline_keyboard: [[{ text: '📊 Что записано', callback_data: 'menu:today' }, { text: '🍽 Еда', callback_data: 'menu:meal' }], [{ text: '🩺 Самочувствие', callback_data: 'menu:symptoms' }]] }
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
    const host = req.headers.host;
    if (host) {
      const webhook = proto + '://' + host + '/api/telegram';
      await telegram('setWebhook', {
        url: webhook,
        allowed_updates: ['message', 'callback_query'],
        drop_pending_updates: false
      });
    }
    const state = await loadState();
    if (!state.chatId) return res.status(200).json({ ok: true, skipped: 'no-chat' });
    const schedule = String(req.headers['x-vercel-cron-schedule'] || '');
    const p = promptFor(schedule);
    if (p.repairOnly) return res.status(200).json({ ok: true, schedule, webhookRepaired: true });
    await sendMessage(state.chatId, p.text, p.keyboard);
    return res.status(200).json({ ok: true, schedule });
  } catch (error) {
    console.error(error);
    return res.status(500).json({ ok: false, error: String(error?.message || error) });
  }
}
