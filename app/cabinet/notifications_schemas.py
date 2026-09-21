from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class VariableDocOut(BaseModel):
    name: str
    description: str
    example: str


class TemplateOut(BaseModel):
    key: str
    group: str
    title: str
    trigger: str
    template: str  # текущий текст: правка владельца либо заводской
    variables: list[str]
    default_template: str
    is_customized: bool
    enabled: bool
    button_text: str | None = None  # текущая подпись кнопки (None, если у события нет кнопки)
    default_button_text: str | None = None
    variable_docs: list[VariableDocOut]
    required_variables: list[str]
    updated_at: datetime | None = None
    updated_by: str | None = None


class TemplateUpdateRequest(BaseModel):
    """Частичное обновление: применяются только переданные поля. `template: null` возвращает заводской текст,
    `button_text: null` — заводскую подпись кнопки."""

    template: str | None = None
    button_text: str | None = None
    enabled: bool | None = None


class PreviewRequest(BaseModel):
    template: str | None = None  # None — текущий текст
    button_text: str | None = None  # None — текущая подпись


class PreviewResponse(BaseModel):
    html: str
    visible_length: int
    warnings: list[str]
    button_text: str | None = None


class EmojiOut(BaseModel):
    name: str
    fallback: str
    custom_id: str
