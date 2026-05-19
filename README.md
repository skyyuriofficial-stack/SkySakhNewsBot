# SkySakhNews Bot

Автоматический Telegram-канал новостей без VPS и без телефона.

Схема:
- GitHub Actions запускает скрипт по расписанию.
- Скрипт собирает новости из RSS / Google News / мировых СМИ.
- OpenRouter Free выбирает 2 лучшие новости и пишет русские посты.
- Telegram Bot API публикует посты в канал.
- state.json хранит уже опубликованные ссылки, чтобы не повторять новости.

## GitHub Secrets

В репозитории откройте:

Settings → Secrets and variables → Actions → New repository secret

Добавьте:

- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHANNEL_ID
- OPENROUTER_API_KEY
- OPENROUTER_MODEL, опционально. По умолчанию: openrouter/free

## Расписание

Сахалин UTC+11.

Публикации:
- 07:00 Сахалин = 20:00 UTC
- 10:00 Сахалин = 23:00 UTC
- 13:00 Сахалин = 02:00 UTC
- 16:00 Сахалин = 05:00 UTC
- 19:00 Сахалин = 08:00 UTC
- 22:00 Сахалин = 11:00 UTC

За каждый слот публикуется 2 новости.

## Ручной запуск

Actions → SkySakhNews Auto Publisher → Run workflow.
