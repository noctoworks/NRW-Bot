# Центр аналитики: фундамент — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Заложить фундамент центра аналитики админки: единое правило времени, единый расчёт выручки (нетто, по `paid_at`, без возвратов), журнал событий `analytics_events` с записью в денежных путях, backfill истории, сверку и возвраты cisPay, закрытие публичной OpenAPI-схемы и пакет для передачи во фронтенд.

**Architecture:** Один модуль времени (`time_utils`) и один расчёт выручки (`revenue.py`) — все метрики берут границы и суммы только оттуда. Append-only таблица `analytics_events` пишется функцией `record_event` в той же транзакции, что и денежная операция, через `INSERT … ON CONFLICT DO NOTHING` по `dedupe_key`. Существующие метрики `analytics_service` переводятся на эти два модуля. Сверка с cisPay читает `GET /transactions` cisPay и обнаруживает возвраты.

**Tech Stack:** Python 3.12 (dev-машина 3.14), FastAPI, SQLAlchemy 2 async, Alembic, aiogram 3, pytest (без pytest-asyncio: тесты вызывают `asyncio.run`), SQLite в тестах / Postgres в проде, `zoneinfo` + `tzdata`.

**Spec:** `docs/superpowers/specs/2026-09-21-analytics-center-design.md` — прочитайте её целиком перед началом. План реализует её раздел 12, пункт 1 «Фундамент».

## Прочитайте это первым (контекст для исполнителя)

**Что это за проект.** `NRW-Bot` — Telegram-бот, продающий VPN-подписки поверх панели Remnawave, плюс FastAPI-кабинет (`/cabinet/*`, `/cabinet/admin/*`) для Mini App. Единственный провайдер разовых платежей — **cisPay** (СБП). Фронтенд лежит в соседнем репозитории `../NRW-MiniApp` — **не трогайте его** (там идёт редизайн). Всё, что нужно фронтенду, передаётся через `docs/api/*` (Task 11).

**Деньги — главное.** Ошибка в денежном пути = потеря денег. Правила проекта:
- Суммы всегда в копейках (`int`). Доменные ошибки (`PromoCodeError`, `GiftCodeError`) бросаются **до** любых изменений: бот ловит их, а `AuthMiddleware` всё равно коммитит сессию.
- Баланс меняется только через `app/services/balance_service.py`.
- Побочные эффекты (события аналитики) не должны ломать денежную операцию и пишутся **в той же транзакции**.

**Как устроены тесты (важно, отличается от типичного).**
- Запуск: `python -m pytest tests -q -p no:warnings` (сейчас должно быть 199 passed). Перед каждым коммитом весь набор обязан проходить.
- Нет `pytest-asyncio`. Каждый тест — обычная функция, внутри `asyncio.run(scenario())`, где `scenario` — `async def`.
- Фикстура `session_factory` (в `tests/conftest.py`) — файловая SQLite во временной папке; `make_user`, `make_tariff` — в `tests/helpers.py`. Mock-Remnawave подключается автоматически (autouse).
- SQLite игнорирует `SELECT … FOR UPDATE`; в Postgres поведение шире. Поэтому защита от гонок делается атомарными `UPDATE`/`INSERT … ON CONFLICT`, а не блокировками.
- Даты: SQLite возвращает naive `datetime`, Postgres — aware. Всегда нормализуйте (`_aware`/`_as_utc`).

**Ловушки окружения (Windows).**
- Длинные `python - <<'EOF'` в Bash-инструменте ломаются («unexpected EOF»). Создавайте файлы инструментом Write, скрипты запускайте отдельно.
- PowerShell 5.1: `Set-Content -Encoding UTF8` пишет BOM. Не используйте для кода; правьте инструментом Edit или скриптом на Python.
- Часть файлов в рабочем копии имеет CRLF (git предупреждает `CRLF will be replaced by LF`). Однострочные правки через Edit безопасны; для многострочных замен используйте помощник из Приложения A.
- Перед запуском на Windows: `pip install tzdata` (иначе `ZoneInfo('Europe/Moscow')` падает с `ZoneInfoNotFoundError`); `set PYTHONIOENCODING=utf-8` для вывода кириллицы.

**Коммиты.** Сообщения на русском (как в истории репозитория), в конце — атрибуция, которую требует ваша среда. Не пушить. Один коммит на задачу (или чаще).

## Global Constraints

Значения скопированы из спецификации дословно.

- Хранение и передача времени — **всегда UTC**; границы дня/недели/месяца — в отчётном поясе `REPORT_TIMEZONE` (по умолчанию `Europe/Moscow`), плюс необязательный параметр `?tz=` (IANA-имя, проверяется по `zoneinfo`) на аналитических эндпоинтах. Зависимость `tzdata` обязательна.
- Выручка = `COALESCE(merchant_revenue_kopeks, amount_kopeks)` (чистая сумма мерчанту), по времени `COALESCE(paid_at, transaction.created_at)`, без оплат с баланса и без `refunded`; типы транзакций `subscription_payment` и `gift`; рядом всегда оборот (`charged`) и комиссия (`charged − net`); доля `net_known`.
- Окна «за N дней» выравниваются по границам отчётных дней: сумма графика за период равна карточке за то же окно.
- Ответы аналитических API: дни — `YYYY-MM-DD` в отчётном поясе; моменты времени — ISO-8601 UTC; в ответах есть поле `timezone`.
- Журнал `analytics_events`: только добавление; `user_id` → `ON DELETE SET NULL`; `dedupe_key` уникален; запись — `INSERT … ON CONFLICT DO NOTHING` в той же транзакции; индексы `(type, occurred_at)`, `(user_id)`, `unique(dedupe_key)`.
- Типы событий v1: `user_registered`, `trial_started`, `subscription_first_paid`, `subscription_renewed`, `subscription_expired`, `promocode_activated`, `gift_redeemed`, `referral_reward_paid`, `bonus_granted`, `payment_refunded`.
- Миграции только добавляющие (nullable-колонки, новая таблица), откат безопасен. Диапазон аналитических запросов ≤ 731 дня. Невалидный `tz` → 422.
- Backfill — отдельный скрипт с `--dry-run`, все записи `source='backfill'`, повторный запуск не даёт дублей.
- Публичный `/openapi.json` закрыт; схема передаётся файлом `docs/api/openapi.json`.
- Комментарии и docstring в проекте — на русском, в стиле окружающего кода.

## Решения, принятые планом (уточнения к спецификации)

1. События `subscription_first_paid` / `subscription_renewed` пишутся для **каждой** покупки/продления подписки независимо от источника денег; `amount_kopeks` — реальные деньги провайдеру (для оплаты с баланса — `0`). Потребители, которым нужны «платящие», фильтруют `amount_kopeks > 0`.
2. Покупка подарка (`Transaction.type='gift'`) — это выручка (через `Payment`), но события подписки не порождает; «погашение» подарка — событие `gift_redeemed`.
3. Скидка запоминается в `Payment.raw_payload['discount_percent'|'discount_kind']` в момент создания платежа (для асинхронных платежей цена/скидка могут измениться к моменту оплаты).
4. Возврат cisPay считается полным: платёж → `refunded`, транзакция → `refunded`, выручка уменьшается, пишется `payment_refunded`. Отзыв подписки и клоубэк реферальной комиссии при возврате **вне рамок** плана.
5. Бонус «за приглашение» не восстанавливается backfill (нет записи в БД) — только live.
6. Хуки в обработчиках Telegram (`handlers/start.py`, `handlers/admin.py`) покрываются тестами хелперов и статической проверкой вызовов (grep-шаг), а не полной эмуляцией aiogram.

## Карта файлов

| Файл | Действие | Ответственность |
|---|---|---|
| `app/config.py` | изменить | `REPORT_TIMEZONE` + валидатор |
| `requirements.txt` | изменить | `tzdata` |
| `.env.example` | изменить | `REPORT_TIMEZONE` |
| `app/services/time_utils.py` | переписать | границы периодов в отчётном поясе |
| `app/database/models.py` | изменить | `Payment.paid_at/refunded_at/charged…/merchant…`, `PromoGroup.is_active`, `AnalyticsEvent` |
| `migrations/versions/b7d1e5a93c20_add_paid_at_and_analytics_events.py` | создать | миграция |
| `app/services/revenue.py` | создать | единый расчёт выручки |
| `app/services/payment_amounts.py` | создать | `paid_at` и суммы провайдера → `Payment` |
| `app/services/analytics_events.py` | создать | `record_event` и хелперы событий |
| `app/services/pricing_service.py` | изменить | вид скидки |
| `app/services/analytics_service.py` | изменить | перевод на `revenue.py` и `time_utils` |
| `app/cabinet/report_tz.py` | создать | зависимость `?tz=` |
| `app/services/analytics/reconcile.py` | создать | сверка и возвраты cisPay |
| `app/services/analytics/backfill.py` | создать | восстановление истории, `data_quality` |
| `app/cabinet/analytics_routes.py`, `analytics_schemas.py` | создать | `/cabinet/admin/analytics/*` |
| `scripts/backfill_analytics_events.py`, `scripts/export_openapi.py` | создать | CLI |
| `docs/api/README.md`, `docs/api/analytics-foundation.md` | создать | передача во фронтенд |
| `tests/…` | создать | см. задачи |

## Приложение A. Помощник для многострочных правок

Создайте файл `apply_patch.py` во временной папке (не в репозитории). Он заменяет ровно одно вхождение и падает, если фрагмент не найден или встречается не один раз; сохраняет CRLF/LF файла.

```python
import sys


def apply_patch(path: str, old: str, new: str) -> None:
    text = open(path, encoding='utf-8', newline='').read()
    crlf = '\r\n' in text
    text = text.replace('\r\n', '\n')
    count = text.count(old)
    assert count == 1, f'{path}: фрагмент найден {count} раз(а), нужен ровно 1:\n{old[:120]}'
    text = text.replace(old, new, 1)
    if crlf:
        text = text.replace('\n', '\r\n')
    open(path, 'w', encoding='utf-8', newline='').write(text)
```

Использование: в отдельном скрипте `from apply_patch import apply_patch` и вызовы `apply_patch('app/…', OLD, NEW)`.

---

### Task 1: Отчётный часовой пояс и `time_utils`

**Files:**
- Modify: `app/config.py` (добавить поле и валидатор рядом с `LOG_FORMAT`)
- Modify: `requirements.txt` (добавить `tzdata`)
- Modify: `.env.example`
- Rewrite: `app/services/time_utils.py`
- Test: `tests/test_time_utils.py`

**Interfaces:**
- Produces (используют все следующие задачи):
  - `get_report_tz(name: str | None = None) -> ZoneInfo` — `None` → `settings.REPORT_TIMEZONE`; неизвестное имя → `ValueError`.
  - `report_date(dt: datetime, tz: ZoneInfo) -> date`
  - `day_start_utc(now: datetime, tz: ZoneInfo) -> datetime` (aware UTC)
  - `week_start_utc(now, tz)` (понедельник), `month_start_utc(now, tz)`
  - `window_start_utc(now, days: int, tz) -> datetime` — начало отчётного дня «`days − 1` дней назад» (окно из `days` календарных дней, включая сегодня); `days < 1` → `ValueError`.
  - `report_days(now, days: int, tz) -> list[date]` — `days` дат от старой к сегодняшней.
  - `business_day_start_utc(now) -> datetime` — совместимая обёртка (`handlers/admin.py` её использует): `day_start_utc(now, get_report_tz())`.

- [ ] **Step 1: Установить `tzdata` и написать падающие тесты**

Run: `pip install tzdata`

Создайте `tests/test_time_utils.py`:

```python
"""app/services/time_utils.py — границы дня/недели/месяца в отчётном поясе."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from app.config import Settings, settings
from app.services.time_utils import (
    business_day_start_utc,
    day_start_utc,
    get_report_tz,
    month_start_utc,
    report_date,
    report_days,
    week_start_utc,
    window_start_utc,
)

MSK = get_report_tz('Europe/Moscow')
UTC_TZ = get_report_tz('UTC')


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def test_day_boundary_is_moscow_midnight():
    # 23:59:59 МСК 21 сентября -> день начался 21 сентября 00:00 МСК = 20-е 21:00 UTC
    assert day_start_utc(utc(2026, 9, 21, 20, 59, 59), MSK) == utc(2026, 9, 20, 21, 0, 0)
    # ровно полночь МСК -> уже новый день
    assert day_start_utc(utc(2026, 9, 21, 21, 0, 0), MSK) == utc(2026, 9, 21, 21, 0, 0)


def test_payment_at_2355_and_0005_msk_belongs_to_different_days():
    before, after = utc(2026, 9, 20, 20, 55), utc(2026, 9, 20, 21, 5)  # 23:55 и 00:05 МСК
    assert report_date(before, MSK) == date(2026, 9, 20)
    assert report_date(after, MSK) == date(2026, 9, 21)


def test_utc_timezone_uses_utc_midnight():
    assert day_start_utc(utc(2026, 9, 21, 20, 59), UTC_TZ) == utc(2026, 9, 21, 0, 0)


def test_naive_datetime_is_treated_as_utc():
    assert report_date(datetime(2026, 9, 20, 21, 5), MSK) == date(2026, 9, 21)


def test_dst_zone_boundary_is_correct():
    ny = get_report_tz('America/New_York')
    # 8 марта 2026 в США переход на летнее время; полночь ещё по зимнему (UTC-5)
    assert day_start_utc(utc(2026, 3, 8, 12, 0), ny) == utc(2026, 3, 8, 5, 0)


def test_week_starts_on_monday():
    # 23 сентября 2026 — среда; неделя началась в понедельник 21-го 00:00 МСК
    assert week_start_utc(utc(2026, 9, 23, 12, 0), MSK) == utc(2026, 9, 20, 21, 0)
    # в понедельник 21-го в 00:30 МСК неделя только что началась
    assert week_start_utc(utc(2026, 9, 20, 21, 30), MSK) == utc(2026, 9, 20, 21, 0)


def test_month_starts_on_first_moscow_midnight():
    assert month_start_utc(utc(2026, 9, 21, 12, 0), MSK) == utc(2026, 8, 31, 21, 0)
    # 00:30 МСК 1 сентября — это ещё 31 августа по UTC, но уже сентябрь
    assert month_start_utc(utc(2026, 8, 31, 21, 30), MSK) == utc(2026, 8, 31, 21, 0)


def test_window_start_covers_n_calendar_days_including_today():
    now = utc(2026, 9, 21, 12, 0)  # 15:00 МСК, понедельник
    assert window_start_utc(now, 1, MSK) == day_start_utc(now, MSK)
    assert window_start_utc(now, 7, MSK) == utc(2026, 9, 14, 21, 0)  # 15 сентября 00:00 МСК


def test_window_start_rejects_zero_days():
    with pytest.raises(ValueError):
        window_start_utc(utc(2026, 9, 21), 0, MSK)


def test_report_days_is_oldest_first_and_ends_today():
    days = report_days(utc(2026, 9, 21, 12, 0), 3, MSK)

    assert days == [date(2026, 9, 19), date(2026, 9, 20), date(2026, 9, 21)]


def test_get_report_tz_defaults_to_settings_and_rejects_unknown(monkeypatch):
    monkeypatch.setattr(settings, 'REPORT_TIMEZONE', 'UTC')
    assert get_report_tz().key == 'UTC'
    assert get_report_tz('Europe/Moscow').key == 'Europe/Moscow'
    for bad in ('Mars/Base', '../etc/passwd', 'not a zone'):
        with pytest.raises(ValueError):
            get_report_tz(bad)


def test_business_day_start_wrapper_matches_report_timezone(monkeypatch):
    monkeypatch.setattr(settings, 'REPORT_TIMEZONE', 'Europe/Moscow')
    assert business_day_start_utc(utc(2026, 9, 21, 20, 59, 59)) == utc(2026, 9, 20, 21, 0)


def test_settings_reject_unknown_report_timezone():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, BOT_TOKEN='1:test', REPORT_TIMEZONE='Mars/Base')
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `python -m pytest tests/test_time_utils.py -q -p no:warnings`
Expected: FAIL (`ImportError: cannot import name 'get_report_tz'`).

- [ ] **Step 3: Реализация**

Перепишите `app/services/time_utils.py` целиком:

```python
"""Границы календарных периодов для аналитики.

Время в БД и API — всегда UTC. Календарные границы (день/неделя/месяц) считаются
в ОТЧЁТНОМ часовом поясе: по умолчанию settings.REPORT_TIMEZONE (Europe/Moscow),
а эндпоинты могут передать свой (`?tz=`). Кабинет cisPay режет сутки по времени
браузера, поэтому пояс должен быть параметром, а не константой. Любая функция
аналитики берёт границы ТОЛЬКО отсюда — иначе карточки и графики расходятся.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import settings


def get_report_tz(name: str | None = None) -> ZoneInfo:
    """IANA-пояс по имени; None — из настроек. Неизвестное имя -> ValueError."""
    key = name or settings.REPORT_TIMEZONE
    try:
        return ZoneInfo(key)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValueError(f'Неизвестный часовой пояс: {key!r}') from error


def _aware(dt: datetime) -> datetime:
    """SQLite отдаёт naive-даты — считаем их UTC (так их и пишет приложение)."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def report_date(dt: datetime, tz: ZoneInfo) -> date:
    return _aware(dt).astimezone(tz).date()


def _local_midnight_utc(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time.min, tzinfo=tz).astimezone(timezone.utc)


def day_start_utc(now: datetime, tz: ZoneInfo) -> datetime:
    return _local_midnight_utc(report_date(now, tz), tz)


def week_start_utc(now: datetime, tz: ZoneInfo) -> datetime:
    today = report_date(now, tz)
    return _local_midnight_utc(today - timedelta(days=today.weekday()), tz)


def month_start_utc(now: datetime, tz: ZoneInfo) -> datetime:
    return _local_midnight_utc(report_date(now, tz).replace(day=1), tz)


def window_start_utc(now: datetime, days: int, tz: ZoneInfo) -> datetime:
    """Начало окна из `days` календарных дней, включая сегодняшний."""
    if days < 1:
        raise ValueError('days должно быть >= 1')
    return _local_midnight_utc(report_date(now, tz) - timedelta(days=days - 1), tz)


def report_days(now: datetime, days: int, tz: ZoneInfo) -> list[date]:
    """`days` дат окна от старой к сегодняшней (ключи дневных графиков)."""
    if days < 1:
        raise ValueError('days должно быть >= 1')
    today = report_date(now, tz)
    return [today - timedelta(days=offset) for offset in range(days - 1, -1, -1)]


def business_day_start_utc(now: datetime) -> datetime:
    """Совместимость (handlers/admin.py): начало текущего дня в отчётном поясе."""
    return day_start_utc(now, get_report_tz())
```

В `app/config.py` после поля `LOG_FORMAT` добавьте:

```python
    # --- Аналитика: часовой пояс для границ дня/недели/месяца (IANA-имя). Время в
    # БД и API остаётся UTC; кабинет cisPay режет сутки по времени браузера. ---
    REPORT_TIMEZONE: str = 'Europe/Moscow'

    @field_validator('REPORT_TIMEZONE')
    @classmethod
    def _validate_report_timezone(cls, value: str) -> str:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f'REPORT_TIMEZONE: неизвестный часовой пояс {value!r}') from error
        return value
```

В `requirements.txt` добавьте строку `tzdata>=2024.1`. В `.env.example` после `LOG_FORMAT=console` добавьте `REPORT_TIMEZONE=Europe/Moscow`.

- [ ] **Step 4: Тесты проходят, весь набор зелёный**

Run: `python -m pytest tests -q -p no:warnings`
Expected: все проходят (199 + новые).

- [ ] **Step 5: Проверка чувствительности (мутация)**

Временно замените в `day_start_utc` `report_date(now, tz)` на `now.date()` — `test_day_boundary_is_moscow_midnight` и `test_payment_at_2355…` должны упасть. Верните код.

- [ ] **Step 6: Коммит**

```bash
git add app/config.py app/services/time_utils.py requirements.txt .env.example tests/test_time_utils.py
git commit -m "Добавляет отчётный часовой пояс и единый модуль границ периодов"
```

---

### Task 2: Модели и миграция (`paid_at`, `analytics_events`)

**Files:**
- Modify: `app/database/models.py` (`Payment`, `PromoGroup`, новый `AnalyticsEvent`)
- Create: `migrations/versions/b7d1e5a93c20_add_paid_at_and_analytics_events.py`
- Test: `tests/test_migrations.py`

**Interfaces:**
- Produces: `Payment.paid_at`, `Payment.refunded_at`, `Payment.charged_amount_kopeks`, `Payment.merchant_revenue_kopeks` (все `int|datetime|None`); статус `'refunded'` у `Payment.status` и `Transaction.status`; ORM-модель `AnalyticsEvent` с колонками: `id, occurred_at, type, user_id, tariff_id, days, amount_kopeks, campaign_id, promo_code_id, payment_id, discount_percent, discount_kind, source, dedupe_key`.

Контекст: миграция `caa7bbb89896` уже добавила в БД `charged_amount_kopeks`/`merchant_revenue_kopeks`, а `13a3c1d46134` — `promo_groups.is_active`, но в моделях их нет. Единственная текущая голова цепочки — `caa7bbb89896`. Alembic-цепочка написана под Postgres (в `caa7…` есть `::bigint`), поэтому целиком на SQLite её не прогнать — новую миграцию проверяем изолированно.

- [ ] **Step 1: Написать падающие тесты**

Создайте `tests/test_migrations.py`:

```python
"""Миграция b7d1e5a93c20: добавляет paid_at/refunded_at и analytics_events.

Цепочка Alembic целиком написана под Postgres, поэтому здесь проверяем ТОЛЬКО новую
миграцию: берём схему из моделей, «откатываем» её к состоянию до миграции, накатываем
upgrade() и сравниваем результат со схемой моделей (ловит расхождение моделей и миграции)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

from app.database.models import Base

ROOT = Path(__file__).resolve().parent.parent
MIGRATION = next((ROOT / 'migrations' / 'versions').glob('*_add_paid_at_and_analytics_events.py'))


def _load_migration():
    spec = importlib.util.spec_from_file_location('mig_paid_at', MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _schema(engine, table: str) -> dict:
    inspector = sa.inspect(engine)
    columns = {c['name']: (str(c['type']).upper(), c['nullable']) for c in inspector.get_columns(table)}
    indexes = {i['name']: (tuple(i['column_names']), bool(i['unique'])) for i in inspector.get_indexes(table)}
    return {'columns': columns, 'indexes': indexes}


def test_alembic_has_single_head_after_new_migration():
    config = Config(str(ROOT / 'alembic.ini'))
    config.set_main_option('script_location', str(ROOT / 'migrations'))

    assert ScriptDirectory.from_config(config).get_heads() == ['b7d1e5a93c20']


def test_migration_result_matches_models():
    expected = sa.create_engine('sqlite://')
    Base.metadata.create_all(expected)

    actual = sa.create_engine('sqlite://')
    old_tables = [t for t in Base.metadata.sorted_tables if t.name != 'analytics_events']
    Base.metadata.create_all(actual, tables=old_tables)
    with actual.begin() as conn:  # состояние ДО миграции
        conn.exec_driver_sql('DROP INDEX ix_payments_paid_at')
        conn.exec_driver_sql('ALTER TABLE payments DROP COLUMN paid_at')
        conn.exec_driver_sql('ALTER TABLE payments DROP COLUMN refunded_at')
    with actual.begin() as conn:
        context = MigrationContext.configure(conn)
        with Operations.context(context):
            _load_migration().upgrade()

    assert _schema(actual, 'payments') == _schema(expected, 'payments')
    assert _schema(actual, 'analytics_events') == _schema(expected, 'analytics_events')
    foreign_keys = {fk['constrained_columns'][0]: fk['options'].get('ondelete') for fk in sa.inspect(actual).get_foreign_keys('analytics_events')}
    assert foreign_keys['user_id'] == 'SET NULL'


def test_migration_downgrade_restores_previous_state():
    engine = sa.create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        context = MigrationContext.configure(conn)
        with Operations.context(context):
            _load_migration().downgrade()

    inspector = sa.inspect(engine)
    assert 'analytics_events' not in inspector.get_table_names()
    assert 'paid_at' not in {c['name'] for c in inspector.get_columns('payments')}
```

- [ ] **Step 2: Убедиться, что падает**

Run: `python -m pytest tests/test_migrations.py -q -p no:warnings`
Expected: FAIL (`StopIteration`: файл миграции не найден).

- [ ] **Step 3: Модели**

В `app/database/models.py` в класс `Payment` (после `abandoned_reminder_sent`) добавьте:

```python
    # Момент успешной оплаты (UTC). У cisPay — из поля paid_at ответа/вебхука, у остальных —
    # момент финализации. Выручка в аналитике привязана именно к нему (см. app/services/revenue.py).
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # cisPay: сколько списано с покупателя и сколько получит мерчант после комиссии
    # (колонки добавлены миграцией caa7bbb89896; раньше не были описаны в модели).
    charged_amount_kopeks: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    merchant_revenue_kopeks: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
```

Обновите комментарий у `Payment.status`: `# pending|success|failed|refunded`. В класс `PromoGroup` добавьте (колонка есть в БД с миграции `13a3c1d46134`):

```python
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=sa.true())
```
Для этого в импортах models.py добавьте `import sqlalchemy as sa` (или используйте `from sqlalchemy import true` и `server_default=true()`). Если `Index` ещё не импортирован — добавьте его в `from sqlalchemy import …`.

В конец файла добавьте модель:

```python
class AnalyticsEvent(Base):
    """Журнал событий для аналитики (append-only). Пишется app/services/analytics_events.py::
    record_event в той же транзакции, что и денежная операция. user_id -> SET NULL: удаление
    пользователя не должно искажать агрегаты."""

    __tablename__ = 'analytics_events'
    __table_args__ = (
        UniqueConstraint('dedupe_key', name='uq_analytics_events_dedupe_key'),
        Index('ix_analytics_events_type_occurred_at', 'type', 'occurred_at'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    type: Mapped[str] = mapped_column(String(32))
    user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    tariff_id: Mapped[int | None] = mapped_column(ForeignKey('tariffs.id', ondelete='SET NULL'), nullable=True)
    days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amount_kopeks: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey('campaigns.id', ondelete='SET NULL'), nullable=True)
    promo_code_id: Mapped[int | None] = mapped_column(ForeignKey('promocodes.id', ondelete='SET NULL'), nullable=True)
    payment_id: Mapped[int | None] = mapped_column(ForeignKey('payments.id', ondelete='SET NULL'), nullable=True)
    discount_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    discount_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)  # group|sale|winback
    source: Mapped[str] = mapped_column(String(16), default='live')  # live|backfill
    dedupe_key: Mapped[str] = mapped_column(String(128))
```

- [ ] **Step 4: Миграция**

Создайте `migrations/versions/b7d1e5a93c20_add_paid_at_and_analytics_events.py`:

```python
"""add payments.paid_at/refunded_at and analytics_events

