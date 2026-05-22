# SkySakhNews System Specification

```yaml
system:
  name: SkySakhNews
  purpose: >
    Автоматический новостной канал и клуб обсуждения для разумных пользователей.
    Система собирает новости, очищает их, классифицирует, проверяет редакционную значимость,
    подбирает или генерирует тематическое изображение и публикует в Telegram.

runtime:
  platform: GitHub Actions
  timezone_business: Asia/Sakhalin UTC+11
  language: Python 3.11
  secrets:
    required:
      - TELEGRAM_BOT_TOKEN
      - TELEGRAM_CHANNEL_ID
    optional:
      - OPENROUTER_API_KEY
      - OPENROUTER_MODEL

workflows:
  editorial_cycle:
    file: .github/workflows/editorial_cycle.yml
    triggers:
      - workflow_dispatch
      - schedule
      - push_on_editorial_files
    pipeline:
      - Collect drafts
      - Review drafts
      - Priority guard
      - Final guard
      - Publish approved image posts only
      - Commit queue and state
  minimum_release:
    file: .github/workflows/minimum_release.yml
    triggers:
      - workflow_dispatch
      - workflow_run_after_editorial_cycle
    pipeline:
      - Apply minimum release policy
      - Final guard
      - Publish approved image posts only
      - Commit queue and state
  cycle_report:
    file: .github/workflows/editorial_cycle_report.yml
    triggers:
      - workflow_dispatch
      - workflow_run_after_editorial_cycle
    pipeline:
      - Build cycle report
      - Commit cycle report
  smoke_test:
    file: .github/workflows/system_smoke_test.yml
    triggers:
      - workflow_dispatch
    purpose: >
      Проверить исполняемость: чтение файлов, генерация изображения, Telegram getMe/getChat,
      опционально sendPhoto/deleteMessage.

state_files:
  editorial_queue_json:
    path: editorial_queue.json
    role: Очередь черновиков и их статусы.
    statuses:
      pending: Собрано, ещё не проверено.
      hold: В резерве, не публиковать автоматически без дополнительной политики.
      approved: Разрешено к публикации.
      rejected: Отклонено.
      published: Уже опубликовано.
  state_json:
    path: state.json
    role: История опубликованных URL, хэшей заголовков, last_posts, last_cycle_report.
  cycle_report_json:
    path: cycle_report.json
    role: Машиночитаемый итог последнего цикла.

modules:
  editorial_queue:
    file: src/editorial_queue.py
    role: Сбор кандидатов, сохранение черновиков, базовые функции публикации/очереди.
  editorial_review:
    file: src/editorial_review.py
    role: Автоматический редактор: отбор, русификация, первичная категория, reject/hold/approved.
  editorial_priority_guard:
    file: src/editorial_priority_guard.py
    role: Понижение рутинных сводок, особенно ПВО/режимные сообщения без последствий.
  editorial_minimum_release:
    file: src/editorial_minimum_release.py
    role: >
      Резервная политика: если строгий цикл дал approved=0, выбрать максимум 1 безопасный материал.
      Запрещены слабые отрицательные заметки, консульские сообщения, реклама, туториалы, скидки.
  editorial_guard:
    file: src/editorial_guard.py
    role: >
      Финальный стоп перед публикацией: реклама/английский/низкоприоритетные игры/битые тексты.
      Также исправляет категорию и пересобирает текст approved-постов.
  editorial_publish_safe:
    file: src/editorial_publish_safe.py
    role: >
      Безопасный publisher. Публикует только approved. Всегда через sendPhoto.
      Использует source image или локальную generated semantic image.
  thematic_image:
    file: src/thematic_image.py
    role: >
      Локальная генерация тематических изображений 1200x675 через Pillow без внешнего AI.
  editorial_cycle_report:
    file: src/editorial_cycle_report.py
    role: Отчётность: status_counts, approved, published, guards, decision.
  system_smoke_test:
    file: src/system_smoke_test.py
    role: Техническая проверка исполняемости системы.

editorial_policy:
  hard_reject:
    - реклама
    - скидки
    - маркетплейсы
    - драйверы/download pages
    - туториалы
    - личный опыт/колонки вместо новостей
    - англоязычный итоговый текст
    - игровые новости без крупной индустриальной значимости
  security_stream:
    name: РФ / война и безопасность
    publish_if:
      - погибшие
      - раненые
      - ущерб
      - повреждение объекта
      - массовое отключение
      - атака/удар/обстрел с последствиями
      - важный военный/силовой контекст
    reject_or_hold_if:
      - просто режим Ковер
      - просто угроза БПЛА
      - просто сбили N БПЛА без ущерба/жертв/последствий
  incident_stream:
    name: РФ / происшествия
    examples:
      - пожар
      - ДТП
      - авария
      - бытовое ЧП
      - криминал
    rule: >
      Если есть пожар/ДТП/бытовое ЧП/криминал и нет БПЛА/обстрела/войны/диверсии,
      категория должна быть РФ / происшествия, не РФ / война и безопасность.
  economy_stream:
    name: РФ / экономика
    examples:
      - банки
      - кредиты
      - ставки
      - нефть/газ/СПГ
      - зерно/сельское хозяйство
      - экспорт/импорт
  geopolitics_stream:
    name: Геополитика
    examples:
      - Иран
      - Израиль
      - США
      - НАТО
      - Китай
      - Куба
      - ООН
  it_stream:
    name: Мировые IT
    publish_if:
      - крупная компания
      - AI/ИИ
      - кибербезопасность
      - CVE/уязвимость
      - важный продукт/рынок
  games_stream:
    name: Игры / индустрия
    priority: lowest
    publish_if:
      - крупная студия
      - GTA/Rockstar/CD Projekt/PlayStation/Xbox/Nintendo
      - сделка/суд/массовые увольнения/крупный релиз

image_policy:
  required: true
  publication_method: Telegram sendPhoto only
  order:
    - source image when the original source provides a usable image
    - generated semantic image when no usable source image exists
  forbidden:
    - random category fallback photos
    - category_file oil platform for non-energy economy
    - thematic image that contradicts title/body
  generated_semantic_rules:
    economy:
      agriculture_terms: fields/grain/agrofinance visual
      bank_terms: bank/credit visual
      energy_terms: oil/gas/energy visual
      industry_terms: factory/industry visual
    incidents:
      fire_terms: neutral fire/emergency visual
      road_terms: road accident visual
      crime_terms: police/legal incident visual
    security: radar/air-defense/security visual
    geopolitics: diplomacy/flags/summit visual
    it: servers/network/chip visual
    games: gamepad/game industry visual

quality_gates:
  before_publish:
    - status must be approved
    - text must be Russian enough
    - text must not contain duplicate paragraphs
    - text must not contain broken unfinished long paragraph
    - category must match semantic text
    - image must exist
    - post must be sent via safe publisher
  report_decisions:
    published: At least one post was published recently.
    no_approved_to_publish: Nothing safe was approved.
    approved_left_unpublished_check_publish_step: Approved item existed but publish did not send.
```
