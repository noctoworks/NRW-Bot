# NRW-Bot

Telegram-бот для продажи VPN-подписки поверх [Remnawave](https://remna.st/)
(панель управления VPN-нодами) — упрощённый клон Bedolaga VPN-бота. Продажа
через сам бот **и** через встроенный Telegram Mini App с полноценной
веб-админкой (аналитика, LTV/когорты, MRR/churn, управление пользователями и
маркетинговыми кампаниями).

## Возможности

**Пользователю (бот + Mini App):**
- Покупка/продление подписки (СБП/карты через [Platega](https://platega.io/),
  подтверждение поллингом — вебхук не требуется, не нужен публичный домен для
  самого бота), реферальная программа с настраиваемым % и промогруппами
  (скидочные тиры), бесплатный пробный период, подарочные коды, промокоды.
- Mini App: дашборд подписки (трафик/срок/статус), быстрое подключение по
  deep-link в VPN-клиент, экран оплаты с выбором периода — тот же UI,
  1-в-1 повторяющий разметку/токены реального прод-референса (см. `src/`).

**Администратору:**
- Всё то же самое, что в боте (`app/handlers/admin.py`), плюс веб-панель
  (`/cabinet/admin/*`, открывается расширением того же Mini App на десктопе —
  видна только `User.is_admin`): список/карточка пользователя, баланс,
  блокировка, устройства (просмотр/сброс через Remnawave), синхронизация
  БД↔панель, персональный % реферала, промогруппы, маркетинговые кампании
  (deep-link с бонусом — баланс/дни подписки/только атрибуция) со статистикой
  конверсии, полная аналитика: overview, revenue timeseries, LTV, когорты,
  реферальная воронка.
- **Шаблоны автоматических сообщений** (18 событий: оплата, окончание подписки,
  бонусы, напоминания и т.д.): владелец меняет текст, текст кнопки и включает/
  отключает событие — в боте (`/admin` → «✉️ Сообщения») или через API
  `/cabinet/admin/notifications/*`. Разметка HTML с белым списком тегов, кастомные
  эмодзи через `<tg-emoji emoji-id="…">` (нужен Telegram Premium у владельца бота).
  Заводские тексты живут в коде (`app/services/message_templates/registry.py`),
  правки — в таблице `message_templates`; при ошибке разметки уходит заводской
  текст, уведомление не теряется. Подробности — `docs/superpowers/specs/2026-09-21-message-templates-design.md`.

## Архитектура

Один Python-процесс: aiogram-бот (long polling, вебхук не используется) +
опционально FastAPI (`/cabinet/*`, тот же процесс через `asyncio.Task`,
включается `CABINET_ENABLED=true`) — обслуживает и Mini App API, и админку.
Постоянное состояние — Postgres (или SQLite для локальной разработки без
Docker), FSM-хранилище — Redis либо in-memory, если `REDIS_URL` не задан.

```
app/
  config.py              # вся конфигурация — читается из .env (pydantic-settings)
  bot.py                 # сборка Dispatcher, middleware, регистрация хендлеров
  handlers/               # start, subscription, gift, referral, promocode, support, admin,
                            # message_templates_admin (редактор сообщений)
  database/models.py       # ORM-модели (users, subscriptions, tariffs, transactions,
                            # promo_groups, campaigns, referral_earnings, ...)
  external/remnawave/       # интерфейс RemnawaveClient + mock.py (без реальной панели) + real.py
  services/payment/          # интерфейс PaymentProvider + stub.py + platega.py
  services/                   # pricing, referral, campaign, analytics, background-задачи,
                               # balance_service (атомарные операции с балансом)
  services/message_templates/  # реестр событий, рендер/валидация, кэш правок, отправка с откатом
  runtime.py                   # надзор за фоновыми задачами; external/http.py — HTTP с ретраями
  cabinet/                     # FastAPI: /cabinet/* (Mini App) и /cabinet/admin/* (веб-админка)
migrations/                    # Alembic
scripts/
  seed.py                       # сидит тариф + сквады из Remnawave
  migrate_from_old_bot.py        # разовый перенос данных со старого бота (см. докстринг файла)
main.py                          # entrypoint
```

Remnawave и провайдер оплаты спрятаны за интерфейсом (`RemnawaveClient`,
`PaymentProvider`) — переключение mock↔real / stub↔real только через `.env`,
без изменений в коде хендлеров.

## Быстрый старт через Docker (рекомендуется)

Поднимает бота + Postgres в двух контейнерах. По умолчанию — `REMNAWAVE_MODE=mock`
(Remnawave не трогается, работает заглушка в памяти) и `PAYMENTS_MODE=stub`
(любая оплата мгновенно считается успешной) — можно потрогать весь флоу бота
без реальной VPN-панели и реальных платёжных ключей.

```bash
git clone https://github.com/noctoworks/NRW-Bot.git
cd NRW-Bot
cp .env.example .env
```

В `.env` обязательно впишите:
- `BOT_TOKEN` — токен тестового бота от [@BotFather](https://t.me/BotFather)
- `ADMIN_TELEGRAM_IDS` — ваш Telegram id (узнать у [@userinfobot](https://t.me/userinfobot)), через запятую если админов несколько
- `BOT_USERNAME` — username бота без `@`

```bash
docker compose up -d --build
docker compose logs -f bot        # убедиться, что бот стартовал без ошибок
docker compose exec bot python scripts/seed.py   # один раз — создаёт тариф "Онлайн" + тестовые сквады
```

Всё, бот работает — напишите ему `/start` в Telegram. `alembic upgrade head`
прогоняется автоматически при каждом старте контейнера `bot`.

Остановить: `docker compose down` (данные Postgres переживают остановку —
именованный volume `postgres_data`; `docker compose down -v` сотрёт и их).

### Что дальше

- **Реальная Remnawave-панель**: `REMNAWAVE_MODE=real` + `REMNAWAVE_BASE_URL`/`REMNAWAVE_API_KEY` в `.env`, `docker compose up -d --build` заново.
- **Реальные платежи (Platega, СБП/карты)**: `PAYMENTS_MODE=real` + `PLATEGA_MERCHANT_ID`/`PLATEGA_SECRET_KEY`. Подтверждение — вебхуком (мгновенно), требует `CABINET_ENABLED=true`: в личном кабинете Platega укажите адрес `https://admin.nocto.online/platega-webhook` (прод, см. app/cabinet/webhooks.py — путь уже проброшен Caddy на порт 8080, см. диалог 2026-08-20; ничего в Caddyfile менять не нужно, как только NRW-Bot займёт этот порт вместо старого бота). Без вебхука (или пока Platega не сохранит адрес) платежи всё равно подтвердятся — раз в 10 минут отработает страховочный поллинг (`payment_poll_loop`), просто медленнее.
- **Mini App + веб-админка + прод-деплой с HTTPS**: требует ещё два репозитория рядом (`NRW-MiniApp` — фронтенд, и `deploy` — docker-compose с Caddy для домена/HTTPS) — этот `docker-compose.yml` в корне репозитория рассчитан только на автономный тест бота без Mini App. Полная схема разворачивания на VPS — отдельная инструкция (спросите, если нужна).

## Быстрый старт без Docker (Windows, для разработки)

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
REM впишите BOT_TOKEN и ADMIN_TELEGRAM_IDS, как выше
.venv\Scripts\python -m alembic upgrade head
.venv\Scripts\python scripts\seed.py
.venv\Scripts\python main.py
```

> **SQLite и миграции:** цепочка Alembic написана под Postgres — часть старых миграций
> (например, с `->>` по JSON) на SQLite падает. Для локальной БД без Docker вместо
> `alembic upgrade head` запустите `python scripts/init_local_db.py` (схема из моделей +
> `alembic stamp head`), затем `python scripts/seed.py`. На Postgres (Docker/прод)
> работает обычный `alembic upgrade head`.

## Перенос данных со старого бота

Если у вас уже работает старый бот (форк `remnawave-bedolaga-telegram-bot`) на
Postgres — см. `scripts/migrate_from_old_bot.py` (докстринг файла — что именно
переносится и что нет). Сначала `--dry-run`.

## Переменные окружения

Полный список с комментариями — `.env.example`. Коротко по разделам:
Telegram, Database, Redis (опционально), Cabinet/Mini App, Remnawave, Платежи
(Platega), реферальная программа, тариф по умолчанию для сид-скрипта.

## Логирование

Все логи (бот, Cabinet API, фоновые задачи, библиотеки) идут через `structlog`
(`app/logging_setup.py`) в stdout. Настройка — в `.env`:

- `LOG_LEVEL` — `DEBUG` / `INFO` (по умолчанию) / `WARNING` / `ERROR`.
- `LOG_FORMAT` — `console` (читаемый, цвета только в терминале; по умолчанию) или
  `json` (одна строка на событие — для Loki/ELK/Datadog).

В каждую строку внутри обработки автоматически попадает контекст: для апдейтов
Telegram — `update_id`, `telegram_id`, `user_id`; для HTTP — `request_id`
(он же в заголовке ответа `X-Request-ID`), `method`, `path`, `user_id`. Ключевые
события бизнес-логики: `payment_finalized`, `payment_failed`, `balance_changed`
(с `reason`), `subscription_created` / `subscription_extended`,
`promocode_activated`, `gift_redeemed`, `webhook_rejected`, `payment_poll`.
Токены, ключи из настроек и пароли в URL маскируются (`***`) до вывода; текст
обычных сообщений пользователей не логируется.

## Документация

- `docs/api/API.md` — полное описание API кабинета и админки для фронтенда (Mini App/админка):
  авторизация, форматы, ошибки, все эндпоинты; рядом `reference-*.md`, `schemas.md` и
  `openapi.json`. Справочники генерируются: `python scripts/generate_api_docs.py`
  (после изменения роутов/схем перегенерируйте и закоммитьте).
- `docs/superpowers/specs/` — спецификации (дизайн) крупных функций;
  `docs/superpowers/plans/` — пошаговые планы реализации.
  - `2026-09-21-message-templates-*` — шаблоны сообщений (**реализовано**).
  - `2026-09-21-analytics-*` — центр аналитики: журнал событий, сверка с cisPay, отчёты
    (**спецификация и план готовы, не реализовано**).
- `PROGRESS.md` — карта модулей и известные ограничения.

## Тесты

`python -m pytest tests -q -p no:warnings` (SQLite во временном файле, внешние сервисы
замоканы). Тексты автоматических уведомлений закреплены характеризационными тестами
`tests/test_notifications_golden.py` — менять их нужно только осознанно.
