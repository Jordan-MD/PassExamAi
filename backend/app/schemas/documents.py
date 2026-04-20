from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime
import uuid
 
# ---------- Enums ----------
DocumentStatus = Literal[
    "uploaded", "parsing", "chunking", "embedding", "ready", "failed"
]
DocumentSourceType = Literal["exam", "syllabus", "notes", "reference"]


# ---------- Request ----------
class DocumentIngestRequest(BaseModel):
    storage_url: str = Field(..., description="URL Supabase Storage du PDF uploadé")
    filename: str
    project_id: uuid.UUID
    source_type: DocumentSourceType = "notes"


# ---------- Response ----------
class DocumentIngestResponse(BaseModel):
    document_id: uuid.UUID
    job_id: str
    status: DocumentStatus = "uploaded"
    message: str = "Ingestion démarrée en arrière-plan"


class DocumentStatusResponse(BaseModel):
    document_id: uuid.UUID
    status: DocumentStatus
    chunks_count: int = 0
    error_message: Optional[str] = None
    filename: str


class DocumentSchema(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    filename: str
    storage_url: str
    source_type: DocumentSourceType
    status: DocumentStatus
    chunks_count: int = 0
    created_at: Optional[datetime] = None


# ---------- Chunk (usage interne RAG) ----------
class ChunkMetadata(BaseModel):
    document_id: str
    project_id: str
    page_number: Optional[int] = None
    section_title: Optional[str] = None
    chapter_hint: Optional[str] = None
    source_type: DocumentSourceType = "notes"
    chunk_index: int


class DocumentChunk(BaseModel):
    content: str
    metadata: ChunkMetadata
    embedding: Optional[list[float]] = None