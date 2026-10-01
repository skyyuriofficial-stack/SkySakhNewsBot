import { loadState, saveState, logEvent, todayEvents, lastEvent } from '../lib/store.js';
import { sendMessage, answerCallback, menuKeyboard } from '../lib/telegram.js';


function cbKeyboard(rows) {
  return { inline_keyboard: rows };
}

function asNumber(text) {
  const m = String(text || '').replace(',', '.').match(/\d+(?:\.\d+)?/);
  return m ? Number(m[0]) : NaN;
}

function escapeHtml(value) {
  return String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
}

async function askCoach(state, userText) {
  const text = String(userText || '').trim();
  const t = text.toLowerCase();
  const events = todayEvents(state);
  const meals = events.filter((e) => e.type === 'meal');
  const alcohol = events.filter((e) => e.type === 'alcohol' && String(e.value).toLowerCase() !== 'нет');
  const water = events.filter((e) => e.type === 'water').slice(-1)[0];
  const activity = events.filter((e) => e.type === 'activity').slice(-1)[0];

  if (/вечер.*не\s*ем|вечер.*не\s*есть|не\s*ужин|пропуст.*ужин/i.test(t)) {
    return 'Специально не есть вечером не нужно. Если голод есть — сделай умеренный ужин с белком и овощами; если голода нет, насильно есть не требуется. Не компенсируй дневной рацион голоданием.';
  }
  if (/что.*съесть|что.*есть|ужин/i.test(t)) {
    return 'На ужин выбери простой вариант: белковый продукт плюс овощи. Если голод слабый — небольшая порция; если голода нет, можно не есть насильно.';
  }
  if (/алкогол|пив|вино|водк|виски|коньяк/i.test(t)) {
    return 'Алкоголь учитываем отдельно: орлистат его калории не блокирует. На следующий день не компенсируй алкоголь голоданием — вернись к обычному режиму еды и воды.';
  }
  if (/листат|орлистат/i.test(t)) {
    return 'Листату Мини 60 мг не используй как компенсацию переедания. Принимай только по инструкции к препарату и не увеличивай дозу самостоятельно.';
  }
  if (/семавик|семаглутид/i.test(t)) {
    return 'Дозу Семавика самостоятельно не меняй. Если появились выраженная тошнота, повторная рвота или сильная боль в животе — нужна медицинская оценка.';
  }
  if (/итог|разбор|сегодня|день/i.test(t)) {
    const parts = [];
    if (meals.length) parts.push('Еда зафиксирована — это хорошо для контроля.');
    else parts.push('По еде данных мало.');
    if (alcohol.length) parts.push('Алкоголь сегодня был — это отдельный источник калорий и фактор колебаний веса.');
    if (!water) parts.push('Вода сегодня не отмечена.');
    if (!activity) parts.push('Активность сегодня не отмечена.');
    parts.push('План: завтра обычный режим питания без компенсационного голодания; добавь белок в основные приёмы пищи и 20–30 минут спокойной ходьбы.');
    return parts.join(' ');
  }
  return 'Понял. По сегодняшнему дневнику могу ответить про ужин, голод, алкоголь, воду, активность, вес, Семавик или Листату. Напиши вопрос обычным сообщением.';
}

function summaryText(state) {
  const allowed = new Set(['weight','meal','alcohol','semavik','orlistat','water','activity','symptoms']);
  const events = todayEvents(state).filter((e) => allowed.has(e.type));
  if (!events.length) return 'Сегодня пока ничего не записано.';
  const labels = {
    weight: '⚖️ Вес', meal: '🍽 Еда', alcohol: '🍺 Алкоголь', semavik: '💉 Семавик',
    orlistat: '💊 Орлистат', water: '💧 Вода', activity: '🚶 Активность', symptoms: '🩺 Самочувствие'
  };
  return '<b>Сегодня:</b>\n' + events.slice(-20).map((e) => (labels[e.type] || e.type) + ': ' + String(e.value)).join('\n');
}

async function setAwaiting(state, chatId, type, prompt, meta = {}) {
  state.awaiting = { type, meta, at: new Date().toISOString() };
  await saveState(state);
  await sendMessage(chatId, prompt);
}

