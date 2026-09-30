# Veshudei Telegram Bot

Телеграм-бот для личного дневника снижения веса.

## Развертывание в Vercel

1. Создать новый Vercel Project из репозитория `skyyuriofficial-stack/SkySakhNewsBot`.
2. Production Branch: `veshudei-bot`.
3. Root Directory: `veshudei`.
4. Подключить приватный Vercel Blob store к проекту. Vercel добавит `BLOB_READ_WRITE_TOKEN` автоматически.
5. Добавить Environment Variables:
   - `TELEGRAM_BOT_TOKEN` — токен от BotFather.
   - `SETUP_KEY` — длинная случайная строка.
   - `CRON_SECRET` — длинная случайная строка.
6. Deploy.
7. Открыть `https://<project>.vercel.app/api/setup?key=<SETUP_KEY>` один раз. В ответе должно быть `ok: true` и bot `@veshudei_bot`.
8. В Telegram открыть `@veshudei_bot` и нажать Start.

## Расписание

- 08:37 Asia/Sakhalin — утренний контроль.
- 12:45 — перед обедом.
- 16:30 — дневной контроль.
- 20:30 — итог дня.
- Понедельник 08:20 — недельный контроль.

Vercel Cron хранится в UTC; расписания в `vercel.json` уже пересчитаны под Asia/Sakhalin (UTC+11).

## Данные

Журнал хранится в приватном Vercel Blob `veshudei/state.json`. Токены и медицинские данные не должны коммититься в GitHub.

## Команды

- `/start` — привязать чат и открыть меню.
- `/menu` — меню.
- `/today` — записи за текущий день.
