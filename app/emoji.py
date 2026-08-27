"""Кастомные эмодзи (Bot API premium custom emoji, см. диалог).

Требование (подтверждено): у ВЛАДЕЛЬЦА бота — аккаунта, из-под которого бот создан
в @BotFather, — должен быть Telegram Premium. Сам бот "премиума" не имеет, это
свойство человека-владельца. Без Premium у владельца отправка custom_emoji_id
в сообщении будет отклонена Telegram с ошибкой.

Каждый слот ниже — Emoji(fallback, custom_id). Пока custom_id не задан — рендерится
обычный fallback-эмодзи (текущее поведение, доступно всем, не требует Premium).
Как только вы пришлёте реальные custom_emoji_id (см. /emojiid в боте, app/handlers/admin.py) —
проставьте их сюда, и слот начнёт рендериться премиальной анимированной иконкой.

custom-эмодзи в тексте СООБЩЕНИЯ (обычный HTML parse_mode и Rich Message — оба
поддерживают <tg-emoji>) — через Emoji.html()/__str__() ниже.

В ТЕКСТЕ inline-кнопок кастомный эмодзи по-прежнему нельзя (текст кнопки —
обычная строка, никаких сущностей/разметки Bot API туда не пускает) — но у
самой кнопки есть ОТДЕЛЬНОЕ поле icon_custom_emoji_id (Bot API, см. диалог
"давай поставим кастомные эмодзи на кнопках") — маленькая иконка ПЕРЕД текстом
кнопки, не замена символа внутри текста. Те же условия Premium у владельца
бота, что и для <tg-emoji>. Используйте icon_button() ниже вместо ручной
сборки InlineKeyboardButton, когда нужен именно этот кейс.

ЕЩЁ ВАЖНЕЕ (найдено вживую при подключении первых трёх ID, см. диалог): Telegram
требует, чтобы fallback-символ внутри <tg-emoji> ТОЧНО совпадал с "родным" эмодзи
конкретного custom_emoji_id — иначе `RICH_MESSAGE_EMOJI_INVALID`/`ENTITY_TEXT_INVALID`.
Не угадывать fallback самостоятельно — перед добавлением нового ID сверяться через
`bot.get_custom_emoji_stickers(custom_emoji_ids=[...])` и брать оттуда `.emoji` как есть.
Для icon_custom_emoji_id такого сопоставления не требуется (это отдельная иконка,
не привязанная к конкретному символу в тексте), но лишним не будет проверить тем
же способом, что ID вообще существует и не был удалён/просрочен.
"""

from __future__ import annotations

from dataclasses import dataclass

from aiogram.types import InlineKeyboardButton


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


def icon_button(text: str, emoji: Emoji, **kwargs: object) -> InlineKeyboardButton:
    """Кнопка с кастомной иконкой перед текстом, если у emoji задан custom_id
    (icon_custom_emoji_id) — иначе обычный fallback-символ, приклеенный к
    тексту (текущее поведение для всех, у кого ID ещё не проставлен). `text`
    передавайте БЕЗ эмодзи в начале — его подставляет сама функция, в том или
    ином виде. `**kwargs` — остальные поля InlineKeyboardButton (callback_data/
    web_app/url/...), как в обычном конструкторе."""
    if emoji.custom_id:
        return InlineKeyboardButton(text=text, icon_custom_emoji_id=emoji.custom_id, **kwargs)
    return InlineKeyboardButton(text=f'{emoji.fallback} {text}', **kwargs)


# === Слоты, используемые в карточке подписки (app/handlers/subscription.py) ===
GLOBE = Emoji(fallback='🌐')
HOURGLASS = Emoji(fallback='⏳')
CALENDAR = Emoji(fallback='📅')
CHART = Emoji(fallback='📊')
MONEY = Emoji(fallback='💰')
EXPIRED = Emoji(fallback='⛔')
SUCCESS = Emoji(fallback='✅')

# === Способы оплаты — используются и в тексте (PAYMENT_METHODS_RICH), и на
# кнопках выбора способа оплаты (через icon_button(), см. kb_payment_methods
# в handlers/subscription.py и kb_payment_method в handlers/gift.py). ===
SBP = Emoji(fallback='🏦', custom_id='5368446439800197476')  # СБП (Платега)
STARS = Emoji(fallback='⭐️', custom_id='5321485469249198987')  # Telegram Stars
TON = Emoji(fallback='💎')  # custom_id ещё не пришёл — пока обычный fallback

# === Главное меню (app/keyboards/main_menu.py) — только на кнопках, через
# icon_button(). custom_id присланы и сверены через bot.get_custom_emoji_stickers
# (родные эмодзи совпали с fallback ниже). ===
MENU_SUBSCRIPTION = Emoji(fallback='🌐', custom_id='5879585266426973039')  # "Моя подписка"
MENU_RENEW = Emoji(fallback='💎', custom_id='5807465992363710697')  # "Продлить подписку"
MENU_GIFT = Emoji(fallback='🎁', custom_id='6032937473162614352')  # "Подарить подписку"
MENU_REFERRAL = Emoji(fallback='👥', custom_id='5944970130554359187')  # "Пригласить"
MENU_SUPPORT = Emoji(fallback='✉️', custom_id='5967280668885913944')  # "Поддержка"
MENU_PROXY = Emoji(fallback='⚡️', custom_id='5456140674028019486')  # "Прокси"
