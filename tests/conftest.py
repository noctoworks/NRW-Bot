import asyncio
import os
import sys
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# Настройки читаются при импорте app.config — задаём до любых импортов app.*
os.environ.setdefault('BOT_TOKEN', '1:test')
os.environ['DATABASE_URL'] = 'sqlite+aiosqlite:///:memory:'

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def session_factory(tmp_path):
    """Файловая SQLite во временном каталоге — несколько сессий видят одни данные.
    SELECT ... FOR UPDATE SQLite игнорирует, поэтому блокировки Postgres тут не
    проверяются (см. docstring тестов, где это важно)."""
    from app.database.models import Base

    engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "test.db"}', connect_args={'timeout': 30})

    async def setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(setup())
    yield async_sessionmaker(engine, expire_on_commit=False)
    asyncio.run(engine.dispose())


@pytest.fixture(autouse=True)
def isolated_mock_remnawave(monkeypatch):
    """mock-Remnawave держит состояние на уровне класса и пишет его в
    mock_remnawave_state.json в корне проекта — в тестах чистое состояние на
    каждый тест и без записи в файл."""
    from app.external.remnawave import mock

    monkeypatch.setattr(mock, '_save_state', lambda state: None)
    monkeypatch.setattr(mock.MockRemnawaveClient, '_state', mock._State())
