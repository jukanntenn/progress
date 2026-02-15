from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class FieldSchema(BaseModel):
    type: str
    path: str
    label: str
    help_text: Optional[str] = None
    required: bool = False
    default: Any = None
    options: list[str] = []
    validation: dict[str, Any] = {}
    item_label: Optional[str] = None
    item_fields: Optional[list[FieldSchema]] = None
    discriminator: Optional[str] = None
    variants: Optional[dict[str, list[FieldSchema]]] = None


class SectionSchema(BaseModel):
    id: str
    title: str
    description: str = ""
    fields: list[FieldSchema]


class EditorSchema(BaseModel):
    sections: list[SectionSchema]