Revision ID: b7d1e5a93c20
Revises: caa7bbb89896
Create Date: 2026-09-21 12:00:00.000000

Только добавляющая миграция (nullable-колонки и новая таблица) — откат безопасен.
Заполнение paid_at и событий — отдельным скриптом scripts/backfill_analytics_events.py.
"""
from alembic import op
import sqlalchemy as sa


revision = 'b7d1e5a93c20'
down_revision = 'caa7bbb89896'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('payments', sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('payments', sa.Column('refunded_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_payments_paid_at', 'payments', ['paid_at'])

    op.create_table(
        'analytics_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('type', sa.String(length=32), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('tariff_id', sa.Integer(), sa.ForeignKey('tariffs.id', ondelete='SET NULL'), nullable=True),
        sa.Column('days', sa.Integer(), nullable=True),
        sa.Column('amount_kopeks', sa.BigInteger(), nullable=True),
        sa.Column('campaign_id', sa.Integer(), sa.ForeignKey('campaigns.id', ondelete='SET NULL'), nullable=True),
        sa.Column('promo_code_id', sa.Integer(), sa.ForeignKey('promocodes.id', ondelete='SET NULL'), nullable=True),
        sa.Column('payment_id', sa.Integer(), sa.ForeignKey('payments.id', ondelete='SET NULL'), nullable=True),
        sa.Column('discount_percent', sa.Integer(), nullable=True),
        sa.Column('discount_kind', sa.String(length=16), nullable=True),
        sa.Column('source', sa.String(length=16), nullable=False),
        sa.Column('dedupe_key', sa.String(length=128), nullable=False),
        sa.UniqueConstraint('dedupe_key', name='uq_analytics_events_dedupe_key'),
    )
    op.create_index('ix_analytics_events_type_occurred_at', 'analytics_events', ['type', 'occurred_at'])
    op.create_index('ix_analytics_events_user_id', 'analytics_events', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_analytics_events_user_id', table_name='analytics_events')
    op.drop_index('ix_analytics_events_type_occurred_at', table_name='analytics_events')
    op.drop_table('analytics_events')
    op.drop_index('ix_payments_paid_at', table_name='payments')
    op.drop_column('payments', 'refunded_at')
    op.drop_column('payments', 'paid_at')
```

- [ ] **Step 5: Тесты проходят**

Run: `python -m pytest tests/test_migrations.py -q -p no:warnings` затем `python -m pytest tests -q -p no:warnings`
Expected: PASS. Если `test_migration_result_matches_models` показывает расхождение типов/nullable — правьте миграцию под модель (модель — источник истины).

- [ ] **Step 6: Проверка SQL для Postgres (без БД)**

Alembic умеет печатать SQL без подключения. PowerShell:

```powershell
$env:BOT_TOKEN='1:t'; $env:DATABASE_URL='postgresql+asyncpg://u:p@h/db'; alembic upgrade caa7bbb89896:b7d1e5a93c20 --sql
```
Expected: в выводе `ALTER TABLE payments ADD COLUMN paid_at`, `CREATE TABLE analytics_events`, `UPDATE alembic_version`; ошибок нет. (Если `alembic` не найден — `python -m alembic …`.)

- [ ] **Step 7: Коммит**

```bash
git add app/database/models.py migrations/versions/b7d1e5a93c20_add_paid_at_and_analytics_events.py tests/test_migrations.py
git commit -m "Добавляет paid_at/refunded_at, журнал analytics_events и выравнивает модели с миграциями"
```

---

### Task 3: Единый расчёт выручки (`revenue.py`)

**Files:**
- Create: `app/services/revenue.py`
- Modify: `tests/helpers.py` (добавить `make_paid_payment`)
- Test: `tests/test_revenue.py`

**Interfaces:**
- Consumes: `Payment`, `Transaction` из `app.database.models`.
- Produces:
  - `REVENUE_TYPES = ('subscription_payment', 'gift')`
  - `NET_AMOUNT`, `GROSS_AMOUNT`, `PAID_AT` — SQL-выражения `coalesce(...)`.
  - `revenue_conditions() -> list` — условия выручки.
  - `revenue_select(*columns) -> Select` — `select(*columns)` из `Transaction JOIN Payment` с условиями выручки.
  - `window_conditions(since: datetime | None = None, until: datetime | None = None) -> list` — условия по `PAID_AT` (`>= since`, `< until`).
  - `async revenue_sum(db, *, since=None, until=None, gross=False) -> int`
  - `async revenue_summary(db, *, since=None, until=None) -> dict` с ключами `net_kopeks, gross_kopeks, fee_kopeks, count, net_known_share`.
  - `tests/helpers.py::make_paid_payment(factory, user_id, *, amount=10000, net=None, gross=None, provider='cispay', tx_type='subscription_payment', paid_at=None, tx_created_at=None, status='success', tx_status='completed') -> int` (возвращает `payment.id`).

- [ ] **Step 1: Хелпер для тестов**

Добавьте в конец `tests/helpers.py`:

```python
import itertools
from datetime import datetime, timezone

from app.database.models import Payment, Transaction

_external_ids = itertools.count(1)


async def make_paid_payment(
    factory,
    user_id: int,
    *,
    amount: int = 10000,
    net: int | None = None,
    gross: int | None = None,
    provider: str = 'cispay',
    tx_type: str = 'subscription_payment',
    paid_at: datetime | None = None,
    tx_created_at: datetime | None = None,
    status: str = 'success',
    tx_status: str = 'completed',
) -> int:
    """Транзакция + платёж для тестов выручки. paid_at/tx_created_at — aware UTC."""
    async with factory() as db:
        transaction = Transaction(
            user_id=user_id,
            type=tx_type,
            amount_kopeks=amount,
            status=tx_status,
            created_at=tx_created_at or datetime.now(timezone.utc),
        )
        db.add(transaction)
        await db.flush()
        payment = Payment(
            user_id=user_id,
            transaction_id=transaction.id,
            provider=provider,
            external_id=f'ext-{next(_external_ids)}',
            amount_kopeks=amount,
            merchant_revenue_kopeks=net,
            charged_amount_kopeks=gross,
            status=status,
            paid_at=paid_at,
        )
        db.add(payment)
        await db.commit()
        return payment.id
```
(Если импорты `datetime`/`Payment`/`Transaction` уже есть в файле — не дублируйте.)

- [ ] **Step 2: Падающие тесты**

Создайте `tests/test_revenue.py`:

```python
"""app/services/revenue.py — единственное определение «выручки»."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.services.revenue import revenue_sum, revenue_summary
from tests.helpers import make_paid_payment, make_user


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def _run(factory, fn):
    async def scenario():
        async with factory() as db:
            return await fn(db)

    return asyncio.run(scenario())


def test_revenue_is_net_when_merchant_revenue_known(session_factory):
    async def seed():
        user_id = await make_user(session_factory)
        await make_paid_payment(session_factory, user_id, amount=24900, net=23904, gross=24900, paid_at=utc(2026, 9, 21, 10))

    asyncio.run(seed())

    assert _run(session_factory, lambda db: revenue_sum(db)) == 23904
    assert _run(session_factory, lambda db: revenue_sum(db, gross=True)) == 24900


def test_revenue_falls_back_to_amount_when_net_unknown(session_factory):
    async def seed():
        user_id = await make_user(session_factory)
        await make_paid_payment(session_factory, user_id, amount=10000, provider='platega', paid_at=utc(2026, 9, 21, 10))

    asyncio.run(seed())

    assert _run(session_factory, lambda db: revenue_sum(db)) == 10000


def test_excluded_payments_are_not_revenue(session_factory):
    async def seed():
        user_id = await make_user(session_factory)
        when = utc(2026, 9, 21, 10)
        await make_paid_payment(session_factory, user_id, amount=10000, paid_at=when)  # учитывается
        await make_paid_payment(session_factory, user_id, amount=5000, provider='balance', paid_at=when)  # оплата с баланса
        await make_paid_payment(session_factory, user_id, amount=7000, status='refunded', paid_at=when)  # возврат
        await make_paid_payment(session_factory, user_id, amount=8000, tx_type='topup', paid_at=when)  # не выручка
        await make_paid_payment(session_factory, user_id, amount=9000, tx_status='pending', paid_at=when)  # не завершена
        await make_paid_payment(session_factory, user_id, amount=3000, tx_type='gift', paid_at=when)  # подарок — выручка

    asyncio.run(seed())

    assert _run(session_factory, lambda db: revenue_sum(db)) == 13000


def test_time_basis_is_paid_at_not_transaction_creation(session_factory):
    async def seed():
        user_id = await make_user(session_factory)
        # создан 23:55 МСК 20-го, оплачен 00:05 МСК 21-го (= 21:05 UTC 20-го)
        await make_paid_payment(session_factory, user_id, amount=10000, tx_created_at=utc(2026, 9, 20, 20, 55), paid_at=utc(2026, 9, 20, 21, 5))

    asyncio.run(seed())
    boundary = utc(2026, 9, 20, 21, 0)

    assert _run(session_factory, lambda db: revenue_sum(db, since=boundary)) == 10000
    assert _run(session_factory, lambda db: revenue_sum(db, until=boundary)) == 0


def test_paid_at_missing_falls_back_to_transaction_time(session_factory):
    async def seed():
        user_id = await make_user(session_factory)
        await make_paid_payment(session_factory, user_id, amount=4000, paid_at=None, tx_created_at=utc(2026, 9, 21, 9))

    asyncio.run(seed())

    assert _run(session_factory, lambda db: revenue_sum(db, since=utc(2026, 9, 21, 0), until=utc(2026, 9, 22, 0))) == 4000


def test_summary_reports_gross_fee_and_net_known_share(session_factory):
    async def seed():
        user_id = await make_user(session_factory)
        when = utc(2026, 9, 21, 10)
        await make_paid_payment(session_factory, user_id, amount=24900, net=23904, gross=24900, paid_at=when)
        await make_paid_payment(session_factory, user_id, amount=10000, provider='platega', paid_at=when)

    asyncio.run(seed())

    summary = _run(session_factory, lambda db: revenue_summary(db))

    assert summary == {
        'net_kopeks': 33904,
        'gross_kopeks': 34900,
        'fee_kopeks': 996,
        'count': 2,
        'net_known_share': 0.5,
    }


def test_summary_of_empty_period_is_zeros(session_factory):
    summary = _run(session_factory, lambda db: revenue_summary(db))

    assert summary == {'net_kopeks': 0, 'gross_kopeks': 0, 'fee_kopeks': 0, 'count': 0, 'net_known_share': 1.0}
```

- [ ] **Step 3: Убедиться, что падает**

Run: `python -m pytest tests/test_revenue.py -q -p no:warnings`
Expected: FAIL (`ModuleNotFoundError: app.services.revenue`).

- [ ] **Step 4: Реализация**

Создайте `app/services/revenue.py`:

```python
"""Единственное место, где определено, что такое «выручка» для аналитики.

Выручка = ЧИСТАЯ сумма мерчанту (cisPay merchant_revenue; если провайдер её не
сообщает — amount_kopeks), по времени УСПЕШНОЙ ОПЛАТЫ (paid_at; если его нет —
время создания транзакции), только по транзакциям subscription_payment/gift,
без оплат собственным балансом (это уже раздатые бонусы, не новые деньги) и без
возвращённых платежей. Так считает кабинет cisPay — цифры должны сходиться.

analytics_service и все новые метрики берут выручку ТОЛЬКО отсюда.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Payment, Transaction

REVENUE_TYPES = ('subscription_payment', 'gift')

NET_AMOUNT = func.coalesce(Payment.merchant_revenue_kopeks, Payment.amount_kopeks)
GROSS_AMOUNT = func.coalesce(Payment.charged_amount_kopeks, Payment.amount_kopeks)
PAID_AT = func.coalesce(Payment.paid_at, Transaction.created_at)


def revenue_conditions() -> list:
    return [
        Transaction.type.in_(REVENUE_TYPES),
        Transaction.status == 'completed',
        Payment.provider != 'balance',
        Payment.status != 'refunded',
    ]


def revenue_select(*columns):
    """select(*columns) из Transaction JOIN Payment с условиями выручки."""
    return (
        select(*columns)
        .select_from(Transaction)
        .join(Payment, Payment.transaction_id == Transaction.id)
        .where(*revenue_conditions())
    )


def window_conditions(since: datetime | None = None, until: datetime | None = None) -> list:
    """Окно по времени оплаты: since включительно, until не включительно."""
    conditions = []
    if since is not None:
        conditions.append(PAID_AT >= since)
    if until is not None:
        conditions.append(PAID_AT < until)
    return conditions


async def revenue_sum(
    db: AsyncSession, *, since: datetime | None = None, until: datetime | None = None, gross: bool = False
) -> int:
    amount = GROSS_AMOUNT if gross else NET_AMOUNT
    stmt = revenue_select(func.coalesce(func.sum(amount), 0)).where(*window_conditions(since, until))
    return int((await db.execute(stmt)).scalar_one())


async def revenue_summary(db: AsyncSession, *, since: datetime | None = None, until: datetime | None = None) -> dict:
    stmt = revenue_select(
        func.coalesce(func.sum(NET_AMOUNT), 0),
        func.coalesce(func.sum(GROSS_AMOUNT), 0),
        func.count(Payment.id),
        func.count(Payment.merchant_revenue_kopeks),
    ).where(*window_conditions(since, until))
    net, gross, count, net_known = (await db.execute(stmt)).one()
    return {
        'net_kopeks': int(net),
        'gross_kopeks': int(gross),
        'fee_kopeks': int(gross) - int(net),
        'count': int(count),
        'net_known_share': round(net_known / count, 4) if count else 1.0,
    }
```

- [ ] **Step 5: Тесты и мутации**

Run: `python -m pytest tests -q -p no:warnings` → PASS.
Мутации (по одной, каждая должна ронять тест, потом откат): убрать `Payment.status != 'refunded'`; заменить `PAID_AT` на `Transaction.created_at`; заменить `NET_AMOUNT` на `Payment.amount_kopeks`.

- [ ] **Step 6: Коммит**

```bash
git add app/services/revenue.py tests/helpers.py tests/test_revenue.py
git commit -m "Добавляет единый расчёт выручки: нетто, по paid_at, без возвратов"
```

### Task 4: `paid_at` и суммы провайдера в `Payment`

**Files:**
- Create: `app/services/payment_amounts.py`
- Modify: `app/services/payment_finalization.py`, `app/handlers/subscription.py`, `app/handlers/gift.py`, `app/cabinet/webhooks.py`
- Test: `tests/test_payment_amounts.py`

**Interfaces:**
- Produces:
  - `parse_provider_datetime(value: object) -> datetime | None` — ISO-8601 (в т.ч. с `Z`) → aware UTC; мусор → `None`.
  - `apply_provider_details(payment: Payment, raw: dict | None = None) -> None` — из `raw` (по умолчанию `payment.provider_raw_response`) берёт `charged_amount`, `merchant_revenue` (только неотрицательные `int`) и `paid_at` (только если у платежа `paid_at` ещё пуст).
  - `stamp_payment_success(payment: Payment, raw: dict | None = None, now: datetime | None = None) -> None` — `apply_provider_details`, затем `paid_at = now or utcnow`, если всё ещё пуст.

- [ ] **Step 1: Падающие тесты**

Создайте `tests/test_payment_amounts.py`:

```python
"""app/services/payment_amounts.py — paid_at и суммы cisPay попадают в Payment."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.config import settings
from app.database.models import Payment, Transaction, User
from app.handlers.subscription import purchase_or_renew_subscription
from app.services.payment_amounts import apply_provider_details, parse_provider_datetime, stamp_payment_success
from app.services.payment_finalization import finalize_pending_payment
from tests.helpers import make_tariff, make_user


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    'value, expected',
    [
        ('2026-09-21T10:15:30Z', utc(2026, 9, 21, 10, 15, 30)),
        ('2026-09-21T10:15:30.123456+00:00', datetime(2026, 9, 21, 10, 15, 30, 123456, tzinfo=timezone.utc)),
        ('2026-09-21T13:15:30+03:00', utc(2026, 9, 21, 10, 15, 30)),
        ('2026-09-21T10:15:30', utc(2026, 9, 21, 10, 15, 30)),  # без пояса — UTC
        (None, None),
        ('', None),
        ('вчера', None),
        (12345, None),
    ],
)
def test_parse_provider_datetime(value, expected):
    assert parse_provider_datetime(value) == expected


def test_apply_provider_details_takes_valid_fields_only():
    payment = Payment(amount_kopeks=24900)

    apply_provider_details(payment, {'charged_amount': 24900, 'merchant_revenue': 23904, 'paid_at': '2026-09-21T10:15:30Z'})

    assert (payment.charged_amount_kopeks, payment.merchant_revenue_kopeks) == (24900, 23904)
    assert payment.paid_at == utc(2026, 9, 21, 10, 15, 30)


def test_apply_provider_details_ignores_garbage_and_keeps_existing():
    payment = Payment(amount_kopeks=100, merchant_revenue_kopeks=90, paid_at=utc(2026, 1, 1))

    apply_provider_details(payment, {'charged_amount': -5, 'merchant_revenue': 'lots', 'paid_at': '2026-09-21T10:00:00Z'})
    apply_provider_details(payment, None)
    apply_provider_details(payment, {'charged_amount': True})  # bool — не число

    assert payment.charged_amount_kopeks is None and payment.merchant_revenue_kopeks == 90
    assert payment.paid_at == utc(2026, 1, 1)  # уже стоял — не перезаписываем


def test_stamp_uses_provider_time_then_falls_back_to_now():
    with_time = Payment(amount_kopeks=1)
    without_time = Payment(amount_kopeks=1)
    now = utc(2026, 9, 22, 12, 0)

    stamp_payment_success(with_time, {'paid_at': '2026-09-21T10:15:30Z'}, now=now)
    stamp_payment_success(without_time, {}, now=now)

    assert with_time.paid_at == utc(2026, 9, 21, 10, 15, 30)
    assert without_time.paid_at == now


def test_finalize_pending_payment_copies_cispay_amounts_and_paid_at(session_factory):
    async def scenario():
        user_id = await make_user(session_factory)
        tariff_id = await make_tariff(session_factory)
        async with session_factory() as db:
            transaction = Transaction(user_id=user_id, type='subscription_payment', amount_kopeks=24900, status='pending')
            db.add(transaction)
            await db.flush()
            payment = Payment(
                user_id=user_id, transaction_id=transaction.id, provider='cispay', external_id='c-1', amount_kopeks=24900,
                status='pending', raw_payload={'kind': 'subscription', 'tariff_id': tariff_id, 'period_days': 30},
                provider_raw_response={'charged_amount': 24900, 'merchant_revenue': 23904, 'paid_at': '2026-09-21T10:15:30Z'},
            )
            db.add(payment)
            await db.commit()
            payment_id = payment.id
        async with session_factory() as db:
            await finalize_pending_payment(db, await db.get(Payment, payment_id), AsyncMock())

        async with session_factory() as db:
            stored = await db.get(Payment, payment_id)
            assert stored.status == 'success'
            assert (stored.charged_amount_kopeks, stored.merchant_revenue_kopeks) == (24900, 23904)
            assert stored.paid_at.replace(tzinfo=timezone.utc) == utc(2026, 9, 21, 10, 15, 30)

    asyncio.run(scenario())


def test_synchronous_purchase_sets_paid_at(session_factory, monkeypatch):
    monkeypatch.setattr(settings, 'PAYMENTS_MODE', 'stub')

    async def scenario():
        user_id = await make_user(session_factory, balance_kopeks=50000)
        tariff_id = await make_tariff(session_factory)
        before = datetime.now(timezone.utc)
        async with session_factory() as db:
            from app.database.models import Tariff

            await purchase_or_renew_subscription(db, await db.get(User, user_id), await db.get(Tariff, tariff_id), 30, 'balance')
            await db.commit()
        async with session_factory() as db:
            payment = (await db.execute(select(Payment))).scalar_one()
            assert payment.paid_at is not None
            assert payment.paid_at.replace(tzinfo=timezone.utc) >= before.replace(microsecond=0)

    asyncio.run(scenario())
