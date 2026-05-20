# Bella Vladi Face Protocol

Production-ready проект для Telegram-бота Bella Vladi Face Protocol: AI-анализ лица, финальный PNG-протокол, подробный web-отчет, after-photo, админ-панель, очереди, воркеры, webhook и нагрузочный mock-тест.

## Основной сценарий

1. Пользователь открывает Telegram-бота.
2. Проходит согласие, вводит имя, отправляет фото и выбирает зоны/проблемы.
3. Backend сохраняет заявку и отправляет ее в очередь.
4. AI создает подробный `analysis_json`.
5. AI создает короткий `protocol_copy_json` для визуального протокола.
6. Backend нормализует copy, чтобы не ломать layout.
7. Renderer создает один финальный PNG из HTML-шаблона.
8. Backend создает публичный подробный отчет.
9. Telegram отправляет пользователю PNG-протокол и ссылку на отчет.
10. After-photo генерируется отдельным этапом и отправляется только после quality check.

## Что реализовано

- Telegram-бот на aiogram 3.
- Webhook mode для продакшена.
- Optional polling mode для локальной отладки.
- FastAPI backend.
- React/Vite/TypeScript admin panel.
- Публичная страница отчета `/report/:publicToken`.
- PostgreSQL база данных.
- Redis для Celery и progress-state.
- Celery очереди и отдельные воркеры.
- Final face protocol renderer `face_protocol_final`.
- HTML to PNG render через Playwright/Chromium.
- AI analysis pipeline.
- Отдельный `protocol_copy_json`, без вставки сырого `analysis_json` в картинку.
- Нормализация текста под карточки протокола.
- After-photo pipeline через image edit.
- Quality check и выбор лучшего after-photo.
- Knowledge base и prompt templates.
- Админка для заявок, отчетов, настроек, промптов, базы знаний и рассылок.
- Mock mode без траты OpenAI API.
- Нагрузочный mock-тест на массовые заявки.

## Структура проекта

```text
apps/
  backend/
    app/
      ai/                         AI-клиенты, промпты, схемы, image edit client
      after_photo/                Новый universal after-photo pipeline
      api/                        FastAPI routes
      bot/                        Telegram handlers, webhook, progress messages
      core/                       Config, logging, security
      db/                         SQLAlchemy models, seed, sessions
      knowledge/                  Knowledge base loader, chunker, retriever
      load_tests/                 Mock load tests без OpenAI API
      reports/                    HTML report и protocol renderers
      storage/                    Local/S3 storage adapters
      workers/                    Celery app и queue tasks
    alembic/                      Миграции БД
    Dockerfile
    requirements.txt
  frontend/
    src/                          Admin panel и public report
    nginx.conf                    Proxy `/api` и `/storage` в backend
docker-compose.yml
face_protocol.html                Исходный визуальный reference HTML
```

## Docker-сервисы

Все основные процессы разделены в `docker-compose.yml`.

### `postgres`

PostgreSQL 16.

Хранит:

- Telegram-пользователей
- лиды
- заявки на анализ
- выбранные проблемы
- `analysis_json`
- `protocol_copy_json`
- отчеты
- настройки бота
- prompt templates
- knowledge documents
- AI job logs
- after-photo variants и QC results
- пути к фото, PNG и report token

### `redis`

Redis используется для:

- Celery broker
- очередей `analysis`, `report`, `after_photo`, `telegram`
- состояния progress-сообщений Telegram
- lock при startup webhook, чтобы несколько uvicorn workers не дергали `setWebhook` одновременно
- мониторинга очередей в load-test

### `minio`

Локальный S3-compatible storage.

Проект может работать:

- через локальный диск, `STORAGE_DRIVER=local`
- через S3/MinIO, `STORAGE_DRIVER=s3`

### `backend`

FastAPI сервис.

Что делает:

- применяет Alembic migrations
- seed-ит админа, настройки и prompt templates
- принимает Telegram webhook
- отдает admin API
- отдает public report API
- обслуживает storage files
- ставит Telegram webhook
- отдает `/health`

Локально:

```text
http://localhost:8000
```

### `worker_analysis`

Celery worker для очереди `analysis`.

Что делает:

