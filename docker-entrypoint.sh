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
alembic upgrade head

echo "[entrypoint] exec: $*"
exec "$@"