```

- [ ] **Step 2: Убедиться, что падает**

Run: `python -m pytest tests/test_payment_amounts.py -q -p no:warnings`
Expected: FAIL (`ModuleNotFoundError: app.services.payment_amounts`).

- [ ] **Step 3: Реализация модуля**

Создайте `app/services/payment_amounts.py`:

```python
"""Момент оплаты и суммы провайдера -> колонки Payment.

cisPay сообщает в ответе/вебхуке `charged_amount` (списано с покупателя),
`merchant_revenue` (мерчанту после комиссии) и `paid_at` (UTC). Аналитика
(app/services/revenue.py) считает выручку по ним, чтобы сходиться с кабинетом cisPay.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.database.models import Payment


def parse_provider_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _kopeks(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def apply_provider_details(payment: Payment, raw: dict | None = None) -> None:
    raw = raw if raw is not None else payment.provider_raw_response
    if not isinstance(raw, dict):
        return
    charged = _kopeks(raw.get('charged_amount'))
    net = _kopeks(raw.get('merchant_revenue'))
    if charged is not None:
        payment.charged_amount_kopeks = charged
    if net is not None:
        payment.merchant_revenue_kopeks = net
    paid_at = parse_provider_datetime(raw.get('paid_at'))
    if paid_at is not None and payment.paid_at is None:
        payment.paid_at = paid_at


def stamp_payment_success(payment: Payment, raw: dict | None = None, now: datetime | None = None) -> None:
    """Вызывать в момент, когда платёж становится success."""
    apply_provider_details(payment, raw)
    if payment.paid_at is None:
        payment.paid_at = now or datetime.now(timezone.utc)
```

- [ ] **Step 4: Подключить в четырёх местах**

Используйте `apply_patch` (Приложение A) или Edit. Каждый фрагмент должен найтись ровно один раз.

1. `app/services/payment_finalization.py` — импорт `from app.services.payment_amounts import stamp_payment_success` рядом с прочими `from app.services…`, и замена:

```python
# OLD
    payment.status = 'success'
    transaction = None
# NEW
    payment.status = 'success'
    stamp_payment_success(payment)  # paid_at и суммы cisPay из provider_raw_response
    transaction = None
```

2. `app/handlers/subscription.py` — импорт `from app.services.payment_amounts import stamp_payment_success` и замена:

```python
# OLD
    db.add(payment)
    await db.flush()

    if not payment_success:
# NEW
    db.add(payment)
    if payment_success:
        stamp_payment_success(payment, created.raw_response)
    await db.flush()

    if not payment_success:
```

3. `app/handlers/gift.py` — импорт тот же и замена:

```python
# OLD
    db.add(payment)
    await db.flush()

    gift_code = await create_gift_code(
# NEW
    db.add(payment)
    stamp_payment_success(payment, created.raw_response)
    await db.flush()

    gift_code = await create_gift_code(
```
(в старом фрагменте `create_gift_code(` должна идти сразу после пустой строки — сверьтесь с файлом; у синхронной ветки после `db.add(payment)`/`await db.flush()` идёт вызов `create_gift_code`).

4. `app/cabinet/webhooks.py` (ветка автоплатежа) — импорт и замена:

```python
# OLD
        db.add(payment)
        await db.flush()

        try:
            await notify_payment_success(
# NEW
        db.add(payment)
        stamp_payment_success(payment, payload)
        await db.flush()

        try:
            await notify_payment_success(
```

- [ ] **Step 5: Тесты проходят**

Run: `python -m pytest tests -q -p no:warnings`
Expected: PASS (все, включая старые).

- [ ] **Step 6: Коммит**

```bash
git add app/services/payment_amounts.py app/services/payment_finalization.py app/handlers/subscription.py app/handlers/gift.py app/cabinet/webhooks.py tests/test_payment_amounts.py
git commit -m "Сохраняет paid_at и суммы cisPay (нетто/оборот) при успешной оплате"
```

---

### Task 5: Журнал событий — `record_event` и хелперы

**Files:**
- Create: `app/services/analytics_events.py`
- Test: `tests/test_analytics_events.py`

**Interfaces:**
- Consumes: `AnalyticsEvent`, `Payment`, `User` (Task 2).
- Produces:
  - `EVENT_TYPES: frozenset[str]`, `SOURCE_LIVE = 'live'`, `SOURCE_BACKFILL = 'backfill'`
  - `build_insert(dialect_name: str, values: dict)` — `INSERT … ON CONFLICT (dedupe_key) DO NOTHING RETURNING id` для `postgresql`/`sqlite`.
  - `async record_event(db, event_type: str, *, dedupe_key: str, user_id=None, occurred_at=None, tariff_id=None, days=None, amount_kopeks=None, campaign_id=None, promo_code_id=None, payment_id=None, discount_percent=None, discount_kind=None, source='live') -> bool` — `True`, если строка вставлена; `False`, если такой `dedupe_key` уже есть.
  - `expired_dedupe_key(subscription_id: int, end_date: datetime) -> str`
  - `async record_registration(db, user, *, campaign_id=None, occurred_at=None, source='live') -> bool` (ключ `user:{id}:registered`)
  - `async record_trial_started(db, user, *, tariff_id: int | None, days: int | None, occurred_at=None, source='live') -> bool` (ключ `user:{id}:trial`)
  - `async record_bonus(db, *, kind: str, user_id: int, ref: str, days=None, amount_kopeks=None, campaign_id=None, promo_code_id=None, occurred_at=None, source='live') -> bool` (ключ `bonus:{kind}:{ref}`, тип `bonus_granted`)
  - `async record_subscription_purchase(db, *, user_id: int, payment: Payment, tariff_id: int | None, days: int | None, occurred_at: datetime | None = None, source: str = 'live') -> bool` — `subscription_first_paid` (если у пользователя ещё нет платных событий) или `subscription_renewed`; ключ `payment:{payment.id}:paid`; `amount_kopeks` = нетто для реальных денег и `0` для `provider='balance'`; скидка из `payment.raw_payload`; `occurred_at` по умолчанию `payment.paid_at` (иначе «сейчас»).

- [ ] **Step 1: Падающие тесты**

Создайте `tests/test_analytics_events.py`:

```python
"""app/services/analytics_events.py — журнал событий."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql

from app.database.models import AnalyticsEvent, Payment, User
from app.services.analytics_events import (
    EVENT_TYPES,
    build_insert,
    expired_dedupe_key,
    record_bonus,
    record_event,
    record_registration,
    record_subscription_purchase,
    record_trial_started,
)
from tests.helpers import make_paid_payment, make_user


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


async def _events(factory) -> list[AnalyticsEvent]:
    async with factory() as db:
        return list((await db.execute(select(AnalyticsEvent).order_by(AnalyticsEvent.id))).scalars())


def test_record_event_inserts_once_per_dedupe_key(session_factory):
    async def scenario():
        user_id = await make_user(session_factory)
        async with session_factory() as db:
            first = await record_event(db, 'user_registered', dedupe_key='user:1:registered', user_id=user_id)
            again = await record_event(db, 'user_registered', dedupe_key='user:1:registered', user_id=user_id)
            other = await record_event(db, 'user_registered', dedupe_key='user:2:registered', user_id=user_id)
            await db.commit()
        assert (first, again, other) == (True, False, True)
        assert len(await _events(session_factory)) == 2

    asyncio.run(scenario())


def test_duplicate_does_not_poison_the_session(session_factory):
    """Повтор события не должен ломать транзакцию денежной операции."""

    async def scenario():
        user_id = await make_user(session_factory)
        async with session_factory() as db:
            await record_event(db, 'user_registered', dedupe_key='k', user_id=user_id)
            await record_event(db, 'user_registered', dedupe_key='k', user_id=user_id)
            db.add(User(telegram_id=99, referral_code='zz'))  # дальше сессия работает как обычно
            await db.commit()
        async with session_factory() as db:
            assert await db.scalar(select(func.count()).select_from(User)) == 2

    asyncio.run(scenario())


def test_defaults_and_time_normalization(session_factory):
    async def scenario():
        async with session_factory() as db:
            await record_event(db, 'trial_started', dedupe_key='a')
            await record_event(db, 'trial_started', dedupe_key='b', occurred_at=datetime(2026, 9, 21, 10, 0))  # naive -> UTC
            await db.commit()
        first, second = await _events(session_factory)
        assert first.source == 'live' and first.occurred_at is not None
        assert second.occurred_at.replace(tzinfo=timezone.utc) == utc(2026, 9, 21, 10, 0)

    asyncio.run(scenario())


def test_unknown_event_type_is_a_programming_error(session_factory):
    async def scenario():
        async with session_factory() as db:
            with pytest.raises(ValueError):
                await record_event(db, 'made_up', dedupe_key='x')

    asyncio.run(scenario())
    assert 'payment_refunded' in EVENT_TYPES and len(EVENT_TYPES) == 10


def test_postgres_statement_uses_on_conflict_do_nothing():
    stmt = build_insert('postgresql', {'type': 'user_registered', 'dedupe_key': 'k', 'occurred_at': utc(2026, 9, 21), 'source': 'live'})

    sql = str(stmt.compile(dialect=postgresql.dialect()))

    assert 'ON CONFLICT (dedupe_key) DO NOTHING' in sql and 'RETURNING analytics_events.id' in sql
    with pytest.raises(NotImplementedError):
        build_insert('mysql', {})


def test_expired_dedupe_key_is_timezone_stable():
    naive = datetime(2026, 9, 21, 10, 0)
    aware = utc(2026, 9, 21, 10, 0)

    assert expired_dedupe_key(7, naive) == expired_dedupe_key(7, aware) == 'sub:7:expired:2026-09-21T10:00:00+00:00'


def test_registration_trial_and_bonus_helpers(session_factory):
    async def scenario():
        user_id = await make_user(session_factory)
        async with session_factory() as db:
            user = await db.get(User, user_id)
            await record_registration(db, user, campaign_id=None)
            await record_registration(db, user)  # повтор
            await record_trial_started(db, user, tariff_id=None, days=3)
            await record_bonus(db, kind='promo', user_id=user_id, ref='5:1', days=7, promo_code_id=None)
            await db.commit()
        events = await _events(session_factory)
        assert [(e.type, e.dedupe_key) for e in events] == [
            ('user_registered', f'user:{user_id}:registered'),
            ('trial_started', f'user:{user_id}:trial'),
            ('bonus_granted', 'bonus:promo:5:1'),
        ]
        assert events[1].days == 3 and events[2].days == 7

    asyncio.run(scenario())


def _purchase_events(session_factory, payments: list[dict]):
    """Создаёт платежи и записывает события покупок по порядку; возвращает события."""

    async def scenario():
        user_id = await make_user(session_factory)
        ids = [await make_paid_payment(session_factory, user_id, **fields) for fields in payments]
        for payment_id in ids:
            async with session_factory() as db:
                payment = await db.get(Payment, payment_id)
                await record_subscription_purchase(db, user_id=user_id, payment=payment, tariff_id=None, days=30)
                await db.commit()
        return await _events(session_factory)

    return asyncio.run(scenario())


def test_first_purchase_then_renewals(session_factory):
    events = _purchase_events(
        session_factory,
        [
            dict(amount=24900, net=23904, paid_at=utc(2026, 9, 1, 10)),
            dict(amount=24900, net=23904, paid_at=utc(2026, 10, 1, 10)),
            dict(amount=10000, provider='platega', paid_at=utc(2026, 11, 1, 10)),
        ],
    )

    assert [e.type for e in events] == ['subscription_first_paid', 'subscription_renewed', 'subscription_renewed']
    assert [e.amount_kopeks for e in events] == [23904, 23904, 10000]  # нетто; без нетто — amount_kopeks
    assert events[0].occurred_at.replace(tzinfo=timezone.utc) == utc(2026, 9, 1, 10) and events[0].days == 30


def test_balance_funded_purchase_records_zero_amount(session_factory):
    events = _purchase_events(session_factory, [dict(amount=10000, provider='balance', paid_at=utc(2026, 9, 1, 10))])

    assert events[0].type == 'subscription_first_paid' and events[0].amount_kopeks == 0


def test_purchase_event_is_idempotent_and_reads_discount_from_payment(session_factory):
    async def scenario():
        user_id = await make_user(session_factory)
        payment_id = await make_paid_payment(session_factory, user_id, amount=8000, paid_at=utc(2026, 9, 1, 10))
        async with session_factory() as db:
            payment = await db.get(Payment, payment_id)
            payment.raw_payload = {'discount_percent': 20, 'discount_kind': 'group'}
            for _ in range(3):
                await record_subscription_purchase(db, user_id=user_id, payment=payment, tariff_id=None, days=30)
            await db.commit()
        (event,) = await _events(session_factory)
        assert (event.discount_percent, event.discount_kind, event.payment_id) == (20, 'group', payment_id)
        assert event.dedupe_key == f'payment:{payment_id}:paid'

    asyncio.run(scenario())
```

- [ ] **Step 2: Убедиться, что падает**

Run: `python -m pytest tests/test_analytics_events.py -q -p no:warnings`
Expected: FAIL (`ModuleNotFoundError: app.services.analytics_events`).

- [ ] **Step 3: Реализация**

Создайте `app/services/analytics_events.py`:

```python
"""Журнал событий аналитики (таблица analytics_events, append-only).

ВАЖНО: события пишутся в ТОЙ ЖЕ транзакции, что и денежная операция (никогда
отдельной) — не бывает события без платежа и платежа без события. Запись —
`INSERT ... ON CONFLICT (dedupe_key) DO NOTHING`: повтор не создаёт дубль, а
конфликт не бросает исключение и не «отравляет» сессию (в отличие от IntegrityError).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import AnalyticsEvent, Payment, User

SOURCE_LIVE = 'live'
SOURCE_BACKFILL = 'backfill'

EVENT_TYPES = frozenset(
    {
        'user_registered',
        'trial_started',
        'subscription_first_paid',
        'subscription_renewed',
        'subscription_expired',
        'promocode_activated',
        'gift_redeemed',
        'referral_reward_paid',
        'bonus_granted',
        'payment_refunded',
    }
)

_PAID_TYPES = ('subscription_first_paid', 'subscription_renewed')


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def build_insert(dialect_name: str, values: dict):
    if dialect_name == 'postgresql':
        insert = pg_insert
    elif dialect_name == 'sqlite':
        insert = sqlite_insert
    else:
        raise NotImplementedError(f'record_event: неподдерживаемый диалект {dialect_name!r}')
    return (
        insert(AnalyticsEvent)
        .values(**values)
        .on_conflict_do_nothing(index_elements=['dedupe_key'])
        .returning(AnalyticsEvent.id)
    )


async def record_event(
    db: AsyncSession,
    event_type: str,
    *,
    dedupe_key: str,
    user_id: int | None = None,
    occurred_at: datetime | None = None,
    tariff_id: int | None = None,
    days: int | None = None,
    amount_kopeks: int | None = None,
    campaign_id: int | None = None,
    promo_code_id: int | None = None,
    payment_id: int | None = None,
    discount_percent: int | None = None,
    discount_kind: str | None = None,
    source: str = SOURCE_LIVE,
) -> bool:
    """True — событие вставлено; False — событие с таким dedupe_key уже есть."""
    if event_type not in EVENT_TYPES:
        raise ValueError(f'Неизвестный тип события: {event_type!r}')
    values = {
        'occurred_at': _aware(occurred_at or datetime.now(timezone.utc)),
        'type': event_type,
        'user_id': user_id,
        'tariff_id': tariff_id,
        'days': days,
        'amount_kopeks': amount_kopeks,
        'campaign_id': campaign_id,
        'promo_code_id': promo_code_id,
        'payment_id': payment_id,
        'discount_percent': discount_percent,
        'discount_kind': discount_kind,
        'source': source,
        'dedupe_key': dedupe_key,
    }
    stmt = build_insert(db.get_bind().dialect.name, values)
    return (await db.execute(stmt)).scalar_one_or_none() is not None


def expired_dedupe_key(subscription_id: int, end_date: datetime) -> str:
    return f'sub:{subscription_id}:expired:{_aware(end_date).isoformat()}'


async def record_registration(
    db: AsyncSession, user: User, *, campaign_id: int | None = None, occurred_at: datetime | None = None, source: str = SOURCE_LIVE
) -> bool:
    return await record_event(
        db, 'user_registered', dedupe_key=f'user:{user.id}:registered', user_id=user.id,
        campaign_id=campaign_id, occurred_at=occurred_at, source=source,
    )


async def record_trial_started(
    db: AsyncSession, user: User, *, tariff_id: int | None, days: int | None,
    occurred_at: datetime | None = None, source: str = SOURCE_LIVE,
) -> bool:
    return await record_event(
        db, 'trial_started', dedupe_key=f'user:{user.id}:trial', user_id=user.id,
        tariff_id=tariff_id, days=days, occurred_at=occurred_at, source=source,
    )


async def record_bonus(
    db: AsyncSession, *, kind: str, user_id: int, ref: str, days: int | None = None, amount_kopeks: int | None = None,
    campaign_id: int | None = None, promo_code_id: int | None = None,
    occurred_at: datetime | None = None, source: str = SOURCE_LIVE,
) -> bool:
    """«Стоимость» маркетинга: бесплатные дни или бонус на баланс (kind: campaign|promo|referral_invite)."""
    return await record_event(
        db, 'bonus_granted', dedupe_key=f'bonus:{kind}:{ref}', user_id=user_id, days=days,
        amount_kopeks=amount_kopeks, campaign_id=campaign_id, promo_code_id=promo_code_id,
        occurred_at=occurred_at, source=source,
    )


async def record_subscription_purchase(
    db: AsyncSession, *, user_id: int, payment: Payment, tariff_id: int | None, days: int | None,
    occurred_at: datetime | None = None, source: str = SOURCE_LIVE,
) -> bool:
    """first_paid, если у пользователя ещё не было покупок подписки, иначе renewed.
    amount_kopeks — реальные деньги (нетто); для оплаты с баланса — 0."""
    prior = await db.execute(
        select(AnalyticsEvent.id).where(AnalyticsEvent.user_id == user_id, AnalyticsEvent.type.in_(_PAID_TYPES)).limit(1)
    )
    event_type = 'subscription_renewed' if prior.scalar_one_or_none() is not None else 'subscription_first_paid'
    if payment.provider == 'balance':
        amount = 0
    else:
        amount = payment.merchant_revenue_kopeks if payment.merchant_revenue_kopeks is not None else payment.amount_kopeks
    details = payment.raw_payload if isinstance(payment.raw_payload, dict) else {}
    return await record_event(
        db, event_type, dedupe_key=f'payment:{payment.id}:paid', user_id=user_id, tariff_id=tariff_id, days=days,
        amount_kopeks=amount, payment_id=payment.id, discount_percent=details.get('discount_percent'),
        discount_kind=details.get('discount_kind'), occurred_at=occurred_at or payment.paid_at, source=source,
    )
```

- [ ] **Step 4: Тесты проходят**

Run: `python -m pytest tests -q -p no:warnings`
Expected: PASS.

- [ ] **Step 5: Мутации**

Уберите `.on_conflict_do_nothing(...)` из `build_insert` — `test_record_event_inserts_once…` и `test_duplicate_does_not_poison…` падают; замените `'subscription_renewed'` на `'subscription_first_paid'` в `record_subscription_purchase` — падает `test_first_purchase_then_renewals`. Верните код.

- [ ] **Step 6: Коммит**

```bash
git add app/services/analytics_events.py tests/test_analytics_events.py
git commit -m "Добавляет журнал событий analytics_events и record_event с идемпотентной записью"
```

---

### Task 6: События покупок в денежных путях

**Files:**
- Modify: `app/services/pricing_service.py`, `app/handlers/subscription.py`, `app/services/payment_finalization.py`, `app/cabinet/webhooks.py`
- Test: `tests/test_purchase_events.py`

**Interfaces:**
- Consumes: `record_subscription_purchase` (Task 5), `stamp_payment_success` (Task 4).
- Produces (pricing_service):
  - `async get_best_discount_detail(db, user) -> tuple[int, str | None]` — процент и вид (`'group'|'winback'|'sale'`, `None` при 0%);
  - `async get_period_price_detail(db, tariff, period_days: int, user) -> tuple[int, int, str | None]` — `(цена_в_копейках, процент, вид)`.
  - Существующие `get_best_discount`, `get_period_price_kopeks` сохраняют поведение (их тесты в `tests/test_pricing.py` не меняются).

- [ ] **Step 1: Падающие тесты**

Создайте `tests/test_purchase_events.py`:

```python
"""События покупок в денежных путях: покупка с баланса/провайдером, финализация, скидки."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.config import settings
from app.database.models import AnalyticsEvent, BotSetting, Payment, PromoGroup, Tariff, Transaction, User
from app.handlers.subscription import purchase_or_renew_subscription
from app.services.payment.base import CreatedPayment
from app.services.payment_finalization import finalize_pending_payment
from app.services.pricing_service import (
    SALE_DISCOUNT_PERCENT_KEY,
    SALE_ENDS_AT_KEY,
    get_best_discount_detail,
    get_period_price_detail,
)
from tests.helpers import make_tariff, make_user


@pytest.fixture(autouse=True)
def stub_mode(monkeypatch):
    monkeypatch.setattr(settings, 'PAYMENTS_MODE', 'stub')


async def _buy(factory, user_id, tariff_id, method='balance'):
    async with factory() as db:
        await purchase_or_renew_subscription(db, await db.get(User, user_id), await db.get(Tariff, tariff_id), 30, method)
        await db.commit()


async def _events(factory):
    async with factory() as db:
        return list((await db.execute(select(AnalyticsEvent).order_by(AnalyticsEvent.id))).scalars())


def test_balance_purchase_then_renewal_emit_first_paid_then_renewed(session_factory):
    async def scenario():
        user_id = await make_user(session_factory, balance_kopeks=30000)
        tariff_id = await make_tariff(session_factory)
        await _buy(session_factory, user_id, tariff_id)
        await _buy(session_factory, user_id, tariff_id)

        first, second = await _events(session_factory)
        assert (first.type, second.type) == ('subscription_first_paid', 'subscription_renewed')
        assert first.user_id == user_id and first.tariff_id == tariff_id and first.days == 30
        assert first.amount_kopeks == 0  # оплачено с баланса — новых денег нет

    asyncio.run(scenario())


def test_provider_purchase_records_real_money_amount(session_factory):
    async def scenario():
        user_id = await make_user(session_factory, balance_kopeks=3000)
        tariff_id = await make_tariff(session_factory)  # цена 100 ₽, 30 дней
        await _buy(session_factory, user_id, tariff_id, method='platega')  # 30 ₽ баланс + 70 ₽ провайдер

        (event,) = await _events(session_factory)
        assert event.amount_kopeks == 7000
        async with session_factory() as db:
            payment = (await db.execute(select(Payment))).scalar_one()
            assert event.payment_id == payment.id and event.dedupe_key == f'payment:{payment.id}:paid'

    asyncio.run(scenario())


