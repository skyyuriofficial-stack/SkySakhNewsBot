import { loadState, saveState, logEvent, todayEvents, lastEvent } from '../lib/store.js';
import { sendMessage, answerCallback, menuKeyboard, downloadTelegramFile } from '../lib/telegram.js';
import { modelText } from '../lib/model.js';
import { analyzeFoodImage } from '../lib/food.js';
import { waitUntil } from '@vercel/functions';

export const config = { maxDuration: 60 };

function cbKeyboard(rows) {
  return { inline_keyboard: rows };
}

function asNumber(text) {
  const m = String(text || '').replace(',', '.').match(/\d+(?:\.\d+)?/);
  return m ? Number(m[0]) : NaN;
}

function orlistatDosesToday(state) {
  let doses = 0;
  for (const e of todayEvents(state)) {
    if (e.type !== 'orlistat') continue;
    const m = String(e.value || '').replace(',', '.').match(/(\d+(?:\.\d+)?)\s*мг/i);
    const mg = m ? Number(m[1]) : 0;
    if (mg >= 60) doses += Math.max(1, Math.round(mg / 60));
  }
  return doses;
}

function recentOrlistatDose(state, minutes = 45) {
  const now = Date.now();
  return [...(state.events || [])].reverse().find((e) =>
    e.type === 'orlistat' &&
    /(?:^|\D)60\s*мг/i.test(String(e.value || '')) &&
    e.ts && now - Date.parse(e.ts) <= minutes * 60 * 1000
  ) || null;
}

function latestMeal(state) {
  return [...(state.events || [])].reverse().find((e) => e.type === 'meal') || null;
}

function photoResultKeyboard(state, record) {
  const decision = record?.orlistat_decision;
  const doses = orlistatDosesToday(state);

  if (decision === 'take' && doses < 3 && !recentOrlistatDose(state, 45)) {
    return cbKeyboard([
      [{ text: '💊 Принял Листату 60 мг', callback_data: 'orlistat:60' }, { text: '🚫 Не принимал', callback_data: 'orlistat:0' }],
      [{ text: '📊 Сегодня', callback_data: 'menu:today' }, { text: '🌙 Итог дня', callback_data: 'menu:evening' }]
    ]);
  }

  if (decision === 'skip' || decision === 'max' || decision === 'already') {
    return cbKeyboard([
      [{ text: '🚫 Листату не принимаю', callback_data: 'orlistat:0' }],
      [{ text: '📊 Сегодня', callback_data: 'menu:today' }, { text: '🌙 Итог дня', callback_data: 'menu:evening' }]
    ]);
  }

  return cbKeyboard([
    [{ text: '💊 Листата 60 мг', callback_data: 'menu:orlistat' }, { text: '📊 Сегодня', callback_data: 'menu:today' }],
    [{ text: '🌙 Итог дня', callback_data: 'menu:evening' }]
  ]);
}

function quickMealAdvice(text) {
  const t = String(text || '').toLowerCase();
  const fatty = /фри|жарен|фритюр|майонез|сыр|масл|сливк|сметан|бекон|колбас|бургер|пицц|соус|орех|авокад|лосос|свинин/i.test(t);
  const lean = /обезжир|без\s*масла|овощ|фрукт|рис|греч|картофел.*вар|курин.*груд|индейк|творог\s*0|кефир\s*0/i.test(t);
  if (fatty) return 'По описанию жир в приёме пищи, вероятно, есть. Если это основной приём пищи, для Листаты ориентируйся на обычное правило: 60 мг с едой/не позднее часа после, если сегодня ещё не было 3 доз.';
  if (lean) return 'По описанию приём выглядит скорее нежирным, но без состава/этикетки жир точно не считаю. Если жира действительно нет, Листату по инструкции пропускают.';
  return 'По одному тексту жирность надёжно не определяю. Если пришлёшь фото блюда или этикетки, бот сам попробует определить жирность и дать решение по Листате.';
}

function escapeHtml(value) {
  return String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
}

const EVENING_PROMPT = '<b>Вечерний дневник.</b>\nОтветь одним сообщением по пунктам:\n' +
  '1) что и примерно сколько съел за день;\n' +
  '2) был ли алкоголь и сколько;\n' +
  '3) сколько Листаты Мини 60 мг принял и с какими приёмами пищи;\n' +
  '4) сколько воды выпил;\n' +
  '5) была ли ходьба, зарядка, тренировка или сколько примерно шагов;\n' +
  '6) насколько голоден вечером по шкале 0–10;\n' +
  '7) были ли тошнота, боль в животе, рвота, изжога, запор или диарея.\n\n' +
  'После ответа дам короткий разбор и один конкретный план на завтра. Компенсационного голодания не будет.';

