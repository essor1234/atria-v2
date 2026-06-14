"""Artifact domain model."""

from __future__ import annotations
from typing import Any, Optional
from pydantic import BaseModel
import datetime


class Artifact(BaseModel):
    id: int
    is_deleted: bool = False
    created_at: datetime.datetime
    updated_at: Optional[datetime.datetime] = None
    project_id: Optional[int] = None
    conversation_id: Optional[int] = None
    type: str  # file | code | report | image | data
    source_mode: Optional[str] = None  # chat | auto | manual
    title: Optional[str] = None
    pinned: bool = False
    payload_ref: Optional[str] = None  # file path
    preview: Optional[Any] = None  # JSON preview data
    scope: Optional[str] = None  # conversation | project
    local_path: Optional[str] = None  # relative path to artifact file

    model_config = {"from_attributes": True}