- берет заявку из очереди
- загружает фото
- запускает AI-анализ
- сохраняет `analysis_json`
- генерирует `protocol_copy_json`
- нормализует copy
- рендерит финальный PNG-протокол
- сохраняет `face_protocol_version=final_v1`
- сохраняет `face_protocol_image_path`
- запускает генерацию отчета
- ставит задачи Telegram-send
- запускает after-photo отдельно

### `worker_report`

Celery worker для очереди `report`.

Что делает:

- создает detailed report
- сохраняет публичный report token
- готовит данные для `/report/:publicToken`
- не блокирует Telegram webhook и основной analysis worker

### `worker_after_photo`

Celery worker для очереди `after_photo`.

Что делает:

- берет оригинальное фото пользователя
- использует fixed universal prompt
- не использует подробный `analysis_json` для prompt generation
- генерирует несколько variants
- делает quality check
- выбирает лучший approved variant
- сохраняет final after-photo
- ставит статус `APPROVED`, `NEEDS_MANUAL_REVIEW`, `FAILED` или `SKIPPED_NO_API_KEY`

### `worker_telegram`

Celery worker для очереди `telegram`.

Что делает:

- редактирует progress-сообщения в Telegram
- отправляет финальный PNG-протокол
- отправляет ссылку на подробный отчет
- отправляет after-photo, если оно approved
- отправляет fallback-сообщение, если after-photo skipped/failed/manual review

### `bot_polling`

Опциональный сервис только для локальной отладки.

Production mode:

```env
TELEGRAM_UPDATE_MODE=webhook
```

Polling mode:

```bash
docker compose --profile polling up -d bot_polling
```

### `frontend`

React/Vite/TypeScript frontend, который включает:

- admin panel
- public report page

Nginx внутри frontend контейнера проксирует:

- `/api/` в backend
- `/storage/` в backend

Локально:

```text
http://localhost:5173
```

## Telegram-бот

Файлы:

```text
apps/backend/app/bot/
```

Реализованные handlers:

- `handlers_start.py`
- `handlers_consent.py`
- `handlers_name.py`
- `handlers_photo.py`
- `handlers_problems.py`

Пользовательский flow:

1. `/start`
2. согласие
3. ввод имени
4. загрузка фото
5. выбор проблем
6. создание заявки
7. progress-сообщение
8. фоновая генерация
9. отправка PNG-протокола
10. отправка ссылки на подробный отчет
11. отдельная отправка after-photo при approved status

Progress-сообщения:

```text
apps/backend/app/bot/progress.py
apps/backend/app/workers/tasks_telegram.py
```

Пользователь видит, что идет:

- постановка в очередь
- анализ фото
- подготовка персонального протокола
- рендер PNG
- подготовка подробного отчета
- готовый результат

## Telegram webhook

Endpoint:

```text
POST /api/telegram/webhook
```

Файлы:

```text
apps/backend/app/api/routes_telegram.py
apps/backend/app/bot/webhook.py
```

Поддерживается:

- webhook startup при запуске backend
- `TELEGRAM_WEBHOOK_URL`
- `TELEGRAM_WEBHOOK_SECRET`
- `TELEGRAM_WEBHOOK_DROP_PENDING_UPDATES`
- Redis lock для защиты от повторного `setWebhook`
- fallback polling mode для debug

## AI-анализ лица

Файлы:

```text
apps/backend/app/ai/
```

Главные модули:

- `openai_client.py`
- `gemini_client.py`
- `openai_image_client.py`
- `prompts.py`
- `schemas.py`
- `json_repair.py`
- `default_system_prompt.md`

AI stage создает подробный `analysis_json`.

Промпт и база знаний настроены на:

- морфотипы старения
- тип кожи
- тип лица
- зоны внимания
- сильные стороны
- персональное объяснение "почему это происходит"
- мягкий экспертный тон
- отсутствие диагнозов и медицинских обещаний

## Knowledge base

Файлы:

```text
apps/backend/app/knowledge/
```

Реализовано:

- default knowledge base markdown
- loader документов
- chunker
- retriever
- upload/list через admin API

База знаний используется для того, чтобы анализ и протокол были не сухими, а персональными и интересными.

Основной default-файл:

```text
apps/backend/app/knowledge/default_knowledge_base.md
```

## Protocol copy JSON

Визуальный протокол не берет сырой `analysis_json` напрямую.

Pipeline:

