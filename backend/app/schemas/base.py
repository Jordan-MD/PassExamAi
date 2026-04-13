from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
import uuid


class TimestampMixin(BaseModel):
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class UUIDMixin(BaseModel):
    id: Optional[uuid.UUID] = None