import logging
import json
import time
from typing import Optional
import fitz  # PyMuPDF

from app.core.config import settings
from app.db.supabase_client import supabase
from app.rag.chunking import chunk_text
from app.rag.embeddings import embed_chunks
from app.schemas.documents import DocumentChunk

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# 1. Parsing PDF
# ─────────────────────────────────────────────

async def _download_pdf_bytes_from_supabase(storage_url: str) -> bytes:
    """
    Télécharge les bytes du PDF directement via le client Supabase service-role.
    
    On extrait le storage_path depuis l'URL signée :
    https://<project>.supabase.co/storage/v1/object/sign/documents/<user_id>/...
    → storage_path = "<user_id>/..."
    
    Le client service-role bypasse le RLS et le bucket privé sans URL externe.
    """
    import re

    # Extrait le path après "/documents/"
    match = re.search(r"/documents/(.+?)(?:\?|$)", storage_url)
    if not match:
        raise ValueError(f"Impossible d'extraire le storage_path depuis : {storage_url}")

    storage_path = match.group(1)
    logger.info(f"Téléchargement Supabase storage: documents/{storage_path}")

    response = supabase.storage.from_("documents").download(storage_path)

    if not response:
        raise ValueError(f"Fichier vide ou introuvable: {storage_path}")

    logger.info(f"✅ PDF téléchargé depuis Supabase: {len(response)} bytes")
    return response

async def parse_pdf_llamaparse(pdf_bytes: bytes) -> str:
    """
    Parse via LlamaParse à partir des bytes du PDF.
    LlamaParse n'accepte pas les URLs signées Supabase — on lui passe les bytes.
    """
    import tempfile, os
    from llama_parse import LlamaParse

    parser = LlamaParse(
        api_key=settings.llama_parse_api_key,
        result_type="markdown",
        verbose=False,
        language="en",
        system_prompt=(   # ✅ "parsing_instruction" pas "system_prompt"
            "Extract all text content. "
            "Preserve section titles and structure. "
            "Convert tables to markdown format. "
            "Keep mathematical formulas."
        ),
    )

    # LlamaParse attend un fichier — on écrit dans un temp file
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name

    try:
        documents = await parser.aload_data(tmp_path)
        if not documents:
            raise ValueError("LlamaParse n'a retourné aucun contenu")
        full_text = "\n\n".join(doc.text for doc in documents if doc.text)
        logger.info(f"LlamaParse OK — {len(full_text)} caractères extraits")
        return full_text
    finally:
        os.unlink(tmp_path)  # Nettoyage du fichier temporaire


def parse_pdf_pymupdf(pdf_bytes: bytes) -> str:
    """
    Extraction texte via PyMuPDF.
    Fiable, rapide, fonctionne offline — aucune dépendance réseau externe.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    text_parts = []

    for page_num, page in enumerate(doc):
        text = page.get_text("text")
        if text.strip():
            text_parts.append(f"## Page {page_num + 1}\n\n{text}")

    full_text = "\n\n".join(text_parts)
    logger.info(f"PyMuPDF — {len(full_text)} caractères extraits ({len(doc)} pages)")
    return full_text


async def parse_pdf(storage_url: str) -> str:
    """
    Stratégie avec fallback :
    1. Télécharge les bytes via Supabase service-role
    2. Tente LlamaParse (meilleure qualité)
    3. Fallback PyMuPDF (toujours disponible)
    """
    # Téléchargement UNIQUE — les deux parsers utilisent les mêmes bytes
    pdf_bytes = await _download_pdf_bytes_from_supabase(storage_url)

    try:
        return await parse_pdf_llamaparse(pdf_bytes)
    except Exception as e:
        logger.warning(f"LlamaParse failed ({type(e).__name__}) → fallback PyMuPDF")
        return parse_pdf_pymupdf(pdf_bytes)


# ─────────────────────────────────────────────
# 2. Stockage des chunks dans pgvector
# ─────────────────────────────────────────────

async def store_chunks_in_pgvector(
    chunks: list[DocumentChunk],
    document_id: str,
) -> int:
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
    error_message: Optional[str] = None,
) -> None:
    payload: dict = {"status": status}

    if chunks_count > 0:
        payload["chunks_count"] = chunks_count
    if error_message:
        # Tronque à 500 chars pour éviter les dépassements DB
        payload["error_message"] = error_message[:500]

    supabase.table("uploaded_documents").update(payload).eq(
        "id", document_id
    ).execute()

    logger.info(f"Document {document_id} → status: {status}")


# ─────────────────────────────────────────────
# 4. Pipeline COMPLET
# ─────────────────────────────────────────────

async def run_ingestion_pipeline(
    document_id: str,
    storage_url: str,
    project_id: str,
    source_type: str,
    filename: str,
) -> None:
    """
    Pipeline : storage_url → parse → chunk → embed → pgvector.
    Lancé en BackgroundTask — non bloquant.
    """
    logger.info(f"🚀 Ingestion démarrée: document_id={document_id}, file={filename}")

    try:
        # ── ÉTAPE 1 : Parsing ──────────────────────────────
        update_document_status(document_id, "parsing")
        extracted_text = await parse_pdf(storage_url)

        if not extracted_text.strip():
            raise ValueError("Aucun texte extrait du document")

        # Sauvegarde du texte extrait (requis pour la génération roadmap)
        supabase.table("uploaded_documents").update({
            "extracted_text": extracted_text[:50000],
        }).eq("id", document_id).execute()

        # Business rule: the reference exam is only used to build roadmap prompts.
        # It does not need vectorization and should bypass embedding/pgvector steps.
        if source_type == "exam":

            update_document_status(document_id, "ready", chunks_count=0)
            logger.info(f"✅ Ingestion terminée (exam sans embedding): {document_id}")
            return

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

        logger.info(f"Chunking OK: {len(chunks)} chunks pour {filename}")

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
            f"✅ Ingestion terminée: {document_id} → {chunks_count} chunks (file={filename})"
        )

    except Exception as e:
        error_msg = str(e)
        logger.error(f"❌ Ingestion échouée pour {document_id}: {error_msg}")

        update_document_status(document_id, "failed", error_message=error_msg)

parsing_instruction = ""