```text
analysis_json
-> protocol_copy_json
-> normalize_protocol_copy()
-> template.html
-> PNG
```

Файлы:

```text
apps/backend/app/reports/face_protocol_final/schema.py
apps/backend/app/reports/face_protocol_final/normalize.py
```

Нормализация нужна, чтобы:

- ограничивать длину текста
- не ломать карточки
- не вставлять длинные AI-абзацы
- приводить названия зон к короткому виду
- сохранять стабильный layout

## Финальный Face Protocol PNG

Активный renderer:

```text
apps/backend/app/reports/face_protocol_final/
```

Source of truth:

```text
apps/backend/app/reports/face_protocol_final/template.html
```

Главная функция:

```python
render_face_protocol_final_v1(...)
```

Что делает:

- берет `protocol_copy_json`
- нормализует данные
- подставляет Jinja2 variables в HTML
- подставляет фото пользователя
- открывает HTML через Playwright
- делает screenshot только `.sheet`
- сохраняет один PNG
- возвращает путь к PNG

В новых заявках сохраняется:

```text
face_protocol_version = final_v1
face_protocol_image_path = путь к PNG
protocol_copy_json = JSON для шаблона
```

Preview:

```bash
docker compose run --rm backend python -m app.reports.face_protocol_final.preview
```

Smoke-test:

```bash
docker compose run --rm backend python -m app.reports.face_protocol_final.smoke_test
```

## Legacy renderers

Старые renderers оставлены только как guard:

- `apps/backend/app/reports/protocol_image.py`
- `apps/backend/app/reports/protocol_v2/`
- `apps/backend/app/reports/protocol_v3/`
- `apps/backend/app/reports/protocol_v4/`

Они не должны использоваться для новых заявок.

При вызове падают с:

```text
LEGACY_FACE_PROTOCOL_RENDERER_DISABLED_USE_FINAL_V1
```

## Public detailed report

Frontend route:

```text
/report/:publicToken
```

Backend:

```text
apps/backend/app/api/routes_public.py
```

Frontend:

```text
apps/frontend/src/pages/PublicReport.tsx
```

Отчет использует `reportViewModel`, а не вставляет сырой JSON на страницу.

На странице есть:

- loading state
- error state
- original photo
- final protocol PNG
- after-photo block
- after-photo pending/failed/ready/skipped/manual-review states
- персональные блоки анализа
- зоны роста
- сильные стороны
- CTA
- responsive mobile layout

События:

- `report_opened`
- `cta_clicked`

## After-photo

Файлы:

```text
apps/backend/app/after_photo/
```

Модули:

- `prompt_builder.py`
- `generator.py`
- `quality_check.py`
- `schemas.py`
- `preview.py`
- `smoke_test.py`

Новая логика:

```text
original photo
-> fixed universal prompt
-> intensity preset
-> image edit endpoint
-> variants
-> quality check
-> choose best
-> final
-> Telegram send only if approved
```

Главный принцип:

```text
after-photo не строится из detailed analysis_json и зон.
```

After-photo использует:

- оригинальное фото
- fixed prompt
- negative prompt
- preset intensity
- retry logic
- quality check

Intensity presets:

- `subtle`
- `balanced`
- `visible`

Default:

```env
AFTER_PHOTO_DEFAULT_INTENSITY=balanced
```

Quality check оценивает:

- same identity
- realism
- visible improvement
- skin texture preserved
- too much retouch
- plastic surgery effect

Если ключей нет:

```text
SKIPPED_NO_API_KEY
```

Основной анализ, протокол и отчет при этом не ломаются.

Preview:

```bash
docker compose run --rm backend python -m app.after_photo.preview
```

Smoke-test:

```bash
docker compose run --rm backend python -m app.after_photo.smoke_test
```

## Admin panel

URL:

```text
http://localhost:5173/login
```

Seed admin:

```text
admin@bellavladi.local
admin12345
```

Разделы:

- Dashboard
- Leads
- Lead detail
- Analysis
- Analysis detail
- Reports
- Knowledge Base
- Prompt Templates
- Broadcasts
- Campaigns
- Admins
- Settings

В карточке анализа можно смотреть:

- user photo
- selected problems
- `analysis_json`
- `protocol_copy_json`
- personal insight JSON
- final face protocol PNG
- public report link
- after-photo status
- after-photo variants
- after-photo quality results
- final after-photo
- AI logs/errors

