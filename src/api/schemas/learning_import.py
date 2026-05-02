"""Pydantic schemas for the Learning Library bulk import API.

Position fields are intentionally absent from all import schemas.
The server auto-assigns position = array index for topics, sections, and items.
Any payload that includes a 'position' field will be rejected with 422 because
all models use ConfigDict(extra="forbid").
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ImportItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=240)


class ImportSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    items: list[ImportItem] = Field(default_factory=list, max_length=20)


class ImportMaterial(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1)
    source_type: str | None = Field(default=None, max_length=40)
    source_url: str | None = Field(default=None, max_length=2048)
    source_title: str | None = Field(default=None, max_length=240)
    metadata: dict[str, Any] | None = None


class ImportTopic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    depth: Literal["foundational", "deep"] = "foundational"
    sections: list[ImportSection] = Field(default_factory=list, max_length=20)
    material: ImportMaterial | None = None


class LearningImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topics: list[ImportTopic] = Field(min_length=1, max_length=50)


class ImportSkip(BaseModel):
    name: str
    reason: Literal["name_collision"]


class ImportResult(BaseModel):
    dry_run: bool
    topics_created: int
    sections_created: int
    items_created: int
    materials_created: int
    topics_skipped: list[ImportSkip]
    created_topic_ids: list[str]


class MaterialOut(BaseModel):
    id: str
    topic_id: str
    content: str
    source_type: str | None
    source_url: str | None
    source_title: str | None
    metadata: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class MaterialUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1)
    source_type: str | None = None
    source_url: str | None = None
    source_title: str | None = None
    metadata: dict[str, Any] | None = None
