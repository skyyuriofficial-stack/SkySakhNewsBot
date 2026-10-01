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
  const per100 = raw.per_100g && typeof raw.per_100g === 'object' ? {
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

  let fatPresent = raw.fat_present;
  if (typeof fatPresent !== 'boolean') {
    const fat = portion?.fat_g ?? per100?.fat_g;
    fatPresent = fat == null ? null : fat > 0.3;
  }

  return {
    food_name: String(raw.food_name || '').trim() || 'Еда по фото',
    portion_g: portionG,
    per_100g: per100,
    whole_portion: portion,
    fat_present: fatPresent,
    fried_or_fatty_components: Array.isArray(raw.fried_or_fatty_components) ? raw.fried_or_fatty_components.map(String).slice(0, 5) : [],
    visible_label: Boolean(raw.visible_label),
    confidence: Math.max(0, Math.min(1, n(raw.confidence) ?? 0.5)),
    notes: String(raw.notes || '').trim()
  };
}

function numberNear(text, patterns) {
  for (const p of patterns) {
    const m = text.match(p);
    if (m) {
      const x = n(m[1]);
      if (x != null) return x;
    }
  }
  return null;
}

function parseOcr(text, caption = '') {
  const src = String(text || '').replace(/\r/g, '\n').replace(/[ \t]+/g, ' ');
  const lines = src.split('\n').map((x) => x.trim()).filter(Boolean);

  let name = '';
  for (const line of lines.slice(0, 8)) {
    if (line.length >= 5 && line.length <= 100 && !/состав|энерг|пищева|белк|жир|углев|дата|штрих|barcode|ккал/i.test(line)) {
      name = line;
      break;
    }
  }
  if (!name && caption) name = caption.replace(/^я\s*(?:поел|съел)\s*[:\-]?/i, '').trim();
  if (!name) name = 'Еда по фото';

  const portionG = numberNear(src, [
    /(?:масса|вес|нетто|порци[яи]|1\s*\/)?\s*(\d{2,4})\s*(?:г|гр|g)\b/i,
    /\b(\d{2,4})\s*(?:г|гр|g)\b/i
  ]);

  const kcal = numberNear(src, [
    /(?:энерг\w*\s*ценн\w*|ккал|kcal)[^\d]{0,30}(\d{2,4}(?:[.,]\d+)?)/i,
    /(\d{2,4}(?:[.,]\d+)?)\s*(?:ккал|kcal)/i
  ]);
  const protein = numberNear(src, [
    /(?:белк\w*|\bб\b)\s*[:\-]?\s*(\d{1,3}(?:[.,]\d+)?)/i
  ]);
  const fat = numberNear(src, [
    /(?:жир\w*|\bж\b)\s*[:\-]?\s*(\d{1,3}(?:[.,]\d+)?)/i
  ]);
  const carbs = numberNear(src, [
    /(?:углев\w*|\bу\b)\s*[:\-]?\s*(\d{1,3}(?:[.,]\d+)?)/i
  ]);

  const hasPer100 = /(?:на\s*100\s*(?:г|гр|g)|100\s*(?:г|гр|g))/i.test(src);
  const per100 = (kcal != null || protein != null || fat != null || carbs != null) && hasPer100
    ? { kcal, protein_g: protein, fat_g: fat, carbs_g: carbs }
    : null;

  let whole = null;
  if (per100 && portionG) {
    const f = portionG / 100;
    whole = {
      kcal: kcal == null ? null : round1(kcal * f),
      protein_g: protein == null ? null : round1(protein * f),
      fat_g: fat == null ? null : round1(fat * f),
      carbs_g: carbs == null ? null : round1(carbs * f)
    };
  } else if (!hasPer100 && (kcal != null || protein != null || fat != null || carbs != null)) {
    whole = { kcal, protein_g: protein, fat_g: fat, carbs_g: carbs };
  }

  const fatWords = [];
  if (/майонез/i.test(src)) fatWords.push('майонез');
  if (/соус/i.test(src)) fatWords.push('соус');
  if (/фрай|жарен|фритюр/i.test(src)) fatWords.push('жареный/фритюрный компонент');
  if (/сыр/i.test(src)) fatWords.push('сыр');
  if (/масло/i.test(src)) fatWords.push('масло');

  const fatValue = whole?.fat_g ?? per100?.fat_g;
  const fatPresent = fatValue != null ? fatValue > 0.3 : (fatWords.length ? true : null);

  return normalizeNutrition({
    food_name: name,
    portion_g: portionG,
    per_100g: per100,
    whole_portion: whole,
    fat_present: fatPresent,
    fried_or_fatty_components: fatWords,
    visible_label: Boolean(per100 || /состав|пищева|энерг/i.test(src)),
    confidence: per100 ? 0.72 : 0.48,
    notes: 'Распознано локально по тексту на фотографии.'
  });
}

