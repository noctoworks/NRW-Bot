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
    # Перенесено из бэкапа старого бота (email/OAuth-логин в старой панели) —
    # новый бот его никак не использует (нет email-аутентификации), только хранит.
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Telegram full_name (first_name [+ last_name]) на момент регистрации — только
    # для случая, когда у пользователя нет @username. Не ресинкается (как и username).
    full_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    language: Mapped[str] = mapped_column(String(8), default='ru')

    balance_kopeks: Mapped[int] = mapped_column(BigInteger, default=0)

    referral_code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    referred_by_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    # Персональная переопределённая ставка реферала (0-100) — NULL значит "взять
    # settings.REFERRAL_PERCENT" (см. services/referral_service.py::credit_referral_earning).
    # Не 0 по умолчанию: 0 означало бы "начислять 0%", а не "используй глобальную".
    referral_commission_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)

    remnawave_uuid: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # Скидочный тир (см. PromoGroup ниже) — NULL значит "без скидки". Назначается
    # через /cabinet/admin/users/{id}/promo-group.
    promo_group_id: Mapped[int | None] = mapped_column(ForeignKey('promo_groups.id', ondelete='SET NULL'), nullable=True)
    # Пробный период уже использован — не выдаём повторно, даже если подписка
    # истекла и юзер обнулился по всем остальным полям.
    trial_used: Mapped[bool] = mapped_column(Boolean, default=False)

    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)

    # Для админ-панели (см. диалог "1:1 как у Bedolaga", §Фаза 2): последняя
    # активность обновляется в AuthMiddleware на каждом апдейте, используется для
    # "Онлайн сейчас/сегодня/за неделю" и "Последняя активность" в карточке юзера.
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Ставится, когда send_message падает с TelegramForbiddenError (юзер заблокировал
    # бота) — используется в разделе "Заблокировавшие бота" и при рассылках, чтобы не
    # тратить лишний запрос на заведомо недоступного получателя.
    blocked_bot: Mapped[bool] = mapped_column(Boolean, default=False)
    # Приветственный nudge (см. app/services/background.py::welcome_nudge_loop,
    # диалог 2026-08-21 "рассылки по событиям/напоминалки") — одно отложенное
    # сообщение через WELCOME_NUDGE_DELAY_HOURS после регистрации тем, кто ещё
    # не купил подписку. Дедупликация тем же паттерном, что reminder_3d_sent
    # у Subscription — иначе цикл слал бы его повторно на каждой итерации.
    welcome_nudge_sent: Mapped[bool] = mapped_column(Boolean, default=False)

    subscription: Mapped['Subscription | None'] = relationship(
        back_populates='user', uselist=False, cascade='all, delete-orphan'
    )
    referred_by: Mapped['User | None'] = relationship(remote_side=[id])
    promo_group: Mapped['PromoGroup | None'] = relationship()


class PromoGroup(TimestampMixin, Base):
    """Скидочный тир на юзера (см. диалог, портировано из Bedolaga упрощённо —
    там 3 отдельных процента под отдельные покупки трафика/устройств-аддонов,
    которых у нас нет; здесь один discount_percent на всю цену подписки)."""

    __tablename__ = 'promo_groups'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    discount_percent: Mapped[int] = mapped_column(Integer, default=0)


class Campaign(TimestampMixin, Base):
    """Маркетинговая кампания — deep-link /start <start_parameter> без префикса
    (в отличие от нашего ref_CODE/gift_CODE — не пересекается, см. диалог/Фаза 4
    и handlers/start.py::_parse_payload). Портировано из Bedolaga упрощённо: без
    партнёрской сети/affiliate click-id, bonus_type 'tariff' не заводим отдельно
    от 'subscription' — у нас один тариф, они совпадают."""

    __tablename__ = 'campaigns'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    start_parameter: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    bonus_type: Mapped[str] = mapped_column(String(16))  # balance|subscription|none
    balance_bonus_kopeks: Mapped[int] = mapped_column(BigInteger, default=0)
    subscription_duration_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class CampaignRegistration(Base):
    """Дедуп + учёт — ровно одна запись на юзера на кампанию (по факту у нас и
    так только новые юзеры попадают сюда, см. handlers/start.py, но constraint
    оставлен как страховка от повторного начисления)."""

    __tablename__ = 'campaign_registrations'
    __table_args__ = (UniqueConstraint('campaign_id', 'user_id', name='uq_campaign_user'),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey('campaigns.id', ondelete='CASCADE'), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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

    # Бесплатный пробный период (см. диалог, Фаза 3) — по умолчанию переиспользует
    # лимиты тарифа (traffic_limit_gb/device_limit/squad_uuids), только короче срок.
    # trial_squad_uuids/trial_traffic_limit_gb — необязательные оверрайды: если
    # заданы, триал-пользователя заводят в отдельный сквад (напр. "Trial") со
    # своим лимитом трафика вместо сквадов/лимита обычного тарифа (см. диалог:
    # отдельный сквад Trial + 15GB). Пустой список/NULL — старое поведение.
    trial_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    trial_period_days: Mapped[int] = mapped_column(Integer, default=3)
    trial_squad_uuids: Mapped[list] = mapped_column(JSON, default=list)
    trial_traffic_limit_gb: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Оверрайд лимита устройств для триала (см. trial_traffic_limit_gb выше) —
    # NULL значит "взять device_limit обычного тарифа".
    trial_device_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Subscription(TimestampMixin, Base):
    __tablename__ = 'subscriptions'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), unique=True)
    tariff_id: Mapped[int] = mapped_column(ForeignKey('tariffs.id'))

    status: Mapped[str] = mapped_column(String(16), default='active')  # active|expired|disabled
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    # True — выдана автовыдачей триала (start.py) или админом через "🎁 Триал"
    # (handlers/admin.py cb_user_grant_sub); сбрасывается в False реальной оплатой
    # (subscription.py, services/payment_finalization.py). Продление бесплатными
    # днями (реферал/подарок/промокод/кампания) флаг НЕ трогает — см.
    # subscription_provisioning.py::provision_or_extend_subscription(is_trial=None).
    is_trial: Mapped[bool] = mapped_column(Boolean, default=False)

    traffic_limit_gb: Mapped[int] = mapped_column(BigInteger, default=0)
    traffic_used_gb: Mapped[float] = mapped_column(default=0)
    device_limit: Mapped[int] = mapped_column(Integer, default=3)

    subscription_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    short_uuid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    autopay_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Platega subscriptionId (их transactionId из ответа create_subscription) —
    # нужен, чтобы отменить подписку (POST /subscription/{id}/cancel) и сверять
    # входящие callback'и (SubscriptionId в теле) с конкретной записью. NULL,
    # пока автоплатёж не включён либо после отмены/PastDue.
    platega_subscription_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Дедупликация плановых напоминаний об истечении (§12а архитектурного документа)
    reminder_3d_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    reminder_1d_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    # Win-back после истечения (см. app/services/background.py::winback_loop,
    # диалог 2026-08-21) — одно сообщение через WINBACK_DELAY_DAYS после
    # end_date тем, кто не продлил. Сбрасывается в False при каждом продлении
    # (provision_or_extend_subscription) — так же, как reminder_3d/1d_sent —
    # иначе после следующего истечения win-back уже не пришлёт себя снова.
    winback_sent: Mapped[bool] = mapped_column(Boolean, default=False)

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

    provider: Mapped[str] = mapped_column(String(32))  # stars|platega|ton|stub
    external_id: Mapped[str] = mapped_column(String(128))
    amount_kopeks: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16), default='pending')  # pending|success|failed
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    # Незавершённая покупка (см. app/services/background.py::payment_poll_loop,
    # диалог 2026-08-21) — одно напоминание, если платёж всё ещё pending спустя
    # ABANDONED_PAYMENT_DELAY_MINUTES. Не трогаем сам платёж/его status —
    # только дедупликация напоминания, поллинг статуса продолжается как раньше.
    abandoned_reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False)


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


