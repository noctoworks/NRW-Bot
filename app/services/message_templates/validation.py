"""Проверки шаблона сообщения при сохранении (одни и те же для API и редактора в боте)."""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser

from app.services.message_templates.registry import EventDef
from app.services.message_templates.render import PLACEHOLDER_RE, find_placeholders, render_template

# Теги, которые поддерживает HTML-режим Telegram (https://core.telegram.org/bots/api#html-style).
ALLOWED_TAGS = frozenset(
    {'b', 'strong', 'i', 'em', 'u', 'ins', 's', 'strike', 'del', 'a', 'code', 'pre', 'tg-spoiler', 'blockquote', 'tg-emoji'}
)
ALLOWED_LINK_PREFIXES = ('https://', 'http://', 'tg://')
MAX_TEXT_LENGTH = 4096  # лимит Telegram на длину видимого текста сообщения
MAX_BUTTON_LENGTH = 64


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    visible_length: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors


class _MarkupChecker(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.errors: list[str] = []
        self.text: list[str] = []
        self.has_emoji = False

    def _error(self, message: str) -> None:
        if message not in self.errors:
            self.errors.append(message)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in ALLOWED_TAGS:
            self._error(f'Тег <{tag}> не поддерживается Telegram. Разрешены: {", ".join(sorted(ALLOWED_TAGS))}.')
            return
        attributes = dict(attrs)
        if tag == 'a':
            href = (attributes.get('href') or '').strip()
            if not href.lower().startswith(ALLOWED_LINK_PREFIXES):
                self._error('У ссылки <a> нужен href, начинающийся с https://, http:// или tg://.')
            extra = set(attributes) - {'href'}
        elif tag == 'tg-emoji':
            self.has_emoji = True
            emoji_id = attributes.get('emoji-id') or ''
            if not emoji_id.isdigit():
                self._error('У <tg-emoji> нужен атрибут emoji-id из цифр (ID кастомного эмодзи).')
            extra = set(attributes) - {'emoji-id'}
        elif tag == 'blockquote':
            extra = set(attributes) - {'expandable'}
        else:
            extra = set(attributes)
        if extra:
            self._error(f'У тега <{tag}> не поддерживаются атрибуты: {", ".join(sorted(extra))}.')
        self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag not in ALLOWED_TAGS:
            self._error(f'Тег </{tag}> не поддерживается Telegram.')
        elif not self.stack or self.stack[-1] != tag:
            self._error(f'Лишний или неправильно вложенный закрывающий тег </{tag}>.')
        else:
            self.stack.pop()

    def handle_data(self, data: str) -> None:
        self.text.append(data)

    def finish(self) -> None:
        self.close()
        if self.stack:
            self._error('Не закрыты теги: ' + ', '.join(f'<{tag}>' for tag in self.stack) + '.')


def validate_template(event: EventDef, template: str) -> ValidationResult:
    result = ValidationResult()

    # 1. Фигурные скобки допустимы только в виде известных переменных.
    if '{' in PLACEHOLDER_RE.sub('', template) or '}' in PLACEHOLDER_RE.sub('', template):
        result.errors.append('Фигурные скобки допустимы только для переменных вида {имя} (строчные латинские буквы и _).')

    # 2. Переменные события.
    used = find_placeholders(template)
    allowed = event.variable_names
    unknown = [name for name in used if name not in allowed]
    if unknown:
        listing = ', '.join('{' + name + '}' for name in allowed)
        for name in unknown:
            if allowed:
                result.errors.append('Неизвестная переменная {' + name + '}. Доступны: ' + listing + '.')
            else:
                result.errors.append('Неизвестная переменная {' + name + '}: в этом сообщении нет переменных.')
    for name in event.required_variables:
        if name not in used:
            result.errors.append('Переменная {' + name + '} обязательна и должна быть в тексте.')

    # 3. Разметка и длина — на тексте с примерами значений (значения экранируются, тегов не добавят).
    checker = _MarkupChecker()
    checker.feed(render_template(template, event.samples()))
    checker.finish()
    result.errors.extend(error for error in checker.errors if error not in result.errors)

    visible = ''.join(checker.text)
    result.visible_length = len(visible)
    if '<' in visible:
        result.errors.append('Символ < в обычном тексте нужно писать как &lt; (и > как &gt;).')
    if not visible.strip():
        result.errors.append('Текст не может быть пустым.')
    if result.visible_length > MAX_TEXT_LENGTH:
        result.errors.append(f'Слишком большая длина: {result.visible_length} символов, максимум {MAX_TEXT_LENGTH}.')

    if checker.has_emoji:
        result.warnings.append(
            'В тексте есть кастомные эмодзи: Telegram проверяет их только при отправке — нажмите «Тест». '
            'Если эмодзи окажется недопустимым, пользователь получит заводской текст.'
        )
    return result


def validate_button_text(event: EventDef, text: str) -> list[str]:
    if not event.has_button:
        return ['У этого сообщения нет кнопки.']
    errors: list[str] = []
    stripped = text.strip()
    if not stripped:
        errors.append('Подпись кнопки не может быть пустой.')
    if len(stripped) > MAX_BUTTON_LENGTH:
        errors.append(f'Подпись кнопки слишком длинная: {len(stripped)} символов, максимум {MAX_BUTTON_LENGTH}.')
    if any(char in stripped for char in '<>&{}'):
        errors.append('В подписи кнопки нельзя использовать разметку и переменные (в том числе кастомные эмодзи).')
    return errors
