import uuid
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from app.core.deps import get_current_user
from app.db.supabase_client import supabase
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

router = APIRouter()
logger = logging.getLogger(__name__)


class ProjectCreateRequest(BaseModel):
    title: str
    subject: Optional[str] = None
    target_exam_type: Optional[str] = None


class ProjectSchema(BaseModel):
    id: uuid.UUID
    user_id: str
    title: str
    subject: Optional[str] = None
    target_exam_type: Optional[str] = None
    created_at: Optional[datetime] = None


@router.post(
    "",
    response_model=ProjectSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Crée un nouveau projet",
)
async def create_project(
    request: ProjectCreateRequest,
    current_user: dict = Depends(get_current_user),
):
    result = supabase.table("projects").insert({
        "user_id": current_user["user_id"],
        "title": request.title,
        "subject": request.subject,
        "target_exam_type": request.target_exam_type,
    }).execute()

    if not result.data:
        raise HTTPException(status_code=500, detail="Erreur création projet")

    return result.data[0]


@router.get(
    "",
    response_model=list[ProjectSchema],
    summary="Liste les projets de l'utilisateur",
)
async def list_projects(current_user: dict = Depends(get_current_user)):
    result = (
        supabase.table("projects")
        .select("*")
        .eq("user_id", current_user["user_id"])
        .order("created_at", desc=True)
        .execute()
    )
    return result.data or []


@router.get(
    "/{project_id}",
    response_model=ProjectSchema,
    summary="Récupère un projet par ID",
)
async def get_project(
    project_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
):
    result = (
        supabase.table("projects")
        .select("*")
        .eq("id", str(project_id))
        .eq("user_id", current_user["user_id"])
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Projet introuvable")
    return result.data


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
):
    result = (
        supabase.table("projects")
        .select("id")
        .eq("id", str(project_id))
        .eq("user_id", current_user["user_id"])
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Projet introuvable")

    supabase.table("projects").delete().eq("id", str(project_id)).execute()