async function handleCallback(q, state) {
  const chatId = q.message.chat.id;
  const data = q.data || '';
  await answerCallback(q.id);

  if (data === 'menu:weight') return setAwaiting(state, chatId, 'weight', 'Напиши вес одной цифрой, например <b>108.4</b>.');
  if (data === 'menu:meal') return setAwaiting(state, chatId, 'meal', 'Напиши коротко, что съел или собираешься съесть и примерно сколько.');
  if (data === 'menu:water') return setAwaiting(state, chatId, 'water', 'Сколько воды уже выпил сегодня? Например <b>1.2 л</b>.');
  if (data === 'menu:activity') return setAwaiting(state, chatId, 'activity', 'Напиши шаги или активность: например <b>4200 шагов</b> или <b>ходьба 25 мин</b>.');

  if (data === 'menu:alcohol') {
    return sendMessage(chatId, 'Алкоголь сегодня/вчера?', cbKeyboard([
      [{ text: 'Нет', callback_data: 'alcohol:none' }, { text: 'Пиво', callback_data: 'alcohol:beer' }],
      [{ text: 'Вино', callback_data: 'alcohol:wine' }, { text: 'Крепкое', callback_data: 'alcohol:strong' }],
      [{ text: 'Другое', callback_data: 'alcohol:other' }]
    ]));
  }

  if (data.startsWith('alcohol:')) {
    const kind = data.split(':')[1];
    if (kind === 'none') {
      logEvent(state, 'alcohol', 'нет'); state.awaiting = null; await saveState(state);
      return sendMessage(chatId, 'Учёл: алкоголя нет.', menuKeyboard());
    }
    return setAwaiting(state, chatId, 'alcohol_amount', 'Сколько примерно? Например <b>пиво 1.5 л</b> или <b>вино 300 мл</b>.', { kind });
  }

  if (data === 'menu:semavik') {
    return sendMessage(chatId, 'Семавик:', cbKeyboard([
      [{ text: '2.4 мг — укол сделан', callback_data: 'semavik:2.4' }],
      [{ text: 'Другая доза', callback_data: 'semavik:other' }, { text: 'Пропуск', callback_data: 'semavik:skip' }]
    ]));
  }
  if (data === 'semavik:2.4') {
    logEvent(state, 'semavik', '2.4 мг, укол сделан'); state.awaiting = null; await saveState(state);
    return sendMessage(chatId, 'Записал Семавик 2.4 мг. Дозу самостоятельно не повышаем.', menuKeyboard());
  }
  if (data === 'semavik:skip') {
    logEvent(state, 'semavik', 'пропуск'); state.awaiting = null; await saveState(state);
    return sendMessage(chatId, 'Записал пропуск.', menuKeyboard());
  }
  if (data === 'semavik:other') return setAwaiting(state, chatId, 'semavik_other', 'Напиши дозу и что произошло: например <b>1.7 мг, укол сделан</b>.');

  if (data === 'menu:orlistat') {
    return sendMessage(chatId, 'Орлистат / Листата:', cbKeyboard([
      [{ text: 'Не принимал', callback_data: 'orlistat:0' }, { text: '60 мг', callback_data: 'orlistat:60' }],
      [{ text: 'Другая доза', callback_data: 'orlistat:other' }]
    ]));
  }
  if (data === 'orlistat:0' || data === 'orlistat:60') {
    const val = data.endsWith(':60') ? '60 мг' : '0 мг';
    logEvent(state, 'orlistat', val); state.awaiting = null; await saveState(state);
    const note = val === '60 мг' ? ' Учёл орлистат. Дозу фиксируем по конкретному препарату.' : '';
    return sendMessage(chatId, 'Записал: ' + val + '.' + note, menuKeyboard());
  }
  if (data === 'orlistat:other') return setAwaiting(state, chatId, 'orlistat_other', 'Напиши дозу и с какой едой принимал.');

  if (data === 'menu:symptoms') {
    return sendMessage(chatId, 'Самочувствие:', cbKeyboard([
      [{ text: 'Нормально', callback_data: 'sym:ok' }, { text: 'Тошнота', callback_data: 'sym:nausea' }],
      [{ text: 'Боль в животе', callback_data: 'sym:pain' }, { text: 'Рвота', callback_data: 'sym:vomit' }],
      [{ text: 'Запор', callback_data: 'sym:constipation' }, { text: 'Диарея', callback_data: 'sym:diarrhea' }]
    ]));
  }
  if (data.startsWith('sym:')) {
    const map = { ok: 'нормально', nausea: 'тошнота', pain: 'боль в животе', vomit: 'рвота', constipation: 'запор', diarrhea: 'диарея' };
    const key = data.split(':')[1]; const val = map[key] || key;
    logEvent(state, 'symptoms', val); state.awaiting = null; await saveState(state);
    if (key === 'pain' || key === 'vomit') {
      return sendMessage(chatId, 'Записал: ' + val + '. Если боль сильная/постоянная или рвота повторяется — нужна медицинская оценка; при сильной боли в верхней части живота, особенно с рвотой, не откладывай обращение.', menuKeyboard());
    }
    return sendMessage(chatId, 'Записал: ' + val + '.', menuKeyboard());
  }

  if (data === 'menu:advice') return setAwaiting(state, chatId, 'advice', 'Спроси обычным текстом. Например: <b>«Вечером не ем?»</b>, <b>«Что лучше съесть?»</b> или <b>«Почему вес вырос?»</b>. Я отвечу с учётом дневника.');
  if (data === 'menu:today') return sendMessage(chatId, summaryText(state), menuKeyboard());
  return sendMessage(chatId, 'Выбери действие:', menuKeyboard());
}

