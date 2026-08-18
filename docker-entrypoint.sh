#!/bin/sh
# Прогоняет миграции при каждом старте контейнера (идемпотентно — alembic
# просто ничего не делает, если БД уже на head) и передаёт управление
# основной команде (main.py, либо seed.py/migrate_from_old_bot.py при ручном
# docker compose run). Сидинг тарифа (scripts/seed.py) НЕ включён сюда:
# он делает живой запрос к Remnawave (list_internal_squads) — при первом
# старте панель может быть ещё не настроена, поэтому сидинг — отдельный
# ручной шаг (см. deploy/README.md).
set -e

echo "[entrypoint] alembic upgrade head..."
# `alembic` (голый console-script) не добавляет /app в sys.path, а
# migrations/env.py делает `from app.config import settings` — без -m это
# падает с ModuleNotFoundError: No module named 'app' (поймано вживую на
# первом реальном VPS-тесте). `python -m alembic` добавляет cwd (=/app,
# см. WORKDIR в Dockerfile) в sys.path[0], как и локальный
# `.venv\Scripts\python -m alembic upgrade head` из README.
python -m alembic upgrade head

echo "[entrypoint] exec: $*"
exec "$@"
