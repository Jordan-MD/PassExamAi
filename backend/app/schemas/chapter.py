from pydantic import BaseModel, Field
from typing import Optional, Literal
import uuid

ChapterStatus = Literal["locked", "available", "in_progress", "completed"]

class ChapterSchema(BaseModel):
    id: Optional[uuid.UUID] = None
    roadmap_id: Optional[uuid.UUID] = None
    order_index: int
    title: str
    objective: str
    importance: float = Field(default=1.0, ge=0.0, le=3.0)
    status: ChapterStatus = "locked"
# NEW: Tracking the evaluation
    mini_exam_id: Optional[uuid.UUID] = None
    last_exam_score: Optional[float] = None # Score obtained by the student
    passing_score: float = Field(default=70.0, ge=0.0, le=100.0) # Required score to unlock next chapter    