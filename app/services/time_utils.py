"""Границы "бизнес-дня" для метрик вида "сегодня"/"за сутки".

День считается не по UTC-полуночи и не скользящим окном в 24ч, а по
московской календарной полночи (00:00 МСК) — намеренно совпадает с тем, как
считает сутки платёжный шлюз (Platega), чтобы цифры "выручка за сегодня" в
админке и "оборот за сегодня" в личном кабинете Platega сходились. Раньше
граница была 02:00 МСК (ночная активность относилась к предыдущему дню) —
от этого отказались 2026-09-01, увидев расхождение со статистикой Platega.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

MOSCOW_OFFSET = timedelta(hours=3)
BUSINESS_DAY_START_HOUR = 0


def business_day_start_utc(now: datetime) -> datetime:
    """Начало текущего "бизнес-дня" (граница 00:00 МСК), возвращает aware UTC."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    moscow_now = now + MOSCOW_OFFSET
    boundary_moscow = moscow_now.replace(
        hour=BUSINESS_DAY_START_HOUR, minute=0, second=0, microsecond=0
    )
    if moscow_now < boundary_moscow:
        boundary_moscow -= timedelta(days=1)
    return boundary_moscow - MOSCOW_OFFSET
