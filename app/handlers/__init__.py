"""Точка сборки всех хендлеров бота.

Каждый feature-модуль (start.py, subscription.py, referral.py, promocode.py,
gift.py, support.py, admin.py, ...) экспортирует `register_handlers(dp)`.
Добавляя новый модуль — допишите ОДНУ строку в register_all_handlers ниже,
внутри промаркированного блока. Не трогайте остальные строки в этом файле —
это единственная точка, где разные модули потенциально пересекаются.
"""

from __future__ import annotations

from aiogram import Dispatcher


def register_all_handlers(dp: Dispatcher) -> None:
    # === HANDLER REGISTRATIONS (добавлять новые строки только сюда) ===
    from app.handlers import start

    start.register_handlers(dp)

    from app.handlers import subscription

    subscription.register_handlers(dp)

    from app.handlers import referral

    referral.register_handlers(dp)

    from app.handlers import promocode

    promocode.register_handlers(dp)

    from app.handlers import gift

    gift.register_handlers(dp)

    from app.handlers import support

    support.register_handlers(dp)

    from app.handlers import admin

    admin.register_handlers(dp)
    # === END HANDLER REGISTRATIONS ===
