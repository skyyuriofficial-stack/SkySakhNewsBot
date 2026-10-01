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

  try {
    const result = await generateText({
      model: 'openai/gpt-5.6-sol',
      system,
      prompt,
      maxOutputTokens: 500,
      temperature: 0.2
    });
    return String(result.text || '').trim();
  } catch (error) {
    console.error('AI Gateway error', error);
    return 'Я понял вопрос, но ИИ-ответ сейчас временно недоступен. Дневник продолжает работать. Повтори вопрос чуть позже.';
  }
}