def test_discount_is_stored_on_payment_and_event(session_factory):
    async def scenario():
        async with session_factory() as db:
            group = PromoGroup(name='vip', discount_percent=20)
            db.add(group)
            await db.commit()
            group_id = group.id
        user_id = await make_user(session_factory, balance_kopeks=10000, promo_group_id=group_id)
        tariff_id = await make_tariff(session_factory)

        await _buy(session_factory, user_id, tariff_id)

        (event,) = await _events(session_factory)
        assert (event.discount_percent, event.discount_kind) == (20, 'group')
        async with session_factory() as db:
            payment = (await db.execute(select(Payment))).scalar_one()
            assert payment.raw_payload == {'discount_percent': 20, 'discount_kind': 'group'}

    asyncio.run(scenario())


def test_async_provider_purchase_emits_event_only_after_finalize_and_only_once(session_factory, monkeypatch):
    class AsyncProvider:
        async def create_payment(self, **kwargs) -> CreatedPayment:
            return CreatedPayment(external_id='ext-9', payment_url='https://pay.example/9', status='pending')

    monkeypatch.setattr('app.services.payment.router.get_payment_provider', lambda name: AsyncProvider())

    async def scenario():
        user_id = await make_user(session_factory)
        tariff_id = await make_tariff(session_factory)
        await _buy(session_factory, user_id, tariff_id, method='platega')
        assert await _events(session_factory) == []  # ещё не оплачено

        async with session_factory() as db:
            payment_id = (await db.execute(select(Payment.id))).scalar_one()
        for _ in range(2):  # вебхук и поллинг подряд
            async with session_factory() as db:
                await finalize_pending_payment(db, await db.get(Payment, payment_id), AsyncMock())

        (event,) = await _events(session_factory)
        assert event.type == 'subscription_first_paid' and event.amount_kopeks == 10000

    asyncio.run(scenario())


def test_discount_kind_selection(session_factory):
    async def scenario():
        async with session_factory() as db:
            group = PromoGroup(name='g', discount_percent=10)
            db.add(group)
            await db.commit()
            group_id = group.id
            db.add(BotSetting(key=SALE_DISCOUNT_PERCENT_KEY, value='30'))
            db.add(BotSetting(key=SALE_ENDS_AT_KEY, value=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat()))
            await db.commit()
        with_group = await make_user(session_factory, telegram_id=1, promo_group_id=group_id)
        tariff_id = await make_tariff(session_factory, period_prices_kopeks={'30': 10000})
        async with session_factory() as db:
            percent, kind = await get_best_discount_detail(db, await db.get(User, with_group))
            price, price_percent, price_kind = await get_period_price_detail(db, await db.get(Tariff, tariff_id), 30, await db.get(User, with_group))
        assert (percent, kind) == (30, 'sale')  # акция выгоднее группы
        assert (price, price_percent, price_kind) == (7000, 30, 'sale')

    asyncio.run(scenario())


def test_no_discount_has_no_kind(session_factory):
    async def scenario():
        user_id = await make_user(session_factory)
        async with session_factory() as db:
            assert await get_best_discount_detail(db, await db.get(User, user_id)) == (0, None)

    asyncio.run(scenario())
```

- [ ] **Step 2: Убедиться, что падает**

Run: `python -m pytest tests/test_purchase_events.py -q -p no:warnings`
Expected: FAIL (`ImportError: get_best_discount_detail`).

- [ ] **Step 3: `pricing_service` — вид скидки**

В `app/services/pricing_service.py` замените тело `get_best_discount` (docstring сохраните) и добавьте новые функции. Итоговый код блока:

```python
async def _discount_candidates(db: AsyncSession, user: User) -> list[tuple[int, datetime | None, str]]:
    """[(процент, дедлайн, вид)] — порядок важен: при равных процентах побеждает первая."""
    group_discount = 0
    if user.promo_group_id is not None:
        group = await db.get(PromoGroup, user.promo_group_id)
        group_discount = group.discount_percent if group else 0
    trial_discount, trial_deadline = await get_trial_winback_discount(db, user)
    sale_discount, sale_deadline = await get_active_sale_discount(db)
    return [
        (group_discount, None, 'group'),
        (trial_discount, trial_deadline, 'winback'),
        (sale_discount, sale_deadline, 'sale'),
    ]


async def get_best_discount(db: AsyncSession, user: User) -> tuple[int, datetime | None]:
    """(процент, дедлайн) максимальной из скидок … (оставьте прежний docstring)."""
    percent, deadline, _ = max(await _discount_candidates(db, user), key=lambda c: c[0])
    return percent, deadline


async def get_best_discount_detail(db: AsyncSession, user: User) -> tuple[int, str | None]:
    """(процент, вид скидки: group|winback|sale) — вид None, если скидки нет.
    Нужен аналитике (какая скидка привела к покупке)."""
    percent, _, kind = max(await _discount_candidates(db, user), key=lambda c: c[0])
    return percent, (kind if percent > 0 else None)


async def get_period_price_detail(db: AsyncSession, tariff: Tariff, period_days: int, user: User) -> tuple[int, int, str | None]:
    """(цена_в_копейках, процент, вид) — та же цена, что get_period_price_kopeks, плюс скидка."""
    base = int(tariff.period_prices_kopeks[str(period_days)])
    percent, kind = await get_best_discount_detail(db, user)
    return apply_discount(base, percent), percent, kind
```

- [ ] **Step 4: Хуки в `handlers/subscription.py`**

Импорты: к строке `from app.services.pricing_service import …` добавьте `get_period_price_detail`; добавьте `from app.services.analytics_events import record_subscription_purchase`. Затем четыре замены (`apply_patch`, каждая ровно одно вхождение):

```python
# 1. OLD
    amount_kopeks = await get_period_price_kopeks(db, tariff, period_days, db_user)

    description = f'Подписка «{tariff.name}» на {period_days} дн.'
# 1. NEW
    amount_kopeks, discount_percent, discount_kind = await get_period_price_detail(db, tariff, period_days, db_user)

    description = f'Подписка «{tariff.name}» на {period_days} дн.'
```
```python
# 2. OLD (создание Payment)
        raw_payload={},
# 2. NEW
        raw_payload={'discount_percent': discount_percent, 'discount_kind': discount_kind},
```
```python
# 3. OLD (контекст асинхронного платежа)
            'balance_offset_kopeks': balance_offset_kopeks,
        }
# 3. NEW
            'balance_offset_kopeks': balance_offset_kopeks,
            'discount_percent': discount_percent,
            'discount_kind': discount_kind,
        }
```
```python
# 4. OLD (перед начислением реферальной комиссии в синхронной ветке)
    await db.flush()

    try:
        await credit_referral_earning(db, payment, bot=bot)
# 4. NEW
    await db.flush()

    await record_subscription_purchase(db, user_id=db_user.id, payment=payment, tariff_id=tariff.id, days=period_days)

    try:
        await credit_referral_earning(db, payment, bot=bot)
```

- [ ] **Step 5: Хуки в финализации и автоплатеже**

`app/services/payment_finalization.py` — импорт `from app.services.analytics_events import record_subscription_purchase` и замена:

```python
# OLD
    try:
        await credit_referral_earning(db, payment, bot=bot)
    except Exception:
        logger.exception('credit_referral_earning упал (не блокирует подтверждение платежа)')
# NEW
    if kind == 'subscription':
        await record_subscription_purchase(db, user_id=user.id, payment=payment, tariff_id=tariff.id, days=period_days)

    try:
        await credit_referral_earning(db, payment, bot=bot)
    except Exception:
        logger.exception('credit_referral_earning упал (не блокирует подтверждение платежа)')
