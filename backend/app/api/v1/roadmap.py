import uuid
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from app.core.deps import get_current_user
from app.db.supabase_client import supabase
from app.ai.roadmap_generator import generate_roadmap, _db_to_roadmap_schema
from app.schemas.roadmap import RoadmapSchema, RoadmapGenerateRequest

router = APIRouter()
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# POST /roadmap/generate
# Lance la génération (peut prendre 10-30s)
# ─────────────────────────────────────────────
@router.post(
    "/generate",
    response_model=RoadmapSchema,
    summary="Génère la roadmap pour un projet (RAG + web enrichment)",
)
async def generate_roadmap_endpoint(
    request: RoadmapGenerateRequest,
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["user_id"]

    # Vérifie que le projet appartient à l'utilisateur
    project = (
        supabase.table("projects")
        .select("id")
        .eq("id", str(request.project_id))
        .eq("user_id", user_id)
        .single()
        .execute()
    )

    if not project.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Projet introuvable ou accès refusé",
        )

    try:
        roadmap = await generate_roadmap(
            project_id=str(request.project_id),
            user_id=user_id,
        )
        return roadmap

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Roadmap generation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la génération: {str(e)}",
        )


# ─────────────────────────────────────────────
# GET /roadmap/{id}
# Récupère une roadmap existante avec ses chapitres
# ─────────────────────────────────────────────
@router.get(
    "/{roadmap_id}",
    response_model=RoadmapSchema,
    summary="Récupère une roadmap et ses chapitres",
)
async def get_roadmap(
    roadmap_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
):
    result = (
        supabase.table("roadmaps")
        .select("*, chapters(*)")
        .eq("id", str(roadmap_id))
        .single()
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Roadmap introuvable")

    # Vérifie ownership via le projet
    project = (
        supabase.table("projects")
        .select("id")
        .eq("id", result.data["project_id"])
        .eq("user_id", current_user["user_id"])
        .single()
        .execute()
    )

    if not project.data:
        raise HTTPException(status_code=403, detail="Accès refusé")

    return _db_to_roadmap_schema(result.data)


# ─────────────────────────────────────────────
# GET /roadmap?project_id=...
# Liste les roadmaps d'un projet
# ─────────────────────────────────────────────
@router.get(
    "",
    response_model=list[RoadmapSchema],
    summary="Liste les roadmaps d'un projet",
)
async def list_roadmaps(
    project_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
):
    # Vérifie ownership
    project = (
        supabase.table("projects")
        .select("id")
        .eq("id", str(project_id))
        .eq("user_id", current_user["user_id"])
        .single()
        .execute()
    )

    if not project.data:
        raise HTTPException(status_code=404, detail="Projet introuvable")

    result = (
        supabase.table("roadmaps")
        .select("*, chapters(*)")
        .eq("project_id", str(project_id))
        .eq("status", "ready")
        .order("created_at", desc=True)
        .execute()
    )

    return [_db_to_roadmap_schema(row) for row in (result.data or [])]