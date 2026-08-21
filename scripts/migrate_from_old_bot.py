"""Разовый перенос данных из старой базы (remnawave-bedolaga-telegram-bot,
100+ таблиц) в bedolaga-lite (14 моделей, см. app/database/models.py).

Переносим: users, subscriptions (по одной самой актуальной на юзера — у нас
Subscription.user_id уникален, мульти-тарифность старого бота не поддерживаем),
transactions (история для LTV/аналитики), referral_earnings, promo_groups.
Даты (User/Subscription/Transaction/ReferralEarning.created_at, Subscription.
start_date) переносятся РЕАЛЬНЫЕ из старой базы, а не момент прогона скрипта —
см. диалог, "сохранить всё без исключений" касается в первую очередь этого:
никаких "все юзеры зарегистрировались сегодня" после переезда. Тип транзакции
без аналога в новой пятёрке типов (withdrawal/failed_refund/poll_reward — см.
_TX_TYPE_MAP) переносится ОРИГИНАЛЬНОЙ строкой, а не отбрасывается и не
переклассифицируется в topup — Transaction.type не enum на уровне БД.

Всё остальное — тикеты, купоны, wheel of fortune, Apple IAP, провайдер-специфичные
таблицы платежей (yookassa/heleket/mulenpay/...), автоплатежи, опросы, контесты,
лендинги и т.д. — в bedolaga-lite не существует как концепция (ни таблицы, ни
экрана, ни хендлера) и этим скриптом НЕ переносится. Требование "сохранить всё
без исключений" (см. диалог от 2026-08-20) для этих разделов ЕЩЁ НЕ РЕШЕНО —
либо расширять схему bedolaga-lite под них, либо держать старую базу как
read-only архив. Явно НЕ переносим Payment (провайдерские pending/webhook-записи)
— для истории платежей достаточно Transaction, а Payment.raw_payload/external_id
старых провайдеров всё равно не совместимы с новыми (Platega-only, см. диалог).

Remnawave НЕ трогаем — ничего не создаём и не меняем в панели. Единственная
задача — восстановить у нового User.remnawave_uuid ссылку на УЖЕ существующего
там пользователя, чтобы не плодить новые VPN-аккаунты при следующей покупке/
синхронизации.

ВАЖНО (проверено на реальном ответе панели, 2026-08-19 — предыдущая версия этого
докстринга/кода была основана на устаревшем контракте, см. app/external/remnawave/
real.py:7-17 "это меняли предыдущий агент по ошибке — не возвращать обратно"):
после апгрейда панели (коммит "replace all users routes to use id instead of
uuid", июль 2026, уже в стабильных релизах) поле `uuid` из ответа GET /users
ПРОПАЛО ВООБЩЕ — там только `id: number` + `shortUuid`. Живой резолв через
GET /api/users/by-id/{id} в ожидании поля `uuid` в ответе больше не работает
(вернёт None на каждой строке). Правильный текущий контракт: remnawave_uuid в
нашей БД — это просто str(remnawave_id) старой базы, БЕЗ каких-либо API-запросов
к панели. Старое легаси-поле users.remnawave_uuid (настоящий UUID-формат) больше
не резолвится панелью и не используется.

Предусловия:
  - .env новой базы (DATABASE_URL) указывает на ЦЕЛЕВОЙ Postgres, alembic upgrade
    head уже прогнан, в базе есть хотя бы один Tariff (см. scripts/seed.py) —
    остальные тарифы (Семейный/Корпоративный/Легаси и т.д.) скрипт создаёт сам
    по именам старых тарифов, см. ниже.
  - REMNAWAVE_BASE_URL этого бота указывает на ТУ ЖЕ панель, где физически жили
    старые аккаунты — иначе перенесённый remnawave_uuid будет числом с чужой
    панели и все действия с юзером (продление/устройства/enable) будут падать
    404/400. Никакого сетевого запроса к панели сам скрипт не делает.

Запуск (dry-run по умолчанию показывает, что будет сделано, без записи):
    OLD_DATABASE_URL=postgresql://user:pass@host/old_db \\
    .venv/Scripts/python.exe scripts/migrate_from_old_bot.py --dry-run

    # реальный прогон:
    OLD_DATABASE_URL=postgresql://user:pass@host/old_db \\
    .venv/Scripts/python.exe scripts/migrate_from_old_bot.py

Идемпотентность: юзеры матчатся по telegram_id (unique в обеих базах) — повторный
запуск не создаёт дублей среди уже перенесённых, только досоздаёт то, чего не было
(включая backfill remnawave_uuid/email на уже перенесённых). Subscription тоже
безопасен при повторном запуске — пропускается, если у юзера уже есть подписка.
Transaction/ReferralEarning НЕ дедуплицируются по контенту (в старой базе нет
стабильного внешнего ключа, который можно было бы сверить) — если процесс упал
ПОСЛЕ переноса транзакций одного юзера и перезапущен, транзакции этого юзера
задвоятся. Чтобы ограничить масштаб такого сбоя, скрипт коммитит per-user
(одна транзакция БД на одного старого юзера), а не всё разом в конце.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncpg
from sqlalchemy import func, select

from app.database.database import AsyncSessionLocal
from app.database.models import PromoGroup, ReferralEarning, Subscription, Tariff, Transaction, User

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger('migrate')

# Старые статусы подписки, которые считаем "живыми" при выборе, какую ИЗ
# НЕСКОЛЬКИХ старых Subscription переносить (у нас на юзера ровно одна) —
# см. User.subscription property в старой модели (app/database/models.py:2126).
_LIVE_STATUSES = ('active', 'trial', 'limited')

# Старые TransactionType (app/database/models.py:131 старого бота) -> наш
# Transaction.type. Переименовываем только то, что 1:1 совпадает по смыслу с
# нашими типами (иначе 'deposit'/'gift_payment' не попали бы в
# analytics_service.REVENUE_TYPES/referral_service, которые матчат по
# конкретным строкам 'topup'/'gift'). Всё остальное ('withdrawal',
# 'failed_refund', 'poll_reward' — см. _tx_type ниже) сохраняем ОРИГИНАЛЬНОЙ
# старой строкой типа: полностью историческая запись важнее вписывания в
# нашу пятёрку типов (см. диалог — сохранить всё без исключений). На
# аналитику/выручку это не влияет — Transaction.type не enum на уровне БД
# (обычная String(32)), а REVENUE_TYPES матчит по конкретным известным
# строкам, так что незнакомый тип просто не попадёт в выручку/рефералку —
# что и корректно, это не покупка.
_TX_TYPE_MAP = {
    'deposit': 'topup',
    'subscription_payment': 'subscription_payment',
    'referral_reward': 'referral_reward',
    'refund': 'refund',
    'gift_payment': 'gift',
}


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='Только посчитать/показать, ничего не писать в новую БД')
    args = parser.parse_args()

    old_dsn = os.environ.get('OLD_DATABASE_URL')
    if not old_dsn:
        raise SystemExit('Задайте OLD_DATABASE_URL (postgresql://... старой базы)')

    old_conn = await asyncpg.connect(old_dsn)
    try:
        await _run(old_conn, dry_run=args.dry_run)
    finally:
        await old_conn.close()


async def _run(old_conn: asyncpg.Connection, *, dry_run: bool) -> None:
    async with AsyncSessionLocal() as db:
        any_tariff = (await db.execute(select(Tariff.id).limit(1))).scalar_one_or_none()
        if any_tariff is None:
            raise SystemExit('В новой базе нет ни одного тарифа — сначала прогоните scripts/seed.py')

        # === Тарифы: old tariff_id -> new tariff_id, по имени. Тариф без аналога
        # (например "Корпоративный") создаётся новым, неактивным — только чтобы
        # существующие подписчики не потеряли обозначение своего плана; новым
        # покупателям такой тариф не показывается. NULL tariff_id старой подписки
        # (легаси/до введения тарифов) — отдельный тариф-заглушка "Легаси". ===
        old_tariffs = await old_conn.fetch('SELECT id, name, device_limit FROM tariffs')
        existing_tariff_by_name = {
            name: tid for tid, name in (await db.execute(select(Tariff.id, Tariff.name))).all()
        }
        old_tariff_id_to_new: dict[int | None, int] = {}
        for row in old_tariffs:
            name = row['name']
            if name in existing_tariff_by_name:
                new_id = existing_tariff_by_name[name]
            else:
                t = Tariff(name=name, period_prices_kopeks={}, traffic_limit_gb=0,
                            device_limit=row['device_limit'] or 3, squad_uuids=[], is_active=False)
                db.add(t)
                await db.flush()
                existing_tariff_by_name[name] = t.id
                new_id = t.id
                logger.info('Тариф создан (для существующих подписчиков, неактивный): %s', name)
            old_tariff_id_to_new[row['id']] = new_id

        legacy_name = 'Легаси (перенесено из старого бота)'
        if legacy_name in existing_tariff_by_name:
            legacy_tariff_id = existing_tariff_by_name[legacy_name]
        else:
            t = Tariff(name=legacy_name, period_prices_kopeks={}, traffic_limit_gb=0,
                        device_limit=5, squad_uuids=[], is_active=False)
            db.add(t)
            await db.flush()
            legacy_tariff_id = t.id
            logger.info('Тариф создан (для существующих подписчиков, неактивный): %s', legacy_name)
        old_tariff_id_to_new[None] = legacy_tariff_id
        if not dry_run:
            await db.commit()

        # === Промогруппы: id старой -> id новой (по имени, создаём при отсутствии) ===
        old_groups = await old_conn.fetch('SELECT id, name, server_discount_percent FROM promo_groups')
        promo_group_id_map: dict[int, int] = {}
        for row in old_groups:
            existing = (await db.execute(select(PromoGroup).where(PromoGroup.name == row['name']))).scalar_one_or_none()
            if existing is None:
                # server_discount_percent — ближайший аналог "скидки на всю подписку"
                # у нас (флэт-скидка, без разбивки по серверам/трафику/устройствам,
                # см. диалог/PromoGroup в app/database/models.py). traffic_/device_
                # discount_percent старой группы теряются осознанно — нет колонки-аналога.
                existing = PromoGroup(name=row['name'], discount_percent=row['server_discount_percent'] or 0)
                db.add(existing)
                await db.flush()
                logger.info('Промогруппа создана: %s (%s%%)', row['name'], existing.discount_percent)
            promo_group_id_map[row['id']] = existing.id
        if not dry_run:
            await db.commit()

        # === Пользователи ===
        # status != 'deleted' — уважаем удаление аккаунта в старом боте, не
        # воскрешаем такие записи при переносе.
        old_users = await old_conn.fetch(
            "SELECT id, telegram_id, username, email, language, balance_kopeks, referral_code, referred_by_id, "
            "remnawave_id, promo_group_id, referral_commission_percent, "
            "has_had_paid_subscription, status, created_at "
            "FROM users WHERE telegram_id IS NOT NULL AND status != 'deleted' ORDER BY id"
        )
        skipped_email_only = await old_conn.fetchval('SELECT count(*) FROM users WHERE telegram_id IS NULL')
        skipped_deleted = await old_conn.fetchval(
            "SELECT count(*) FROM users WHERE telegram_id IS NOT NULL AND status = 'deleted'"
        )
        total_old_users = len(old_users) + skipped_email_only + skipped_deleted

        # === Контрольные суммы старой базы — сверяются в конце с новой (см.
        # диалог "нормальная и целая база данных"): без этого миграция может
        # молча потерять/задвоить строки, и заметить это можно только руками
        # позже, когда концов уже не найти. ===
        _old_user_ids = [row['id'] for row in old_users]
        # НЕ сумма по всем кандидатам — уже существующих юзеров (matched по
        # telegram_id) миграция не трогает, их баланс в сумму включать нельзя,
        # иначе сверка ниже ложно кричит "расхождение" на каждом повторном
        # запуске (см. диалог, 2026-08-20 — поймано вживую на 370₽ у одного
        # already-existing юзера). Накапливается ниже, только когда юзер
        # реально создаётся.
        old_balance_sum = 0
        old_tx_total = await old_conn.fetchval(
            'SELECT count(*) FROM transactions WHERE user_id = ANY($1::int[])', _old_user_ids
        )
        old_earnings_total = await old_conn.fetchval(
            'SELECT count(*) FROM referral_earnings WHERE user_id = ANY($1::int[])', _old_user_ids
        )

        old_id_to_new_id: dict[int, int] = {}
        pending_referred_by: dict[int, int] = {}  # new_user_id -> old_referred_by_id (второй проход)
        created, updated, email_backfilled = 0, 0, 0
        created_new_ids: list[int] = []  # только новые User.id — для сверки суммы баланса ниже

        for row in old_users:
            telegram_id = row['telegram_id']
            existing = (await db.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one_or_none()

            # remnawave_uuid = str(remnawave_id) панели, без резолва по API (см. докстринг).
            remnawave_uuid = str(row['remnawave_id']) if row['remnawave_id'] else None
            is_blocked = row['status'] == 'blocked'

            lang = (row['language'] or 'ru')[:2]
            if lang not in ('ru', 'en'):
                lang = 'ru'

            if existing is None:
                referral_code = row['referral_code']
                if referral_code:
                    referral_code = referral_code[:16]
                    clash = (
                        await db.execute(select(User.id).where(User.referral_code == referral_code))
                    ).scalar_one_or_none()
                    if clash is not None:
                        referral_code = None  # перегенерируется ниже
                if not referral_code:
                    from app.services.referral_service import generate_referral_code

                    for _ in range(10):
                        candidate = generate_referral_code()
                        clash = (
                            await db.execute(select(User.id).where(User.referral_code == candidate))
                        ).scalar_one_or_none()
                        if clash is None:
                            referral_code = candidate
                            break

                # has_had_paid_subscription НЕ равно "триал использован" (см. диалог):
                # старый бот считает триал использованным, если юзер либо платил,
                # либо у него ЕСТЬ ЛЮБАЯ подписка кроме неоплаченного черновика
                # триала (см. User.is_trial_already_used/Subscription.is_pending_trial
                # в старой модели, app/database/models.py:2126/2384) — иначе юзер,
                # попробовавший триал и не заплативший, получил бы вторую бесплатную
                # попытку в новом боте.
                has_any_real_sub = await old_conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM subscriptions WHERE user_id = $1 "
                    "AND NOT (status = 'pending' AND is_trial = true))",
                    row['id'],
                )
                trial_used = bool(row['has_had_paid_subscription']) or bool(has_any_real_sub)

                new_user = User(
                    telegram_id=telegram_id,
                    username=row['username'],
                    email=row['email'],
                    language=lang,
                    balance_kopeks=row['balance_kopeks'] or 0,
                    referral_code=referral_code,
                    remnawave_uuid=remnawave_uuid,
                    promo_group_id=promo_group_id_map.get(row['promo_group_id']),
                    referral_commission_percent=row['referral_commission_percent'],
                    trial_used=trial_used,
                    is_blocked=is_blocked,
                    created_at=_aware(row['created_at']),
                )
                db.add(new_user)
                await db.flush()
                created += 1
                created_new_ids.append(new_user.id)
                old_balance_sum += row['balance_kopeks'] or 0
                old_id_to_new_id[row['id']] = new_user.id
                if row['referred_by_id']:
                    pending_referred_by[new_user.id] = row['referred_by_id']
            else:
                old_id_to_new_id[row['id']] = existing.id
                if remnawave_uuid and not existing.remnawave_uuid:
                    existing.remnawave_uuid = remnawave_uuid
                    updated += 1
                if row['email'] and not existing.email:
                    existing.email = row['email']
                    email_backfilled += 1

        # Второй проход: referred_by_id (self-FK, требует, чтобы ВСЕ юзеры уже
        # существовали — иначе циклические/форвардные ссылки не резолвились бы).
        for new_user_id, old_referrer_id in pending_referred_by.items():
            new_referrer_id = old_id_to_new_id.get(old_referrer_id)
            if new_referrer_id is None:
                continue
            user_obj = await db.get(User, new_user_id)
            user_obj.referred_by_id = new_referrer_id

        logger.info(
            'Пользователи: %s всего в старой базе (%s email-only, %s deleted пропущено), создано %s, '
            'обновлено (remnawave_uuid) %s, email добавлен %s',
            total_old_users,
            skipped_email_only,
            skipped_deleted,
            created,
            updated,
            email_backfilled,
        )
        if not dry_run:
            await db.commit()
        else:
            await db.rollback()
            logger.info('--dry-run: пользователи НЕ записаны, дальше подписки/транзакции считаются от той же выборки')

        # === Подписки (одна самая актуальная на юзера) + транзакции + рефералка —
        # по одному старому юзеру за раз, с покоммитным флашем (см. докстринг). ===
        subs_created, tx_created, tx_unmapped, earnings_created = 0, 0, 0, 0
        for row in old_users:
            new_user_id = old_id_to_new_id.get(row['id'])
            if new_user_id is None or dry_run:
                continue

            already_has_sub = (
                await db.execute(select(Subscription.id).where(Subscription.user_id == new_user_id))
            ).scalar_one_or_none()
            if already_has_sub is None:
                sub_row = await old_conn.fetchrow(
                    "SELECT status, is_trial, tariff_id, end_date, traffic_limit_gb, traffic_used_gb, device_limit, "
                    "subscription_url, remnawave_short_uuid, autopay_enabled, start_date, created_at "
                    "FROM subscriptions WHERE user_id = $1 "
                    "ORDER BY (status IN ('active','trial','limited')) DESC, created_at DESC LIMIT 1",
                    row['id'],
                )
                if sub_row is not None:
                    old_status = sub_row['status']
                    new_status = 'active' if old_status in _LIVE_STATUSES else (
                        'disabled' if old_status == 'disabled' else 'expired'
                    )
                    db.add(
                        Subscription(
                            user_id=new_user_id,
                            tariff_id=old_tariff_id_to_new[sub_row['tariff_id']],
                            status=new_status,
                            start_date=_aware(sub_row['start_date']) or _aware(sub_row['created_at']),
                            end_date=_aware(sub_row['end_date']) or datetime.now(timezone.utc),
                            traffic_limit_gb=sub_row['traffic_limit_gb'] or 0,
                            traffic_used_gb=sub_row['traffic_used_gb'] or 0,
                            device_limit=sub_row['device_limit'] or 3,
                            subscription_url=sub_row['subscription_url'],
                            short_uuid=sub_row['remnawave_short_uuid'],
                            autopay_enabled=bool(sub_row['autopay_enabled']),
                            created_at=_aware(sub_row['created_at']),
                        )
                    )
                    subs_created += 1

            tx_rows = await old_conn.fetch(
                'SELECT type, amount_kopeks, description, is_completed, created_at '
                'FROM transactions WHERE user_id = $1 ORDER BY id',
                row['id'],
            )
            for tx in tx_rows:
                new_type = _TX_TYPE_MAP.get(tx['type'])
                if new_type is None:
                    new_type = tx['type']  # нет аналога — сохраняем как есть, см. _TX_TYPE_MAP
                    tx_unmapped += 1
                db.add(
                    Transaction(
                        user_id=new_user_id,
                        type=new_type,
                        # Старый бот хранит subscription_payment/gift_payment
                        # СО ЗНАКОМ МИНУС (это списание с внутреннего баланса
                        # в его модели учёта, см. create_transaction в
                        # app/database/crud/transaction.py оригинала) — у
                        # нас amount_kopeks ВСЕГДА положительный, направление
                        # определяется только type (см. models.py). Без abs()
                        # доход в analytics_service.py считался бы отрицательным
                        # (найдено вживую на реальном прогоне, 2026-08-20).
                        amount_kopeks=abs(tx['amount_kopeks']),
                        status='completed' if tx['is_completed'] else 'pending',
                        description=tx['description'],
                        created_at=_aware(tx['created_at']),
                    )
                )
                tx_created += 1

            earning_rows = await old_conn.fetch(
                'SELECT referral_id, amount_kopeks, reason, created_at FROM referral_earnings WHERE user_id = $1',
                row['id'],
            )
            for earning in earning_rows:
                source_new_id = old_id_to_new_id.get(earning['referral_id'])
                if source_new_id is None:
                    # Структурный, а не случайный пробел (проверено на реальном
                    # прогоне 2026-08-20, см. диалог): source — покупатель,
                    # сгенерировавший начисление, БЕЗ telegram_id (email/веб-
                    # аккаунт старого бота). ReferralEarning.source_user_id
                    # NOT NULL и ссылается на users — у нас в принципе нет
                    # способа завести такого юзера (User.telegram_id обязателен).
                    # Начисление реферера теряется как строка истории, хотя сами
                    # деньги уже зачислены ему на balance_kopeks (переносится
                    # отдельно, независимо от этого цикла) — это ожидаемо
                    # отражается в old_earnings_total ниже, не считается багом.
                    continue
                db.add(
                    ReferralEarning(
                        user_id=new_user_id,
                        source_user_id=source_new_id,
                        amount_kopeks=earning['amount_kopeks'],
                        source='purchase' if 'purchase' in (earning['reason'] or '') else 'topup',
                        created_at=_aware(earning['created_at']),
                    )
                )
                earnings_created += 1

            await db.commit()

        logger.info(
            'Подписки создано: %s, транзакций перенесено: %s (из них %s с типом без аналога — сохранён как есть), '
            'начислений рефералки: %s',
            subs_created,
            tx_created,
            tx_unmapped,
            earnings_created,
        )

        if dry_run:
            return

        # === Сверка со старой базой. Несовпадение — сигнал остановиться и
        # разобраться, а не пожимать плечами: транзакции/рефералка не
        # дедуплицируются (см. докстринг), так что расхождение почти всегда
        # значит, что скрипт уже запускали раньше и часть строк задвоилась. ===
        new_balance_sum = (
            await db.execute(select(func.coalesce(func.sum(User.balance_kopeks), 0)).where(User.id.in_(created_new_ids)))
        ).scalar_one() if created_new_ids else 0

        ok = old_tx_total == tx_created and old_earnings_total == earnings_created and old_balance_sum == new_balance_sum
        logger.info(
            '%s Сверка со старой базой: транзакций %s/%s, начислений рефералки %s/%s, '
            'сумма баланса новых юзеров %s/%s коп.',
            'OK.' if ok else 'РАСХОЖДЕНИЕ!',
            tx_created, old_tx_total,
            earnings_created, old_earnings_total,
            new_balance_sum, old_balance_sum,
        )
        if not ok:
            logger.warning(
                'Расхождение почти всегда значит повторный запуск поверх уже частично '
                'перенесённых данных (транзакции/рефералка не дедуплицируются) — проверьте '
                'перед тем, как считать базу перенесённой полностью.'
            )


if __name__ == '__main__':
    asyncio.run(main())
