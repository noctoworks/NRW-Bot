from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class BroadcastTargetOut(BaseModel):
    key: str
    label: str
    recipient_count: int


class BroadcastTariffOut(BaseModel):
    id: int
    name: str
    recipient_count: int


class BroadcastButtonOut(BaseModel):
    key: str
    label: str


class BroadcastOptionsResponse(BaseModel):
    targets: list[BroadcastTargetOut]
    tariffs: list[BroadcastTariffOut]
    buttons: list[BroadcastButtonOut]


class BroadcastPreviewRequest(BaseModel):
    target: str


class BroadcastPreviewResponse(BaseModel):
    target_display_name: str
    recipient_count: int


class BroadcastCreateRequest(BaseModel):
    target: str
    text: str = Field(min_length=1, max_length=4000)
    media_type: str | None = None
    media_file_id: str | None = None
    buttons: list[str] = Field(default_factory=lambda: ['home'])


class BroadcastOut(BaseModel):
    id: int
    status: str
    target_type: str
    target_display_name: str
    total_count: int
    sent_count: int
    failed_count: int
    blocked_count: int
    has_media: bool
    media_type: str | None
    admin_name: str | None
    created_at: datetime
    completed_at: datetime | None


class BroadcastListResponse(BaseModel):
    items: list[BroadcastOut]
    total: int
    page: int
    total_pages: int
