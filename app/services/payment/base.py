"""Интерфейс платёжного провайдера. Каждая реализация (stub/yookassa/cryptobot/stars)
следует одному контракту, чтобы вызывающий код (purchase.py и т.п.) не знал деталей."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class CreatedPayment:
    external_id: str
    payment_url: str | None  # None для Stars (используется send_invoice в самом боте)
    status: str  # pending|success


class PaymentProvider(ABC):
    provider_name: str

    @abstractmethod
    async def create_payment(self, *, user_id: int, amount_kopeks: int, description: str) -> CreatedPayment: ...

    @abstractmethod
    async def verify_webhook(self, payload: dict, headers: dict) -> bool:
        """True, если вебхук подлинный и можно доверять payload."""

    @abstractmethod
    async def check_payment_status(self, external_id: str) -> str:
        """Опрос статуса — используется payment_poll фоновой задачей (§12)."""
