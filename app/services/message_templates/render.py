"""Подстановка переменных {имя} в шаблон сообщения.

Значения экранируются как HTML (бот шлёт сообщения с parse_mode=HTML): имя пользователя с `<`
или `&` не должно ломать разметку. Сам шаблон — доверенная разметка владельца (её проверяет
validation.py при сохранении)."""

from __future__ import annotations

import html
import re
from collections.abc import Mapping

PLACEHOLDER_RE = re.compile(r'\{([a-z_]+)\}')


def find_placeholders(template: str) -> list[str]:
    """Имена переменных в порядке появления, без повторов."""
    return list(dict.fromkeys(PLACEHOLDER_RE.findall(template)))


def render_template(template: str, variables: Mapping[str, object]) -> str:
    """Однопроходная подстановка: подставленное значение повторно не разбирается.
    Неизвестные имена остаются как есть (валидный шаблон их не содержит)."""

    def replace(match: re.Match) -> str:
        name = match.group(1)
        if name not in variables:
            return match.group(0)
        return html.escape(str(variables[name]), quote=True)

    return PLACEHOLDER_RE.sub(replace, template)