Действия:

- regenerate analysis
- regenerate protocol copy
- regenerate face protocol PNG
- regenerate public report
- regenerate after-photo
- edit settings
- edit CTA
- edit prompts
- upload knowledge documents
- broadcast messages

## Prompt templates

Prompt templates создаются seed-ом и редактируются в админке.

Типовые шаблоны:

- analysis system prompt
- short protocol copy prompt
- detailed report prompt
- after-photo prompt
- after-photo negative prompt
- bot tone
- disclaimer

Это позволяет менять AI-логику и тексты без изменения кода, если меняется только copy/prompt.

## Storage

Storage adapters:

```text
apps/backend/app/storage/local.py
apps/backend/app/storage/s3.py
```

Local mode:

```env
STORAGE_DRIVER=local
LOCAL_STORAGE_PATH=./storage
```

S3/MinIO mode:

```env
STORAGE_DRIVER=s3
S3_ENDPOINT=
S3_BUCKET=
S3_ACCESS_KEY_ID=
S3_SECRET_ACCESS_KEY=
S3_REGION=
```

Что хранится:

- uploaded user photos
- final protocol PNG
- HTML previews
- after-photo variants
- final after-photo
- dev debug files

Runtime files не коммитятся в git.

## Очереди и масштабирование

Celery app:

```text
apps/backend/app/workers/celery_app.py
```

Очереди:

- `analysis`
- `report`
- `after_photo`
- `telegram`

Task files:

- `tasks_analysis.py`
- `tasks_report.py`
- `tasks_after_photo.py`
- `tasks_telegram.py`
- `tasks_broadcast.py`

Масштабирование:

```bash
docker compose up -d --scale worker_analysis=3 --scale worker_report=2 --scale worker_telegram=2
```

Concurrency env:

```env
WEB_CONCURRENCY=2
ANALYSIS_WORKER_CONCURRENCY=2
REPORT_WORKER_CONCURRENCY=1
AFTER_PHOTO_WORKER_CONCURRENCY=1
TELEGRAM_WORKER_CONCURRENCY=4
CELERY_RESULT_EXPIRES_SECONDS=3600
```

Для большой нагрузки after-photo лучше держать отдельной низкой очередью или временно отключить:

```env
ENABLE_AFTER_PHOTO=false
```

## Load test

Mock load-test:

```text
apps/backend/app/load_tests/mock_analysis_batch.py
```

Он создает синтетические заявки и прогоняет pipeline без расходов OpenAI API.

Запуск:

```bash
docker compose run --rm backend python -m app.load_tests.mock_analysis_batch --count 500 --queue load_test_analysis
```

Отдельный безопасный worker:

```bash
docker compose run -d --name facefitness-load-worker-500 \
  -e AI_FORCE_MOCK=true \
  -e OPENAI_API_KEY= \
  -e ENABLE_AFTER_PHOTO=false \
  backend celery -A app.workers.celery_app worker \
  --loglevel=info -Q load_test_analysis --concurrency=4
```

Проект прогонялся на 500 mock-заявках без OpenAI API calls.

## Database и migrations

Migrations:

```text
apps/backend/alembic/versions/
```

Models:

```text
apps/backend/app/db/models.py
```

Важные поля новых заявок:

```text
face_protocol_version
face_protocol_image_path
protocol_copy_json
after_photo_status
after_photo_variant_paths
after_photo_final_path
after_photo_quality_results
after_photo_used_intensity
after_photo_retry_count
```

## API routes

Backend routes:

- `routes_auth.py` - auth/login
- `routes_admins.py` - admins
- `routes_analysis.py` - analysis operations/regeneration
- `routes_broadcasts.py` - Telegram broadcasts
- `routes_campaigns.py` - campaign/deep links
- `routes_dashboard.py` - dashboard metrics
- `routes_knowledge.py` - knowledge base
- `routes_leads.py` - leads
- `routes_prompts.py` - prompt templates
- `routes_public.py` - public report API/events
- `routes_reports.py` - generated reports
- `routes_settings.py` - settings/CTA
- `routes_telegram.py` - Telegram webhook

## Быстрый старт

```bash
cp .env.example .env
docker compose up -d --build
```

Открыть:

```text
Backend health: http://localhost:8000/health
Admin:          http://localhost:5173/login
MinIO console:  http://localhost:9001
```

