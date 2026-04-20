import uuid
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from typing import Optional
from datetime import date, datetime

from app.core.deps import get_current_user
from app.services.project_service import ProjectService

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Schemas (inline car spécifiques à cette route) ────────────────────────────

class ProjectCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    subject: Optional[str] = None
    target_exam_type: Optional[str] = None
    deadline: Optional[date] = None
    hours_per_day: float = Field(default=2.0, ge=0.5, le=16.0)
    days_per_week: int = Field(default=5, ge=1, le=7)


class ProjectUpdateRequest(BaseModel):
    """Partial update — tous les champs optionnels."""
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    subject: Optional[str] = None
    target_exam_type: Optional[str] = None
    deadline: Optional[date] = None
    hours_per_day: Optional[float] = Field(None, ge=0.5, le=16.0)
    days_per_week: Optional[int] = Field(None, ge=1, le=7)


class ProjectSchema(BaseModel):
    id: uuid.UUID
    user_id: str
    title: str
    subject: Optional[str] = None
    target_exam_type: Optional[str] = None
    deadline: Optional[date] = None
    hours_per_day: Optional[float] = None
    days_per_week: Optional[int] = None
    created_at: Optional[datetime] = None


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("", response_model=ProjectSchema, status_code=status.HTTP_201_CREATED)
async def create_project(
    request: ProjectCreateRequest,
    current_user: dict = Depends(get_current_user),
):
    try:
        return ProjectService.create(
            user_id=current_user["user_id"],
            title=request.title,
            subject=request.subject,
            target_exam_type=request.target_exam_type,
            deadline=str(request.deadline) if request.deadline else None,
            hours_per_day=request.hours_per_day,
            days_per_week=request.days_per_week,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=list[ProjectSchema])
async def list_projects(current_user: dict = Depends(get_current_user)):
    return ProjectService.get_all_by_user(current_user["user_id"])


@router.get("/{project_id}", response_model=ProjectSchema)
async def get_project(
    project_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
):
    project = ProjectService.get_by_id(str(project_id), current_user["user_id"])
    if not project:
        raise HTTPException(status_code=404, detail="Projet introuvable")
    return project


@router.patch("/{project_id}", response_model=ProjectSchema)
async def update_project(
    project_id: uuid.UUID,
    request: ProjectUpdateRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Mise à jour partielle — seuls les champs fournis sont modifiés.
    Essentiel pour mettre à jour la deadline et le planning d'étude.
    """
    updated = ProjectService.update(
        project_id=str(project_id),
        user_id=current_user["user_id"],
        title=request.title,
        subject=request.subject,
        target_exam_type=request.target_exam_type,
        deadline=str(request.deadline) if request.deadline else None,
        hours_per_day=request.hours_per_day,
        days_per_week=request.days_per_week,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Projet introuvable")
    return updated


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
):
    deleted = ProjectService.delete(str(project_id), current_user["user_id"])
    if not deleted:
        raise HTTPException(status_code=404, detail="Projet introuvable")