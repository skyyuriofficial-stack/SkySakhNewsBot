import { loadState } from '../lib/store.js';
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

    if (schedule === '53 8 * * *') {
      const me = await telegram('getMe');
      const before = await telegram('getWebhookInfo');
      const productionHost = process.env.VERCEL_PROJECT_PRODUCTION_URL || req.headers.host;
      const base = /^https?:\/\//i.test(productionHost || '') ? productionHost : 'https://' + productionHost;
      const canonicalWebhook = base.replace(/\/$/, '') + '/api/telegram';
      const setResult = await telegram('setWebhook', {
        url: canonicalWebhook,
        allowed_updates: ['message', 'callback_query'],
        drop_pending_updates: false
      });
      const after = await telegram('getWebhookInfo');

      let selfTest = 'not-run';
      if (state.chatId) {
        try {
          const fakeUpdate = {
            update_id: 999999991,
            message: {
              message_id: 999999991,
              date: Math.floor(Date.now()/1000),
              chat: { id: state.chatId, type: 'private' },
              from: { id: state.userId || state.chatId, is_bot: false, first_name: 'SelfTest' },
              text: '/today'
            }
          };
          const rr = await fetch(canonicalWebhook, {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify(fakeUpdate)
          });
          selfTest = String(rr.status);
        } catch (e) {
          selfTest = 'ERR ' + String(e?.message || e);
        }

        const diag = '<b>Veshudei DIAG</b>\n' +
          'bot=@' + String(me?.username || '?') + '\n' +
          'before=' + String(before?.url || '(empty)') + '\n' +
          'before pending=' + String(before?.pending_update_count ?? '?') + '\n' +
          'before error=' + String(before?.last_error_message || 'none') + '\n' +
          'target=' + canonicalWebhook + '\n' +
          'setWebhook=' + String(setResult) + '\n' +
          'after=' + String(after?.url || '(empty)') + '\n' +
          'after pending=' + String(after?.pending_update_count ?? '?') + '\n' +
          'after error=' + String(after?.last_error_message || 'none') + '\n' +
          'self-test HTTP=' + selfTest;
        await sendMessage(state.chatId, diag);
      }
      return res.status(200).json({ ok: true, diagnostic: true, selfTest });
    }

    if (schedule === '30 8 * * *' || schedule === '45 8 * * *') return res.status(200).json({ ok: true, schedule, webhookRepaired: true });
    if (!state.chatId) return res.status(200).json({ ok: true, skipped: 'no-chat' });
    const p = promptFor(schedule);
    await sendMessage(state.chatId, p.text, p.keyboard);
    return res.status(200).json({ ok: true, schedule });
  } catch (error) {
    console.error(error);
    return res.status(500).json({ ok: false, error: String(error?.message || error) });
  }
}
