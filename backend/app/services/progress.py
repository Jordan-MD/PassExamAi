import uuid
import logging
from fastapi import APIRouter, Depends, HTTPException
from app.core.deps import get_current_user
from app.db.supabase_client import supabase
from pydantic import BaseModel
from typing import Optional

router = APIRouter()
logger = logging.getLogger(__name__)


class ProgressSchema(BaseModel):
    chapter_id: uuid.UUID
    chapter_title: str
    chapter_order: int
    completion_status: str
    last_seen_at: Optional[str] = None


class ProjectProgressSummary(BaseModel):
    project_id: uuid.UUID
    total_chapters: int
    completed_chapters: int
    in_progress_chapters: int
    completion_percentage: float
    chapters: list[ProgressSchema]


@router.get(
    "",
    response_model=ProjectProgressSummary,
    summary="Progression complète d'un projet",
)
async def get_progress(
    project_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["user_id"]

    # Vérifie ownership
    project = (
        supabase.table("projects")
        .select("id")
        .eq("id", str(project_id))
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    if not project.data:
        raise HTTPException(status_code=404, detail="Projet introuvable")

    # Récupère la roadmap active
    roadmap = (
        supabase.table("roadmaps")
        .select("id")
        .eq("project_id", str(project_id))
        .eq("status", "ready")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not roadmap.data:
        return ProjectProgressSummary(
            project_id=project_id,
            total_chapters=0,
            completed_chapters=0,
            in_progress_chapters=0,
            completion_percentage=0.0,
            chapters=[],
        )

    roadmap_id = roadmap.data[0]["id"]

    # Récupère tous les chapitres avec leur progression
    chapters_result = (
        supabase.table("chapters")
        .select("id, title, order_index, status")
        .eq("roadmap_id", roadmap_id)
        .order("order_index")
        .execute()
    )

    # Récupère la progression utilisateur
    progress_result = (
        supabase.table("progress")
        .select("chapter_id, completion_status, last_seen_at")
        .eq("user_id", user_id)
        .execute()
    )
    progress_map = {
        str(p["chapter_id"]): p for p in (progress_result.data or [])
    }

    chapters = []
    completed = 0
    in_progress = 0

    for ch in (chapters_result.data or []):
        ch_id = str(ch["id"])
        prog = progress_map.get(ch_id)

        # Statut priorité : table progress > table chapters
        comp_status = (
            prog["completion_status"] if prog else ch.get("status", "locked")
        )

        if comp_status == "completed":
            completed += 1
        elif comp_status == "in_progress":
            in_progress += 1

        chapters.append(ProgressSchema(
            chapter_id=uuid.UUID(ch["id"]),
            chapter_title=ch["title"],
            chapter_order=ch["order_index"],
            completion_status=comp_status,
            last_seen_at=prog["last_seen_at"] if prog else None,
        ))

    total = len(chapters)
    pct = (completed / total * 100) if total > 0 else 0.0

    return ProjectProgressSummary(
        project_id=project_id,
        total_chapters=total,
        completed_chapters=completed,
        in_progress_chapters=in_progress,
        completion_percentage=round(pct, 1),
        chapters=chapters,
    )