import re
import logging
from functools import lru_cache

from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import Document as LlamaDocument

from app.schemas.documents import ChunkMetadata, DocumentChunk
from app.core.config import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_splitter() -> SentenceSplitter:
    """
    Singleton SentenceSplitter — objet lourd, instancié une seule fois.
    lru_cache garantit qu'il n'est créé qu'une fois même en concurrence.
    """
    return SentenceSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        paragraph_separator="\n\n",
        secondary_chunking_regex=r"[.!?。]\s+",  # ✅ raw string
    )


def chunk_text(
    text: str,
    document_id: str,
    project_id: str,
    source_type: str = "notes",
    filename: str = "",
) -> list[DocumentChunk]:
    """
    Découpe le texte en chunks avec métadonnées enrichies.
    Utilise SentenceSplitter (LlamaIndex) pour respecter les frontières de phrases.
    """
    if not text or not text.strip():
        logger.warning(f"Texte vide pour document {document_id}")
        return []

    splitter = _get_splitter()
    doc = LlamaDocument(
        text=text,
        metadata={"filename": filename, "source_type": source_type},
    )

    nodes = splitter.get_nodes_from_documents([doc])
    chunks = []

    for idx, node in enumerate(nodes):
        section_title = _extract_section_title(node.text)

        metadata = ChunkMetadata(
            document_id=document_id,
            project_id=project_id,
            page_number=node.metadata.get("page_label"),
            section_title=section_title,
            source_type=source_type,
            chunk_index=idx,
        )

        chunks.append(DocumentChunk(content=node.text, metadata=metadata))

    logger.info(f"Document {document_id} → {len(chunks)} chunks (source_type={source_type})")
    return chunks


def _extract_section_title(text: str) -> str | None:
    """
    Extrait un titre Markdown depuis les premières lignes du chunk.
    Seules les lignes débutant par '#' sont considérées comme titres.
    L'heuristique "ligne courte" était trop agressive.
    """
    for line in text.strip().split("\n")[:3]:
        line = line.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip()
    return None