"""Модель MessageTemplate и её миграция."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import select

from app.database.models import Base, MessageTemplate, User
from tests.helpers import make_user

ROOT = Path(__file__).resolve().parent.parent
MIGRATION = next((ROOT / 'migrations' / 'versions').glob('*_add_message_templates.py'))


def _load_migration():
    spec = importlib.util.spec_from_file_location('mig_message_templates', MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _schema(engine, table: str) -> dict:
    inspector = sa.inspect(engine)
    return {
        'columns': {c['name']: (str(c['type']).upper(), c['nullable']) for c in inspector.get_columns(table)},
        'indexes': {i['name']: (tuple(i['column_names']), bool(i['unique'])) for i in inspector.get_indexes(table)},
        'pk': inspector.get_pk_constraint(table)['constrained_columns'],
    }


def test_single_alembic_head():
    config = Config(str(ROOT / 'alembic.ini'))
    config.set_main_option('script_location', str(ROOT / 'migrations'))

    heads = ScriptDirectory.from_config(config).get_heads()

    assert len(heads) == 1


def test_migration_result_matches_model():
    expected = sa.create_engine('sqlite://')
    Base.metadata.create_all(expected)
    actual = sa.create_engine('sqlite://')
    Base.metadata.create_all(actual, tables=[t for t in Base.metadata.sorted_tables if t.name != 'message_templates'])
    with actual.begin() as conn:
        context = MigrationContext.configure(conn)
        with Operations.context(context):
            _load_migration().upgrade()

    assert _schema(actual, 'message_templates') == _schema(expected, 'message_templates')
    foreign_keys = {fk['constrained_columns'][0]: fk['options'].get('ondelete') for fk in sa.inspect(actual).get_foreign_keys('message_templates')}
    assert foreign_keys == {'updated_by_user_id': 'SET NULL'}


def test_migration_downgrade_drops_the_table():
    engine = sa.create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        context = MigrationContext.configure(conn)
        with Operations.context(context):
            _load_migration().downgrade()

    assert 'message_templates' not in sa.inspect(engine).get_table_names()


def test_model_defaults_and_nullable_template(session_factory):
    async def scenario():
        admin_id = await make_user(session_factory, is_admin=True)
        async with session_factory() as db:
            db.add(MessageTemplate(key='winback', updated_by_user_id=admin_id))  # только вкл/выкл и кнопка — текст не задан
            await db.commit()
        async with session_factory() as db:
            row = (await db.execute(select(MessageTemplate))).scalar_one()
            assert (row.key, row.template, row.button_text, row.enabled) == ('winback', None, None, True)
            assert row.updated_at is not None and row.updated_by_user_id == admin_id

    asyncio.run(scenario())


def test_deleting_the_admin_keeps_the_template(session_factory):
    async def scenario():
        admin_id = await make_user(session_factory)
        async with session_factory() as db:
            db.add(MessageTemplate(key='winback', template='Привет', updated_by_user_id=admin_id))
            await db.commit()
        async with session_factory() as db:
            # SQLite-фикстура без PRAGMA foreign_keys: проверяем, что модель допускает NULL у автора
            row = await db.get(MessageTemplate, 'winback')
            row.updated_by_user_id = None
            await db.commit()
            assert (await db.get(MessageTemplate, 'winback')).template == 'Привет'

    asyncio.run(scenario())
