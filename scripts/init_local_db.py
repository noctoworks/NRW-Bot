"""Создаёт схему локальной SQLite-БД из моделей и помечает её актуальной версией Alembic.

Цепочка миграций написана под Postgres и на SQLite местами падает, поэтому для разработки без Docker:
    python scripts/init_local_db.py && python scripts/seed.py
На Postgres используйте обычный `alembic upgrade head`.
"""
import asyncio
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.database import models  # noqa: E402
from app.database.database import engine  # noqa: E402


async def main() -> None:
    if not settings.is_sqlite():
        sys.exit('DATABASE_URL не SQLite — используйте `python -m alembic upgrade head`.')
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)
    subprocess.run([sys.executable, '-m', 'alembic', 'stamp', 'head'], check=True)
    print('Локальная БД создана и помечена актуальной версией миграций.')


asyncio.run(main())
