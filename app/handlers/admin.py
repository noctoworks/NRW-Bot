"""TODO(agent:admin-support): /admin меню — пользователи/тарифы/промокоды/рассылка/статистика —
см. §11 clone-architecture.md. Доступ проверять через db_user.is_admin (см. AuthMiddleware)."""

from __future__ import annotations

from aiogram import Dispatcher


def register_handlers(dp: Dispatcher) -> None:
    pass
