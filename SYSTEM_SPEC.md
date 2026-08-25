# SkySakhNews — Production Specification

## 1. Назначение

SkySakhNews — полностью автоматическая система публикации новостей в Telegram. Основной приоритет — события Сахалинской области; дополнительные потоки — Россия, мир о России, геополитика и IT.

Ключевой принцип:

```text
ИИ не управляет системой и не разрешает публикацию собственного текста.
Код собирает, фильтрует, классифицирует и проверяет.
ИИ используется как переводчик/редактор, после чего его результат проверяет независимый gate.
```

Текущая production-версия: `stable-v10.2`.

---

## 2. Runtime

```yaml
platform: GitHub Actions
python: "3.11"
business_timezone: "Asia/Sakhalin UTC+11"
state_file: state.json
publisher_workflow: .github/workflows/auto_publish_v7.yml
production_entrypoint: src/editorial_gate_runner.py
posts_per_run: 2
max_age_hours: 36
run_cooldown_minutes: 20
```

Плановый запуск по Сахалину:

```text
07:00, 10:00, 13:00, 16:00, 19:00, 22:00
```

Cron UTC:

```text
0 2,5,8,11,20,23 * * *
```

---

## 3. Единственный production-контур

```text
GitHub Actions schedule/workflow_dispatch
              ↓
compile + mandatory regression suite
              ↓
src/editorial_gate_runner.py
              ↓
src/production.py
              ↓
src/news_bot_v9.py
              ↓
src/news_bot_v8.py
              ↓
Telegram Bot API
              ↓
state.json + health/audit
```

Других плановых publisher-workflow в репозитории нет.

Служебные workflows:

```yaml
production_ci.yml:
  purpose: compile and semantic regression tests
  telegram_publish: false
system_smoke_test.yml:
  purpose: manual technical smoke test
  scheduled: false
```

---

## 4. Источники

### Сахалин

```yaml
SakhalinMedia:
  mode: RSS
ASTV:
  mode: first-party HTML adapter
Sakh.online:
  mode: first-party HTML adapter
Sakhalin Google:
  mode: discovery RSS
  requirement: resolve to verified direct article URL
```

### Россия и мир

```text
Interfax
TASS
Reuters
AP News
BBC World
The Guardian World
BBC Technology
The Guardian Technology
```

Habr исключён из production из-за широкого тематического шума.

---

## 5. Полный pipeline

### 5.1. Collection

Для каждого источника система получает:

```text
RSS/HTML entry
publication datetime
title
summary/description
direct article URL
article paragraphs
article images / RSS media / OG image
```

### 5.2. Freshness

```text
publication datetime missing → reject
age > 36 hours → reject
future timestamp → reject
```

Отсутствие даты не считается доказательством свежести.

### 5.3. Direct-link integrity

Google News используется только для обнаружения материала.

```text
Google wrapper
      ↓
resolve original URL
      ↓
compare RSS title with original page title
      ↓
match → continue
mismatch / unresolved → reject
```

Финальная ссылка Google News не допускается.

### 5.4. Minimum information

Кандидат отклоняется, если:

- заголовок слишком короткий;
- описание/статья не содержит достаточной фактуры;
- материал является рекламой, рецептом, афишей, спортом или другим шумом вне потоков.

### 5.5. Initial classification

Первичный классификатор учитывает тип источника, географию и тип события. Его решение не является окончательным.

### 5.6. Category reconciliation

Модуль: `src/category_reconciler.py`.

Принцип:

```text
source headline → primary geography/topic signal
article lead    → fallback signal
publisher domain ≠ story geography
```

Приоритет правил:

1. явный IT-сюжет;
2. явная сахалинская география в заголовке;
3. явная иностранная география в заголовке;
4. сахалинская география в начале статьи;
5. раздел международных новостей;
6. российская безопасность / происшествие / экономика / политика;
7. отсутствие безопасного потока → reject.

