"""Схемы документов заявки."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.enums import DocType


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    doc_type: DocType
    filename: str
    size_bytes: int
    uploaded_at: datetime
