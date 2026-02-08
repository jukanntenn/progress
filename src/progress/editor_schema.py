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


class SectionSchema(BaseModel):
    id: str
    title: str
    description: str = ""
    fields: list[FieldSchema]


class EditorSchema(BaseModel):
    sections: list[SectionSchema]