async function localOcr(bytes) {
  let worker = null;
  try {
    const { createWorker } = await import('tesseract.js');
    worker = await createWorker('rus+eng');
    const result = await worker.recognize(Buffer.from(bytes));
    return String(result?.data?.text || '').trim();
  } catch (error) {
    console.error('Veshudei OCR fallback:', error?.message || error);
    return '';
  } finally {
    try { if (worker) await worker.terminate(); } catch (_) {}
  }
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
    if (mg >= 60 && e.ts && now - Date.parse(e.ts) < 90 * 60 * 1000) recentDose = true;
  }

  const severeSymptoms = events.some((e) =>
    e.type === 'symptoms' && /сильн.*бол|постоянн.*бол|рвот|кров|обмор|невозможн.*пить/i.test(String(e.value || ''))
  );

  return { doses, recentDose, severeSymptoms };
}

function fatPer100(analysis) {
  if (analysis?.per_100g?.fat_g != null) return analysis.per_100g.fat_g;
  if (analysis?.whole_portion?.fat_g != null && analysis?.portion_g) {
    return analysis.whole_portion.fat_g / analysis.portion_g * 100;
  }
  return null;
}

function fatClass(analysis) {
  const f = fatPer100(analysis);
  if (f == null) {
    if (analysis?.fat_present === false) return 'практически без жира';
    if (analysis?.fat_present === true) return 'жир в составе есть';
    return 'жирность точно не определена';
  }
  if (f <= 3) return 'низкая жирность';
  if (f > 17.5) return 'высокая жирность';
  return 'умеренная жирность';
}

function orlistatAdvice(state, analysis) {
  const status = orlistatStatus(state);
  if (status.severeSymptoms) {
    return 'Листата: из-за отмеченных выраженных ЖКТ-симптомов дозу по фото не советую; нужна медицинская оценка.';
  }
  if (status.doses >= 3) {
    return 'Листата: НЕТ — сегодня уже зафиксированы 3 дозы по 60 мг; больше в сутки не добавлять.';
  }
  if (status.recentDose) {
    return 'Листата: повторно НЕ принимать, если предыдущие 60 мг были с этим же приёмом пищи.';
  }
  if (analysis?.fat_present === false) {
    return 'Листата: ПРОПУСТИТЬ — по распознанным данным жира в этой еде практически нет.';
  }
  if (analysis?.fat_present === true) {
    return 'Листата: ДА, если это основной приём пищи и ты сейчас ешь или закончил не более часа назад — 60 мг по инструкции; если уже принял с этой едой, повторно не принимать.';
  }
  return 'Листата: по фото жира определить надёжно не удалось. По инструкции 60 мг принимают только с основным приёмом пищи, содержащим жир; если жира нет — пропускают.';
}

function fmt(value, suffix = '') {
  return value == null ? null : String(round1(value)).replace('.', ',') + suffix;
}