Синдицированный материал SakhalinMedia о Хабаровске, туризме, рецептах или общероссийских советах не становится сахалинской новостью только из-за домена СМИ.

Глобальные Brent/WTI/OPEC/ECB/Fed/мировые биржи не становятся `Россия / экономика` без российского предмета новости.

### 5.7. Source/category pre-gate

До генерации текста проверяется:

```text
source title
source article meaning
reconciled category
```

Если категория не подтверждается смыслом источника, материал не передаётся редактору.

### 5.8. Editorial generation

OpenRouter получает:

```yaml
category: reconciled category
source: publisher
source_title: original title
source_text: article facts
required_facts: quake facts when applicable
```

Требования к результату:

- русский заголовок;
- два-три связных абзаца;
- только факты источника;
- evidence для заголовка и каждого абзаца;
- без списков `Суть / Что известно / Почему важно`;
- без придуманных чисел;
- без английских предложений.

### 5.9. OpenRouter reliability

Модуль: `src/editorial_gate_runner.py`.

```text
configured OPENROUTER_MODEL
          ↓ failure/empty content
openrouter/free fallback
          ↓ failure
safe extractive path or skip
```

Обрабатываются:

- пустой `message.content`;
- content в list-формате;
- отсутствие choices;
- HTTP errors;
- invalid JSON;
- timeout/rate limit.

### 5.10. Deterministic text validation

Проверяются:

- длина заголовка и поста;
- два содержательных абзаца;
- отсутствие обрывков;
- доля латиницы;
- запрещённые шаблонные фразы;
- придуманные числа;
- evidence присутствует в источнике;
- отсутствие соседних повторов;
- рекламные вставки и подписи СМИ удалены.

### 5.11. Quake fact schema

Если источник содержит параметр, итоговый пост обязан его сохранить:

```yaml
magnitude: required when present
depth_km: required when present
distance_km: required when present
intensity_points: required when present
time: required when present
```

### 5.12. Independent semantic Editorial Gate

Модуль: `src/editorial_gate.py`.

Генератор не может одобрить собственный текст.

Проверяется:

```text
generated title ↔ source headline
generated title ↔ source article
body facts ↔ source
assigned category ↔ story meaning
modality ↔ source
numbers ↔ source
clickbait ↔ source
```

Обязательные критерии:

```yaml
title_matches_source: ">= 90"
category_matches_story: ">= 90"
facts_supported: true
meaning_changed: false
```

Модальность запрещено усиливать:

```text
может       → сделал
планирует   → запустил
обсуждает   → принял
рассматривает → ввёл
ожидается   → произошло
```

Для переведённого или перефразированного заголовка требуется независимый AI-review. Жёсткую детерминированную ошибку AI-review отменить не может.

### 5.13. Extractive fallback

Если OpenRouter недоступен или generated draft не проходит проверку, русскоязычный источник может быть опубликован только через безопасный extractive fallback:

- заголовок источника без суффикса СМИ;
- два полных предложения непосредственно из статьи;
- без перефразирования;
- без добавленных чисел;
- без рекламных фрагментов;
- с повторным Editorial Gate.

Если fallback не проходит — материал пропускается.

### 5.14. Image pipeline

Приоритет:

```text
article image
RSS media
page image
OG image
```

Отбрасываются:

- logo/header/banner/icon/avatar;
- placeholder/default/social card;
- текстовые заголовочные карточки;
- слишком маленькие изображения;
- баннерные пропорции;
- слабая связь контекста картинки с заголовком;
- повтор изображения по URL или SHA1.

Для Interfax сомнительная брендовая картинка снимается.

Если безопасной картинки нет:

```text
valid story → sendMessage
```

То есть плохая картинка не убивает корректную новость.

### 5.15. Deduplication

Между запусками и внутри выпуска проверяются:

```text
article URL
normalized title SHA1
image URL
image SHA1
topic cluster
```

Одинаковая картинка снимается; повтор одного и того же сюжета пропускается.

### 5.16. Editorial order

