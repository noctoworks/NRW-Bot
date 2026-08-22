"""Интерфейс платёжного провайдера. Каждая реализация (stub/platega/stars/ton)
следует одному контракту, чтобы вызывающий код (purchase.py и т.п.) не знал деталей."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram import Bot


@dataclass
class CreatedPayment:
    external_id: str
    payment_url: str | None  # None для Stars (используется send_invoice в самом боте)
    status: str  # pending|success


class PaymentProvider(ABC):
    provider_name: str

    @abstractmethod
    async def create_payment(
        self,
        *,
        user_id: int,
        amount_kopeks: int,
        description: str,
        bot: 'Bot | None' = None,
        telegram_id: int | None = None,
    ) -> CreatedPayment:
        """bot/telegram_id — только для StarsProvider (шлёт инвойс сам через
        Bot.send_invoice, у Stars нет ни payment_url, ни отдельного API для
        создания счёта). Остальные провайдеры эти два параметра игнорируют."""

    @abstractmethod
    async def verify_webhook(self, payload: dict, headers: dict) -> bool:
        """True, если вебхук подлинный и можно доверять payload."""

    @abstractmethod
    async def check_payment_status(self, external_id: str, *, amount_kopeks: int | None = None) -> str:
        """Опрос статуса — используется payment_poll фоновой задачей (§12).

        amount_kopeks — опционально, нужен ТОЛЬКО TonProvider (см.
        app/services/payment/ton.py, диалог 2026-08-21): в отличие от Platega/
        Stars, где сумму подтверждает сам провайдер, у TON "провайдер" —
        это сам блокчейн, транзакцию с нужным комментарием мог прислать кто угодно
        на любую сумму, поэтому сумму обязаны сверить мы сами. Остальные провайдеры
        параметр игнорируют."""