class SupportTicket(Base):
    """Тикет поддержки — одна переписка юзера с поддержкой. status='open' пока
    юзер/админ не закроют явно (закрытие — только из MiniApp-админки, см.
    app/cabinet/admin_routes.py). assigned_admin_* — «застолбил» тикет тот
    админ, кто ответил первым (паттерн как у BroadcastHistory.admin_id/admin_name
    ниже), это не жёсткий лок — остальные админы всё равно видят и могут
    ответить, просто в шапке пересланного сообщения видно, кто уже ведёт."""

    __tablename__ = 'support_tickets'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    status: Mapped[str] = mapped_column(String(16), default='open')  # open|closed
    assigned_admin_id: Mapped[int | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    assigned_admin_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SupportMessage(Base):
    __tablename__ = 'support_messages'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('support_tickets.id', ondelete='CASCADE'), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    direction: Mapped[str] = mapped_column(String(8))  # in|out
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SupportMessageDelivery(Base):
    """Кому из админов и под каким message_id переслано конкретное входящее
    сообщение — нужно, чтобы reply-роутинг (on_admin_reply) работал для ЛЮБОГО
    админа, а не только для первого в ADMIN_TELEGRAM_IDS (старое ограничение,
    см. app/handlers/support.py)."""

    __tablename__ = 'support_message_deliveries'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    support_message_id: Mapped[int] = mapped_column(ForeignKey('support_messages.id', ondelete='CASCADE'), index=True)
    admin_telegram_id: Mapped[int] = mapped_column(BigInteger)
    admin_message_id: Mapped[int] = mapped_column(BigInteger)


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


class BroadcastHistory(Base):
    """Перенесено из реального модуля рассылок Bedolaga (см. диалог "берём как есть") —
    структура полей 1:1, кроме отсутствующих у нас полей (email-only рассылки,
    категории уведомлений) — их не завели, у нас нет соответствующих концепций."""

    __tablename__ = 'broadcast_history'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_type: Mapped[str] = mapped_column(String(64))
    message_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    has_media: Mapped[bool] = mapped_column(Boolean, default=False)
    media_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    media_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    media_caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    sent_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    blocked_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default='in_progress')  # in_progress|completed|partial
    admin_id: Mapped[int | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    admin_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