```text
1. Сахалин, если есть прошедший кандидат
2. Мир о России
3. Россия / безопасность
4. Россия / происшествия
5. Россия / политика
6. Россия / экономика
7. Геополитика
8. IT
```

За цикл — максимум два поста. Качество важнее количества: допускается один или ноль постов.

### 5.17. Telegram publishing

```text
safe image exists → sendPhoto
photo failed      → sendMessage fallback
no safe image     → sendMessage
```

Формат:

```text
КАТЕГОРИЯ

ЖИРНЫЙ КОНКРЕТНЫЙ ЗАГОЛОВОК

абзац 1

абзац 2

РУБРИКА · источник
```

### 5.18. State and health

`state.json` хранит:

```yaml
published_urls: duplicate prevention
published_title_hashes: duplicate prevention
last_posts:
  - title
  - source
  - category_key
  - url
  - image_url
  - image_hash
  - topic_cluster
  - publish_method
  - editorial_gate
last_run:
  version: stable-v10.2
  status: running|ok|error
  candidates: integer
  local_candidates: integer
  published: integer
  local_stream: health object
  editorial_gate: audit counters
  stats: pipeline counters
```

После запуска workflow проверяет:

- `version == stable-v10.2`;
- `status == ok`;
- существует `finished_sakhalin`;
- локальный поток не `down`;
- каждый опубликованный пост имеет `editorial_gate.approved == true`;
- title/category scores не ниже 90;
- факты подтверждены;
- смысл не изменён;
- URL не является Google News.

При нарушении job завершается ошибкой.

---

## 6. Категории

```yaml
sakh:
  label: "📍 Сахалин"
  footer: "САХАЛИН"
sakh_chp:
  label: "📍 Сахалин"
  footer: "ЧП | САХАЛИН"
sakh_quake:
  label: "📍 Сахалин"
  footer: "САХАЛИН | СЕЙСМИКА"
world_ru:
  label: "🌍 Мир о России"
  footer: "МИР О РОССИИ"
ru_security:
  label: "🇷🇺 Россия / безопасность"
  footer: "РОССИЯ | БЕЗОПАСНОСТЬ"
ru_incident:
  label: "🇷🇺 Россия / происшествия"
  footer: "РОССИЯ | ПРОИСШЕСТВИЯ"
ru_pol:
  label: "🇷🇺 Россия / политика"
  footer: "РОССИЯ | ПОЛИТИКА"
ru_eco:
  label: "🇷🇺 Россия / экономика"
  footer: "РОССИЯ | ЭКОНОМИКА"
geo:
  label: "🧭 Геополитика"
  footer: "МИР | ГЕОПОЛИТИКА"
it:
  label: "💻 IT / технологии"
  footer: "IT | ТЕХНОЛОГИИ"
```

---

## 7. Обязательные регрессии

Production CI и publisher gate содержат проверки исторических ошибок:

```text
Иран/США → не Сахалин
Канада/пошлины Трампа → не Россия/экономика
Habr/магнитные ленты → не Сахалин
Хабаровский материал SakhalinMedia → не Сахалин
Brent/global oil → не Россия/экономика
БПЛА/аэропорт → Россия/безопасность
гибель/пожар/ДТП → Россия/происшествия, не политика
сахалинский прогноз дождя → Сахалин, не ЧП
иностранный материал российского СМИ → не российский поток автоматически
может/планирует → нельзя усиливать до совершённого действия
придуманное число → reject
```

---

## 8. Последняя проверка

`editorial_audit_report.json` содержит последнюю расширенную проверку на живых источниках:

```yaml
version: stable-v10.2
all_pass: true
failed: 0
```

После dry-аудита выполнен реальный one-shot Telegram run:

```yaml
version: stable-v10.2
status: ok
published: 2
local_stream: healthy
editorial_gate_pass: 2
telegram_fail: 0
```

Оба реально опубликованных поста прошли title/source, category/story, facts и modality checks.
