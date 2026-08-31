"""Границы "бизнес-дня" для метрик вида "сегодня"/"за сутки".

День считается не по UTC-полуночи и не скользящим окном в 24ч, а по
московскому времени с границей в 02:00 (ночная активность до 2 часов ночи
по МСК ещё относится к предыдущему дню) — так задумано владельцем продукта.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

MOSCOW_OFFSET = timedelta(hours=3)
BUSINESS_DAY_START_HOUR = 2


def business_day_start_utc(now: datetime) -> datetime:
    """Начало текущего "бизнес-дня" (граница 02:00 МСК), возвращает aware UTC."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    moscow_now = now + MOSCOW_OFFSET
    boundary_moscow = moscow_now.replace(
        hour=BUSINESS_DAY_START_HOUR, minute=0, second=0, microsecond=0
    )
    if moscow_now < boundary_moscow:
        boundary_moscow -= timedelta(days=1)
    return boundary_moscow - MOSCOW_OFFSET