function buildReply(state, a, provider) {
  const lines = [];
  const source = a.visible_label ? 'по этикетке' : (provider === 'ocr' ? 'по тексту на фото' : 'по фото');
  lines.push('🍽 <b>' + escapeHtml(a.food_name) + '</b>' + (a.portion_g ? ', ' + fmt(a.portion_g, ' г') : '') + '.');

  const p = a.whole_portion;
  if (p && [p.kcal, p.protein_g, p.fat_g, p.carbs_g].some((x) => x != null)) {
    const vals = [];
    if (p.kcal != null) vals.push('≈' + fmt(p.kcal, ' ккал'));
    if (p.protein_g != null) vals.push('Б ' + fmt(p.protein_g, ' г'));
    if (p.fat_g != null) vals.push('Ж ' + fmt(p.fat_g, ' г'));
    if (p.carbs_g != null) vals.push('У ' + fmt(p.carbs_g, ' г'));
    lines.push('На порцию ' + source + ': ' + vals.join(' · ') + '.');
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
  const parts = a.fried_or_fatty_components?.length ? ' (' + a.fried_or_fatty_components.join(', ') + ')' : '';
  lines.push('Жирность: <b>' + escapeHtml(cls) + '</b>' + escapeHtml(parts) + '.');
  lines.push(escapeHtml(orlistatAdvice(state, a)));

  const f100 = fatPer100(a);
  if (f100 != null && f100 > 17.5) {
    lines.push('Следующий шаг: не добавляй к этому приёму ещё жирный соус/закуску; высокий жир повышает риск неприятных ЖКТ-эффектов орлистата.');
  } else {
    lines.push('Следующий шаг: эту еду считаю в дневнике; дальше без компенсационного голодания.');
  }

  return lines.join('\n');
}

function escapeHtml(value) {
  return String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
}

export async function analyzeFoodImage(state, file, caption = '') {
  const context = todayEvents(state).slice(-20).map((e) => e.type + ': ' + String(e.value)).join('\n');
  const system = [
    'Ты анализируешь фотографию еды для личного дневника снижения веса.',
    'Верни ТОЛЬКО валидный JSON без markdown.',
    'Если видна этикетка, считай её главным источником и не выдумывай нечитаемые значения.',
    'Если этикетки нет, распознай блюдо и оцени порцию/состав с разумной неопределённостью.',
    'Отдельно отметь наличие жира и жареных/жирных компонентов.',
    'Не ставь диагнозы.'
  ].join('\n');
  const prompt = `Подпись пользователя: ${caption || '(нет)'}
Дневник сегодня:
${context || '(нет)'}

JSON-схема:
{
  "food_name": "строка",
  "portion_g": число или null,
  "per_100g": {"kcal": число|null, "protein_g": число|null, "fat_g": число|null, "carbs_g": число|null} или null,
  "whole_portion": {"kcal": число|null, "protein_g": число|null, "fat_g": число|null, "carbs_g": число|null} или null,
  "fat_present": true|false|null,
  "fried_or_fatty_components": ["строки"],
  "visible_label": true|false,
  "confidence": число 0..1,
  "notes": "кратко"
}`;

  const remote = await modelVision({
    system,
    text: prompt,
    imageBytes: file.bytes,
    mimeType: file.mimeType,
    maxTokens: 500
  });

  let analysis = normalizeNutrition(jsonFromText(remote.text));
  let provider = remote.provider;

  if (!analysis || analysis.confidence < 0.45) {
    const ocr = await localOcr(file.bytes);
    const ocrAnalysis = parseOcr(ocr, caption);
    if (!analysis || (ocrAnalysis?.confidence ?? 0) > analysis.confidence) {
      analysis = ocrAnalysis;
      provider = 'ocr';
    }
  }

  if (!analysis) {
    analysis = normalizeNutrition({
      food_name: caption.replace(/^я\s*(?:поел|съел)\s*[:\-]?/i, '').trim() || 'Еда по фото',
      portion_g: null,
      per_100g: null,
      whole_portion: null,
      fat_present: null,
      visible_label: false,
      confidence: 0.2,
      notes: 'Не удалось надёжно распознать фотографию.'
    });
    provider = 'fallback';
  }

  return {
    analysis,
    provider,
    reply: buildReply(state, analysis, provider),
    record: {
      name: analysis.food_name,
      portion_g: analysis.portion_g,
      nutrition: analysis.whole_portion,
      per_100g: analysis.per_100g,
      fat_present: analysis.fat_present,
      fat_class: fatClass(analysis),
      recognition_provider: provider,
      confidence: analysis.confidence
    }
  };
}