function numberedAnswer(text, n) {
  const re = new RegExp('(?:^|\\n)\\s*' + n + '\\s*[).:\\-]\\s*([^\\n]+)', 'i');
  const m = String(text || '').match(re);
  return m ? m[1].trim() : '';
}

function eveningReview(state, text) {
  const events = todayEvents(state);
  const foodInput = numberedAnswer(text, 1);
  const alcoholInput = numberedAnswer(text, 2);
  const orlistatInput = numberedAnswer(text, 3);
  const waterInput = numberedAnswer(text, 4);
  const activityInput = numberedAnswer(text, 5);
  const hungerInput = numberedAnswer(text, 6);
  const symptomsInput = numberedAnswer(text, 7);

  const meals = events.filter((e) => e.type === 'meal');
  const alcoholEvent = events.filter((e) => e.type === 'alcohol').slice(-1)[0];
  const waterEvent = events.filter((e) => e.type === 'water').slice(-1)[0];
  const activityEvent = events.filter((e) => e.type === 'activity').slice(-1)[0];
  const symptomsEvent = events.filter((e) => e.type === 'symptoms').slice(-1)[0];

  const alcohol = alcoholInput || String(alcoholEvent?.value || '');
  const water = waterInput || String(waterEvent?.value || '');
  const activity = activityInput || String(activityEvent?.value || '');
  const symptoms = symptomsInput || String(symptomsEvent?.value || '');

  let hunger = hungerInput;
  if (!hunger) {
    const hm = String(text || '').match(/голод\D{0,12}(10|[0-9])(?:\s*\/\s*10)?/i);
    if (hm) hunger = hm[1];
  }

  const good = [];
  const issues = [];

  if (foodInput || meals.length) good.push('еда за день зафиксирована');
  else issues.push('по еде недостаточно данных');

  if (alcohol) {
    if (/нет|не\s*было|0\b/i.test(alcohol)) good.push('алкоголя не было');
    else issues.push('алкоголь был: ' + alcohol);
  }

  const doses = orlistatDosesToday(state);
  if (orlistatInput || doses > 0) good.push('Листата учтена: ' + doses + '/3 доз');

  const wm = String(water).replace(',', '.').match(/(\d+(?:\.\d+)?)\s*л/i);
  const liters = wm ? Number(wm[1]) : NaN;
  if (Number.isFinite(liters)) {
    if (liters < 1.2) issues.push('воды мало: около ' + liters + ' л');
    else good.push('вода отмечена: около ' + liters + ' л');
  } else if (!water) {
    issues.push('вода не указана');
  }

  const stepsMatch = String(activity).replace(/\s/g, '').match(/(\d{3,6})(?:шаг|step)/i);
  const steps = stepsMatch ? Number(stepsMatch[1]) : NaN;
  if (activity) {
    if (/нет|не\s*было/i.test(activity)) issues.push('активности не было');
    else if (Number.isFinite(steps) && steps < 4000) issues.push('активность низкая: около ' + steps + ' шагов');
    else good.push('активность отмечена');
  } else {
    issues.push('активность не указана');
  }

  const hm = String(hunger).match(/\b(10|[0-9])\b/);
  const h = hm ? Number(hm[1]) : NaN;
  if (Number.isFinite(h)) {
    if (h >= 8) issues.push('вечерний голод высокий: ' + h + '/10');
    else good.push('вечерний голод ' + h + '/10');
  } else {
    issues.push('вечерний голод не указан');
  }

  if (symptoms) {
    if (/нет|норм/i.test(symptoms)) good.push('ЖКТ-симптомов не отмечено');
    else issues.push('есть симптомы: ' + symptoms);
  }

  let plan = 'Завтра: после одного основного приёма пищи сделай 25 минут спокойной ходьбы.';
  if (alcohol && !/нет|не\s*было|0\b/i.test(alcohol)) {
    plan = 'Завтра: без алкоголя, без компенсационного голодания — обычный режим питания.';
  } else if (Number.isFinite(liters) && liters < 1.2) {
    plan = 'Завтра: выпей 1,5 л воды равномерно в течение дня, если врач не ограничивал жидкость.';
  } else if (Number.isFinite(h) && h >= 8) {
    plan = 'Завтра: запланируй нормальный белковый ужин, чтобы не доводить вечерний голод до 8–10/10.';
  }

  const goodText = good.length ? 'Удачно: ' + good.slice(0, 4).join('; ') + '.' : 'Удачно: дневник заполнен частично.';
  const issueText = issues.length ? 'Перебор/недобор: ' + issues.slice(0, 4).join('; ') + '.' : 'Перебор/недобор: явных проблем по указанным данным не вижу.';
  return goodText + '\n' + issueText + '\n' + plan;
}

