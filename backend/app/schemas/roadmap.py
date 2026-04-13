from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
import uuid

ChapterStatus = str  # 'locked' | 'available' | 'in_progress' | 'completed'


class ChapterSchema(BaseModel):
    id: Optional[uuid.UUID] = None
    roadmap_id: Optional[uuid.UUID] = None
    order_index: int
    title: str
    objective: str
    importance: float = Field(default=1.0, ge=0.0, le=3.0)
    status: ChapterStatus = "locked"


class RoadmapSchema(BaseModel):
    id: Optional[uuid.UUID] = None
    project_id: uuid.UUID
    title: str
    status: str = "generating"
    chapters: List[ChapterSchema] = []
    doc_content_hash: Optional[str] = None
    created_at: Optional[datetime] = None


class RoadmapGenerateRequest(BaseModel):
    project_id: uuid.UUID