"""Единая точка конфигурации проекта.

Все настройки читаются из .env через pydantic-settings. Никаких секретов
с дефолтными значениями (кроме заведомо безопасных, например REFERRAL_PERCENT) —
см. memory/feedback про CABINET_JWT_SECRET у Bedolaga: там дефолтный fallback
на BOT_TOKEN был уязвимостью. Здесь такого нет: CABINET_JWT_SECRET обязателен,
как только CABINET_ENABLED=true (см. валидатор ниже).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    # --- Telegram ---
    BOT_TOKEN: str
    BOT_USERNAME: str = ''
    ADMIN_TELEGRAM_IDS: str = ''  # CSV, напр. "123,456"

    @field_validator('BOT_USERNAME')
    @classmethod
    def _strip_bot_username_at(cls, value: str) -> str:
        # BOT_USERNAME используется как есть в t.me/{BOT_USERNAME}?start=... по
        # всему проекту (referral.py, gift.py, cabinet/admin_routes.py) — с
        # ведущим '@' ссылка ломается (t.me/@name вместо t.me/name). Найдено
        # живьём: пользователь заполнил .env с '@', как принято в остальных
        # местах Telegram UI — нормализуем один раз здесь, а не в каждом
        # вызывающем месте.
        return value.lstrip('@')

    # --- Database ---
    DATABASE_URL: str = 'sqlite+aiosqlite:///./bot.db'

    # --- Redis ---
    REDIS_URL: str = ''

    # --- Cabinet (Mini App) ---
    CABINET_ENABLED: bool = False
    CABINET_JWT_SECRET: str = ''
    CABINET_ALLOWED_ORIGINS: str = ''
    CABINET_PORT: int = 8080
    # Публичный https-адрес задеплоенного Mini App — используется кнопкой
    # "Подключить VPN" в боте (WebAppInfo требует https). Пусто = кнопка
    # использует прежний прямой happ://-fallback (см. handlers/subscription.py).
    MINIAPP_URL: str = ''

    # --- Remnawave ---
    REMNAWAVE_MODE: Literal['mock', 'real'] = 'mock'
    REMNAWAVE_BASE_URL: str = ''
    REMNAWAVE_API_KEY: str = ''
    # Опционально: если nginx перед панелью настроен на "маскирование" (панель
    # Remnawave прячется за секретным query/cookie-параметром — без него nginx
    # рвёт соединение без ответа на ЛЮБОЙ путь, включая /api/*, что снаружи
    # выглядит как Cloudflare 520). Формат — как в query-строке: "key=value".
    # Найдено вживую в nginx-конфиге панели (map $arg_<KEY> ...) — если у вас
    # такого маскирования нет, оставьте пустым.
    REMNAWAVE_PANEL_SECRET_PARAM: str = ''

    # --- Платежи ---
    PAYMENTS_MODE: Literal['stub', 'real'] = 'stub'
    PLATEGA_MERCHANT_ID: str = ''
    PLATEGA_SECRET_KEY: str = ''
    PLATEGA_BASE_URL: str = 'https://app.platega.io'
    PLATEGA_API_VERSION: Literal['v1', 'v2'] = 'v1'
    # Непрозрачный код способа оплаты, который Platega выдаёт под конкретный мерчант-каскад
    # (СБП/карты/что-то ещё) — сверьте в личном кабинете Platega или у их поддержки,
    # значение по умолчанию НЕ гарантированно подходит именно вашему мерчанту.
    PLATEGA_PAYMENT_METHOD_CODE: int = 2
    CRYPTOBOT_API_TOKEN: str = ''

    # --- Курсы для отображения цены в других валютах на экране оплаты (см. диалог,
    # референс-скрин показывает цену сразу в $ и ★). ПРИБЛИЗИТЕЛЬНО — настройте под
    # актуальный курс, это только для отображения, не источник истины для реальных
    # платежей (когда подключим Platega/CryptoBot/Stars по-настоящему, конвертация
    # должна брать курс у самого провайдера, а не отсюда). ---
    USD_RATE_KOPEKS: int = 9000  # сколько копеек в $1 (по умолчанию ~90₽/$)
    STARS_RATE_KOPEKS: int = 100  # сколько копеек стоит 1 Telegram Star (по умолчанию 1₽/★, откалибровано под референс-скрин: 444₽ -> ★444)

    # --- Реферальная программа ---
    REFERRAL_PERCENT: int = Field(default=25, ge=0, le=100)
    # Двусторонний бонус (см. диалог "виральность"): раньше по реф-ссылке
    # приглашённый получал ровно тот же триал, что и любой другой новый
    # пользователь — перехода по ссылке друга он не чувствовал вообще, только
    # реферер что-то зарабатывал (REFERRAL_PERCENT). Эти дни добавляются
    # ПОВЕРХ обычного триала — только для новых юзеров, у кого распознан
    # ref_CODE при регистрации.
    REFERRAL_SIGNUP_BONUS_DAYS: int = Field(default=3, ge=0)

    # --- Сид-данные ---
    DEFAULT_TARIFF_NAME: str = 'Standard'

    @model_validator(mode='after')
    def _validate_dependent_secrets(self) -> 'Settings':
        if self.CABINET_ENABLED and not self.CABINET_JWT_SECRET:
            raise ValueError(
                'CABINET_ENABLED=true требует явного CABINET_JWT_SECRET. '
                'Никакого fallback на BOT_TOKEN не предусмотрено (осознанно).'
            )
        if self.REMNAWAVE_MODE == 'real' and not (self.REMNAWAVE_BASE_URL and self.REMNAWAVE_API_KEY):
            raise ValueError('REMNAWAVE_MODE=real требует REMNAWAVE_BASE_URL и REMNAWAVE_API_KEY')
        if self.PAYMENTS_MODE == 'real' and not (
            (self.PLATEGA_MERCHANT_ID and self.PLATEGA_SECRET_KEY) or self.CRYPTOBOT_API_TOKEN
        ):
            raise ValueError('PAYMENTS_MODE=real требует ключей хотя бы одного провайдера')
        return self

    def admin_ids(self) -> set[int]:
        return {int(x.strip()) for x in self.ADMIN_TELEGRAM_IDS.split(',') if x.strip()}

    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith('sqlite')


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
