from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import Document as LlamaDocument
from app.schemas.documents import ChunkMetadata, DocumentChunk
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)


def chunk_text(
    text: str,
    document_id: str,
    project_id: str,
    source_type: str = "notes",
    filename: str = "",
) -> list[DocumentChunk]:
    """
    Découpe le texte extrait en chunks avec métadonnées.
    Utilise SentenceSplitter de LlamaIndex pour respecter les limites de phrases.
    """
    if not text or not text.strip():
        logger.warning(f"Texte vide pour document {document_id}")
        return []

    # Splitter configuré selon le SDD
    splitter = SentenceSplitter(
        chunk_size=settings.chunk_size,        # 512 tokens
        chunk_overlap=settings.chunk_overlap,   # 50 tokens
        paragraph_separator="\n\n",
        secondary_chunking_regex="[.!?。]\s+",
    )

    # On crée un document LlamaIndex pour utiliser le splitter
    doc = LlamaDocument(
        text=text,
        metadata={"filename": filename, "source_type": source_type},
    )

    nodes = splitter.get_nodes_from_documents([doc])
    chunks = []

    for idx, node in enumerate(nodes):
        # Extraire les métadonnées contextuelles du contenu
        section_title = _extract_section_title(node.text)
        chapter_hint = _extract_chapter_hint(node.text)

        metadata = ChunkMetadata(
            document_id=document_id,
            project_id=project_id,
            page_number=node.metadata.get("page_label"),
            section_title=section_title,
            chapter_hint=chapter_hint,
            source_type=source_type,
            chunk_index=idx,
        )

        chunks.append(DocumentChunk(content=node.text, metadata=metadata))

    logger.info(f"Document {document_id} → {len(chunks)} chunks créés")
    return chunks


def _extract_section_title(text: str) -> str | None:
    """
    Tente d'extraire un titre de section depuis les premières lignes du chunk.
    Heuristique simple : ligne courte en début de chunk = probable titre.
    """
    lines = text.strip().split("\n")
    for line in lines[:3]:
        line = line.strip()
        # Titre Markdown ou ligne courte sans ponctuation de fin
        if line.startswith("#") or (
            len(line) > 0 and len(line) < 80 and not line.endswith((".", ",", ";"))
        ):
            return line.lstrip("#").strip()
    return None


def _extract_chapter_hint(text: str) -> str | None:
    """
    Détecte les mentions de chapitres dans le texte.
    Ex: 'Chapter 3', 'Chapitre 2', 'Section 1.2'
    """
    import re
    patterns = [
        r"(?:chapter|chapitre|section|partie|part)\s+(\d+[\.\d]*)",
        r"(?:chap|sec|pt)\.\s*(\d+[\.\d]*)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text[:200], re.IGNORECASE)
        if match:
            return match.group(0)
    return None