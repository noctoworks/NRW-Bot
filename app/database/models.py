"""14 моделей ядра — см. §4 архитектурного документа (clone-architecture.md).

Устройства (HWID) НЕ хранятся здесь — они всегда live-запрос к Remnawave
через User.remnawave_uuid (см. app/external/remnawave/base.py). Это осознанное
решение, а не недосмотр.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(TimestampMixin, Base):
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    language: Mapped[str] = mapped_column(String(8), default='ru')

    balance_kopeks: Mapped[int] = mapped_column(BigInteger, default=0)

    referral_code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    referred_by_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)

    remnawave_uuid: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)

    subscription: Mapped['Subscription | None'] = relationship(
        back_populates='user', uselist=False, cascade='all, delete-orphan'
    )
    referred_by: Mapped['User | None'] = relationship(remote_side=[id])


class Tariff(TimestampMixin, Base):
    __tablename__ = 'tariffs'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    # {"30": 29900, "90": 79900, "180": 139900, "360": 249900} — цена в копейках за период (дни).
    period_prices_kopeks: Mapped[dict] = mapped_column(JSON, default=dict)
    traffic_limit_gb: Mapped[int] = mapped_column(BigInteger, default=0)  # 0 = безлимит
    device_limit: Mapped[int] = mapped_column(Integer, default=3)
    squad_uuids: Mapped[list] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Subscription(TimestampMixin, Base):
    __tablename__ = 'subscriptions'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), unique=True)
    tariff_id: Mapped[int] = mapped_column(ForeignKey('tariffs.id'))

    status: Mapped[str] = mapped_column(String(16), default='active')  # active|expired|disabled
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    traffic_limit_gb: Mapped[int] = mapped_column(BigInteger, default=0)
    traffic_used_gb: Mapped[float] = mapped_column(default=0)
    device_limit: Mapped[int] = mapped_column(Integer, default=3)

    subscription_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    short_uuid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    autopay_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    # Дедупликация плановых напоминаний об истечении (§12а архитектурного документа)
    reminder_3d_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    reminder_1d_sent: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped['User'] = relationship(back_populates='subscription')
    tariff: Mapped['Tariff'] = relationship()


class Transaction(TimestampMixin, Base):
    __tablename__ = 'transactions'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    type: Mapped[str] = mapped_column(String(32))  # topup|subscription_payment|referral_reward|refund|gift
    amount_kopeks: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16), default='completed')
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)


class Payment(TimestampMixin, Base):
    __tablename__ = 'payments'
    __table_args__ = (UniqueConstraint('provider', 'external_id', name='uq_payment_provider_external_id'),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey('transactions.id'), nullable=True)

    provider: Mapped[str] = mapped_column(String(32))  # stars|yookassa|cryptobot|stub
    external_id: Mapped[str] = mapped_column(String(128))
    amount_kopeks: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16), default='pending')  # pending|success|failed
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)


class PromoCode(TimestampMixin, Base):
    __tablename__ = 'promocodes'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)  # читаемый, напр. SUMMER2026
    type: Mapped[str] = mapped_column(String(16))  # balance|days
    value: Mapped[int] = mapped_column(Integer)  # копейки (balance) или дни (days)
    max_activations: Mapped[int] = mapped_column(Integer, default=1)
    activations_count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class PromoCodeUse(Base):
    __tablename__ = 'promocode_uses'
    __table_args__ = (UniqueConstraint('promocode_id', 'user_id', name='uq_promocode_user'),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    promocode_id: Mapped[int] = mapped_column(ForeignKey('promocodes.id', ondelete='CASCADE'))
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'))
    used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GiftCode(TimestampMixin, Base):
    __tablename__ = 'gift_codes'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    tariff_id: Mapped[int] = mapped_column(ForeignKey('tariffs.id'))
    period_days: Mapped[int] = mapped_column(Integer)
    gifter_user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'))
    redeemed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReferralEarning(TimestampMixin, Base):
    __tablename__ = 'referral_earnings'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)  # реферер
    source_user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'))  # кто оплатил
    payment_id: Mapped[int | None] = mapped_column(ForeignKey('payments.id'), nullable=True)
    amount_kopeks: Mapped[int] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(32))  # purchase|topup


class SupportMessage(Base):
    __tablename__ = 'support_messages'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    direction: Mapped[str] = mapped_column(String(8))  # in|out
    body: Mapped[str] = mapped_column(Text)
    admin_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # id пересланного сообщения в админ-чате, для reply-роутинга
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CabinetRefreshToken(Base):
    """Задел под Mini App (этап 2) — не используется, пока CABINET_ENABLED=false."""

    __tablename__ = 'cabinet_refresh_tokens'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    token_hash: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ServerSquad(Base):
    __tablename__ = 'server_squads'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    squad_uuid: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    country: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class BotSetting(Base):
    __tablename__ = 'bot_settings'

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
