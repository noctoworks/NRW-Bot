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

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    # --- Telegram ---
    BOT_TOKEN: str
    BOT_USERNAME: str = ''
    ADMIN_TELEGRAM_IDS: str = ''  # CSV, напр. "123,456"

    # --- Database ---
    DATABASE_URL: str = 'sqlite+aiosqlite:///./bot.db'

    # --- Redis ---
    REDIS_URL: str = ''

    # --- Cabinet (Mini App), подключаем на отдельном этапе ---
    CABINET_ENABLED: bool = False
    CABINET_JWT_SECRET: str = ''
    CABINET_ALLOWED_ORIGINS: str = ''

    # --- Remnawave ---
    REMNAWAVE_MODE: Literal['mock', 'real'] = 'mock'
    REMNAWAVE_BASE_URL: str = ''
    REMNAWAVE_API_KEY: str = ''

    # --- Платежи ---
    PAYMENTS_MODE: Literal['stub', 'real'] = 'stub'
    YOOKASSA_SHOP_ID: str = ''
    YOOKASSA_SECRET_KEY: str = ''
    CRYPTOBOT_API_TOKEN: str = ''

    # --- Реферальная программа ---
    REFERRAL_PERCENT: int = Field(default=25, ge=0, le=100)

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
            (self.YOOKASSA_SHOP_ID and self.YOOKASSA_SECRET_KEY) or self.CRYPTOBOT_API_TOKEN
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
