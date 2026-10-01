import { sakhalinDay } from './store.js';
import { modelVision } from './model.js';

function n(value) {
  const x = Number(String(value ?? '').replace(',', '.'));
  return Number.isFinite(x) ? x : null;
}

function round1(value) {
  return Number.isFinite(value) ? Math.round(value * 10) / 10 : null;
}

function jsonFromText(text) {
  const raw = String(text || '').trim();
  if (!raw) return null;
  const stripped = raw.replace(/^\`\`\`(?:json)?/i, '').replace(/\`\`\`$/i, '').trim();
  const start = stripped.indexOf('{');
  const end = stripped.lastIndexOf('}');
  if (start < 0 || end <= start) return null;
  try { return JSON.parse(stripped.slice(start, end + 1)); } catch (_) { return null; }
}

function normalizeNutrition(raw) {
  if (!raw || typeof raw !== 'object') return null;

  const portionG = n(raw.portion_g);
  let per100 = raw.per_100g && typeof raw.per_100g === 'object' ? {
    kcal: n(raw.per_100g.kcal),
    protein_g: n(raw.per_100g.protein_g),
    fat_g: n(raw.per_100g.fat_g),
    carbs_g: n(raw.per_100g.carbs_g)
  } : null;

  let portion = raw.whole_portion && typeof raw.whole_portion === 'object' ? {
    kcal: n(raw.whole_portion.kcal),
    protein_g: n(raw.whole_portion.protein_g),
    fat_g: n(raw.whole_portion.fat_g),
    carbs_g: n(raw.whole_portion.carbs_g)
  } : null;

  if (portionG && per100 && (!portion || portion.kcal == null)) {
    const f = portionG / 100;
    portion = {
      kcal: per100.kcal == null ? null : round1(per100.kcal * f),
      protein_g: per100.protein_g == null ? null : round1(per100.protein_g * f),
      fat_g: per100.fat_g == null ? null : round1(per100.fat_g * f),
      carbs_g: per100.carbs_g == null ? null : round1(per100.carbs_g * f)
    };
  }

  if (portionG && portion && !per100) {
    const f = 100 / portionG;
    per100 = {
      kcal: portion.kcal == null ? null : round1(portion.kcal * f),
      protein_g: portion.protein_g == null ? null : round1(portion.protein_g * f),
      fat_g: portion.fat_g == null ? null : round1(portion.fat_g * f),
      carbs_g: portion.carbs_g == null ? null : round1(portion.carbs_g * f)
    };
  }

  let fatPresent = raw.fat_present;
  if (typeof fatPresent !== 'boolean') {
    const fat = portion?.fat_g ?? per100?.fat_g;
    fatPresent = fat == null ? null : fat > 0.3;
  }

  let mainMeal = raw.is_main_meal;
  if (typeof mainMeal !== 'boolean') mainMeal = null;

  return {
    food_name: String(raw.food_name || '').trim() || 'Еда по фото',
    portion_g: portionG,
    per_100g: per100,
    whole_portion: portion,
    fat_present: fatPresent,
    fried_or_fatty_components: Array.isArray(raw.fried_or_fatty_components)
      ? raw.fried_or_fatty_components.map(String).slice(0, 6)
      : [],
    visible_label: Boolean(raw.visible_label),
    is_main_meal: mainMeal,
    meal_type: String(raw.meal_type || 'unknown').slice(0, 24),
    confidence: Math.max(0, Math.min(1, n(raw.confidence) ?? 0.5)),
    notes: String(raw.notes || '').trim()
  };
}

function todayEvents(state) {
  const day = sakhalinDay();
  return (state.events || []).filter((e) => e.day === day);
}

function orlistatStatus(state) {
  const events = todayEvents(state);
  let doses = 0;
  let recentDose = false;
  const now = Date.now();

  for (const e of events) {
    if (e.type !== 'orlistat') continue;
    const m = String(e.value || '').replace(',', '.').match(/(\d+(?:\.\d+)?)\s*мг/i);
    const mg = m ? Number(m[1]) : 0;
    if (mg >= 60) doses += Math.max(1, Math.round(mg / 60));
    if (mg >= 60 && e.ts && now - Date.parse(e.ts) <= 45 * 60 * 1000) recentDose = true;
  }

  const severeSymptoms = events.some((e) =>
    e.type === 'symptoms' &&
    /сильн.*бол|постоянн.*бол|повторн.*рвот|кров|обмор|невозможн.*пить/i.test(String(e.value || ''))
  );

  return { doses, recentDose, severeSymptoms };
}

function inferMainMeal(analysis, caption = '') {
  const c = String(caption || '').toLowerCase();
  if (/перекус|снэк|snack/i.test(c)) return false;
  if (/завтрак|обед|ужин|я\s*(?:поел|съел|ем)|основн.*при[её]м/i.test(c)) return true;
  if (typeof analysis?.is_main_meal === 'boolean') return analysis.is_main_meal;

  const kcal = analysis?.whole_portion?.kcal;
  const grams = analysis?.portion_g;
  if ((Number.isFinite(kcal) && kcal >= 220) || (Number.isFinite(grams) && grams >= 150)) return true;
  if ((Number.isFinite(kcal) && kcal < 140) && (Number.isFinite(grams) && grams < 100)) return false;
  return null;
}

function fatPer100(a) {
  if (a?.per_100g?.fat_g != null) return a.per_100g.fat_g;
  if (a?.whole_portion?.fat_g != null && a?.portion_g) {
    return a.whole_portion.fat_g / a.portion_g * 100;
  }
  return null;
}

function fatClass(a) {
  const total = a?.whole_portion?.fat_g;
  const per100 = fatPer100(a);

  if (a?.fat_present === false) return 'практически без жира';
  if ((Number.isFinite(total) && total >= 20) || (Number.isFinite(per100) && per100 > 17.5)) {
    return 'высокая жирность на порцию';
  }
  if ((Number.isFinite(total) && total >= 10) || (Number.isFinite(per100) && per100 > 7)) {
    return 'умеренная жирность';
  }
  if ((Number.isFinite(total) && total < 5) && (per100 == null || per100 <= 3)) {
    return 'низкая жирность';
  }
  if (a?.fat_present === true) return 'жир в составе есть';
  return 'жирность точно не определена';
}

function orlistatDecision(state, a, caption = '') {
  const status = orlistatStatus(state);
  const mainMeal = inferMainMeal(a, caption);

  if (status.severeSymptoms) {
    return {
      code: 'medical',
      text: '💊 <b>Листата: решение по фото откладываю.</b> В дневнике есть выраженные ЖКТ-симптомы — сначала нужна медицинская оценка.'
    };
  }

  if (status.doses >= 3) {
    return {
      code: 'max',
      text: '💊 <b>Листата: НЕ ПРИНИМАТЬ.</b> Сегодня уже зафиксированы 3 дозы по 60 мг.'
    };
  }

  if (status.recentDose) {
    return {
      code: 'already',
      text: '💊 <b>Листата: повторно НЕ ПРИНИМАТЬ.</b> 60 мг уже отмечены менее 45 минут назад; если это та же еда, вторую дозу не добавлять.'
    };
  }

  if (a?.fat_present === false) {
    return {
      code: 'skip',
      text: '💊 <b>Листата: ПРОПУСТИТЬ.</b> По распознанным данным жира в этом приёме пищи практически нет.'
    };
  }

  if (mainMeal === false) {
    return {
      code: 'skip',
      text: '💊 <b>Листата: ПРОПУСТИТЬ.</b> Это выглядит как перекус, а не основной приём пищи.'
    };
  }

  if (a?.fat_present === true && mainMeal === true) {
    return {
      code: 'take',
      text: '💊 <b>Листата: ПРИНЯТЬ 60 мг.</b> Я распознал основной приём пищи, содержащий жир. Принимать во время еды или не позднее 1 часа после неё; если уже принимал с этой едой — повторно не принимать. После отметки будет ' + (status.doses + 1) + '/3 доз сегодня.'
    };
  }

  if (a?.fat_present === true) {
    return {
      code: 'conditional',
      text: '💊 <b>Листата: СКОРЕЕ ДА, если это основной приём пищи.</b> Жир в еде есть; 60 мг — во время еды или не позднее 1 часа после. Для небольшого перекуса отдельную дозу не добавляю.'
    };
  }

  return {
    code: 'unknown',
    text: '💊 <b>Листата: пока НЕ РЕШАЮ.</b> По фото не удалось надёжно подтвердить жир. Если на упаковке есть строка «жиры» или состав — пришли крупнее, либо напиши значение.'
  };
}

function fmt(value, suffix = '') {
  return value == null ? null : String(round1(value)).replace('.', ',') + suffix;
}

function escapeHtml(value) {
  return String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
}

function buildReply(state, a, provider, caption = '') {
  const lines = [];
  const source = a.visible_label
    ? 'по этикетке'
    : (provider ? 'по фото' : 'по подписи/контексту');

  lines.push('🍽 <b>' + escapeHtml(a.food_name) + '</b>' + (a.portion_g ? ', ' + fmt(a.portion_g, ' г') : '') + '.');

  const p = a.whole_portion;
  if (p && [p.kcal, p.protein_g, p.fat_g, p.carbs_g].some((x) => x != null)) {
    const vals = [];
    if (p.kcal != null) vals.push('≈' + fmt(p.kcal, ' ккал'));
    if (p.protein_g != null) vals.push('Б ' + fmt(p.protein_g, ' г'));
    if (p.fat_g != null) vals.push('Ж ' + fmt(p.fat_g, ' г'));
    if (p.carbs_g != null) vals.push('У ' + fmt(p.carbs_g, ' г'));
    lines.push('На всю порцию ' + source + ': ' + vals.join(' · ') + '.');
  } else if (a.per_100g && [a.per_100g.kcal, a.per_100g.protein_g, a.per_100g.fat_g, a.per_100g.carbs_g].some((x) => x != null)) {
    const x = a.per_100g;
    const vals = [];
    if (x.kcal != null) vals.push(fmt(x.kcal, ' ккал'));
    if (x.protein_g != null) vals.push('Б ' + fmt(x.protein_g, ' г'));
    if (x.fat_g != null) vals.push('Ж ' + fmt(x.fat_g, ' г'));
    if (x.carbs_g != null) vals.push('У ' + fmt(x.carbs_g, ' г'));
    lines.push('На 100 г ' + source + ': ' + vals.join(' · ') + '.');
  }

  const cls = fatClass(a);
  const parts = a.fried_or_fatty_components?.length
    ? ' — ' + a.fried_or_fatty_components.join(', ')
    : '';
  lines.push('🧈 Жирность: <b>' + escapeHtml(cls) + '</b>' + escapeHtml(parts) + '.');

  const decision = orlistatDecision(state, a, caption);
  lines.push(decision.text);

  if (a.confidence < 0.65) {
    lines.push('🔎 Уверенность распознавания средняя: нечитаемые цифры я не додумываю.');
  }

  const totalFat = a?.whole_portion?.fat_g;
  if (Number.isFinite(totalFat) && totalFat >= 20) {
    lines.push('➡️ Следующий шаг: не добавляй к этому приёму ещё жирный соус/закуску; при большом количестве жира ЖКТ-эффекты орлистата встречаются чаще.');
  } else {
    lines.push('➡️ Следующий шаг: приём пищи занесён в дневник; дальше без компенсационного голодания.');
  }

  return { text: lines.join('\n'), decision: decision.code, mainMeal: inferMainMeal(a, caption) };
}

function fallbackAnalysis(caption = '') {
  const cleaned = String(caption || '').replace(/^я\s*(?:поел|съел|ем)\s*[:\-]?/i, '').trim();
  const fatty = /фри|жарен|фритюр|майонез|сыр|масл|сливк|сметан|бекон|колбас|бургер|пицц|соус|орех|авокад|лосос|свинин/i.test(cleaned);
  return normalizeNutrition({
    food_name: cleaned || 'Еда по фото',
    portion_g: null,
    per_100g: null,
    whole_portion: null,
    fat_present: fatty ? true : null,
    fried_or_fatty_components: fatty ? ['жирный компонент по подписи'] : [],
    visible_label: false,
    is_main_meal: /я\s*(?:поел|съел|ем)|завтрак|обед|ужин/i.test(String(caption || '')) ? true : null,
    meal_type: 'unknown',
    confidence: cleaned ? 0.35 : 0.15,
    notes: 'Vision-провайдер недоступен; использован только текст подписи.'
  });
}

export async function analyzeFoodImage(state, file, caption = '') {
  const context = todayEvents(state)
    .slice(-20)
    .map((e) => e.type + ': ' + String(e.value))
    .join('\n');

  const system = [
    'Ты анализируешь фотографию еды для личного дневника снижения веса.',
    'Верни ТОЛЬКО валидный JSON без markdown.',
    'Если видна этикетка, этикетка — главный источник: точно прочитай название, массу порции, ккал и Б/Ж/У. Нечитаемые цифры ставь null, не выдумывай.',
    'Если этикетки нет, распознай блюдо и оцени массу и КБЖУ только когда это разумно; для оценок снижай confidence.',
    'Отдельно укажи наличие жира, жареных/жирных компонентов и является ли это основным приёмом пищи.',
    'Основной приём пищи: завтрак, обед, ужин либо полноценная порция; небольшой снек/напиток — не основной.',
    'Не давай медицинских советов и не решай дозировку лекарства — это сделает приложение по правилам после распознавания.'
  ].join('\n');

  const prompt = 'Подпись пользователя: ' + (caption || '(нет)') +
    '\nДневник сегодня:\n' + (context || '(нет)') +
    '\n\nJSON-схема:\n' +
    '{' +
    '"food_name":"строка",' +
    '"portion_g":число|null,' +
    '"per_100g":{"kcal":число|null,"protein_g":число|null,"fat_g":число|null,"carbs_g":число|null}|null,' +
    '"whole_portion":{"kcal":число|null,"protein_g":число|null,"fat_g":число|null,"carbs_g":число|null}|null,' +
    '"fat_present":true|false|null,' +
    '"fried_or_fatty_components":["строки"],' +
    '"visible_label":true|false,' +
    '"is_main_meal":true|false|null,' +
    '"meal_type":"breakfast|lunch|dinner|snack|unknown",' +
    '"confidence":число 0..1,' +
    '"notes":"кратко"' +
    '}';

  const remote = await modelVision({
    system,
    text: prompt,
    imageBytes: file.bytes,
    mimeType: file.mimeType,
    maxTokens: 520
  });

  let analysis = normalizeNutrition(jsonFromText(remote.text));
  let provider = remote.provider;

  if (!analysis || analysis.confidence < 0.35) {
    analysis = fallbackAnalysis(caption);
    provider = provider || null;
  }

  const reply = buildReply(state, analysis, provider, caption);

  return {
    analysis,
    provider,
    reply: reply.text,
    record: {
      name: analysis.food_name,
      portion_g: analysis.portion_g,
      nutrition: analysis.whole_portion,
      per_100g: analysis.per_100g,
      fat_present: analysis.fat_present,
      fat_class: fatClass(analysis),
      is_main_meal: reply.mainMeal,
      meal_type: analysis.meal_type,
      orlistat_decision: reply.decision,
      recognition_provider: provider || 'fallback',
      confidence: analysis.confidence
    },
    errors: remote.errors || []
  };
}
