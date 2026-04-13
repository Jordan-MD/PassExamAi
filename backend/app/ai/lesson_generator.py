import json
import logging
from app.ai.llm_client import llm_complete
from app.db.supabase_client import supabase
from app.rag.retrieval import retrieve_for_chapter
from app.rag.query_rewriter import rewrite_query
from app.schemas.lesson import LessonSchema, ExampleSchema, SourceReference
from app.web.firecrawl_client import enrich_with_web

logger = logging.getLogger(__name__)

LESSON_SYSTEM_PROMPT = """You are an expert educational content writer.
Create a comprehensive lesson for a student preparing for an exam.

Output ONLY valid JSON (no markdown backticks, no explanation):
{
  "content": "string — full lesson in Markdown (headings, bullet points, formulas)",
  "examples": [
    {"title": "string", "content": "string — worked example with step-by-step solution"}
  ],
  "source_references": [
    {"type": "doc|web", "url": "string or null", "excerpt": "string — key quote or idea"}
  ],
  "visual_aids_description": "string or null — describe any diagram that would help"
}

Rules:
- content: minimum 400 words, well-structured Markdown
- examples: 2 to 3 worked examples minimum
- source_references: cite every RAG chunk and web source used
- Focus strictly on the chapter topic — do not drift
- All text in English
"""


def _build_lesson_prompt(
    chapter_title: str,
    chapter_objective: str,
    rag_chunks: list[dict],
    web_sources: list[dict],
) -> str:
    # Contexte RAG
    rag_context = ""
    if rag_chunks:
        parts = []
        for i, chunk in enumerate(rag_chunks[:5]):
            content = chunk.get("content", "")[:1500]
            parts.append(f"[Document chunk {i+1}]\n{content}")
        rag_context = "\n\n".join(parts)

    # Contexte web
    web_context = ""
    if web_sources:
        parts = []
        for i, src in enumerate(web_sources[:2]):
            content = src.get("content", "")[:2000]
            url = src.get("url", "")
            parts.append(f"[Web source {i+1} — {url}]\n{content}")
        web_context = "\n\n".join(parts)

    return f"""Chapter: {chapter_title}
Learning objective: {chapter_objective}

## Document Content (primary source):
{rag_context if rag_context else "No document chunks available."}

## Web Research (supplementary):
{web_context if web_context else "No web enrichment available."}

Generate a complete lesson for this chapter.
""".strip()


async def generate_lesson(
    chapter_id: str,
    project_id: str,
    use_web_enrichment: bool = True,
) -> LessonSchema:
    """
    Génère la leçon d'un chapitre.
    Vérifie d'abord si une leçon existe déjà (cache DB).
    """
    # ── Cache : leçon déjà générée ? ─────────────────────
    existing = (
        supabase.table("lessons")
        .select("*")
        .eq("chapter_id", chapter_id)
        .limit(1)
        .execute()
    )
    if existing.data:
        logger.info(f"Cache hit leçon pour chapitre {chapter_id}")
        return _db_to_lesson_schema(existing.data[0])

    # ── Récupère le chapitre ──────────────────────────────
    chapter_result = (
        supabase.table("chapters")
        .select("title, objective")
        .eq("id", chapter_id)
        .single()
        .execute()
    )
    if not chapter_result.data:
        raise ValueError(f"Chapitre {chapter_id} introuvable")

    chapter = chapter_result.data
    title = chapter["title"]
    objective = chapter.get("objective", "")

    # ── RAG : chunks pertinents ───────────────────────────
    rag_chunks = await retrieve_for_chapter(
        chapter_title=title,
        project_id=project_id,
        top_k=5,
    )

    # ── Web enrichment ────────────────────────────────────
    web_sources = []
    if use_web_enrichment:
        try:
            web_sources = await enrich_with_web(
                queries=[
                    f"{title} explained with examples",
                    f"{title} {objective} study notes",
                ],
                max_urls_to_crawl=2,
                search_depth="advanced",
            )
        except Exception as e:
            logger.warning(f"Web enrichment lesson failed: {e}")

    # ── LLM ──────────────────────────────────────────────
    user_prompt = _build_lesson_prompt(title, objective, rag_chunks, web_sources)
    messages = [
        {"role": "system", "content": LESSON_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    raw = await llm_complete(
        messages=messages,
        task="lesson",
        max_tokens=3000,
        response_format={"type": "json_object"},
    )

    # ── Parse + Validation ────────────────────────────────
    lesson = _parse_lesson(raw, chapter_id)

    # ── Sauvegarde DB ─────────────────────────────────────
    saved = _save_lesson(lesson, chapter_id)
    return saved


def _parse_lesson(raw: str, chapter_id: str) -> LessonSchema:
    import uuid
    try:
        data = json.loads(raw)
        examples = [
            ExampleSchema(title=e["title"], content=e["content"])
            for e in data.get("examples", [])
        ]
        refs = [
            SourceReference(
                type=r.get("type", "doc"),
                url=r.get("url"),
                excerpt=r.get("excerpt", ""),
            )
            for r in data.get("source_references", [])
        ]
        return LessonSchema(
            chapter_id=uuid.UUID(chapter_id),
            content=data["content"],
            examples=examples,
            source_references=refs,
            visual_aids_description=data.get("visual_aids_description"),
        )
    except Exception as e:
        raise ValueError(f"Lesson parse error: {e}")


def _save_lesson(lesson: LessonSchema, chapter_id: str) -> LessonSchema:
    import uuid
    result = supabase.table("lessons").insert({
        "chapter_id": chapter_id,
        "content": lesson.content,
        "examples": [e.model_dump() for e in lesson.examples],
        "source_references": [r.model_dump() for r in lesson.source_references],
    }).execute()
    if result.data:
        lesson.id = uuid.UUID(result.data[0]["id"])
    return lesson


def _db_to_lesson_schema(row: dict) -> LessonSchema:
    import uuid
    return LessonSchema(
        id=uuid.UUID(row["id"]),
        chapter_id=uuid.UUID(row["chapter_id"]),
        content=row["content"],
        examples=[ExampleSchema(**e) for e in (row.get("examples") or [])],
        source_references=[SourceReference(**r) for r in (row.get("source_references") or [])],
    )