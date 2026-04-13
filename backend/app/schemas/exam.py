from pydantic import BaseModel, Field
from typing import Optional, List
import uuid
from app.schemas.exercise import QuestionType, MCQOption, RubricStep


class ExamQuestionSchema(BaseModel):
    id: Optional[uuid.UUID] = None
    chapter_id: Optional[uuid.UUID] = None
    question_type: QuestionType
    prompt: str
    options: Optional[List[MCQOption]] = None
    correct_answer: Optional[str] = None
    rubric: Optional[List[RubricStep]] = None
    points: float = 1.0
    order_index: int


class ExamSchema(BaseModel):
    id: Optional[uuid.UUID] = None
    roadmap_id: uuid.UUID
    title: str
    time_limit: Optional[int] = None      # Minutes
    question_count: int = 10
    questions: List[ExamQuestionSchema] = []


class ExamGenerateRequest(BaseModel):
    roadmap_id: uuid.UUID
    time_limit: Optional[int] = None
    question_count: int = 10


class SectionScore(BaseModel):
    chapter_id: str
    chapter_title: str
    score: float
    max_score: float


class ExamResult(BaseModel):
    submission_id: uuid.UUID
    total_score: float
    max_score: float
    percentage: float
    section_scores: List[SectionScore]
    feedback: str
    submitted_at: Optional[str] = None