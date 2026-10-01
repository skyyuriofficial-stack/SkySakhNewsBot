import { generateText } from 'ai';

function fmtEvent(e) {
  return '[' + e.day + '] ' + e.type + ': ' + String(e.value);
}

function recentContext(state) {
  const events = (state.events || [])
    .filter((e) => !['system'].includes(e.type))
    .slice(-60);
  const diary = events.filter((e) => !['chat_user','chat_assistant'].includes(e.type)).map(fmtEvent).join('\n');
  const chat = events.filter((e) => ['chat_user','chat_assistant'].includes(e.type)).slice(-10).map((e) => (e.type === 'chat_user' ? 'Пользователь: ' : 'Ассистент: ') + String(e.value)).join('\n');
  return { diary, chat };
}

function localFallback(state, userText) {
  const t = String(userText || '').toLowerCase();
  const today = (state.events || []).filter((e) => e.day === new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Sakhalin', year: 'numeric', month: '2-digit', day: '2-digit'
  }).format(new Date()));

  if (/вечер.*не\s*ем|вечер.*не\s*есть|не\s*ужин|пропуст.*ужин/i.test(t)) {
    return 'Специально не есть вечером не нужно. Если голод есть — сделай умеренный ужин с белком и овощами; если голода нет, насильно есть не требуется. Не компенсируй дневной рацион голоданием.';
  }
  if (/что.*съесть|что.*есть|ужин/i.test(t)) {
    return 'Для ужина выбери простой вариант: порция белка + овощи, без попытки «доголодать» день. Если напишешь, что уже ел сегодня и насколько голоден по шкале 0–10, уточню вариант.';
  }
  if (/пив|алкогол|вино|водк|виски|коньяк/i.test(t)) {
    return 'Алкоголь учитываем отдельно: орлистат его калории не блокирует. На следующий день не голодай в компенсацию — вернись к обычному режиму питания и воды.';
  }
  if (/листат|орлистат/i.test(t)) {
    return 'Листату Мини 60 мг не используй для компенсации переедания. Принимай только по инструкции к препарату и не увеличивай дозу самостоятельно.';
  }

  const hasMeal = today.some((e) => e.type === 'meal');
  const hasWater = today.some((e) => e.type === 'water');
  if (!hasMeal) return 'Чтобы дать точный совет, сначала напиши, что и примерно сколько съел сегодня.';
  if (!hasWater) return 'По еде запись есть. Добавь, сколько воды выпил сегодня, и я дам более точный следующий шаг.';
  return 'По дневнику отвечу напрямую. Напиши, что именно хочешь решить сейчас: ужин, голод, алкоголь, вода, активность или вес.';
}

export async function askCoach(state, userText) {
  const { diary, chat } = recentContext(state);
  const now = new Intl.DateTimeFormat('ru-RU', {
    timeZone: 'Asia/Sakhalin', dateStyle: 'full', timeStyle: 'short'
  }).format(new Date());

  const system = `Ты — персональный помощник по контролю снижения веса в Telegram.
Отвечай по-русски, коротко, конкретно и без морализаторства.
Главная задача — анализировать текущий дневник и давать выполнимый следующий шаг.
Учитывай еду, алкоголь, воду, активность, вес, самочувствие, семаглутид (Семавик) и орлистат, если они реально записаны.
Не выдумывай отсутствующие данные. Если для ответа критично не хватает факта — задай один короткий уточняющий вопрос.
Не предлагай голодание как наказание за срыв или алкоголь. При снижении аппетита следи, чтобы пользователь не уходил в бессмысленный недобор белка и жидкости.
Не меняй самостоятельно дозировки рецептурных препаратов и не советуй повышать/возобновлять семаглутид без врача. Для орлистата учитывай, что дозировка зависит от конкретного препарата и его инструкции.
Алкогольные калории орлистат не блокирует; вес после алкоголя может временно меняться из-за жидкости.
При сильной или постоянной боли в животе, повторной рвоте, невозможности пить, желтухе, обмороке или резком ухудшении самочувствия советуй срочную медицинскую оценку.
Если вопрос обычный (например «вечером не ем?»), дай прямой ответ и 1–3 конкретных действия.
Обычно отвечай 2–6 предложениями. Не добавляй длинных лекций и лишних дисклеймеров.
Текущее сахалинское время: ${now}.`;

  const prompt = `ДНЕВНИК (последние записи):\n${diary || 'нет записей'}\n\nПОСЛЕДНИЙ ДИАЛОГ:\n${chat || 'нет'}\n\nНОВОЕ СООБЩЕНИЕ ПОЛЬЗОВАТЕЛЯ:\n${userText}`;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 7000);
  try {
    const result = await generateText({
      model: 'openai/gpt-5.6-sol',
      system,
      prompt,
      maxOutputTokens: 500,
      temperature: 0.2,
      abortSignal: controller.signal
    });
    const answer = String(result.text || '').trim();
    return answer || localFallback(state, userText);
  } catch (error) {
    console.error('AI Gateway error', error);
    return localFallback(state, userText);
  } finally {
    clearTimeout(timer);
  }
}
