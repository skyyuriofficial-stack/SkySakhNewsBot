import { loadState, saveState, todayEvents } from '../lib/store.js';
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


function eveningPrompt(state) {
  const events = todayEvents(state);
  const meals = events.filter((e) => e.type === 'meal');
  const alcohol = events.filter((e) => e.type === 'alcohol').slice(-1)[0];
  const water = events.filter((e) => e.type === 'water').slice(-1)[0];
  const activity = events.filter((e) => e.type === 'activity').slice(-1)[0];
  const symptoms = events.filter((e) => e.type === 'symptoms').slice(-1)[0];
  const orlistat = events.filter((e) => e.type === 'orlistat' && /(?:^|\D)60\s*мг/i.test(String(e.value || '')));

  const known = [];
  const missing = [];

  if (meals.length) known.push('🍽 еда: ' + meals.length + ' приём(а) уже в дневнике');
  else missing.push('что и примерно сколько съел за день');

  if (alcohol) known.push('🍺 алкоголь: ' + String(alcohol.value));
  else missing.push('был ли алкоголь и сколько');

  if (orlistat.length) known.push('💊 Листата: ' + orlistat.length + '/3 доз по 60 мг');
  else missing.push('сколько Листаты Мини 60 мг принял и с какими приёмами пищи');

  if (water) known.push('💧 вода: ' + String(water.value));
  else missing.push('сколько воды выпил');

  if (activity) known.push('🚶 активность: ' + String(activity.value));
  else missing.push('ходьба/зарядка/тренировка или сколько шагов');

  if (symptoms) known.push('🩺 самочувствие: ' + String(symptoms.value));
  else missing.push('были ли тошнота, боль в животе, рвота, изжога, запор или диарея');

  missing.push('насколько голоден сейчас по шкале 0–10');

  const knownText = known.length ? '<b>Уже знаю за сегодня:</b>\n' + known.join('\n') + '\n\n' : '';
  const askText = '<b>Осталось уточнить:</b>\n' + missing.map((x, i) => (i + 1) + ') ' + x).join('\n');

  return {
    awaitingType: 'evening_checkin',
    text: '<b>20:30 — вечерний дневник.</b>\n' +
      'Я не буду переспрашивать то, что уже собрал автоматически.\n\n' +
      knownText + askText +
      '\n\nОтветь одним сообщением в свободной форме. После этого дам короткий разбор и один конкретный план на завтра — без компенсационного голодания.',
    keyboard: {
      inline_keyboard: [
        [{ text: '📊 Что уже записано', callback_data: 'menu:today' }, { text: '🌙 Заполнить итог', callback_data: 'menu:evening' }]
      ]
    }
  };
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

    const p = schedule === '30 9 * * *' ? eveningPrompt(state) : promptFor(schedule);
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