function diaryContext(state) {
  return (state.events || [])
    .filter((e) => e.type !== 'system')
    .slice(-40)
    .map((e) => '[' + e.day + '] ' + e.type + ': ' + String(e.value))
    .join('\n');
}

async function aiTextReply(state, userText) {
  const result = await modelText({
    system: [
      'Ты Veshudei — автономный помощник по снижению веса в Telegram.',
      'Отвечай по-русски, кратко и конкретно.',
      'Сам распознавай намерение пользователя: запись еды, вопрос, вода, алкоголь, активность или итог дня.',
      'Учитывай только реально имеющиеся записи дневника и не выдумывай факты.',
      'Если пользователь сообщает еду — оцени структуру приёма пищи и дай один практический следующий шаг.',
      'Для Листаты Мини 60 мг: не используй её как компенсацию еды; ориентируйся на инструкцию — с основным приёмом пищи, содержащим жир; если жира нет, дозу пропускают; не более 3 доз по 60 мг в сутки.',
      'Не предлагай компенсационное голодание, обезвоживание или чрезмерную тренировку.',
      'Не меняй дозу Семавика самостоятельно.',
      'Если данных достаточно — не задавай лишних уточняющих вопросов.',
      'При сильной/нарастающей боли в животе, повторной рвоте, крови, обмороке или невозможности пить рекомендуй срочную медицинскую оценку.'
    ].join('\n'),
    text: 'ДНЕВНИК:\n' + (diaryContext(state) || 'нет записей') + '\n\nСООБЩЕНИЕ:\n' + userText,
    maxTokens: 280
  });
  if (result.errors?.length) console.error('Veshudei model fallbacks:', result.errors.join(' | '));
  return result.text || null;
}
async function analyzeFoodPhoto(state, message) {
  const photos = Array.isArray(message.photo) ? message.photo : [];
  const largest = photos[photos.length - 1];
  const documentImage = message.document?.mime_type?.startsWith('image/') ? message.document : null;
  const fileId = largest?.file_id || documentImage?.file_id || null;
  const caption = String(message.caption || '').trim();

  if (!fileId) {
    return {
      log: 'Фото еды' + (caption ? ': ' + caption : ''),
      reply: '🍽 Фото получил и записал. На нём не удалось получить файл достаточного качества.',
      record: { name: caption || 'Еда по фото', recognition_provider: 'fallback', confidence: 0.1 }
    };
  }

  try {
    const file = await downloadTelegramFile(fileId);
    const result = await analyzeFoodImage(state, file, caption);
    return {
      log: result.record?.name || ('Фото еды' + (caption ? ': ' + caption : '')),
      reply: result.reply,
      record: result.record
    };
  } catch (error) {
    console.error('Veshudei photo pipeline:', error?.message || error);
    return {
      log: 'Фото еды' + (caption ? ': ' + caption : ''),
      reply: '🍽 Фото получил и сохранил как приём пищи, но распознавание сейчас не завершилось. Повторно присылать фото не обязательно — дневник запись не потеряет.',
      record: { name: caption || 'Еда по фото', recognition_provider: 'error', confidence: 0.1 }
    };
  }
}
async function localCoach(state, userText) {
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

async function askCoach(state, userText) {
  const ai = await aiTextReply(state, userText);
  if (ai) return ai;
  return localCoach(state, userText);
}

function summaryText(state) {
  const allowed = new Set(['weight','meal','alcohol','semavik','orlistat','water','activity','symptoms']);
  const events = todayEvents(state).filter((e) => allowed.has(e.type));
  if (!events.length) return 'Сегодня пока ничего не записано.';
  const labels = {
    weight: '⚖️ Вес', meal: '🍽 Еда', alcohol: '🍺 Алкоголь', semavik: '💉 Семавик',
    orlistat: '💊 Листата 60 мг', water: '💧 Вода', activity: '🚶 Активность', symptoms: '🩺 Самочувствие'
  };
  const rows = events.slice(-20).map((e) => {
    let value = String(e.value);
    if (e.type === 'meal' && e.food) {
      const bits = [e.food.name || e.value];
      if (e.food.portion_g) bits.push(String(e.food.portion_g).replace('.', ',') + ' г');
      if (e.food.nutrition?.kcal != null) bits.push('≈' + String(Math.round(e.food.nutrition.kcal)) + ' ккал');
      if (e.food.fat_class) bits.push(e.food.fat_class);
      value = bits.join(' · ');
    }
    return (labels[e.type] || e.type) + ': ' + escapeHtml(value);
  });

  const recognizedMeals = events.filter((e) => e.type === 'meal' && e.food?.nutrition);
  const totals = recognizedMeals.reduce((acc, e) => {
    const x = e.food.nutrition || {};
    for (const k of ['kcal','protein_g','fat_g','carbs_g']) {
      if (Number.isFinite(x[k])) acc[k] += x[k];
    }
    return acc;
  }, { kcal: 0, protein_g: 0, fat_g: 0, carbs_g: 0 });

  let footer = '';
  if (recognizedMeals.length) {
    footer = '\n\n<b>По распознанным фото/этикеткам:</b> ≈' + Math.round(totals.kcal) + ' ккал · Б ' +
      totals.protein_g.toFixed(1).replace('.', ',') + ' · Ж ' + totals.fat_g.toFixed(1).replace('.', ',') +
      ' · У ' + totals.carbs_g.toFixed(1).replace('.', ',') + ' г. Это неполный итог, если часть еды была без КБЖУ.';
  }
  return '<b>Сегодня:</b>\n' + rows.join('\n') + footer;
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
    if (val === '60 мг') {
      const doses = orlistatDosesToday(state);
      if (doses >= 3) {
        state.awaiting = null; await saveState(state);
        return sendMessage(chatId, 'Листата: сегодня уже записаны <b>3 дозы по 60 мг</b>. Четвёртую не добавляю.', menuKeyboard());
      }
      const recent = recentOrlistatDose(state, 45);
      if (recent) {
        state.awaiting = null; await saveState(state);
        return sendMessage(chatId, 'Листата 60 мг уже записана менее 45 минут назад. Повторную дозу с тем же приёмом пищи не добавляю.', menuKeyboard());
      }
    }
    const meal = latestMeal(state);
    logEvent(state, 'orlistat', val, meal ? { meal: meal.value, meal_ts: meal.ts } : {});
    state.awaiting = null; await saveState(state);
    const note = val === '60 мг'
      ? ' Записал с текущим/последним приёмом пищи. Всего сегодня: ' + orlistatDosesToday(state) + '/3 доз.'
      : '';
    return sendMessage(chatId, 'Записал: <b>' + val + '</b>.' + note, menuKeyboard());
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
  if (data === 'menu:evening') return setAwaiting(state, chatId, 'evening_checkin', EVENING_PROMPT);
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
  if (text === '/evening') return setAwaiting(state, chatId, 'evening_checkin', EVENING_PROMPT);

  const a = state.awaiting;
  if (!a) {
    const quickWeight = text.match(/^вес\s*[:=]?\s*(\d+(?:[.,]\d+)?)/i);
    if (quickWeight) { state.awaiting = { type: 'weight', meta: {}, at: new Date().toISOString() }; return handleText({ ...message, text: quickWeight[1] }, state); }

    const quickMeal = text.match(/^(?:я\s*(?:поел|съел|ел)|еда|завтрак|обед|ужин)\s*[:\-]?\s*(.+)$/i);
    if (quickMeal?.[1]) {
      const value = quickMeal[1].trim();
      logEvent(state, 'meal', value);
      const answer = await askCoach(state, 'Я только что съел: ' + value + '. Коротко оцени и дай следующий шаг.');
      logEvent(state, 'chat_assistant', answer);
      await saveState(state);
      return sendMessage(chatId, '🍽 <b>Записал.</b>\n' + escapeHtml(answer) + '\n' + escapeHtml(quickMealAdvice(value)), menuKeyboard());
    }

    const quickWater = text.match(/(?:выпил|вода)\s*[:\-]?\s*(\d+(?:[.,]\d+)?)\s*л/i);
    if (quickWater) {
      const n = Number(quickWater[1].replace(',', '.'));
      logEvent(state, 'water', n + ' л');
      await saveState(state);
      return sendMessage(chatId, '💧 Записал воду: <b>' + n + ' л</b>.', menuKeyboard());
    }

    const quickSteps = text.match(/(\d{3,6})\s*(?:шаг|шагов)/i);
    if (quickSteps) {
      logEvent(state, 'activity', quickSteps[1] + ' шагов');
      await saveState(state);
      return sendMessage(chatId, '🚶 Записал активность: <b>' + quickSteps[1] + ' шагов</b>.', menuKeyboard());
    }

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

  if (a.type === 'evening_checkin') {
    logEvent(state, 'evening_checkin', text);
    state.awaiting = null;
    const answer = eveningReview(state, text);
    logEvent(state, 'evening_review', answer);
    await saveState(state);
    return sendMessage(chatId, '<b>Итог дня:</b>\n' + escapeHtml(answer), menuKeyboard());
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
    return sendMessage(chatId, '🍽 Еду записал. ' + escapeHtml(quickMealAdvice(text)), menuKeyboard());
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

  const update = req.body || {};
  const chatId = update.message?.chat?.id || update.callback_query?.message?.chat?.id || null;
  console.log('[veshudei:webhook] update', {
    updateId: update.update_id ?? null,
    hasMessage: Boolean(update.message),
    hasCallback: Boolean(update.callback_query),
    hasPhoto: Boolean(update.message?.photo?.length || update.message?.document?.mime_type?.startsWith('image/'))
  });

  try {
    const state = await loadState();
    const updateId = update.update_id;
    const processed = Array.isArray(state.processedUpdateIds) ? state.processedUpdateIds : [];

    if (Number.isFinite(updateId) && processed.includes(updateId)) {
      return res.status(200).json({ ok: true, duplicate: true });
    }

    const markProcessed = async () => {
      if (!Number.isFinite(updateId)) return;
      const ids = Array.isArray(state.processedUpdateIds) ? state.processedUpdateIds : [];
      if (ids.includes(updateId)) return;
      state.processedUpdateIds = [...ids, updateId].slice(-250);
      await saveState(state);
    };

    if (update.callback_query) {
      await handleCallback(update.callback_query, state);
      await markProcessed();
      return res.status(200).json({ ok: true });
    }

    if (update.message?.photo?.length || update.message?.document?.mime_type?.startsWith('image/')) {
      if (chatId) {
        try {
          await sendMessage(chatId, '📷 Фото получил. Сам распознаю блюдо/этикетку, КБЖУ, жирность и сразу скажу по Листате.');
        } catch (_) {}
      }

      const message = update.message;
      const task = (async () => {
        try {
          const fresh = await loadState();
          const analysis = await analyzeFoodPhoto(fresh, message);
          logEvent(fresh, 'meal', analysis.log, {
            source: 'photo',
            media_group_id: message.media_group_id || null,
            food: analysis.record || null
          });
          if (fresh.awaiting?.type !== 'evening_checkin') fresh.awaiting = null;
          await saveState(fresh);
          await sendMessage(chatId, analysis.reply, photoResultKeyboard(fresh, analysis.record));
        } catch (error) {
          console.error('Veshudei background photo:', error?.message || error);
          try {
            await sendMessage(chatId, '⚠️ Фото сохранил в дневник, но распознавание сейчас не завершилось. Повторять запись еды вручную не нужно.');
          } catch (_) {}
        }
      })();

      try {
        waitUntil(task);
      } catch (_) {
        await task;
      }
      await markProcessed();
      return res.status(200).json({ ok: true, accepted: 'photo' });
    }

    if (update.message?.text) {
      await handleText(update.message, state);
      await markProcessed();
    } else {
      await markProcessed();
    }

    return res.status(200).json({ ok: true });
  } catch (error) {
    console.error('Veshudei webhook error:', error);
    if (chatId) {
      try {
        await sendMessage(chatId, '⚠️ Сообщение получил, но обработка этого ввода не завершилась. Дневник не отключён; попробуй ещё раз.');
      } catch (_) {}
    }
    return res.status(200).json({ ok: true, error: 'handled' });
  }
}