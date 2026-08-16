"""Кастомные эмодзи (Bot API premium custom emoji, см. диалог).

Требование (подтверждено): у ВЛАДЕЛЬЦА бота — аккаунта, из-под которого бот создан
в @BotFather, — должен быть Telegram Premium. Сам бот "премиума" не имеет, это
свойство человека-владельца. Без Premium у владельца отправка custom_emoji_id
в сообщении будет отклонена Telegram с ошибкой.

Каждый слот ниже — Emoji(fallback, custom_id). Пока custom_id не задан — рендерится
обычный fallback-эмодзи (текущее поведение, доступно всем, не требует Premium).
Как только вы пришлёте реальные custom_emoji_id (см. /emojiid в боте, app/handlers/admin.py) —
проставьте их сюда, и слот начнёт рендериться премиальной анимированной иконкой.

ВАЖНО: custom-эмодзи работают только в тексте СООБЩЕНИЯ (обычный HTML parse_mode
и Rich Message — оба поддерживают <tg-emoji>), но НЕ в тексте inline-кнопок —
это ограничение самого Bot API, не наше.

ЕЩЁ ВАЖНЕЕ (найдено вживую при подключении первых трёх ID, см. диалог): Telegram
требует, чтобы fallback-символ внутри <tg-emoji> ТОЧНО совпадал с "родным" эмодзи
конкретного custom_emoji_id — иначе `RICH_MESSAGE_EMOJI_INVALID`/`ENTITY_TEXT_INVALID`.
Не угадывать fallback самостоятельно — перед добавлением нового ID сверяться через
`bot.get_custom_emoji_stickers(custom_emoji_ids=[...])` и брать оттуда `.emoji` как есть.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Emoji:
    fallback: str
    custom_id: str | None = None

    def html(self) -> str:
        if self.custom_id:
            return f'<tg-emoji emoji-id="{self.custom_id}">{self.fallback}</tg-emoji>'
        return self.fallback

    def __str__(self) -> str:  # удобно использовать прямо в f-строках
        return self.html()


# === Слоты, используемые в карточке подписки (app/handlers/subscription.py) ===
GLOBE = Emoji(fallback='🌐')
HOURGLASS = Emoji(fallback='⏳')
CALENDAR = Emoji(fallback='📅')
CHART = Emoji(fallback='📊')
MONEY = Emoji(fallback='💰')
EXPIRED = Emoji(fallback='⛔')
SUCCESS = Emoji(fallback='✅')

# === Способы оплаты — присланы и проверены вживую (см. диалог), используются
# только в ТЕКСТЕ (описание/подтверждение выбранного способа), НЕ в кнопках. ===
SBP = Emoji(fallback='🏦', custom_id='5368446439800197476')  # СБП (Платега)
CRYPTO = Emoji(fallback='🪙', custom_id='5398080099234886346')  # Криптовалюта
STARS = Emoji(fallback='⭐️', custom_id='5321485469249198987')  # Telegram Stars
