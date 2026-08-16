# bedolaga-lite

Упрощённый клон Bedolaga VPN-бота. Архитектура и все проектные решения — в
опубликованном документе (см. ссылку в диалоге разработки), здесь — только код.

## Быстрый старт (Windows, без Docker)

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
# впишите в .env: BOT_TOKEN (тестовый бот от @BotFather), ADMIN_TELEGRAM_IDS (ваш id)
.venv\Scripts\python -m alembic upgrade head
.venv\Scripts\python main.py
```

По умолчанию:
- `REMNAWAVE_MODE=mock` — Remnawave не трогаем, работает заглушка в памяти
- `PAYMENTS_MODE=stub` — любая оплата мгновенно считается успешной
- БД — SQLite (`bot.db` в корне проекта)
- Redis не нужен — FSM в памяти процесса

## Структура

```
app/
  config.py              # вся конфигурация, .env
  bot.py                 # сборка Dispatcher, регистрация middleware/handlers
  states.py               # FSM
  database/
    models.py              # 13 таблиц + связка promocode_uses
    database.py             # engine/session
  external/remnawave/       # интерфейс + мок-клиент Remnawave
  services/payment/          # интерфейс + стаб платёжного провайдера
  middlewares/auth.py         # загрузка db_user по telegram_id
  handlers/                    # feature-модули бота (заготовки, TODO)
migrations/                    # Alembic
main.py                         # entrypoint
```

## Точки расширения для новых модулей

- Хендлер — файл в `app/handlers/`, экспортирует `register_handlers(dp)`,
  подключается ОДНОЙ строкой в `app/handlers/__init__.py`.
- Reмnawave/платежи — реализации за интерфейсом (`RemnawaveClient`,
  `PaymentProvider`), переключение `mock↔real` / `stub↔real` — через `.env`,
  без изменения кода хендлеров/сервисов.