## Локальный запуск без Docker

Backend:

```bash
cd apps/backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
python -m app.db.seed
uvicorn app.main:app --reload
```

Worker:

```bash
cd apps/backend
source .venv/bin/activate
celery -A app.workers.celery_app worker --loglevel=info -Q analysis,report,after_photo,telegram
```

Frontend:

```bash
cd apps/frontend
npm install
npm run dev
```

## Telegram setup

Для локального webhook через ngrok:

```bash
ngrok http 8000
```

`.env`:

```env
BACKEND_URL=https://your-ngrok-domain
TELEGRAM_WEBHOOK_URL=https://your-ngrok-domain/api/telegram/webhook
TELEGRAM_UPDATE_MODE=webhook
TELEGRAM_BOT_TOKEN=
TELEGRAM_BOT_USERNAME=
```

Перезапуск:

```bash
docker compose up -d --build backend worker_analysis worker_report worker_after_photo worker_telegram
```

Polling для debug:

```bash
docker compose --profile polling up -d bot_polling
```

## Environment variables

Скопировать:

```bash
cp .env.example .env
```

Ключевые переменные:

```env
DATABASE_URL=
REDIS_URL=
BACKEND_URL=
FRONTEND_URL=
PUBLIC_APP_URL=
CORS_ORIGINS=
JWT_SECRET=

TELEGRAM_BOT_TOKEN=
TELEGRAM_WEBHOOK_URL=
TELEGRAM_UPDATE_MODE=webhook
TELEGRAM_WEBHOOK_SECRET=
TELEGRAM_BOT_USERNAME=

OPENAI_API_KEY=
OPENAI_ANALYSIS_MODEL=
OPENAI_PROTOCOL_COPY_MODEL=
OPENAI_REPORT_MODEL=
OPENAI_AFTER_PHOTO_IMAGE_MODEL=gpt-image-2
OPENAI_VISION_QA_MODEL=

FACE_PROTOCOL_VERSION=final_v1
ENABLE_AFTER_PHOTO=true
AFTER_PHOTO_PROVIDER=openai
AFTER_PHOTO_DEFAULT_INTENSITY=balanced
AFTER_PHOTO_VARIANT_COUNT=3

STORAGE_DRIVER=local
LOCAL_STORAGE_PATH=./storage
```

Файл `.env` нельзя коммитить. Он уже добавлен в `.gitignore`.

## Mock mode

Mock mode включается:

```env
AI_FORCE_MOCK=true
```

или автоматически, если нет OpenAI key/model.

Mock mode нужен для:

- локальной разработки
- smoke tests
- preview
- load tests
- проверки Telegram flow без расходов AI API

## Проверки

Face protocol preview:

```bash
docker compose run --rm backend python -m app.reports.face_protocol_final.preview
```

Face protocol smoke-test:

```bash
docker compose run --rm backend python -m app.reports.face_protocol_final.smoke_test
```

After-photo preview:

```bash
docker compose run --rm backend python -m app.after_photo.preview
```

After-photo smoke-test:

```bash
docker compose run --rm backend python -m app.after_photo.smoke_test
```

Health:

```bash
curl http://localhost:8000/health
```

Queue length:

```bash
docker compose exec redis redis-cli llen analysis
docker compose exec redis redis-cli llen report
docker compose exec redis redis-cli llen after_photo
docker compose exec redis redis-cli llen telegram
```

## Production checklist

Перед трафиком:

- заменить `JWT_SECRET`
- заменить seed admin password
- выставить публичные HTTPS домены
- настроить Telegram webhook
- проверить `getWebhookInfo`
- указать OpenAI model names
- решить, включать ли after-photo на первом трафике
- настроить worker scaling
- использовать S3/MinIO для persistent photo storage при нескольких хостах
- выполнить Alembic migrations
- запустить smoke-tests
- запустить mock load-test
- проверить Redis queue lengths
- проверить worker logs
- настроить backup PostgreSQL
- настроить log aggregation/Sentry/monitoring

## Git и runtime files

В репозиторий не попадают:

- `.env`
- local storage
- generated protocol PNG
- after-photo variants
- logs
- frontend `dist`
- `node_modules`
- Python caches

В git лежат только source code, migrations, templates, prompts, Docker config и документация.

