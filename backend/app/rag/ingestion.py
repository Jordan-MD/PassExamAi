import hashlib
import logging
from typing import Optional
import fitz  # PyMuPDF — fallback si LlamaParse échoue

from llama_parse import LlamaParse

from app.core.config import settings
from app.db.supabase_client import supabase
from app.rag.chunking import chunk_text
from app.rag.embeddings import embed_chunks
from app.schemas.documents import DocumentChunk

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# 1. Parsing PDF
# ─────────────────────────────────────────────

async def parse_pdf_llamaparse(storage_url: str) -> str:
    """
    Parse le PDF via LlamaParse (gère OCR, tableaux, formules).
    Retourne le texte en Markdown propre.
    """
    parser = LlamaParse(
        api_key=settings.llama_parse_api_key,
        result_type="markdown",
        verbose=False,
        language="en",               # On force l'anglais pour la compétition
        parsing_instruction=(
            "Extract all text content. "
            "Preserve section titles and structure. "
            "Convert tables to markdown format. "
            "Keep mathematical formulas."
        ),
    )

    # LlamaParse accepte une URL directement
    documents = await parser.aload_data(storage_url)

    if not documents:
        raise ValueError("LlamaParse n'a retourné aucun contenu")

    # Concatène tous les pages/sections
    full_text = "\n\n".join(doc.text for doc in documents if doc.text)
    logger.info(f"LlamaParse OK — {len(full_text)} caractères extraits")
    return full_text


def parse_pdf_pymupdf_fallback(pdf_bytes: bytes) -> str:
    """
    Fallback PyMuPDF si LlamaParse est indisponible.
    Extraction texte simple, sans OCR.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    text_parts = []

    for page_num, page in enumerate(doc):
        text = page.get_text("text")
        if text.strip():
            text_parts.append(f"## Page {page_num + 1}\n\n{text}")

    full_text = "\n\n".join(text_parts)
    logger.info(f"PyMuPDF fallback — {len(full_text)} caractères extraits")
    return full_text


# ─────────────────────────────────────────────
# 2. Stockage des chunks dans pgvector
# ─────────────────────────────────────────────

async def store_chunks_in_pgvector(
    chunks: list[DocumentChunk],
    document_id: str,
) -> int:
    """
    Insère les chunks avec embeddings dans Supabase pgvector.
    Retourne le nombre de chunks stockés.
    """
    if not chunks:
        return 0

    rows = []
    for chunk in chunks:
        if chunk.embedding is None:
            logger.warning(f"Chunk {chunk.metadata.chunk_index} sans embedding — ignoré")
            continue

        rows.append({
            "document_id": document_id,
            "chunk_index": chunk.metadata.chunk_index,
            "content": chunk.content,
            "embedding": chunk.embedding,
            "metadata": chunk.metadata.model_dump(),
        })

    if not rows:
        return 0

    # Insert par batch de 50 pour éviter les timeouts
    batch_size = 50
    total_inserted = 0

    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        response = supabase.table("document_chunks").insert(batch).execute()
        total_inserted += len(response.data)

    logger.info(f"✅ {total_inserted} chunks stockés dans pgvector")
    return total_inserted


# ─────────────────────────────────────────────
# 3. Mise à jour du statut document
# ─────────────────────────────────────────────

def update_document_status(
    document_id: str,
    status: str,
    chunks_count: int = 0,
    error_message: str | None = None,
) -> None:
    """Mise à jour atomique du statut dans la table uploaded_documents."""
    payload = {"status": status, "updated_at": "now()"}

    if chunks_count > 0:
        payload["chunks_count"] = chunks_count
    if error_message:
        payload["error_message"] = error_message

    supabase.table("uploaded_documents").update(payload).eq(
        "id", document_id
    ).execute()

    logger.info(f"Document {document_id} → status: {status}")


# ─────────────────────────────────────────────
# 4. Pipeline COMPLET (lancé en BackgroundTask)
# ─────────────────────────────────────────────

async def run_ingestion_pipeline(
    document_id: str,
    storage_url: str,
    project_id: str,
    source_type: str,
    filename: str,
) -> None:
    """
    Pipeline complet d'ingestion :
    storage_url → LlamaParse → chunks → embeddings → pgvector
    
    Lancé en BackgroundTask — jamais dans une requête synchrone.
    Le frontend poll GET /documents/{id}/status toutes les 3 secondes.
    """
    logger.info(f"🚀 Ingestion démarrée: document_id={document_id}")

    try:
        # ── ÉTAPE 1 : Parsing ──────────────────────────────
        update_document_status(document_id, "parsing")

        try:
            extracted_text = await parse_pdf_llamaparse(storage_url)
        except Exception as e:
            logger.warning(f"LlamaParse failed: {e} — tentative PyMuPDF fallback")
            # Fallback : télécharge le PDF et utilise PyMuPDF
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.get(storage_url)
                resp.raise_for_status()
                extracted_text = parse_pdf_pymupdf_fallback(resp.content)

        if not extracted_text.strip():
            raise ValueError("Aucun texte extrait du document")

        # Sauvegarde le texte extrait pour usage ultérieur (génération roadmap)
        supabase.table("uploaded_documents").update({
            "extracted_text": extracted_text[:50000],  # Cap à 50k chars en DB
            "updated_at": "now()",
        }).eq("id", document_id).execute()

        # ── ÉTAPE 2 : Chunking ─────────────────────────────
        update_document_status(document_id, "chunking")

        chunks = chunk_text(
            text=extracted_text,
            document_id=document_id,
            project_id=project_id,
            source_type=source_type,
            filename=filename,
        )

        if not chunks:
            raise ValueError("Aucun chunk produit après le découpage")

        # ── ÉTAPE 3 : Embeddings ───────────────────────────
        update_document_status(document_id, "embedding")

        embedded_chunks = await embed_chunks(chunks)

        # ── ÉTAPE 4 : Stockage pgvector ────────────────────
        chunks_count = await store_chunks_in_pgvector(
            chunks=embedded_chunks,
            document_id=document_id,
        )

        # ── SUCCÈS ─────────────────────────────────────────
        update_document_status(document_id, "ready", chunks_count=chunks_count)
        logger.info(
            f"✅ Ingestion terminée: {document_id} → {chunks_count} chunks dans pgvector"
        )

    except Exception as e:
        error_msg = str(e)
        logger.error(f"❌ Ingestion échouée pour {document_id}: {error_msg}")
        update_document_status(document_id, "failed", error_message=error_msg)