```

`app/cabinet/webhooks.py` (ветка автоплатежа) — импорт `from app.services.analytics_events import record_subscription_purchase` и замена:

```python
# OLD
        db.add(payment)
        stamp_payment_success(payment, payload)
        await db.flush()

        try:
            await notify_payment_success(
# NEW
        db.add(payment)
        stamp_payment_success(payment, payload)
        await db.flush()
        await record_subscription_purchase(
            db, user_id=user.id, payment=payment, tariff_id=subscription.tariff_id, days=AUTOPAY_PERIOD_DAYS
        )

        try:
            await notify_payment_success(
```

- [ ] **Step 6: Тесты проходят**

Run: `python -m pytest tests -q -p no:warnings`
Expected: PASS (все, включая `tests/test_pricing.py`, `tests/test_purchase_flow.py`).

- [ ] **Step 7: Проверка вызовов (grep)**

Run: `grep -rn "record_subscription_purchase" app --include=*.py`
Expected: вызовы в `handlers/subscription.py`, `services/payment_finalization.py`, `cabinet/webhooks.py` (+ определение). Покупка подарка (`handlers/gift.py`) события подписки **не** порождает — это по плану.

- [ ] **Step 8: Коммит**

```bash
git add app/services/pricing_service.py app/handlers/subscription.py app/services/payment_finalization.py app/cabinet/webhooks.py tests/test_purchase_events.py
git commit -m "Пишет события покупок и запоминает применённую скидку в платеже"
```

### Task 7: События жизненного цикла (регистрация, триал, истечение, промо, подарок, рефералка, бонусы)

**Files:**
- Modify: `app/handlers/start.py`, `app/handlers/admin.py`, `app/cabinet/routes.py`, `app/services/background.py`, `app/services/promocode_service.py`, `app/services/gift_service.py`, `app/services/referral_service.py`, `app/services/campaign_service.py`
- Test: `tests/test_lifecycle_events.py`

**Interfaces:**
- Consumes: `record_event`, `record_registration`, `record_trial_started`, `record_bonus`, `expired_dedupe_key` (Task 5).
- Produces: изменённая сигнатура `credit_referral_invite_bonus(db, referrer, bot=None, *, invited_user_id: int | None = None)`. Ключи идемпотентности: `promo:{code_id}:{user_id}`, `bonus:promo:{code_id}:{user_id}`, `gift:{gift_id}:redeemed`, `referral_payment:{payment_id}`, `bonus:referral_invite:{referrer_id}:{invited_id}`, `bonus:campaign:{campaign_id}:{user_id}`, `sub:{id}:expired:{end_date_utc_iso}`.

- [ ] **Step 1: Падающие тесты**

Создайте `tests/test_lifecycle_events.py`:

```python
"""События жизненного цикла: промо, подарок, рефералка, кампания, истечение, регистрация."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.cabinet.app import create_app
from app.cabinet.deps import get_db
from app.config import settings
from app.database.models import (
    AnalyticsEvent, Campaign, GiftCode, Payment, PromoCode, Subscription, Transaction, User,
)
from app.services import background
from app.services.campaign_service import apply_campaign_bonus
from app.services.gift_service import GiftCodeError, redeem_gift_code
from app.services.promocode_service import PromoCodeError, activate_promocode
from app.services.referral_service import credit_referral_earning, credit_referral_invite_bonus
from tests.helpers import make_paid_payment, make_tariff, make_user


async def _events(factory, event_type: str | None = None) -> list[AnalyticsEvent]:
    async with factory() as db:
        stmt = select(AnalyticsEvent).order_by(AnalyticsEvent.id)
        if event_type:
            stmt = stmt.where(AnalyticsEvent.type == event_type)
        return list((await db.execute(stmt)).scalars())


# --- промокоды -----------------------------------------------------------------


async def _promo(factory, **fields) -> int:
    async with factory() as db:
        promo = PromoCode(**{**dict(code='SUMMER', type='balance', value=5000, max_activations=5), **fields})
        db.add(promo)
        await db.commit()
        return promo.id


async def _activate(factory, user_id: int) -> None:
    async with factory() as db:
        await activate_promocode(db, code='SUMMER', user=await db.get(User, user_id))
        await db.commit()


def test_balance_promocode_emits_activation_and_bonus_cost(session_factory):
    async def scenario():
        user_id = await make_user(session_factory)
        promo_id = await _promo(session_factory)
        await _activate(session_factory, user_id)

        (activated,) = await _events(session_factory, 'promocode_activated')
        (bonus,) = await _events(session_factory, 'bonus_granted')
        assert (activated.user_id, activated.promo_code_id, activated.dedupe_key) == (user_id, promo_id, f'promo:{promo_id}:{user_id}')
        assert (bonus.amount_kopeks, bonus.days, bonus.promo_code_id) == (5000, None, promo_id)

    asyncio.run(scenario())


def test_days_promocode_bonus_is_in_days(session_factory):
    async def scenario():
        user_id = await make_user(session_factory)
        await make_tariff(session_factory)
        await _promo(session_factory, type='days', value=7)
        await _activate(session_factory, user_id)

        (bonus,) = await _events(session_factory, 'bonus_granted')
        assert (bonus.days, bonus.amount_kopeks) == (7, None)

    asyncio.run(scenario())


def test_rejected_promocode_emits_nothing(session_factory):
    async def scenario():
        user_id = await make_user(session_factory)
        await _promo(session_factory, is_active=False)
        with pytest.raises(PromoCodeError):
            await _activate(session_factory, user_id)

        assert await _events(session_factory) == []

    asyncio.run(scenario())


# --- подарок -------------------------------------------------------------------


def test_gift_redeem_emits_once(session_factory):
    async def scenario():
        gifter = await make_user(session_factory, telegram_id=100)
        recipient = await make_user(session_factory, telegram_id=1)
        other = await make_user(session_factory, telegram_id=2)
        tariff_id = await make_tariff(session_factory)
        async with session_factory() as db:
            gift = GiftCode(code='GIFT1', tariff_id=tariff_id, period_days=30, gifter_user_id=gifter,
                            expires_at=datetime.now(timezone.utc) + timedelta(days=30))
            db.add(gift)
            await db.commit()
            gift_id = gift.id
        for user_id in (recipient, other):
            async with session_factory() as db:
                try:
                    await redeem_gift_code(db, code='GIFT1', recipient=await db.get(User, user_id))
                except GiftCodeError:
                    pass
                await db.commit()

        (event,) = await _events(session_factory, 'gift_redeemed')
        assert (event.user_id, event.tariff_id, event.days, event.dedupe_key) == (recipient, tariff_id, 30, f'gift:{gift_id}:redeemed')

    asyncio.run(scenario())


# --- рефералка и кампании ------------------------------------------------------


def test_referral_reward_event_and_idempotency(session_factory):
    async def scenario():
        referrer = await make_user(session_factory, telegram_id=100, referral_commission_percent=10)
        buyer = await make_user(session_factory, telegram_id=200, referred_by_id=referrer)
        payment_id = await make_paid_payment(session_factory, buyer, amount=10000, paid_at=datetime.now(timezone.utc))
        for _ in range(2):
            async with session_factory() as db:
                await credit_referral_earning(db, await db.get(Payment, payment_id))
                await db.commit()

        (event,) = await _events(session_factory, 'referral_reward_paid')
        assert (event.user_id, event.payment_id, event.amount_kopeks) == (referrer, payment_id, 1000)

    asyncio.run(scenario())


def test_invite_bonus_event_requires_invited_user(session_factory):
    async def scenario():
        referrer = await make_user(session_factory, telegram_id=100)
        invited = await make_user(session_factory, telegram_id=200)
        await make_tariff(session_factory)
        async with session_factory() as db:
            await credit_referral_invite_bonus(db, await db.get(User, referrer))  # без invited_user_id — события нет
            await db.commit()
        assert await _events(session_factory, 'bonus_granted') == []
        async with session_factory() as db:
            await credit_referral_invite_bonus(db, await db.get(User, referrer), invited_user_id=invited)
            await db.commit()

        (bonus,) = await _events(session_factory, 'bonus_granted')
        assert (bonus.user_id, bonus.days, bonus.dedupe_key) == (referrer, 3, f'bonus:referral_invite:{referrer}:{invited}')

    asyncio.run(scenario())


def test_campaign_bonuses_are_recorded_with_campaign_id(session_factory):
    async def scenario():
        balance_user = await make_user(session_factory, telegram_id=1)
        days_user = await make_user(session_factory, telegram_id=2)
        await make_tariff(session_factory)
        async with session_factory() as db:
            balance_campaign = Campaign(name='A', start_parameter='a', bonus_type='balance', balance_bonus_kopeks=3000, is_active=True)
            days_campaign = Campaign(name='B', start_parameter='b', bonus_type='subscription', subscription_duration_days=5, is_active=True)
            db.add_all([balance_campaign, days_campaign])
            await db.commit()
            ids = (balance_campaign.id, days_campaign.id)
        for campaign_id, user_id in zip(ids, (balance_user, days_user)):
            async with session_factory() as db:
                await apply_campaign_bonus(db, campaign=await db.get(Campaign, campaign_id), user=await db.get(User, user_id))
                await db.commit()

        by_campaign = {e.campaign_id: e for e in await _events(session_factory, 'bonus_granted')}
        assert (by_campaign[ids[0]].amount_kopeks, by_campaign[ids[0]].days) == (3000, None)
        assert (by_campaign[ids[1]].amount_kopeks, by_campaign[ids[1]].days) == (None, 5)

    asyncio.run(scenario())


# --- истечение подписки --------------------------------------------------------


def test_expiry_emits_event_once(session_factory, monkeypatch):
    monkeypatch.setattr(background, 'AsyncSessionLocal', session_factory)
    monkeypatch.setattr(background, 'get_remnawave_client', lambda: SimpleNamespace(disable_user=AsyncMock()))

    async def scenario():
        user_id = await make_user(session_factory, remnawave_uuid='rw-1')
        tariff_id = await make_tariff(session_factory)
        end = datetime.now(timezone.utc) - timedelta(hours=1)
        async with session_factory() as db:
            db.add(Subscription(user_id=user_id, tariff_id=tariff_id, status='active', end_date=end))
            await db.commit()
        await background.run_expiry_check_once(AsyncMock())
        await background.run_expiry_check_once(AsyncMock())

        (event,) = await _events(session_factory, 'subscription_expired')
        assert (event.user_id, event.tariff_id) == (user_id, tariff_id)
        assert event.occurred_at.replace(tzinfo=timezone.utc) == end

    asyncio.run(scenario())


# --- регистрация через Mini App -----------------------------------------------


def _init_data(user: dict) -> str:
    fields = {'auth_date': str(int(time.time())), 'user': json.dumps(user)}
    check = '\n'.join(f'{key}={value}' for key, value in sorted(fields.items()))
    secret = hmac.new(b'WebAppData', settings.BOT_TOKEN.encode(), hashlib.sha256).digest()
    fields['hash'] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def test_miniapp_registration_emits_one_event_for_repeated_logins(session_factory, monkeypatch):
    monkeypatch.setattr(settings, 'CABINET_JWT_SECRET', 'x' * 32)
    engine = create_async_engine(str(session_factory.kw['bind'].url), connect_args={'timeout': 30})
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with factory() as session:
            yield session

    app = create_app(AsyncMock())
    app.dependency_overrides[get_db] = override_get_db
    body = {'init_data': _init_data({'id': 777, 'username': 'newbie', 'language_code': 'ru'})}
    with TestClient(app) as client:
        assert client.post('/cabinet/auth/telegram', json=body).status_code == 200
        assert client.post('/cabinet/auth/telegram', json=body).status_code == 200

    (event,) = asyncio.run(_events(session_factory, 'user_registered'))
    assert event.dedupe_key == f'user:{event.user_id}:registered' and event.campaign_id is None


# --- обработчики Telegram подключены к событиям -------------------------------


def test_telegram_handlers_are_wired_to_events():
    """Обработчики aiogram не эмулируем целиком — проверяем, что вызовы на месте."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / 'app'
    start = (root / 'handlers' / 'start.py').read_text(encoding='utf-8')
    admin = (root / 'handlers' / 'admin.py').read_text(encoding='utf-8')

    assert 'await record_registration(db, new_user, campaign_id=campaign_id)' in start
    assert 'await record_trial_started(' in start
    assert 'invited_user_id=new_user.id' in start
    assert 'await record_trial_started(db, target' in admin
```

- [ ] **Step 2: Убедиться, что падает**

Run: `python -m pytest tests/test_lifecycle_events.py -q -p no:warnings`
Expected: FAIL (события не пишутся; `credit_referral_invite_bonus` не принимает `invited_user_id`).

- [ ] **Step 3: Сервисы (промокод, подарок, рефералка, кампания, истечение)**

Во всех правках — импорт нужных функций из `app.services.analytics_events` в верх файла. Используйте `apply_patch`.

`app/services/promocode_service.py` — импорт `from app.services.analytics_events import record_bonus, record_event`; замена:

```python
# OLD
    await db.refresh(promocode, ['activations_count'])
# NEW
    await db.refresh(promocode, ['activations_count'])
    bonus_days = promocode.value if promocode.type == 'days' else None
    bonus_amount = promocode.value if promocode.type == 'balance' else None
    await record_event(
        db, 'promocode_activated', dedupe_key=f'promo:{promocode.id}:{user.id}', user_id=user.id,
        promo_code_id=promocode.id, days=bonus_days, amount_kopeks=bonus_amount,
    )
    await record_bonus(
        db, kind='promo', user_id=user.id, ref=f'{promocode.id}:{user.id}', days=bonus_days,
        amount_kopeks=bonus_amount, promo_code_id=promocode.id,
    )
```

`app/services/gift_service.py` — импорт `from app.services.analytics_events import record_event`; перед строкой `    log.info('gift_redeemed', …` добавьте:

```python
    await record_event(
        db, 'gift_redeemed', dedupe_key=f'gift:{gift_code.id}:redeemed', user_id=recipient.id,
        tariff_id=gift_code.tariff_id, days=gift_code.period_days,
    )
```

`app/services/referral_service.py` — импорт `from app.services.analytics_events import record_bonus, record_event`; замены:

```python
# 1. OLD
        await db.flush()

        if bot is not None:
            try:
                await notify_referral_bonus(
# 1. NEW
        await db.flush()
        await record_event(
            db, 'referral_reward_paid', dedupe_key=f'referral_payment:{payment.id}', user_id=referrer.id,
            payment_id=payment.id, amount_kopeks=amount_kopeks,
        )

        if bot is not None:
            try:
                await notify_referral_bonus(
```
```python
# 2. OLD (сигнатура; сохраните существующие аннотации типов)
async def credit_referral_invite_bonus(db: AsyncSession, referrer: User, bot: Bot | None = None) -> None:
# 2. NEW
async def credit_referral_invite_bonus(
    db: AsyncSession, referrer: User, bot: Bot | None = None, *, invited_user_id: int | None = None
) -> None:
```
```python
# 3. OLD
        await provision_or_extend_subscription(db, user=referrer, tariff=tariff, period_days=REFERRAL_INVITE_BONUS_DAYS)
        await db.flush()
# 3. NEW
        await provision_or_extend_subscription(db, user=referrer, tariff=tariff, period_days=REFERRAL_INVITE_BONUS_DAYS)
        await db.flush()
        if invited_user_id is not None:
            await record_bonus(
                db, kind='referral_invite', user_id=referrer.id, ref=f'{referrer.id}:{invited_user_id}',
                days=REFERRAL_INVITE_BONUS_DAYS,
            )
```

`app/services/campaign_service.py` — импорт `from app.services.analytics_events import record_bonus`; замены:

```python
# 1. OLD
            await credit_balance(db, user, campaign.balance_bonus_kopeks, reason='campaign_bonus')
# 1. NEW
            await credit_balance(db, user, campaign.balance_bonus_kopeks, reason='campaign_bonus')
            await record_bonus(
                db, kind='campaign', user_id=user.id, ref=f'{campaign.id}:{user.id}',
                amount_kopeks=campaign.balance_bonus_kopeks, campaign_id=campaign.id,
            )
```
```python
# 2. OLD
                await provision_or_extend_subscription(
                    db, user=user, tariff=tariff, period_days=campaign.subscription_duration_days
                )
# 2. NEW
                await provision_or_extend_subscription(
                    db, user=user, tariff=tariff, period_days=campaign.subscription_duration_days
                )
                await record_bonus(
                    db, kind='campaign', user_id=user.id, ref=f'{campaign.id}:{user.id}',
                    days=campaign.subscription_duration_days, campaign_id=campaign.id,
                )
```

`app/services/background.py` — импорт `from app.services.analytics_events import expired_dedupe_key, record_event`; замена в `run_expiry_check_once`:

```python
# OLD
            sub.status = 'expired'
            log.info('subscription_expired', user_id=user.id, subscription_id=sub.id)
# NEW
            sub.status = 'expired'
            await record_event(
                db, 'subscription_expired', dedupe_key=expired_dedupe_key(sub.id, sub.end_date), user_id=user.id,
                tariff_id=sub.tariff_id, occurred_at=sub.end_date,
            )
            log.info('subscription_expired', user_id=user.id, subscription_id=sub.id)
```

- [ ] **Step 4: Обработчики и кабинет**

`app/handlers/start.py` — импорт `from app.services.analytics_events import record_registration, record_trial_started`; замены:

```python
# 1. OLD
    if campaign_param:
        from app.services.campaign_service import apply_campaign_bonus, get_campaign_by_start_parameter

        campaign = await get_campaign_by_start_parameter(db, campaign_param)
        if campaign is not None:
            await apply_campaign_bonus(db, campaign=campaign, user=new_user)
# 1. NEW
    campaign_id: int | None = None
    if campaign_param:
        from app.services.campaign_service import apply_campaign_bonus, get_campaign_by_start_parameter

        campaign = await get_campaign_by_start_parameter(db, campaign_param)
        if campaign is not None:
            campaign_id = campaign.id
            await apply_campaign_bonus(db, campaign=campaign, user=new_user)

    await record_registration(db, new_user, campaign_id=campaign_id)
```
```python
# 2. OLD
            new_user.trial_used = True
            await db.flush()
            trial_days = trial_tariff.trial_period_days + signup_bonus_days
# 2. NEW
            new_user.trial_used = True
            await db.flush()
            trial_days = trial_tariff.trial_period_days + signup_bonus_days
            await record_trial_started(db, new_user, tariff_id=trial_tariff.id, days=trial_days)
```
```python
# 3. OLD
            await credit_referral_invite_bonus(db, referrer, callback.bot)
# 3. NEW
            await credit_referral_invite_bonus(db, referrer, callback.bot, invited_user_id=new_user.id)
```

`app/handlers/admin.py` — импорт `from app.services.analytics_events import record_trial_started`; замена (ручная выдача триала):

```python
# OLD
    if is_trial:
        target.trial_used = True
    await db.flush()
# NEW
    if is_trial:
        target.trial_used = True
        await record_trial_started(db, target, tariff_id=tariff.id, days=period_days)
    await db.flush()
```

`app/cabinet/routes.py` — импорт `from app.services.analytics_events import record_registration`; замена в `auth_telegram`:

```python
# OLD
        db.add(user)
        await db.flush()

    if user.is_blocked:
# NEW
        db.add(user)
        await db.flush()
        await record_registration(db, user)

    if user.is_blocked:
```

- [ ] **Step 5: Тесты проходят**

Run: `python -m pytest tests -q -p no:warnings`
Expected: PASS. Если `test_expiry_emits_event_once` падает на сравнении времени из-за микросекунд/SQLite — сравнивайте `occurred_at` с `end` с точностью до секунды.

- [ ] **Step 6: Проверка вызовов**

Run: `grep -rn "record_registration\|record_trial_started\|record_bonus\|record_event(" app --include=*.py | grep -v "def \|import"`
Expected: вызовы в `handlers/start.py`, `handlers/admin.py`, `cabinet/routes.py`, `services/{background,promocode_service,gift_service,referral_service,campaign_service,analytics_events}.py`.

- [ ] **Step 7: Коммит**

```bash
git add app tests/test_lifecycle_events.py
git commit -m "Пишет события регистрации, триала, истечения, промокодов, подарков, рефералки и бонусов"
```

---

### Task 8: Перевод существующей аналитики на `revenue.py` и `time_utils`

**Files:**
- Create: `app/cabinet/report_tz.py`
- Modify: `app/services/analytics_service.py`, `app/cabinet/admin_schemas.py`, `app/cabinet/admin_routes.py`
- Test: `tests/test_analytics_service.py`

**Interfaces:**
- Consumes: `revenue.py` (Task 3), `time_utils.py` (Task 1).
- Produces:
  - `app/cabinet/report_tz.py::report_tz(tz: str | None = Query(None)) -> ZoneInfo` — FastAPI-зависимость; неизвестный пояс → HTTP 422.
  - Все функции `analytics_service`, считающие деньги или календарные границы, получают необязательные `tz: ZoneInfo | None = None` и `now: datetime | None = None` (по умолчанию — отчётный пояс из настроек и текущий момент). `now` нужен тестам.
  - **Изменение поведения (отразить в описании коммита):** выручка нетто (~на комиссию ниже), по `paid_at`, границы суток по отчётному поясу; `get_revenue_timeseries(days=N)` теперь возвращает **ровно N** точек (раньше N+1), заканчивая сегодняшним отчётным днём; окна «7/30 дней» — по календарным дням.

- [ ] **Step 1: Падающие тесты**

Создайте `tests/test_analytics_service.py`:

```python
"""analytics_service после перевода на revenue.py/time_utils: нетто, paid_at, отчётный пояс."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.cabinet.admin_deps import require_admin
from app.cabinet.app import create_app
from app.cabinet.deps import get_db
from app.database.models import User
from app.services import analytics_service as svc
from app.services.time_utils import get_report_tz
from tests.helpers import make_paid_payment, make_user

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)  # 15:00 МСК, понедельник
MSK = get_report_tz('Europe/Moscow')
UTC_TZ = get_report_tz('UTC')


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def _seed(factory):
    async def scenario():
        user = await make_user(factory)
        await make_paid_payment(factory, user, amount=24900, net=23904, gross=24900, paid_at=utc(2026, 9, 21, 5, 0))  # утро 21-го МСК
        await make_paid_payment(factory, user, amount=10000, provider='platega', paid_at=utc(2026, 9, 20, 22, 0),
                                tx_created_at=utc(2026, 9, 20, 21, 55))  # 01:00 МСК 21-го, но 20-е по UTC
        await make_paid_payment(factory, user, amount=5000, provider='platega', paid_at=utc(2026, 9, 20, 18, 0))  # вечер 20-го МСК
        await make_paid_payment(factory, user, amount=7000, provider='platega', paid_at=utc(2026, 9, 10, 12, 0))  # внутри 30 дней
        await make_paid_payment(factory, user, amount=9999, status='refunded', paid_at=utc(2026, 9, 21, 6, 0))  # возврат
        await make_paid_payment(factory, user, amount=9999, provider='balance', paid_at=utc(2026, 9, 21, 6, 0))  # с баланса
        return user

    return asyncio.run(scenario())


def _call(factory, fn, **kwargs):
    async def scenario():
        async with factory() as db:
            return await fn(db, **kwargs)

    return asyncio.run(scenario())


def test_overview_windows_are_net_paid_at_and_report_calendar_days(session_factory):
    _seed(session_factory)

    overview = _call(session_factory, svc.get_overview, tz=MSK, now=NOW)

    assert overview['revenue_today_kopeks'] == 23904 + 10000  # оба платежа — 21-е по МСК
    assert overview['revenue_7d_kopeks'] == 23904 + 10000 + 5000
    assert overview['revenue_30d_kopeks'] == 23904 + 10000 + 5000 + 7000
    assert overview['revenue_all_time_kopeks'] == 45904
    assert overview['revenue_30d_gross_kopeks'] == 24900 + 10000 + 5000 + 7000
    assert overview['fees_30d_kopeks'] == 996
    assert overview['net_known_share_30d'] == 0.25
    assert overview['timezone'] == 'Europe/Moscow'
    assert overview['avg_check_kopeks'] == round(45904 / 4)


def test_overview_respects_requested_timezone(session_factory):
    _seed(session_factory)

    overview = _call(session_factory, svc.get_overview, tz=UTC_TZ, now=NOW)

    assert overview['revenue_today_kopeks'] == 23904  # по UTC второй платёж — ещё 20-е
    assert overview['timezone'] == 'UTC'


def test_timeseries_has_exactly_n_report_days_and_sums_to_the_card(session_factory):
    _seed(session_factory)

    series = _call(session_factory, svc.get_revenue_timeseries, days=7, tz=MSK, now=NOW)
    overview = _call(session_factory, svc.get_overview, tz=MSK, now=NOW)

    assert [point['date'] for point in series] == [f'2026-09-{day:02d}' for day in range(15, 22)]
    assert sum(point['revenue_kopeks'] for point in series) == overview['revenue_7d_kopeks']
    assert series[-1] == {'date': '2026-09-21', 'revenue_kopeks': 33904, 'count': 2}
    assert series[-2]['revenue_kopeks'] == 5000


def test_month_revenue_starts_at_moscow_month_boundary(session_factory):
    async def seed():
        user = await make_user(session_factory)
        await make_paid_payment(session_factory, user, amount=1000, provider='platega', paid_at=utc(2026, 8, 31, 22, 0))  # 01:00 МСК 1 сентября
        await make_paid_payment(session_factory, user, amount=2000, provider='platega', paid_at=utc(2026, 8, 31, 20, 0))  # ещё август по МСК

    asyncio.run(seed())

    assert _call(session_factory, svc.get_revenue_this_month, tz=MSK, now=NOW) == 1000
    assert _call(session_factory, svc.get_revenue_this_month, tz=UTC_TZ, now=NOW) == 0  # по UTC это август


def test_weekday_breakdown_uses_report_timezone(session_factory):
    _seed(session_factory)

    by_weekday = {row['weekday']: row['revenue_kopeks'] for row in _call(session_factory, svc.get_revenue_by_weekday, days=90, tz=MSK, now=NOW)}

    assert by_weekday[0] == 33904  # понедельник 21-го по МСК (второй платёж — 01:00 понедельника)
    assert by_weekday[6] == 5000  # воскресенье 20-го


def test_breakdowns_are_net(session_factory):
    _seed(session_factory)

    by_provider = {row['provider']: row['revenue_kopeks'] for row in _call(session_factory, svc.get_revenue_by_provider, days=30, tz=MSK, now=NOW)}
    by_type = {row['type']: row['revenue_kopeks'] for row in _call(session_factory, svc.get_revenue_by_type, days=30, tz=MSK, now=NOW)}
    composition = _call(session_factory, svc.get_revenue_by_provider_timeseries, days=3, tz=MSK, now=NOW)

    assert by_provider == {'cispay': 23904, 'platega': 22000}
    assert by_type == {'subscription_payment': 45904, 'gift': 0}
    assert composition['days'] == ['2026-09-19', '2026-09-20', '2026-09-21']
    assert {row['provider']: row['values'] for row in composition['series']} == {'cispay': [0, 0, 23904], 'platega': [0, 5000, 10000]}


def test_recent_payments_show_net_amount_and_paid_time(session_factory):
    _seed(session_factory)

    rows = _call(session_factory, svc.get_recent_payments, limit=2)

    assert [r['amount_kopeks'] for r in rows] == [23904, 10000]
    assert rows[0]['created_at'].replace(tzinfo=timezone.utc) == utc(2026, 9, 21, 5, 0)  # время оплаты


def test_ltv_is_net(session_factory):
    _seed(session_factory)

    ltv = _call(session_factory, svc.get_ltv)

    assert ltv['paying_users_count'] == 1 and ltv['top_payers'][0]['total_kopeks'] == 45904


def test_cohort_month_follows_report_timezone(session_factory):
    async def seed():
        user = await make_user(session_factory, created_at=utc(2026, 8, 31, 22, 0))  # 1 сентября 01:00 МСК
        await make_paid_payment(session_factory, user, amount=1000, provider='platega', paid_at=utc(2026, 9, 5, 12, 0))

    asyncio.run(seed())

    msk = _call(session_factory, svc.get_cohorts, tz=MSK)
    utc_result = _call(session_factory, svc.get_cohorts, tz=UTC_TZ)

    assert [c['cohort_month'] for c in msk['cohorts']] == ['2026-09']
    assert [c['cohort_month'] for c in utc_result['cohorts']] == ['2026-08']


def test_pulse_today_uses_report_day(session_factory):
    pulse = _call(session_factory, svc.get_subscription_pulse, tz=MSK, now=NOW)

    assert set(pulse) >= {'new_today', 'renewals_today', 'expiring_24h', 'expiring_3d'}


# --- HTTP: параметр tz и заголовок --------------------------------------------


@pytest.fixture
def admin_client(session_factory):
    engine = create_async_engine(str(session_factory.kw['bind'].url), connect_args={'timeout': 30})
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with factory() as session:
            yield session

    app = create_app(AsyncMock())
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_admin] = lambda: User(id=1, telegram_id=1, referral_code='a', is_admin=True)
    with TestClient(app) as client:
        yield client


def test_unknown_timezone_is_422(admin_client):
    assert admin_client.get('/cabinet/admin/overview?tz=Mars/Base').status_code == 422


def test_timeseries_endpoint_returns_n_points_and_timezone_header(admin_client):
    response = admin_client.get('/cabinet/admin/revenue-timeseries?days=5&tz=UTC')

    assert response.status_code == 200
    assert len(response.json()) == 5 and response.headers['X-Report-Timezone'] == 'UTC'


def test_overview_endpoint_exposes_timezone_and_fee_fields(admin_client):
    body = admin_client.get('/cabinet/admin/overview').json()

    assert body['timezone'] == 'Europe/Moscow'
    assert {'revenue_30d_gross_kopeks', 'fees_30d_kopeks', 'net_known_share_30d'} <= set(body)
```

- [ ] **Step 2: Убедиться, что падает**

Run: `python -m pytest tests/test_analytics_service.py -q -p no:warnings`
Expected: FAIL (`TypeError: get_overview() got an unexpected keyword argument 'tz'`).

- [ ] **Step 3: Зависимость `?tz=`**

Создайте `app/cabinet/report_tz.py`:

```python
"""FastAPI-зависимость ?tz= для аналитических эндпоинтов."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from fastapi import HTTPException, Query, status

from app.services.time_utils import get_report_tz


def report_tz(
    tz: str | None = Query(None, description='IANA-часовой пояс для границ дней (по умолчанию REPORT_TIMEZONE)'),
) -> ZoneInfo:
    try:
        return get_report_tz(tz)
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error
```

- [ ] **Step 4: Сервис аналитики — общие правки**

В `app/services/analytics_service.py`:

1. Импорты: замените `from datetime import date, datetime, timedelta, timezone` на то же (оставьте) и добавьте:
```python
from zoneinfo import ZoneInfo

from app.services.revenue import (
    NET_AMOUNT,
    PAID_AT,
    REVENUE_TYPES,
    revenue_select,
    revenue_sum,
    revenue_summary,
    window_conditions,
)
from app.services.time_utils import day_start_utc, get_report_tz, month_start_utc, report_date, report_days, window_start_utc
```
Уберите `from app.services.time_utils import business_day_start_utc` и строку `REVENUE_TYPES = ('subscription_payment', 'gift')` (теперь импортируется; `campaign_service` продолжит импортировать `REVENUE_TYPES` отсюда — имя в модуле сохраняется).

2. **Удалите** `_revenue_query` и `_revenue_sum` (и их длинные комментарии про 2026-09-16 перенесите одной строкой в docstring модуля: «выручка считается в app/services/revenue.py»). Оставьте `_NOT_BALANCE_FUNDED` (нужен счётчикам) и `_as_utc`.

3. Замените функции целиком:

```python
async def get_revenue_all_time(db: AsyncSession) -> int:
    return await revenue_sum(db)


async def get_revenue_this_month(db: AsyncSession, *, tz: ZoneInfo | None = None, now: datetime | None = None) -> int:
    """Календарный месяц в отчётном поясе (не скользящие 30 дней) — для честного сравнения
    с Remnawave currentMonthPayments в чистой прибыли."""
    tz = tz or get_report_tz()
    now = now or datetime.now(timezone.utc)
    return await revenue_sum(db, since=month_start_utc(now, tz))
```

4. `get_subscription_pulse`: сигнатура `(db, *, tz: ZoneInfo | None = None, now: datetime | None = None)`; первые строки тела:
```python
    tz = tz or get_report_tz()
    now = now or datetime.now(timezone.utc)
    today_start = day_start_utc(now, tz)
```
(вместо `now = datetime.now(timezone.utc)` и `today_start = business_day_start_utc(now)`).

5. `get_overview`: сигнатура `(db, *, tz: ZoneInfo | None = None, now: datetime | None = None)`. Замены внутри:

```python
# OLD
    now = datetime.now(timezone.utc)
    today_start = business_day_start_utc(now)

    revenue_today = await _revenue_sum(db, since=today_start)
    revenue_7d = await _revenue_sum(db, since=now - timedelta(days=7))
    revenue_30d = await _revenue_sum(db, since=now - timedelta(days=30))
    revenue_all_time = await _revenue_sum(db)
# NEW
    tz = tz or get_report_tz()
    now = now or datetime.now(timezone.utc)
    today_start = day_start_utc(now, tz)
    since_7d = window_start_utc(now, 7, tz)
    since_30d = window_start_utc(now, 30, tz)

    revenue_today = await revenue_sum(db, since=today_start)
    revenue_7d = await revenue_sum(db, since=since_7d)
    summary_30d = await revenue_summary(db, since=since_30d)
    revenue_30d = summary_30d['net_kopeks']
    revenue_all_time = await revenue_sum(db)
```
```python
# OLD  (new_users_7d)
        await db.execute(select(func.count(User.id)).where(User.created_at >= now - timedelta(days=7)))
# NEW
        await db.execute(select(func.count(User.id)).where(User.created_at >= since_7d))
```
```python
# OLD  (tx_count_30d и avg_check)
    tx_count_30d = (
        await db.execute(
            select(func.count(Transaction.id)).where(
                Transaction.type.in_(REVENUE_TYPES),
                Transaction.status == 'completed',
                Transaction.created_at >= now - timedelta(days=30),
                _NOT_BALANCE_FUNDED,
            )
        )
    ).scalar_one()
    avg_check_kopeks = round(revenue_30d / tx_count_30d) if tx_count_30d else 0
# NEW
    tx_count_30d = summary_30d['count']
    avg_check_kopeks = round(revenue_30d / tx_count_30d) if tx_count_30d else 0
```
В `new_paying_subscriptions_today` условие `Subscription.created_at >= today_start` не меняется. В возвращаемый словарь добавьте:
```python
        'revenue_30d_gross_kopeks': summary_30d['gross_kopeks'],
        'fees_30d_kopeks': summary_30d['fee_kopeks'],
        'net_known_share_30d': summary_30d['net_known_share'],
        'timezone': tz.key,
```
`_churn_percent(db, since=now - timedelta(days=30), until=now)` оставьте без изменений (это про подписки, не деньги).

6. Замените остальные функции целиком:

```python
async def get_revenue_timeseries(
    db: AsyncSession, *, days: int = 30, tz: ZoneInfo | None = None, now: datetime | None = None
) -> list[dict]:
    """Ровно `days` отчётных дней, последний — сегодняшний. Сумма точек за период равна
    карточке «за N дней» (окна выровнены по границам отчётных дней)."""
    tz = tz or get_report_tz()
    now = now or datetime.now(timezone.utc)
    since = window_start_utc(now, days, tz)
    result = await db.execute(revenue_select(PAID_AT, NET_AMOUNT).where(*window_conditions(since=since)))
    buckets: dict[date, dict] = defaultdict(lambda: {'revenue_kopeks': 0, 'count': 0})
    for paid_at, amount_kopeks in result.all():
        day = report_date(paid_at, tz)
        buckets[day]['revenue_kopeks'] += amount_kopeks
        buckets[day]['count'] += 1
    return [
        {'date': day.isoformat(), **buckets.get(day, {'revenue_kopeks': 0, 'count': 0})}
        for day in report_days(now, days, tz)
    ]


async def get_ltv(db: AsyncSession) -> dict:
    result = await db.execute(
        revenue_select(Transaction.user_id, func.sum(NET_AMOUNT)).group_by(Transaction.user_id)
    )
    per_user: dict[int, int] = {user_id: int(total) for user_id, total in result.all()}
    # ... дальше без изменений (total_users, arpu, медиана, top_payers) ...
```
(в `get_ltv` заменяется только запрос и `per_user`; остальная часть функции остаётся как есть.)

```python
def _month_key(dt: datetime, tz: ZoneInfo) -> tuple[int, int]:
    local = _as_utc(dt).astimezone(tz)
    return local.year, local.month
```
`get_cohorts(db, *, max_months: int = 6, tz: ZoneInfo | None = None)`: в начале `tz = tz or get_report_tz()`; `cohort_by_user = {user_id: _month_key(created_at, tz) …}`; запрос выручки:
```python
    tx_result = await db.execute(revenue_select(Transaction.user_id, PAID_AT, NET_AMOUNT))
    ...
    for user_id, paid_at, amount_kopeks in tx_result.all():
        ...
        offset = _month_offset(cohort, _month_key(paid_at, tz))
```
(остальное без изменений).

```python
async def get_recent_payments(db: AsyncSession, *, limit: int = 10) -> list[dict]:
    """Последние платежи: нетто-сумма и ВРЕМЯ ОПЛАТЫ (в поле created_at — имя сохранено для фронтенда)."""
    result = await db.execute(
        revenue_select(Transaction, NET_AMOUNT, PAID_AT).order_by(PAID_AT.desc()).limit(limit)
    )
    rows = result.all()
    if not rows:
        return []
    users_result = await db.execute(select(User).where(User.id.in_([t.user_id for t, _, _ in rows])))
    users_by_id = {u.id: u for u in users_result.scalars().all()}
    payments = []
    for t, net_kopeks, paid_at in rows:
        user = users_by_id.get(t.user_id)
        if user is None:
            continue
        payments.append(
            {
                'user_id': user.id, 'telegram_id': user.telegram_id, 'username': user.username,
                'full_name': user.full_name, 'amount_kopeks': net_kopeks, 'type': t.type, 'created_at': paid_at,
            }
        )
    return payments


async def get_revenue_by_type(db: AsyncSession, *, days: int = 30, tz: ZoneInfo | None = None, now: datetime | None = None) -> list[dict]:
    tz = tz or get_report_tz()
    now = now or datetime.now(timezone.utc)
    since = window_start_utc(now, days, tz)
    result = await db.execute(
        revenue_select(Transaction.type, func.coalesce(func.sum(NET_AMOUNT), 0))
        .where(*window_conditions(since=since))
        .group_by(Transaction.type)
    )
    by_type = dict(result.all())
    return [{'type': t, 'revenue_kopeks': int(by_type.get(t, 0))} for t in REVENUE_TYPES]


async def get_revenue_by_provider(db: AsyncSession, *, days: int = 30, tz: ZoneInfo | None = None, now: datetime | None = None) -> list[dict]:
    tz = tz or get_report_tz()
    now = now or datetime.now(timezone.utc)
    since = window_start_utc(now, days, tz)
    result = await db.execute(
        revenue_select(Payment.provider, func.coalesce(func.sum(NET_AMOUNT), 0))
        .where(*window_conditions(since=since))
        .group_by(Payment.provider)
        .order_by(func.sum(NET_AMOUNT).desc())
    )
    return [{'provider': provider, 'revenue_kopeks': int(revenue)} for provider, revenue in result.all()]


async def get_revenue_by_provider_timeseries(
    db: AsyncSession, *, days: int = 30, tz: ZoneInfo | None = None, now: datetime | None = None
) -> dict:
    tz = tz or get_report_tz()
    now = now or datetime.now(timezone.utc)
    since = window_start_utc(now, days, tz)
    result = await db.execute(revenue_select(PAID_AT, Payment.provider, NET_AMOUNT).where(*window_conditions(since=since)))
    buckets: dict[date, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    providers_seen: set[str] = set()
    for paid_at, provider, amount_kopeks in result.all():
        buckets[report_date(paid_at, tz)][provider] += amount_kopeks
        providers_seen.add(provider)
    day_objects = report_days(now, days, tz)
    series = [
        {'provider': provider, 'values': [buckets.get(day, {}).get(provider, 0) for day in day_objects]}
        for provider in sorted(providers_seen)
    ]
    return {'days': [day.isoformat() for day in day_objects], 'series': series}


async def get_revenue_by_weekday(db: AsyncSession, *, days: int = 90, tz: ZoneInfo | None = None, now: datetime | None = None) -> list[dict]:
    tz = tz or get_report_tz()
    now = now or datetime.now(timezone.utc)
    since = window_start_utc(now, days, tz)
    result = await db.execute(revenue_select(PAID_AT, NET_AMOUNT).where(*window_conditions(since=since)))
    buckets = [0] * 7  # 0 = понедельник
    for paid_at, amount_kopeks in result.all():
        buckets[report_date(paid_at, tz).weekday()] += amount_kopeks
    return [{'weekday': i, 'revenue_kopeks': buckets[i]} for i in range(7)]
```

- [ ] **Step 5: Схемы и маршруты**

`app/cabinet/admin_schemas.py`: в `OverviewResponse` добавьте поля (после существующих, все с умолчаниями — аддитивно):
```python
    revenue_30d_gross_kopeks: int = 0
    fees_30d_kopeks: int = 0
    net_known_share_30d: float = 1.0
    timezone: str = ''
```
и `timezone: str = ''` в `SalesBreakdownResponse`, `RevenueCompositionResponse`, `SubscriptionPulseOut`, `LtvResponse`, `CohortsResponse`.

`app/cabinet/admin_routes.py`: импорты `from zoneinfo import ZoneInfo`, `from fastapi import Response` (если нет), `from app.cabinet.report_tz import report_tz`. Замените обработчики (декораторы и `response_model` сохраните):

```python
async def overview(db: AsyncSession = Depends(get_db), tz: ZoneInfo = Depends(report_tz), _admin: User = Depends(require_admin)) -> dict:
    return await analytics_service.get_overview(db, tz=tz)


async def revenue_timeseries(
    response: Response, days: int = Query(30, ge=1, le=800), db: AsyncSession = Depends(get_db),
    tz: ZoneInfo = Depends(report_tz), _admin: User = Depends(require_admin),
) -> list[dict]:
    response.headers['X-Report-Timezone'] = tz.key
    return await analytics_service.get_revenue_timeseries(db, days=days, tz=tz)


async def recent_payments(
    response: Response, limit: int = Query(10, ge=1, le=50), db: AsyncSession = Depends(get_db),
    tz: ZoneInfo = Depends(report_tz), _admin: User = Depends(require_admin),
) -> list[dict]:
    response.headers['X-Report-Timezone'] = tz.key
    return await analytics_service.get_recent_payments(db, limit=limit)


async def sales_breakdown(db: AsyncSession = Depends(get_db), tz: ZoneInfo = Depends(report_tz), _admin: User = Depends(require_admin)) -> dict:
    return {
        'by_type': await analytics_service.get_revenue_by_type(db, tz=tz),
        'by_provider': await analytics_service.get_revenue_by_provider(db, tz=tz),
        'by_weekday': await analytics_service.get_revenue_by_weekday(db, tz=tz),
        'active_subs_by_tariff': await analytics_service.get_active_subscriptions_by_tariff(db),
        'timezone': tz.key,
    }


async def revenue_composition(
    days: int = Query(30, ge=1, le=90), db: AsyncSession = Depends(get_db),
    tz: ZoneInfo = Depends(report_tz), _admin: User = Depends(require_admin),
) -> dict:
    return {**await analytics_service.get_revenue_by_provider_timeseries(db, days=days, tz=tz), 'timezone': tz.key}


async def subscription_pulse(db: AsyncSession = Depends(get_db), tz: ZoneInfo = Depends(report_tz), _admin: User = Depends(require_admin)) -> dict:
    return await analytics_service.get_subscription_pulse(db, tz=tz)
```
`net_profit`: добавьте `tz: ZoneInfo = Depends(report_tz)` и `revenue_this_month = float(await analytics_service.get_revenue_this_month(db, tz=tz)) / 100`. `ltv`/`cohorts`: добавьте `tz` (для `cohorts` передайте `tz=tz`) и `'timezone': tz.key` в возвращаемый словарь (`{**await …, 'timezone': tz.key}`). `get_overview` уже кладёт `timezone` сам; `get_subscription_pulse` — нет: для `subscription_pulse` верните `{**await …, 'timezone': tz.key}`.

- [ ] **Step 6: Тесты проходят**

Run: `python -m pytest tests -q -p no:warnings`
Expected: PASS. Если старые тесты (`tests/test_pricing.py` и др.) не затронуты — они должны проходить без правок.

- [ ] **Step 7: Мутации**

По одной, каждая роняет тест, затем откат: в `get_overview` заменить `window_start_utc(now, 7, tz)` на `now - timedelta(days=7)`; в `get_revenue_timeseries` заменить `report_date(paid_at, tz)` на `_as_utc(paid_at).date()`; в `revenue_select` убрать `Payment.status != 'refunded'`.

- [ ] **Step 8: Коммит**

```bash
git add app/cabinet/report_tz.py app/services/analytics_service.py app/cabinet/admin_schemas.py app/cabinet/admin_routes.py tests/test_analytics_service.py
git commit -m "Переводит аналитику на единый расчёт выручки и отчётный пояс (нетто, paid_at, ?tz=)

Поведение: выручка нетто (ниже брутто на комиссию), границы суток по REPORT_TIMEZONE,
revenue-timeseries(days=N) возвращает ровно N точек."
```

### Task 9: Сверка с cisPay и обнаружение возвратов

**Files:**
- Modify: `app/services/time_utils.py` (добавить `day_bounds_utc`), `app/services/payment/cispay.py`, `app/services/background.py`, `main.py`, `app/cabinet/app.py`
- Create: `app/services/analytics/__init__.py` (пустой), `app/services/analytics/reconcile.py`, `app/cabinet/analytics_schemas.py`, `app/cabinet/analytics_routes.py`
- Test: `tests/test_reconcile.py`

**Interfaces:**
- Consumes: `revenue_select`, `NET_AMOUNT`, `GROSS_AMOUNT`, `PAID_AT`, `window_conditions` (Task 3); `record_event` (Task 5); `parse_provider_datetime` (Task 4); `report_tz` (Task 8).
- Produces:
  - `time_utils.day_bounds_utc(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]` — `[начало дня, начало следующего дня)` в UTC.
  - `CisPayProvider.list_transactions(*, status: str | None = None, limit: int = 100, offset: int = 0) -> dict` (ответ cisPay: `{items, limit, offset, has_more}`) и `CisPayProvider.iter_transactions(*, status=None, max_pages=100)` — async-генератор элементов, сначала новые.
  - `reconcile.normalize_item(item: dict) -> dict | None` → `{external_id, status, charged_kopeks, net_kopeks, paid_at, created_at}`.
  - `reconcile.reconcile_cispay_day(db, provider, *, day: date, tz: ZoneInfo, max_pages: int = 100) -> dict` (структура ниже).
  - `reconcile.apply_cispay_refunds(db, provider, *, now: datetime | None = None, max_pages: int = 100) -> list[int]` — id платежей, переведённых в `refunded`. Коммит — на вызывающем.
  - `background.run_cispay_refund_check_once() -> list[int]`, `background.cispay_refund_loop(interval_seconds: int = 86400)`.
  - HTTP: `GET /cabinet/admin/analytics/reconcile/cispay?date=YYYY-MM-DD&tz=` и `POST /cabinet/admin/analytics/reconcile/cispay/refunds`.

Форма ответа `reconcile_cispay_day`:
```json
{
  "date": "2026-09-21", "timezone": "Europe/Moscow",
  "cispay": {"count": 2, "charged_kopeks": 34900, "net_kopeks": 33904},
  "ours":   {"count": 2, "charged_kopeks": 34900, "net_kopeks": 33904},
  "diff":   {"count": 0, "charged_kopeks": 0, "net_kopeks": 0},
  "missing_in_ours":   [{"external_id": "…", "charged_kopeks": 100, "net_kopeks": 96, "paid_at": "2026-09-21T05:00:00+00:00"}],
  "missing_in_cispay": [],
  "amount_mismatch":   [{"external_id": "…", "ours_net_kopeks": 1, "cispay_net_kopeks": 2, "ours_charged_kopeks": 1, "cispay_charged_kopeks": 2}]
}
```
`diff` = ours − cispay. Поля элементов cisPay `/transactions` (по их OpenAPI, `MerchantTransactionItem`): `id`, `status` (`PENDING|PAID|FAILED|EXPIRED|REFUNDED`), `amount`, `charged_amount`, `merchant_revenue`, `created_at`, `paid_at` (UTC). **Сверьтесь** с `https://api.cispay.app/openapi.json` (схема `MerchantTransactionItem`) до начала: если имя поля идентификатора отличается от `id`, поправьте только `normalize_item`.

- [ ] **Step 1: Падающие тесты**

Создайте `tests/test_reconcile.py`:

```python
"""Сверка с cisPay и возвраты."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.cabinet.admin_deps import require_admin
from app.cabinet.app import create_app
from app.cabinet.deps import get_db
from app.config import settings
from app.database.models import AnalyticsEvent, Payment, Transaction, User
from app.services import background
from app.services.analytics.reconcile import apply_cispay_refunds, normalize_item, reconcile_cispay_day
from app.services.payment.cispay import CisPayProvider
from app.services.revenue import revenue_sum
from app.services.time_utils import day_bounds_utc, get_report_tz
from tests.helpers import make_paid_payment, make_user

MSK = get_report_tz('Europe/Moscow')
UTC_TZ = get_report_tz('UTC')


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat().replace('+00:00', 'Z')


def item(external_id: str, *, status='PAID', charged=24900, net=23904, paid_at=None, created_at=None) -> dict:
    return {
        'id': external_id, 'status': status, 'amount': charged, 'charged_amount': charged, 'merchant_revenue': net,
        'created_at': iso(created_at or (paid_at or utc(2026, 9, 21, 5, 0))), 'paid_at': iso(paid_at) if paid_at else None,
    }


class FakeCisPay:
    """Ведёт себя как CisPayProvider.iter_transactions: сначала новые, фильтр по status."""

    def __init__(self, items: list[dict]) -> None:
        self.items = items

    async def iter_transactions(self, *, status=None, max_pages=100):
        for entry in self.items:
            if status is None or entry['status'] == status:
                yield entry


async def _payment(factory, user_id, external_id, **fields) -> int:
    payment_id = await make_paid_payment(factory, user_id, **fields)
    async with factory() as db:
        payment = await db.get(Payment, payment_id)
        payment.external_id = external_id
        await db.commit()
    return payment_id


def _reconcile(factory, provider, day=date(2026, 9, 21), tz=MSK):
    async def scenario():
        async with factory() as db:
            return await reconcile_cispay_day(db, provider, day=day, tz=tz)

    return asyncio.run(scenario())


def test_day_bounds_in_report_timezone():
    assert day_bounds_utc(date(2026, 9, 21), MSK) == (utc(2026, 9, 20, 21, 0), utc(2026, 9, 21, 21, 0))


def test_normalize_item():
    normalized = normalize_item(item('abc', paid_at=utc(2026, 9, 21, 5, 0)))

    assert normalized == {
        'external_id': 'abc', 'status': 'PAID', 'charged_kopeks': 24900, 'net_kopeks': 23904,
        'paid_at': utc(2026, 9, 21, 5, 0), 'created_at': utc(2026, 9, 21, 5, 0),
    }
    assert normalize_item({'status': 'PAID'}) is None  # без id


def test_matching_day_has_no_differences(session_factory):
    async def seed():
        user = await make_user(session_factory)
        await _payment(session_factory, user, 'a', amount=24900, net=23904, gross=24900, paid_at=utc(2026, 9, 21, 5, 0))
        await _payment(session_factory, user, 'b', amount=10000, net=9600, gross=10000, paid_at=utc(2026, 9, 21, 7, 0))

    asyncio.run(seed())
    provider = FakeCisPay([
        item('b', charged=10000, net=9600, paid_at=utc(2026, 9, 21, 7, 0)),
        item('a', paid_at=utc(2026, 9, 21, 5, 0)),
    ])

    result = _reconcile(session_factory, provider)

    assert result['cispay'] == {'count': 2, 'charged_kopeks': 34900, 'net_kopeks': 33504}
    assert result['ours'] == result['cispay'] and result['diff'] == {'count': 0, 'charged_kopeks': 0, 'net_kopeks': 0}
    assert result['missing_in_ours'] == [] and result['missing_in_cispay'] == [] and result['amount_mismatch'] == []
    assert (result['date'], result['timezone']) == ('2026-09-21', 'Europe/Moscow')


def test_payment_known_only_to_one_side_is_listed(session_factory):
    async def seed():
        user = await make_user(session_factory)
        await _payment(session_factory, user, 'ours-only', amount=5000, net=4800, gross=5000, paid_at=utc(2026, 9, 21, 5, 0))

    asyncio.run(seed())
    provider = FakeCisPay([item('cispay-only', charged=7000, net=6720, paid_at=utc(2026, 9, 21, 6, 0))])

    result = _reconcile(session_factory, provider)

    assert [row['external_id'] for row in result['missing_in_ours']] == ['cispay-only']
    assert result['missing_in_ours'][0]['net_kopeks'] == 6720
    assert [row['external_id'] for row in result['missing_in_cispay']] == ['ours-only']
    assert result['diff'] == {'count': 0, 'charged_kopeks': -2000, 'net_kopeks': -1920}


def test_amount_mismatch_is_reported(session_factory):
    async def seed():
        user = await make_user(session_factory)
        await _payment(session_factory, user, 'x', amount=24900, net=23000, gross=24900, paid_at=utc(2026, 9, 21, 5, 0))

    asyncio.run(seed())
    provider = FakeCisPay([item('x', charged=24900, net=23904, paid_at=utc(2026, 9, 21, 5, 0))])

    (mismatch,) = _reconcile(session_factory, provider)['amount_mismatch']

    assert mismatch == {
        'external_id': 'x', 'ours_net_kopeks': 23000, 'cispay_net_kopeks': 23904,
        'ours_charged_kopeks': 24900, 'cispay_charged_kopeks': 24900,
    }


def test_day_boundary_follows_requested_timezone(session_factory):
    async def seed():
        user = await make_user(session_factory)
        await _payment(session_factory, user, 'late', amount=1000, net=960, gross=1000, paid_at=utc(2026, 9, 20, 21, 30))

    asyncio.run(seed())
    provider = FakeCisPay([item('late', charged=1000, net=960, paid_at=utc(2026, 9, 20, 21, 30))])

    assert _reconcile(session_factory, provider, day=date(2026, 9, 21), tz=MSK)['cispay']['count'] == 1  # 00:30 МСК 21-го
    assert _reconcile(session_factory, provider, day=date(2026, 9, 21), tz=UTC_TZ)['cispay']['count'] == 0  # по UTC это 20-е


def test_only_paid_items_inside_the_window_count_and_scan_stops_at_old_items(session_factory):
    provider = FakeCisPay([
        item('new', paid_at=utc(2026, 9, 21, 5, 0)),
        item('pending', status='PENDING', paid_at=None, created_at=utc(2026, 9, 21, 4, 0)),
        item('too-old', paid_at=utc(2026, 9, 1, 5, 0)),  # создан за много дней до окна -> дальше список не читаем
        item('after-old', paid_at=utc(2026, 9, 21, 6, 0)),
    ])

    result = _reconcile(session_factory, provider)

    assert [row['external_id'] for row in result['missing_in_ours']] == ['new']


# --- возвраты ------------------------------------------------------------------


def test_refund_marks_payment_excludes_revenue_and_is_idempotent(session_factory):
    async def scenario():
        user = await make_user(session_factory)
        refunded_id = await _payment(session_factory, user, 'r1', amount=24900, net=23904, gross=24900, paid_at=utc(2026, 9, 21, 5, 0))
        await _payment(session_factory, user, 'keep', amount=10000, net=9600, gross=10000, paid_at=utc(2026, 9, 21, 6, 0))
        provider = FakeCisPay([
            item('r1', status='REFUNDED', paid_at=utc(2026, 9, 21, 5, 0)),
            item('unknown', status='REFUNDED', paid_at=utc(2026, 9, 21, 5, 0)),  # у нас такого платежа нет
        ])
        now = utc(2026, 9, 22, 8, 0)

        async with session_factory() as db:
            first = await apply_cispay_refunds(db, provider, now=now)
            await db.commit()
        async with session_factory() as db:
            second = await apply_cispay_refunds(db, provider, now=now)
            await db.commit()

        assert first == [refunded_id] and second == []
        async with session_factory() as db:
            payment = await db.get(Payment, refunded_id)
            assert payment.status == 'refunded' and payment.refunded_at.replace(tzinfo=timezone.utc) == now
            assert (await db.get(Transaction, payment.transaction_id)).status == 'refunded'
            assert await revenue_sum(db) == 9600  # возвращённый платёж ушёл из выручки
            (event,) = (await db.execute(select(AnalyticsEvent).where(AnalyticsEvent.type == 'payment_refunded'))).scalars().all()
            assert (event.payment_id, event.amount_kopeks, event.dedupe_key) == (refunded_id, 23904, f'payment:{refunded_id}:refunded')

    asyncio.run(scenario())


# --- провайдер: пагинация ------------------------------------------------------


def test_iter_transactions_follows_pagination(monkeypatch):
    pages = {0: {'items': [{'id': '1'}, {'id': '2'}], 'has_more': True}, 100: {'items': [{'id': '3'}], 'has_more': False}}
    calls = []

    async def fake_list(self, *, status=None, limit=100, offset=0):
        calls.append((status, offset))
        return pages[offset]

    monkeypatch.setattr(CisPayProvider, 'list_transactions', fake_list)

    async def collect():
        return [entry['id'] async for entry in CisPayProvider().iter_transactions(status='PAID')]

    assert asyncio.run(collect()) == ['1', '2', '3']
    assert calls == [('PAID', 0), ('PAID', 100)]


def test_iter_transactions_respects_max_pages(monkeypatch):
    async def endless(self, *, status=None, limit=100, offset=0):
        return {'items': [{'id': str(offset)}], 'has_more': True}

    monkeypatch.setattr(CisPayProvider, 'list_transactions', endless)

    async def collect():
        return [entry['id'] async for entry in CisPayProvider().iter_transactions(max_pages=3)]

    assert asyncio.run(collect()) == ['0', '100', '200']


# --- фоновая проверка возвратов ------------------------------------------------


def test_background_refund_check(session_factory, monkeypatch):
    monkeypatch.setattr(background, 'AsyncSessionLocal', session_factory)
    monkeypatch.setattr('app.services.payment.get_payment_provider', lambda name: FakeCisPay([item('r1', status='REFUNDED', paid_at=utc(2026, 9, 21, 5, 0))]))

    async def scenario():
        user = await make_user(session_factory)
        payment_id = await _payment(session_factory, user, 'r1', amount=24900, net=23904, gross=24900, paid_at=utc(2026, 9, 21, 5, 0))
        assert await background.run_cispay_refund_check_once() == [payment_id]
        assert await background.run_cispay_refund_check_once() == []

    asyncio.run(scenario())


# --- HTTP ----------------------------------------------------------------------


@pytest.fixture
def admin_client(session_factory):
    engine = create_async_engine(str(session_factory.kw['bind'].url), connect_args={'timeout': 30})
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with factory() as session:
            yield session

    app = create_app(AsyncMock())
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_admin] = lambda: User(id=1, telegram_id=1, referral_code='a', is_admin=True)
    with TestClient(app) as client:
        yield client


def test_reconcile_endpoint_requires_configured_cispay(admin_client, monkeypatch):
    monkeypatch.setattr(settings, 'PAYMENTS_MODE', 'stub')

    assert admin_client.get('/cabinet/admin/analytics/reconcile/cispay?date=2026-09-21').status_code == 409


def test_reconcile_endpoint_returns_report(admin_client, session_factory, monkeypatch):
    monkeypatch.setattr(settings, 'PAYMENTS_MODE', 'real')
    monkeypatch.setattr(settings, 'CISPAY_API_KEY', 'k')
    monkeypatch.setattr('app.cabinet.analytics_routes.get_payment_provider', lambda name: FakeCisPay([item('only', paid_at=utc(2026, 9, 21, 5, 0))]))

    response = admin_client.get('/cabinet/admin/analytics/reconcile/cispay?date=2026-09-21&tz=Europe/Moscow')

    assert response.status_code == 200
    body = response.json()
    assert body['timezone'] == 'Europe/Moscow' and body['cispay']['count'] == 1 and body['missing_in_ours'][0]['external_id'] == 'only'


def test_reconcile_endpoint_validates_input(admin_client, monkeypatch):
    monkeypatch.setattr(settings, 'PAYMENTS_MODE', 'real')
    monkeypatch.setattr(settings, 'CISPAY_API_KEY', 'k')

    assert admin_client.get('/cabinet/admin/analytics/reconcile/cispay?date=2026-09-21&tz=Mars/Base').status_code == 422
    assert admin_client.get('/cabinet/admin/analytics/reconcile/cispay?date=not-a-date').status_code == 422


def test_refund_endpoint_applies_refunds(admin_client, session_factory, monkeypatch):
    monkeypatch.setattr(settings, 'PAYMENTS_MODE', 'real')
    monkeypatch.setattr(settings, 'CISPAY_API_KEY', 'k')
    monkeypatch.setattr('app.cabinet.analytics_routes.get_payment_provider', lambda name: FakeCisPay([item('r1', status='REFUNDED', paid_at=utc(2026, 9, 21, 5, 0))]))

    async def seed():
        user = await make_user(session_factory)
        return await _payment(session_factory, user, 'r1', amount=24900, net=23904, gross=24900, paid_at=utc(2026, 9, 21, 5, 0))

    payment_id = asyncio.run(seed())

    response = admin_client.post('/cabinet/admin/analytics/reconcile/cispay/refunds')

    assert response.status_code == 200 and response.json() == {'refunded_payment_ids': [payment_id]}
```

- [ ] **Step 2: Убедиться, что падает**

Run: `python -m pytest tests/test_reconcile.py -q -p no:warnings`
Expected: FAIL (`ImportError: day_bounds_utc` / нет модуля `app.services.analytics.reconcile`).

- [ ] **Step 3: `time_utils.day_bounds_utc`**

Добавьте в `app/services/time_utils.py`:

```python
def day_bounds_utc(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """[начало дня, начало следующего дня) отчётного дня `day` в UTC."""
    return _local_midnight_utc(day, tz), _local_midnight_utc(day + timedelta(days=1), tz)
```

- [ ] **Step 4: Провайдер cisPay**

В `app/services/payment/cispay.py` внутри класса `CisPayProvider` (рядом с `check_payment_status`) добавьте:

```python
    async def list_transactions(self, *, status: str | None = None, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        """GET /transactions — транзакции магазина, сначала новые (limit <= 100)."""
        params: dict[str, Any] = {'limit': limit, 'offset': offset}
        if status:
            params['status'] = status
        return await self._request('GET', '/transactions', params=params)

    async def iter_transactions(self, *, status: str | None = None, max_pages: int = 100):
        """Асинхронно отдаёт транзакции постранично (по 100), сначала новые."""
        for page in range(max_pages):
            data = await self.list_transactions(status=status, offset=page * 100)
            for entry in data.get('items') or []:
                yield entry
            if not data.get('has_more'):
                return
        logger.warning('cisPay iter_transactions: достигнут лимит в %s страниц, список может быть неполным', max_pages)
```

- [ ] **Step 5: Сервис сверки и возвратов**

Создайте пустой `app/services/analytics/__init__.py` и `app/services/analytics/reconcile.py`:

```python
"""Сверка нашей выручки с кабинетом cisPay и обнаружение возвратов (REFUNDED).

cisPay отдаёт `GET /transactions` (сначала новые, без фильтра по датам), поэтому день собирается
обходом списка с остановкой, когда создание транзакции ушло за окно + MAX_PAY_LAG.
"""

from __future__ import annotations

import logging
from contextlib import aclosing
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Payment, Transaction
from app.services.analytics_events import record_event
from app.services.payment_amounts import parse_provider_datetime
from app.services.revenue import GROSS_AMOUNT, NET_AMOUNT, PAID_AT, revenue_select, window_conditions
from app.services.time_utils import day_bounds_utc

logger = logging.getLogger(__name__)

# Платёж оплачивают не позже, чем через MAX_PAY_LAG после создания (срок жизни ссылки).
MAX_PAY_LAG = timedelta(days=2)


def _int(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def normalize_item(entry: dict) -> dict | None:
    external_id = str(entry.get('id') or '').strip()
    if not external_id:
        return None
    charged = _int(entry.get('charged_amount'))
    if charged is None:
        charged = _int(entry.get('amount')) or 0
    net = _int(entry.get('merchant_revenue'))
    return {
        'external_id': external_id,
        'status': str(entry.get('status') or '').upper(),
        'charged_kopeks': charged,
        'net_kopeks': net if net is not None else charged,
        'paid_at': parse_provider_datetime(entry.get('paid_at')),
        'created_at': parse_provider_datetime(entry.get('created_at')),
    }


def _totals(rows) -> dict:
    rows = list(rows)
    return {
        'count': len(rows),
        'charged_kopeks': sum(r['charged_kopeks'] for r in rows),
        'net_kopeks': sum(r['net_kopeks'] for r in rows),
    }


def _listing(row: dict) -> dict:
    paid_at = row.get('paid_at')
    return {
        'external_id': row['external_id'],
        'charged_kopeks': row['charged_kopeks'],
        'net_kopeks': row['net_kopeks'],
        'paid_at': paid_at.isoformat() if paid_at is not None else None,
    }


async def _collect_cispay_paid(provider, *, since: datetime, until: datetime, max_pages: int) -> dict[str, dict]:
    found: dict[str, dict] = {}
    async with aclosing(provider.iter_transactions(max_pages=max_pages)) as stream:
        async for entry in stream:
            row = normalize_item(entry)
            if row is None:
                continue
            created_at = row['created_at']
            if created_at is not None and created_at < since - MAX_PAY_LAG:
                break  # список «сначала новые» — дальше только более старые
            if row['status'] == 'PAID' and row['paid_at'] is not None and since <= row['paid_at'] < until:
                found[row['external_id']] = row
    return found


async def reconcile_cispay_day(db: AsyncSession, provider, *, day: date, tz: ZoneInfo, max_pages: int = 100) -> dict:
    since, until = day_bounds_utc(day, tz)
    remote = await _collect_cispay_paid(provider, since=since, until=until, max_pages=max_pages)

    result = await db.execute(
        revenue_select(Payment.external_id, NET_AMOUNT, GROSS_AMOUNT, PAID_AT)
        .where(Payment.provider == 'cispay', *window_conditions(since, until))
    )
    ours: dict[str, dict] = {}
    for external_id, net, gross, paid_at in result.all():
        ours[external_id] = {'external_id': external_id, 'net_kopeks': int(net), 'charged_kopeks': int(gross), 'paid_at': paid_at}

    mismatches = []
    for external_id in sorted(set(ours) & set(remote)):
        mine, theirs = ours[external_id], remote[external_id]
        if mine['net_kopeks'] != theirs['net_kopeks'] or mine['charged_kopeks'] != theirs['charged_kopeks']:
            mismatches.append(
                {
                    'external_id': external_id,
                    'ours_net_kopeks': mine['net_kopeks'],
                    'cispay_net_kopeks': theirs['net_kopeks'],
                    'ours_charged_kopeks': mine['charged_kopeks'],
                    'cispay_charged_kopeks': theirs['charged_kopeks'],
                }
            )

    ours_totals, remote_totals = _totals(ours.values()), _totals(remote.values())
    return {
        'date': day.isoformat(),
        'timezone': tz.key,
        'cispay': remote_totals,
        'ours': ours_totals,
        'diff': {key: ours_totals[key] - remote_totals[key] for key in ours_totals},
        'missing_in_ours': [_listing(remote[k]) for k in sorted(set(remote) - set(ours))],
        'missing_in_cispay': [_listing(ours[k]) for k in sorted(set(ours) - set(remote))],
        'amount_mismatch': mismatches,
    }


async def apply_cispay_refunds(db: AsyncSession, provider, *, now: datetime | None = None, max_pages: int = 100) -> list[int]:
    """Платежи, у которых cisPay показывает REFUNDED, а у нас ещё success, -> refunded.
    Возврат считается полным. Идемпотентна. Коммит — на вызывающем."""
    now = now or datetime.now(timezone.utc)
    refunded: list[int] = []
    async with aclosing(provider.iter_transactions(status='REFUNDED', max_pages=max_pages)) as stream:
        async for entry in stream:
            row = normalize_item(entry)
            if row is None or row['status'] != 'REFUNDED':
                continue
            payment = (
                await db.execute(
                    select(Payment).where(
                        Payment.provider == 'cispay', Payment.external_id == row['external_id'], Payment.status == 'success'
                    )
                )
            ).scalar_one_or_none()
            if payment is None:
                continue
            net = payment.merchant_revenue_kopeks if payment.merchant_revenue_kopeks is not None else payment.amount_kopeks
            payment.status = 'refunded'
            payment.refunded_at = now
            if payment.transaction_id is not None:
                transaction = await db.get(Transaction, payment.transaction_id)
                if transaction is not None:
                    transaction.status = 'refunded'
            await record_event(
                db, 'payment_refunded', dedupe_key=f'payment:{payment.id}:refunded', user_id=payment.user_id,
                payment_id=payment.id, amount_kopeks=net, occurred_at=now,
            )
            refunded.append(payment.id)
    await db.flush()
    return refunded
```

- [ ] **Step 6: Схемы и маршруты**

Создайте `app/cabinet/analytics_schemas.py`:

```python
from __future__ import annotations

from pydantic import BaseModel


class ReconcileTotals(BaseModel):
    count: int
    charged_kopeks: int
    net_kopeks: int


class ReconcileItem(BaseModel):
    external_id: str
    charged_kopeks: int
    net_kopeks: int
    paid_at: str | None = None


class ReconcileMismatch(BaseModel):
    external_id: str
    ours_net_kopeks: int
    cispay_net_kopeks: int
    ours_charged_kopeks: int
    cispay_charged_kopeks: int


class CispayReconcileResponse(BaseModel):
    date: str
    timezone: str
    cispay: ReconcileTotals
    ours: ReconcileTotals
    diff: ReconcileTotals
    missing_in_ours: list[ReconcileItem]
    missing_in_cispay: list[ReconcileItem]
    amount_mismatch: list[ReconcileMismatch]


class RefundsResponse(BaseModel):
    refunded_payment_ids: list[int]
```

Создайте `app/cabinet/analytics_routes.py`:

```python
"""/cabinet/admin/analytics/* — аналитика центра аналитики (только чтение, кроме явного запуска возвратов)."""

from __future__ import annotations

from datetime import date as date_type
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.cabinet.admin_deps import require_admin
from app.cabinet.analytics_schemas import CispayReconcileResponse, RefundsResponse
from app.cabinet.deps import get_db
from app.cabinet.report_tz import report_tz
from app.config import settings
from app.database.models import User
from app.services.analytics.reconcile import apply_cispay_refunds, reconcile_cispay_day
from app.services.payment import get_payment_provider

router = APIRouter(prefix='/cabinet/admin/analytics')


def _cispay_provider():
    if settings.PAYMENTS_MODE != 'real' or not settings.CISPAY_API_KEY:
        raise HTTPException(status.HTTP_409_CONFLICT, 'cisPay не настроен (нужны PAYMENTS_MODE=real и ключи cisPay)')
    return get_payment_provider('cispay')


@router.get('/reconcile/cispay', response_model=CispayReconcileResponse)
async def reconcile_cispay(
    day: date_type = Query(..., alias='date', description='Отчётный день YYYY-MM-DD'),
    tz: ZoneInfo = Depends(report_tz),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> dict:
    provider = _cispay_provider()
    try:
        return await reconcile_cispay_day(db, provider, day=day, tz=tz)
    except RuntimeError as error:  # cisPay недоступна / вернула ошибку
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from error


@router.post('/reconcile/cispay/refunds', response_model=RefundsResponse)
async def apply_refunds(db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)) -> dict:
    """Обнаруживает возвраты cisPay и переводит платежи в refunded (то же делает суточная фоновая задача)."""
    provider = _cispay_provider()
    try:
        refunded = await apply_cispay_refunds(db, provider)
    except RuntimeError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from error
    await db.commit()
    return {'refunded_payment_ids': refunded}
```

В `app/cabinet/app.py`: импорт `from app.cabinet.analytics_routes import router as analytics_router` и после `app.include_router(admin_router)` добавьте `app.include_router(analytics_router)`.

- [ ] **Step 7: Фоновая проверка возвратов**

В `app/services/background.py` добавьте (рядом с другими `*_loop`; `log`, `logger`, `AsyncSessionLocal`, `asyncio` уже есть в модуле):

```python
async def run_cispay_refund_check_once() -> list[int]:
    """Раз в сутки: возвраты cisPay -> refunded (выручка и события обновляются)."""
    from app.services.analytics.reconcile import apply_cispay_refunds
    from app.services.payment import get_payment_provider

    provider = get_payment_provider('cispay')
    async with AsyncSessionLocal() as db:
        refunded = await apply_cispay_refunds(db, provider)
        await db.commit()
    if refunded:
        log.warning('cispay_refunds_applied', payment_ids=refunded)
    return refunded


async def cispay_refund_loop(interval_seconds: int = 86400) -> None:
    while True:
        try:
            await run_cispay_refund_check_once()
        except Exception:
            logger.exception('cispay_refund_loop: сбой на итерации, продолжаем')
        await asyncio.sleep(interval_seconds)
```

В `main.py`: добавьте `cispay_refund_loop,` в импорт `from app.services.background import (…)` и перед блоком `if settings.BULK_NOTIFICATIONS_ENABLED:` вставьте:

```python
    if settings.PAYMENTS_MODE == 'real' and settings.CISPAY_API_KEY:
        background_tasks['cispay_refunds'] = asyncio.create_task(cispay_refund_loop(), name='cispay_refunds')
```

- [ ] **Step 8: Тесты проходят**

Run: `python -m pytest tests -q -p no:warnings`
Expected: PASS. Проверка импорта: `python -c "import os;os.environ['BOT_TOKEN']='1:t'; import main"`.

- [ ] **Step 9: Мутации**

Каждая роняет тест, затем откат: убрать `Payment.status == 'success'` из выборки в `apply_cispay_refunds` (повтор вернёт id второй раз); заменить `break` на `continue` в `_collect_cispay_paid`; убрать проверку `since <= row['paid_at'] < until`.

- [ ] **Step 10: Коммит**

```bash
git add app tests/test_reconcile.py main.py
git commit -m "Добавляет сверку дня с cisPay и обнаружение возвратов (эндпоинты и суточная задача)"
```

---

### Task 10: Backfill истории и `data_quality`

**Files:**
- Create: `app/services/analytics/backfill.py`, `scripts/backfill_analytics_events.py`
- Test: `tests/test_backfill.py`

**Interfaces:**
- Consumes: `record_*` (Task 5), `apply_provider_details` (Task 4), `expired_dedupe_key`.
- Produces:
  - `async backfill_events(db) -> dict[str, int]` — число ВСТАВЛЕННЫХ событий по типам плюс `payments_paid_at` (сколько платежей получили `paid_at`); без коммита.
  - `async run_backfill(session_factory, *, dry_run: bool = False) -> dict[str, int]` — открывает сессию, вызывает `backfill_events`, коммитит или откатывает.
  - `async data_quality(db) -> dict` — `{'exact_since': str | None, 'backfill_share': float}`; `exact_since` — ISO-время самого раннего `live`-события.
  - CLI: `python scripts/backfill_analytics_events.py [--dry-run]`.

Правила восстановления (источники → события; все с `source='backfill'`, ключи те же, что у live-событий, поэтому повтор и пересечение с live не дают дублей):
- `Payment.paid_at` (для `success`/`refunded` без него): из `provider_raw_response['paid_at']`, иначе `Transaction.created_at`, иначе `Payment.created_at`; суммы cisPay — из `provider_raw_response`.
- `user_registered` — `User.created_at` (+ `campaign_id` из `CampaignRegistration`); `trial_started` — для `trial_used`, время `User.created_at` (приближение).
- Покупки подписки (`Transaction.type='subscription_payment'`, статусы `completed|refunded`, `Payment.status in success|refunded`) по порядку `(время оплаты, id)` на пользователя → `subscription_first_paid`/`subscription_renewed`; `days` — из описания транзакции (`… на N дн.`); тариф неизвестен (`NULL`).
- `subscription_expired` — подписки `expired`, время `end_date`; `promocode_activated` + `bonus_granted(promo)` — `PromoCodeUse`; `gift_redeemed` — погашенные `GiftCode`; `referral_reward_paid` — `ReferralEarning`; `bonus_granted(campaign)` — `CampaignRegistration` с бонусом.
- Не восстанавливаются: бонус за приглашение (нет записи), возвраты (их находит сверка).

- [ ] **Step 1: Падающие тесты**

Создайте `tests/test_backfill.py`:

```python
"""Backfill событий и paid_at из существующих данных."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.database.models import (
    AnalyticsEvent, Campaign, CampaignRegistration, GiftCode, Payment, PromoCode, PromoCodeUse,
    ReferralEarning, Subscription, Transaction, User,
)
from app.services.analytics.backfill import backfill_events, data_quality, run_backfill
from app.services.analytics_events import record_event
from tests.helpers import make_paid_payment, make_tariff, make_user


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


async def _seed(factory) -> dict:
    """История: пользователь A (кампания, триал, две оплаты + покупка с баланса, истёкшая подписка,
    промокод), подарок, реферальное начисление."""
    referrer = await make_user(factory, telegram_id=100)
    user = await make_user(factory, telegram_id=1, created_at=utc(2026, 8, 1, 10, 0), trial_used=True, referred_by_id=referrer)
    tariff_id = await make_tariff(factory)
    async with factory() as db:
        campaign = Campaign(name='C', start_parameter='c', bonus_type='balance', balance_bonus_kopeks=3000, is_active=True)
        db.add(campaign)
        await db.flush()
        db.add(CampaignRegistration(campaign_id=campaign.id, user_id=user))
        promo = PromoCode(code='P', type='days', value=7, max_activations=5)
        db.add(promo)
        await db.flush()
        db.add(PromoCodeUse(promocode_id=promo.id, user_id=user, used_at=utc(2026, 8, 3, 9, 0)))
        db.add(GiftCode(code='G', tariff_id=tariff_id, period_days=30, gifter_user_id=referrer, redeemed_by_user_id=user,
                        redeemed_at=utc(2026, 8, 4, 9, 0), expires_at=utc(2026, 12, 1)))
        db.add(Subscription(user_id=user, tariff_id=tariff_id, status='expired', end_date=utc(2026, 9, 9, 0, 0)))
        await db.commit()
        ids = {'campaign': campaign.id, 'promo': promo.id}

    first = await make_paid_payment(factory, user, amount=24900, net=23904, gross=24900, paid_at=utc(2026, 8, 5, 10, 0))
    async with factory() as db:  # у первой оплаты paid_at и суммы cisPay лежат только в сыром ответе
        payment = await db.get(Payment, first)
        payment.paid_at = None
        payment.merchant_revenue_kopeks = None
        payment.charged_amount_kopeks = None
        payment.provider_raw_response = {'charged_amount': 24900, 'merchant_revenue': 23904, 'paid_at': '2026-08-05T10:00:00Z'}
        transaction = await db.get(Transaction, payment.transaction_id)
        transaction.description = 'Подписка «Базовый» на 30 дн.'
        await db.commit()
    second = await make_paid_payment(factory, user, amount=10000, provider='platega', paid_at=None, tx_created_at=utc(2026, 9, 5, 12, 0))
    third = await make_paid_payment(factory, user, amount=10000, provider='balance', paid_at=utc(2026, 9, 6, 12, 0))
    async with factory() as db:
        db.add(ReferralEarning(user_id=referrer, source_user_id=user, payment_id=first, amount_kopeks=2500, source='purchase'))
        await db.commit()
    return {**ids, 'user': user, 'referrer': referrer, 'first': first, 'second': second, 'third': third}


def _run(factory, fn):
    async def scenario():
        async with factory() as db:
            result = await fn(db)
            await db.commit()
            return result

    return asyncio.run(scenario())


def _events(factory):
    async def fetch():
        async with factory() as db:
            return list((await db.execute(select(AnalyticsEvent).order_by(AnalyticsEvent.occurred_at, AnalyticsEvent.id))).scalars())

    return asyncio.run(fetch())


def test_backfill_creates_events_and_fills_payments(session_factory):
    ids = asyncio.run(_seed(session_factory))

    counts = _run(session_factory, backfill_events)

    events = _events(session_factory)
    by_type: dict[str, list] = {}
    for event in events:
        by_type.setdefault(event.type, []).append(event)
    assert all(e.source == 'backfill' for e in events)
    assert counts['user_registered'] == 2 and counts['trial_started'] == 1
    registered = {e.user_id: e for e in by_type['user_registered']}
    assert registered[ids['user']].campaign_id == ids['campaign']
    assert [e.type for e in events if e.type.startswith('subscription_') and e.type != 'subscription_expired'] == [
        'subscription_first_paid', 'subscription_renewed', 'subscription_renewed',
    ]
    paid = [e for e in events if e.type in ('subscription_first_paid', 'subscription_renewed')]
    assert [e.amount_kopeks for e in paid] == [23904, 10000, 0]  # нетто; платёж без нетто; оплата с баланса
    assert paid[0].days == 30 and paid[1].days is None
    assert len(by_type['subscription_expired']) == 1 and by_type['subscription_expired'][0].occurred_at.replace(tzinfo=timezone.utc) == utc(2026, 9, 9)
    assert [e.days for e in by_type['bonus_granted'] if e.promo_code_id] == [7]
    assert [(e.amount_kopeks) for e in by_type['bonus_granted'] if e.campaign_id] == [3000]
    assert len(by_type['promocode_activated']) == 1 and len(by_type['gift_redeemed']) == 1
    (reward,) = by_type['referral_reward_paid']
    assert (reward.user_id, reward.amount_kopeks, reward.payment_id) == (ids['referrer'], 2500, ids['first'])

    async def check_payments():
        async with session_factory() as db:
            first = await db.get(Payment, ids['first'])
            second = await db.get(Payment, ids['second'])
            assert first.paid_at.replace(tzinfo=timezone.utc) == utc(2026, 8, 5, 10, 0)
            assert (first.merchant_revenue_kopeks, first.charged_amount_kopeks) == (23904, 24900)
            assert second.paid_at.replace(tzinfo=timezone.utc) == utc(2026, 9, 5, 12, 0)  # из времени транзакции

    asyncio.run(check_payments())
    assert counts['payments_paid_at'] == 2


def test_backfill_is_idempotent(session_factory):
    asyncio.run(_seed(session_factory))
    _run(session_factory, backfill_events)
    total = len(_events(session_factory))

    second = _run(session_factory, backfill_events)

    assert len(_events(session_factory)) == total
    assert sum(second.values()) == 0


def test_backfill_does_not_duplicate_live_events(session_factory):
    ids = asyncio.run(_seed(session_factory))

    async def add_live(db):
        return await record_event(db, 'user_registered', dedupe_key=f"user:{ids['user']}:registered", user_id=ids['user'])

    assert _run(session_factory, add_live) is True
    counts = _run(session_factory, backfill_events)

    assert counts['user_registered'] == 1  # только реферер; пользователь уже записан live
    registered = [e for e in _events(session_factory) if e.type == 'user_registered' and e.user_id == ids['user']]
    assert len(registered) == 1 and registered[0].source == 'live'


def test_dry_run_changes_nothing(session_factory):
    asyncio.run(_seed(session_factory))

    counts = asyncio.run(run_backfill(session_factory, dry_run=True))

    assert counts['user_registered'] == 2
    assert _events(session_factory) == []
    async def paid_at_still_empty():
        async with session_factory() as db:
            return await db.scalar(select(func.count()).select_from(Payment).where(Payment.paid_at.is_(None)))
    assert asyncio.run(paid_at_still_empty()) == 2  # два платежа из seed без paid_at (третий — с баланса, у него он есть)


def test_data_quality(session_factory):
    async def scenario():
        async with session_factory() as db:
            empty = await data_quality(db)
            await record_event(db, 'user_registered', dedupe_key='old', occurred_at=utc(2026, 8, 1), source='backfill')
            await record_event(db, 'user_registered', dedupe_key='live1', occurred_at=utc(2026, 9, 20, 10, 0))
            await record_event(db, 'user_registered', dedupe_key='live2', occurred_at=utc(2026, 9, 21, 10, 0))
            await record_event(db, 'user_registered', dedupe_key='old2', occurred_at=utc(2026, 8, 2), source='backfill')
            await db.commit()
            return empty, await data_quality(db)

    empty, quality = asyncio.run(scenario())

    assert empty == {'exact_since': None, 'backfill_share': 0.0}
    assert quality == {'exact_since': '2026-09-20T10:00:00+00:00', 'backfill_share': 0.5}
```

- [ ] **Step 2: Убедиться, что падает**

Run: `python -m pytest tests/test_backfill.py -q -p no:warnings`
Expected: FAIL (`ModuleNotFoundError: app.services.analytics.backfill`). Если `test_dry_run_changes_nothing` считает «два платежа без paid_at» неверно — сверьтесь с `_seed`: у `first` и `second` `paid_at=None`, у `third` он задан.

- [ ] **Step 3: Реализация**

Создайте `app/services/analytics/backfill.py`:

```python
"""Восстановление истории аналитики из существующих данных (разовая операция).

Всё, что пишется, помечено source='backfill', а dedupe_key совпадают с ключами live-событий —
поэтому повторный запуск и пересечение с уже записанными live-событиями дублей не создают.
Точность приближённая (см. правила в плане): `data_quality` показывает, с какой даты данные точные.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    AnalyticsEvent, Campaign, CampaignRegistration, GiftCode, Payment, PromoCode, PromoCodeUse,
    ReferralEarning, Subscription, Transaction, User,
)
from app.services.analytics_events import (
    SOURCE_BACKFILL, expired_dedupe_key, record_bonus, record_event, record_registration,
    record_subscription_purchase, record_trial_started,
)
from app.services.payment_amounts import apply_provider_details

_DAYS_RE = re.compile(r'на (\d+) дн')


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _count(counts: dict, key: str, inserted: bool) -> None:
    if inserted:
        counts[key] += 1


async def backfill_events(db: AsyncSession) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)

    # 1. paid_at и суммы cisPay у уже успешных платежей
    rows = await db.execute(
        select(Payment, Transaction.created_at)
        .outerjoin(Transaction, Transaction.id == Payment.transaction_id)
        .where(Payment.status.in_(('success', 'refunded')))
    )
    for payment, transaction_created_at in rows.all():
        had_paid_at = payment.paid_at is not None
        apply_provider_details(payment, payment.provider_raw_response)
        if payment.paid_at is None:
            payment.paid_at = transaction_created_at or payment.created_at
        if not had_paid_at and payment.paid_at is not None:
            counts['payments_paid_at'] += 1
    await db.flush()

    # 2. регистрации и триалы
    campaign_by_user = dict((await db.execute(select(CampaignRegistration.user_id, CampaignRegistration.campaign_id))).all())
    users = (await db.execute(select(User).order_by(User.id))).scalars().all()
    for user in users:
        _count(counts, 'user_registered', await record_registration(
            db, user, campaign_id=campaign_by_user.get(user.id), occurred_at=user.created_at, source=SOURCE_BACKFILL))
        if user.trial_used:
            _count(counts, 'trial_started', await record_trial_started(
                db, user, tariff_id=None, days=None, occurred_at=user.created_at, source=SOURCE_BACKFILL))

    # 3. покупки подписки — по порядку на пользователя, чтобы first_paid/renewed определились верно
    paid_at_expr = func.coalesce(Payment.paid_at, Transaction.created_at)
    purchases = await db.execute(
        select(Payment, Transaction)
        .join(Transaction, Transaction.id == Payment.transaction_id)
        .where(
            Transaction.type == 'subscription_payment',
            Transaction.status.in_(('completed', 'refunded')),
            Payment.status.in_(('success', 'refunded')),
        )
        .order_by(Payment.user_id, paid_at_expr, Payment.id)
    )
    for payment, transaction in purchases.all():
        match = _DAYS_RE.search(transaction.description or '')
        inserted = await record_subscription_purchase(
            db, user_id=payment.user_id, payment=payment, tariff_id=None,
            days=int(match.group(1)) if match else None,
            occurred_at=payment.paid_at or transaction.created_at, source=SOURCE_BACKFILL,
        )
        _count(counts, 'subscription_purchases', inserted)

    # 4. истёкшие подписки
    for subscription in (await db.execute(select(Subscription).where(Subscription.status == 'expired'))).scalars():
        _count(counts, 'subscription_expired', await record_event(
            db, 'subscription_expired', dedupe_key=expired_dedupe_key(subscription.id, subscription.end_date),
            user_id=subscription.user_id, tariff_id=subscription.tariff_id, occurred_at=subscription.end_date,
            source=SOURCE_BACKFILL))

    # 5. промокоды
    uses = await db.execute(select(PromoCodeUse, PromoCode).join(PromoCode, PromoCode.id == PromoCodeUse.promocode_id))
    for use, promo in uses.all():
        days = promo.value if promo.type == 'days' else None
        amount = promo.value if promo.type == 'balance' else None
        _count(counts, 'promocode_activated', await record_event(
            db, 'promocode_activated', dedupe_key=f'promo:{promo.id}:{use.user_id}', user_id=use.user_id,
            promo_code_id=promo.id, days=days, amount_kopeks=amount, occurred_at=use.used_at, source=SOURCE_BACKFILL))
        _count(counts, 'bonus_promo', await record_bonus(
            db, kind='promo', user_id=use.user_id, ref=f'{promo.id}:{use.user_id}', days=days, amount_kopeks=amount,
            promo_code_id=promo.id, occurred_at=use.used_at, source=SOURCE_BACKFILL))

    # 6. подарки
    for gift in (await db.execute(select(GiftCode).where(GiftCode.redeemed_at.is_not(None)))).scalars():
        _count(counts, 'gift_redeemed', await record_event(
            db, 'gift_redeemed', dedupe_key=f'gift:{gift.id}:redeemed', user_id=gift.redeemed_by_user_id,
            tariff_id=gift.tariff_id, days=gift.period_days, occurred_at=gift.redeemed_at, source=SOURCE_BACKFILL))

    # 7. реферальные начисления
    for earning in (await db.execute(select(ReferralEarning))).scalars():
        key = f'referral_payment:{earning.payment_id}' if earning.payment_id is not None else f'referral_earning:{earning.id}'
        _count(counts, 'referral_reward_paid', await record_event(
            db, 'referral_reward_paid', dedupe_key=key, user_id=earning.user_id, payment_id=earning.payment_id,
            amount_kopeks=earning.amount_kopeks, occurred_at=earning.created_at, source=SOURCE_BACKFILL))

    # 8. бонусы кампаний
    campaign_rows = await db.execute(
        select(CampaignRegistration, Campaign).join(Campaign, Campaign.id == CampaignRegistration.campaign_id)
    )
    for registration, campaign in campaign_rows.all():
        if campaign.bonus_type == 'balance' and campaign.balance_bonus_kopeks > 0:
            days, amount = None, campaign.balance_bonus_kopeks
        elif campaign.bonus_type == 'subscription' and campaign.subscription_duration_days:
            days, amount = campaign.subscription_duration_days, None
        else:
            continue
        _count(counts, 'bonus_campaign', await record_bonus(
            db, kind='campaign', user_id=registration.user_id, ref=f'{campaign.id}:{registration.user_id}',
            days=days, amount_kopeks=amount, campaign_id=campaign.id, occurred_at=registration.created_at,
            source=SOURCE_BACKFILL))

    return dict(counts)


async def run_backfill(session_factory, *, dry_run: bool = False) -> dict[str, int]:
    async with session_factory() as db:
        counts = await backfill_events(db)
        if dry_run:
            await db.rollback()
        else:
            await db.commit()
    return counts


async def data_quality(db: AsyncSession) -> dict:
    """exact_since — самое раннее LIVE-событие (с этой даты данные точные); backfill_share — доля восстановленных."""
    first_live = (await db.execute(select(func.min(AnalyticsEvent.occurred_at)).where(AnalyticsEvent.source == 'live'))).scalar_one()
    total = (await db.execute(select(func.count(AnalyticsEvent.id)))).scalar_one()
    backfilled = (
        await db.execute(select(func.count(AnalyticsEvent.id)).where(AnalyticsEvent.source == SOURCE_BACKFILL))
    ).scalar_one()
    return {
        'exact_since': _aware(first_live).isoformat() if first_live is not None else None,
        'backfill_share': round(backfilled / total, 4) if total else 0.0,
    }
```

Создайте `scripts/backfill_analytics_events.py`:

```python
"""Разовое восстановление истории аналитики (события + paid_at). Сначала --dry-run.

    python scripts/backfill_analytics_events.py --dry-run
    python scripts/backfill_analytics_events.py
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database.database import AsyncSessionLocal  # noqa: E402
from app.services.analytics.backfill import run_backfill  # noqa: E402


async def main(dry_run: bool) -> None:
    counts = await run_backfill(AsyncSessionLocal, dry_run=dry_run)
    print(('DRY-RUN (ничего не сохранено)' if dry_run else 'Готово') + ':')
    for key in sorted(counts):
        print(f'  {key}: {counts[key]}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='посчитать и откатить, ничего не сохраняя')
    asyncio.run(main(parser.parse_args().dry_run))
```

- [ ] **Step 4: Тесты проходят**

Run: `python -m pytest tests -q -p no:warnings`
Expected: PASS. Если `test_backfill_creates_events…` расходится в порядке событий — порядок в тесте задаётся `ORDER BY occurred_at, id`; сверьте даты в `_seed`.

- [ ] **Step 5: Мутации**

Уберите сортировку `order_by(Payment.user_id, paid_at_expr, Payment.id)` в п.3 — `test_backfill_creates_events…` (порядок first/renewed) падает; замените `SOURCE_BACKFILL` на `'live'` в п.2 — падает проверка `source`.

- [ ] **Step 6: Коммит**

```bash
git add app/services/analytics/backfill.py scripts/backfill_analytics_events.py tests/test_backfill.py
git commit -m "Добавляет backfill истории аналитики (события, paid_at) и data_quality"
```

---

### Task 11: Контракт API для фронтенда (закрыть `/openapi.json`, экспорт схемы, документы)

**Files:**
- Modify: `app/cabinet/app.py`
- Create: `app/cabinet/openapi_export.py`, `scripts/export_openapi.py`, `docs/api/README.md`, `docs/api/analytics-foundation.md`
- Regenerate: `docs/api/openapi.json`, `docs/api/reference-*.md`, `docs/api/schemas.md` (файлы уже существуют — см. ниже)

**Уже существует (не пишите заново):** `docs/api/API.md` (ручное руководство), `docs/api/reference-cabinet.md`, `reference-admin.md`, `reference-system.md`, `schemas.md`, `openapi.json` и генератор `scripts/generate_api_docs.py`, который пересоздаёт справочники и `openapi.json` из кода. Их надо не создавать, а **перегенерировать** после изменений API (Step 4) и обновить `API.md` там, где изменилось поведение (раздел «Что изменится»).
- Test: `tests/test_openapi.py`

**Interfaces:**
- Produces: `build_openapi() -> dict` (`app/cabinet/openapi_export.py`); `create_app(bot)` принимает `bot=None`; публичные `/openapi.json`, `/docs`, `/redoc` отвечают 404; схема лежит в `docs/api/openapi.json`.

- [ ] **Step 1: Падающие тесты**

Создайте `tests/test_openapi.py`:

```python
"""Схема API не публикуется на сервере, но экспортируется файлом для фронтенда."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.cabinet.app import create_app
from app.cabinet.openapi_export import build_openapi

SCHEMA_FILE = Path(__file__).resolve().parent.parent / 'docs' / 'api' / 'openapi.json'


def test_public_schema_and_docs_are_closed():
    with TestClient(create_app(AsyncMock())) as client:
        assert client.get('/openapi.json').status_code == 404
        assert client.get('/docs').status_code == 404
        assert client.get('/redoc').status_code == 404


def test_exported_schema_contains_analytics_contract():
    schema = build_openapi()

    assert '/cabinet/admin/analytics/reconcile/cispay' in schema['paths']
    assert '/cabinet/admin/analytics/reconcile/cispay/refunds' in schema['paths']
    overview = schema['components']['schemas']['OverviewResponse']['properties']
    assert {'timezone', 'revenue_30d_gross_kopeks', 'fees_30d_kopeks', 'net_known_share_30d'} <= set(overview)
    tz_param = next(p for p in schema['paths']['/cabinet/admin/overview']['get']['parameters'] if p['name'] == 'tz')
    assert tz_param['in'] == 'query'


def test_committed_schema_file_is_up_to_date():
    """Упало? Изменили API, но не перегенерировали файл: python scripts/export_openapi.py"""
    committed = json.loads(SCHEMA_FILE.read_text(encoding='utf-8'))

    assert committed == json.loads(json.dumps(build_openapi(), ensure_ascii=False, sort_keys=True))
```

- [ ] **Step 2: Убедиться, что падает**

Run: `python -m pytest tests/test_openapi.py -q -p no:warnings`
Expected: FAIL (`ModuleNotFoundError: app.cabinet.openapi_export`).

- [ ] **Step 3: Реализация**

`app/cabinet/app.py`: замените сигнатуру и создание приложения:

```python
def create_app(bot: Bot | None) -> FastAPI:
    # openapi_url=None: схема админ-API не должна быть публично доступна без авторизации.
    # Для фронтенда она экспортируется файлом: scripts/export_openapi.py -> docs/api/openapi.json.
    app = FastAPI(title='NRW Cabinet API', docs_url=None, redoc_url=None, openapi_url=None)
    app.state.bot = bot
```
(остальное тело `create_app` без изменений; прежний заголовок `Bedolaga Cabinet API` заменён.)

Создайте `app/cabinet/openapi_export.py`:

```python
"""Построение OpenAPI-схемы кабинета без запуска сервера (для docs/api/openapi.json)."""

from __future__ import annotations

from app.cabinet.app import create_app


def build_openapi() -> dict:
    return create_app(None).openapi()
```

Создайте `scripts/export_openapi.py`:

```python
"""Экспортирует OpenAPI-схему кабинета в docs/api/openapi.json (после ЛЮБОГО изменения API).

    BOT_TOKEN=x python scripts/export_openapi.py        (Windows PowerShell: $env:BOT_TOKEN='x')
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.cabinet.openapi_export import build_openapi  # noqa: E402

OUTPUT = ROOT / 'docs' / 'api' / 'openapi.json'

if __name__ == '__main__':
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(build_openapi(), ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(f'Записано: {OUTPUT}')
```

- [ ] **Step 4: Сгенерировать схему и запустить тесты**

Run (PowerShell): `$env:BOT_TOKEN='1:test'; python scripts/export_openapi.py; python scripts/generate_api_docs.py`; затем `python -m pytest tests -q -p no:warnings`
Expected: `docs/api/openapi.json` и справочники перегенерированы (в справочниках появились новые эндпоинты `…/analytics/reconcile/cispay*`); генератор печатает `missing from groups: []` — если нет, добавьте недостающие эндпоинты в словарь `S` и списки `GROUPS_*` в `scripts/generate_api_docs.py` (описания на русском). Все тесты PASS.

Затем обновите ручной `docs/api/API.md`: раздел «Что изменится» превратите в «Что изменилось» (выручка нетто, `?tz=`, N точек, новые поля и эндпоинты, `/openapi.json` закрыт, `409`/`502` у сверки).

- [ ] **Step 5: Документы для фронтенда**

Создайте `docs/api/README.md`:

````markdown
# API кабинета: контракт для фронтенда

- `openapi.json` — актуальная OpenAPI-схема кабинета (`/cabinet/*`, `/cabinet/admin/*`). На сервере публичный `/openapi.json` **закрыт**, источник истины — этот файл. Тест `tests/test_openapi.py::test_committed_schema_file_is_up_to_date` следит, чтобы он не отставал.
- Обновить после изменения API: `python scripts/export_openapi.py` (нужна переменная `BOT_TOKEN`, любая строка).
- Сгенерировать TypeScript-типы во фронтенде (репозиторий `NRW-MiniApp`, когда закончится редизайн):

```bash
npx openapi-typescript ../NRW-Bot/docs/api/openapi.json -o src/api/generated/openapi.d.ts
```

- Описание изменений по разделам: `analytics-foundation.md`.
- Полное описание API: `API.md` (правила, авторизация, вебхуки), справочники `reference-*.md`, схемы `schemas.md` — генерируются `scripts/generate_api_docs.py`.
````

Создайте `docs/api/analytics-foundation.md`:

````markdown
# Аналитика: что изменилось для фронтенда (фундамент)

Спецификация: `docs/superpowers/specs/2026-09-21-analytics-center-design.md`. Этот документ — для того, кто подключает интерфейс в `NRW-MiniApp`.

## Общие правила

- **Время в ответах — UTC** (ISO-8601). **Дни** (`date`, `days`) — строки `YYYY-MM-DD` в **отчётном часовом поясе**.
- Отчётный пояс по умолчанию — `Europe/Moscow`. Любой аналитический эндпоинт принимает `?tz=<IANA-имя>` (например `?tz=Europe/Moscow`). Чтобы цифры сходились с кабинетом cisPay (он режет сутки по времени браузера), передавайте пояс браузера: `Intl.DateTimeFormat().resolvedOptions().timeZone`. Неизвестное имя → **422**.
- Пояс, по которому посчитан ответ, возвращается в поле `timezone` (объекты) или в заголовке `X-Report-Timezone` (списки). Подписывайте графики: «дни по МСК» и т. п.
- Деньги — в копейках (`*_kopeks`).

## Что изменилось в существующих эндпоинтах

| Эндпоинт | Изменение |
|---|---|
| Вся выручка (`overview`, `revenue-timeseries`, `sales-breakdown`, `revenue-composition`, `ltv`, `cohorts`, `recent-payments`, `net-profit`) | Выручка теперь **нетто** (после комиссии cisPay) и привязана ко **времени оплаты**, а не создания платежа. Цифры станут ниже прежних примерно на размер комиссии (~4%) и сдвинутся по границам суток. Показывать подпись «выручка чистыми». |
| `GET /cabinet/admin/revenue-timeseries?days=N` | Возвращает **ровно N** точек (раньше N+1), последняя — сегодняшний отчётный день. Сумма точек за период равна карточке «за N дней». |
| `GET /cabinet/admin/overview` | Новые поля: `revenue_30d_gross_kopeks` (оборот), `fees_30d_kopeks` (комиссия), `net_known_share_30d` (доля платежей, где нетто известно точно; ниже 1.0 — часть старых платежей посчитана брутто), `timezone`. Окна «7 дней»/«30 дней» — по календарным дням отчётного пояса. |
| `GET /cabinet/admin/recent-payments` | `amount_kopeks` — нетто; поле `created_at` теперь хранит **время оплаты**. |
| `sales-breakdown`, `revenue-composition`, `subscription-pulse`, `ltv`, `cohorts` | Новое поле `timezone`. |

## Новые эндпоинты

### `GET /cabinet/admin/analytics/reconcile/cispay?date=YYYY-MM-DD[&tz=…]`

Сверка выручки за отчётный день с кабинетом cisPay. Ответ **409**, если cisPay не настроен; **502**, если cisPay недоступна.

```json
{
  "date": "2026-09-21",
  "timezone": "Europe/Moscow",
  "cispay": {"count": 12, "charged_kopeks": 298800, "net_kopeks": 286848},
  "ours":   {"count": 12, "charged_kopeks": 298800, "net_kopeks": 286848},
  "diff":   {"count": 0, "charged_kopeks": 0, "net_kopeks": 0},
  "missing_in_ours":   [{"external_id": "a1b2…", "charged_kopeks": 24900, "net_kopeks": 23904, "paid_at": "2026-09-21T05:00:00+00:00"}],
  "missing_in_cispay": [],
  "amount_mismatch":   [{"external_id": "c3d4…", "ours_net_kopeks": 23000, "cispay_net_kopeks": 23904, "ours_charged_kopeks": 24900, "cispay_charged_kopeks": 24900}]
}
```

`diff` = наше − cisPay. Идеальная сверка: все `diff` нулевые, три списка пусты. Предлагаемый интерфейс (вкладка «Сверка» в разделе «Аналитика»): выбор дня, две колонки «cisPay / у нас» (оборот и чистыми), красный бейдж при ненулевой разнице, таблицы расхождений.

### `POST /cabinet/admin/analytics/reconcile/cispay/refunds`

Находит возвраты cisPay и переводит платежи в статус `refunded` (то же раз в сутки делает фоновая задача). Ответ: `{"refunded_payment_ids": [123, 124]}`.

## Что фронтенду делать

1. Перегенерировать типы из `docs/api/openapi.json` (см. `README.md`).
2. Передавать `tz` браузера во все аналитические запросы; подписывать дни поясом.
3. Показать «чистыми» рядом с оборотом и комиссию (`fees_30d_kopeks`) на обзоре; предупреждение, если `net_known_share_30d < 1`.
4. Учесть, что `revenue-timeseries?days=N` отдаёт N точек.
5. (Позже) вкладка «Сверка».
````

- [ ] **Step 6: Тесты и коммит**

Run: `python -m pytest tests -q -p no:warnings` → PASS.

```bash
git add app/cabinet/app.py app/cabinet/openapi_export.py scripts/export_openapi.py docs/api tests/test_openapi.py
git commit -m "Закрывает публичный /openapi.json, экспортирует схему и описывает контракт для фронтенда"
```

---

### Task 12: Финальная проверка и документация

**Files:**
- Modify: `README.md` (раздел про аналитику и `REPORT_TIMEZONE`)
- Verify: весь репозиторий

- [ ] **Step 1: Полный прогон и импорт-проверки**

Run: `python -m pytest tests -q -p no:warnings`
Expected: PASS, число тестов заметно больше 199.
Run: `python -c "import os;os.environ['BOT_TOKEN']='1:t'; import main; import app.cabinet.app; print('import ok')"`
Expected: `import ok`.

- [ ] **Step 2: Сквозные проверки по grep**

Run: `grep -rn "business_day_start_utc" app --include=*.py` — только `time_utils.py` и `handlers/admin.py`.
Run: `grep -rn "_revenue_sum\|_revenue_query" app --include=*.py` — пусто.
Run: `grep -rn "Payment.amount_kopeks" app/services/analytics_service.py` — пусто (деньги считает `revenue.py`).

- [ ] **Step 3: README**

В `README.md` в раздел «Переменные окружения» (или после раздела «Логирование») добавьте:

```markdown
## Аналитика и время

Время в БД и API — UTC. Границы дней/недель/месяцев в аналитике считаются в часовом поясе `REPORT_TIMEZONE`
(по умолчанию `Europe/Moscow`; на Windows нужен пакет `tzdata`). Выручка — чистая сумма после комиссии cisPay
по времени оплаты, без возвратов. Журнал событий (`analytics_events`) и разовое восстановление истории:
`python scripts/backfill_analytics_events.py --dry-run`, затем без `--dry-run`. Контракт API для фронтенда — `docs/api/`.
```

- [ ] **Step 4: Порядок выкладки (для владельца)**

1. Деплой бэкенда (миграция `b7d1e5a93c20` применится автоматически при старте контейнера).
2. `python scripts/backfill_analytics_events.py --dry-run` → проверить числа → запуск без `--dry-run`.
3. Открыть `GET /cabinet/admin/analytics/reconcile/cispay?date=<вчера>&tz=<ваш пояс>` и сравнить дневной итог с кабинетом cisPay: `cispay.net_kopeks` должен совпасть с суммой «чистыми» в их кабинете, `diff` — нулевой.
4. Сообщить, что цифры выручки сместились на размер комиссии и границы суток.
5. Передать фронтенд-агенту `docs/api/` (после завершения редизайна).

- [ ] **Step 5: Коммит**

```bash
git add README.md
git commit -m "Документирует отчётный часовой пояс, события аналитики и порядок выкладки"
```

---

## Покрытие спецификации

| Раздел спецификации | Задача |
|---|---|
| §3–4 время, `time_utils`, `?tz=` | 1, 8 |
| §5 модель данных, миграции | 2 |
| §7 выручка (`revenue.py`, нетто, `paid_at`, возвраты) | 3, 4, 8 |
| §5 события и точки записи, `record_event` | 5, 6, 7 |
| §8 сверка с cisPay, возвраты | 9 |
| §11 backfill, `data_quality` | 10 |
| §10 ошибки: 422 `tz`, 409/502 cisPay, тихая запись событий | 8, 9, 5 |
| Контракт для фронтенда, закрытие `/openapi.json` | 11 |
| Выкладка и проверка со сверкой | 12 |

**Не входят в этот план (отдельные планы по спецификации):** API «Рост и деньги», «Удержание», «Маркетинг» (подпроекты 2–4) и сам интерфейс во фронтенде.