async function handleText(message, state) {
  const chatId = message.chat.id;
  const text = String(message.text || '').trim();
  if (text === '/start') {
    state.chatId = chatId; state.userId = message.from?.id || null; state.username = message.from?.username || null; state.awaiting = null;
    logEvent(state, 'system', 'start'); await saveState(state);
    return sendMessage(chatId, '<b>Veshudei подключён.</b>\nЯ собираю вес, питание, алкоголь, Семавик, орлистат, воду, активность и самочувствие. Можешь также просто писать мне обычные вопросы — отвечу и дам рекомендацию с учётом дневника. Данные хранятся в приватном хранилище Vercel.', menuKeyboard());
  }
  if (text === '/menu') return sendMessage(chatId, 'Что записываем?', menuKeyboard());
  if (text === '/today') return sendMessage(chatId, summaryText(state), menuKeyboard());

  const a = state.awaiting;
  if (!a) {
    const quickWeight = text.match(/^вес\s*[:=]?\s*(\d+(?:[.,]\d+)?)/i);
    if (quickWeight) { state.awaiting = { type: 'weight', meta: {}, at: new Date().toISOString() }; return handleText({ ...message, text: quickWeight[1] }, state); }
    logEvent(state, 'chat_user', text);
    const answer = await askCoach(state, text);
    logEvent(state, 'chat_assistant', answer);
    await saveState(state);
    return sendMessage(chatId, escapeHtml(answer), menuKeyboard());
  }

  if (a.type === 'advice') {
    logEvent(state, 'chat_user', text);
    state.awaiting = null;
    const answer = await askCoach(state, text);
    logEvent(state, 'chat_assistant', answer);
    await saveState(state);
    return sendMessage(chatId, escapeHtml(answer), menuKeyboard());
  }

  if (a.type === 'weight') {
    const weight = asNumber(text);
    if (!Number.isFinite(weight) || weight < 45 || weight > 250) return sendMessage(chatId, 'Не распознал вес. Напиши, например: <b>108.4</b>.');
    const prev = lastEvent(state, 'weight');
    logEvent(state, 'weight', weight + ' кг'); state.awaiting = null; await saveState(state);
    let note = '';
    if (prev) {
      const p = asNumber(prev.value);
      if (Number.isFinite(p)) { const d = weight - p; note = ' Изменение к прошлой записи: ' + (d >= 0 ? '+' : '') + d.toFixed(1) + ' кг.'; }
    }
    const recentAlcohol = [...(state.events || [])].reverse().find((e) => e.type === 'alcohol' && e.value !== 'нет');
    if (recentAlcohol && Date.now() - Date.parse(recentAlcohol.ts) < 36 * 3600 * 1000) note += ' После алкоголя вес может заметно гулять из-за воды; не считаю эту точку чистой контрольной.';
    return sendMessage(chatId, 'Записал <b>' + weight.toFixed(1) + ' кг</b>.' + note, menuKeyboard());
  }
  if (a.type === 'meal') {
    logEvent(state, 'meal', text); state.awaiting = null; await saveState(state);
    return sendMessage(chatId, 'Еду записал. Если принимаешь орлистат (Листата, Ксеникал или другой препарат орлистата) — фиксируй его отдельно кнопкой 💊.', menuKeyboard());
  }
  if (a.type === 'water') {
    const n = asNumber(text);
    if (!Number.isFinite(n)) return sendMessage(chatId, 'Напиши объём, например <b>1.5 л</b>.');
    logEvent(state, 'water', n + ' л'); state.awaiting = null; await saveState(state);
    return sendMessage(chatId, 'Воду записал: ' + n + ' л.', menuKeyboard());
  }
  if (a.type === 'activity') {
    logEvent(state, 'activity', text); state.awaiting = null; await saveState(state);
    return sendMessage(chatId, 'Активность записал.', menuKeyboard());
  }
  if (a.type === 'alcohol_amount') {
    const names = { beer: 'пиво', wine: 'вино', strong: 'крепкое', other: 'другое' };
    logEvent(state, 'alcohol', (names[a.meta?.kind] || 'алкоголь') + ': ' + text); state.awaiting = null; await saveState(state);
    return sendMessage(chatId, 'Алкоголь записал. Следующий вес пометим как потенциально искажённый водой; орлистат алкогольные калории не блокирует.', menuKeyboard());
  }
  if (a.type === 'semavik_other') {
    logEvent(state, 'semavik', text); state.awaiting = null; await saveState(state);
    return sendMessage(chatId, 'Семавик записал. Самостоятельно дозу не повышай.', menuKeyboard());
  }
  if (a.type === 'orlistat_other') {
    logEvent(state, 'orlistat', text); state.awaiting = null; await saveState(state);
    return sendMessage(chatId, 'Записал. Для орлистата ориентируйся на дозировку именно твоего препарата; разные формы могут содержать разное количество мг.', menuKeyboard());
  }
  state.awaiting = null; await saveState(state);
  return sendMessage(chatId, 'Записал. Открой /menu для следующего пункта.', menuKeyboard());
}

export default async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ ok: false });
  try {
    const update = req.body || {};
    const state = await loadState();
    if (update.callback_query) await handleCallback(update.callback_query, state);
    else if (update.message?.text) await handleText(update.message, state);
    return res.status(200).json({ ok: true });
  } catch (error) {
    console.error(error);
    return res.status(200).json({ ok: true, error: 'handled' });
  }
}
