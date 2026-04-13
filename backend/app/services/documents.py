import uuid
import logging
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException, status
from app.core.deps import get_current_user
from app.db.supabase_client import supabase
from app.rag.ingestion import run_ingestion_pipeline
from app.schemas.documents import (
    DocumentIngestRequest,
    DocumentIngestResponse,
    DocumentStatusResponse,
    DocumentSchema,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# POST /documents/ingest
# Lance l'ingestion en arrière-plan
# ─────────────────────────────────────────────
@router.post(
    "/ingest",
    response_model=DocumentIngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Lance l'ingestion d'un document PDF",
)
async def ingest_document(
    request: DocumentIngestRequest,
    background_tasks: BackgroundTasks,
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

    # Crée l'entrée document en DB avec status 'uploaded'
    doc_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())

    supabase.table("uploaded_documents").insert({
        "id": doc_id,
        "project_id": str(request.project_id),
        "filename": request.filename,
        "storage_url": request.storage_url,
        "source_type": request.source_type,
        "status": "uploaded",
    }).execute()

    # Lance le pipeline en arrière-plan (non bloquant)
    background_tasks.add_task(
        run_ingestion_pipeline,
        document_id=doc_id,
        storage_url=request.storage_url,
        project_id=str(request.project_id),
        source_type=request.source_type,
        filename=request.filename,
    )

    logger.info(f"Ingestion lancée: doc_id={doc_id}, user={user_id}")

    return DocumentIngestResponse(
        document_id=uuid.UUID(doc_id),
        job_id=job_id,
        status="uploaded",
        message="Ingestion démarrée. Polllez GET /documents/{id}/status",
    )


# ─────────────────────────────────────────────
# GET /documents/{id}/status
# Polled par le frontend toutes les 3 secondes
# ─────────────────────────────────────────────
@router.get(
    "/{document_id}/status",
    response_model=DocumentStatusResponse,
    summary="Statut de l'ingestion (à poller)",
)
async def get_document_status(
    document_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
):
    response = (
        supabase.table("uploaded_documents")
        .select("id, status, chunks_count, error_message, filename, project_id")
        .eq("id", str(document_id))
        .single()
        .execute()
    )

    if not response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document introuvable",
        )

    doc = response.data

    # Vérifie que le document appartient à l'utilisateur (via le projet)
    project = (
        supabase.table("projects")
        .select("id")
        .eq("id", doc["project_id"])
        .eq("user_id", current_user["user_id"])
        .single()
        .execute()
    )

    if not project.data:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès refusé",
        )

    return DocumentStatusResponse(
        document_id=uuid.UUID(doc["id"]),
        status=doc["status"],
        chunks_count=doc.get("chunks_count", 0),
        error_message=doc.get("error_message"),
        filename=doc["filename"],
    )


# ─────────────────────────────────────────────
# GET /documents?project_id=...
# ─────────────────────────────────────────────
@router.get(
    "",
    response_model=list[DocumentSchema],
    summary="Liste les documents d'un projet",
)
async def list_documents(
    project_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
):
    # Vérifie ownership du projet
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

    docs = (
        supabase.table("uploaded_documents")
        .select("*")
        .eq("project_id", str(project_id))
        .order("created_at", desc=True)
        .execute()
    )

    return docs.data or []


# ─────────────────────────────────────────────
# DELETE /documents/{id}
# ─────────────────────────────────────────────
@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
):
    # Vérifie ownership avant suppression
    doc = (
        supabase.table("uploaded_documents")
        .select("id, project_id, storage_url")
        .eq("id", str(document_id))
        .single()
        .execute()
    )

    if not doc.data:
        raise HTTPException(status_code=404, detail="Document introuvable")

    project = (
        supabase.table("projects")
        .select("id")
        .eq("id", doc.data["project_id"])
        .eq("user_id", current_user["user_id"])
        .single()
        .execute()
    )

    if not project.data:
        raise HTTPException(status_code=403, detail="Accès refusé")

    # Suppression en cascade (chunks supprimés par FK ON DELETE CASCADE)
    supabase.table("uploaded_documents").delete().eq(
        "id", str(document_id)
    ).execute()