import hashlib
import json
import logging
from datetime import date
from typing import Optional

from app.ai.llm_client import llm_complete
from app.db.supabase_client import supabase
from app.rag.retrieval import retrieve_chunks
from app.schemas.roadmap import RoadmapSchema, ChapterSchema
from app.web.firecrawl_client import enrich_with_web

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Prompt principal — sortie JSON stricte
# ─────────────────────────────────────────────
ROADMAP_SYSTEM_PROMPT = """You are an expert educational curriculum designer.
Analyze the provided exam/course material and create a personalized revision roadmap.

The roadmap MUST be adapted to the student's available study time.
If time is short, reduce chapter count and focus on highest-importance topics.
If time allows, provide comprehensive coverage.

Output ONLY valid JSON:
{
  "title": "string",
  "estimated_total_hours": 20.0,
  "chapters": [
    {
      "order_index": 1,
      "title": "string",
      "objective": "string",
      "importance": 2.0,
      "estimated_hours": 3.0
    }
  ]
}

Rules:
- importance: 0.5 (minor) → 3.0 (exam-critical)
- estimated_hours: realistic study time per chapter
- Sum of estimated_hours should match available study time
- Order: prerequisites before advanced topics
- Base content on the uploaded exam material — web is supplementary only
- All text in English

IMPORTANT (Order of Priority):
  Priority 1: The uploaded EXAM (determine the syllabus from it).
  Priority 2: The provided NOTES (use them to fill the gaps).
  Priority 3: The sources from web search
"""


def _build_roadmap_user_prompt(
    doc_content: str,
    web_sources: list[dict],
    subject: str = "",
    exam_type: str = "",
    study_plan_context: str = "",
) -> str:
    """
    Construit le prompt utilisateur avec le contenu du document
    et les sources web enrichies.
    """
    web_context = ""
    if web_sources:
        web_parts = []
        for i, source in enumerate(web_sources[:3]):
            content = source.get("content", "")[:2000]
            title = source.get("title", f"Source {i+1}")
            url = source.get("url", "")
            web_parts.append(f"### Web Source {i+1}: {title}\nURL: {url}\n{content}")
        web_context = "\n\n".join(web_parts)

    context_parts = []
    if subject:
        context_parts.append(f"Subject: {subject}")
    if exam_type:
        context_parts.append(f"Exam type: {exam_type}")
    if study_plan_context:
        context_parts.append(study_plan_context)

    context_header = "\n".join(context_parts)

    return f"""
{context_header}

## Uploaded Document Content (primary source — prioritize this):
{doc_content[:6000]}

## Web Research (supplementary enrichment):
{web_context if web_context else "No web enrichment available."}

Generate the revision roadmap based on this material.
""".strip()


# ─────────────────────────────────────────────
# Cache : même document = même roadmap
# ─────────────────────────────────────────────

def _compute_content_hash(text: str) -> str:
    return hashlib.sha256(text[:10000].encode()).hexdigest()[:16]


def _get_cached_roadmap(project_id: str, content_hash: str) -> Optional[dict]:
    result = (
        supabase.table("roadmaps")
        .select("*, chapters(*)")
        .eq("project_id", project_id)
        .eq("doc_content_hash", content_hash)
        .eq("status", "ready")
        .single()
        .execute()
    )
    return result.data if result.data else None


# ─────────────────────────────────────────────
# Pipeline principal
# ─────────────────────────────────────────────

async def generate_roadmap(
    project_id: str,
    user_id: str,
) -> RoadmapSchema:
    """
    Génère une roadmap structurée pour un projet :
    1. Récupère le texte extrait du dernier document prêt
    2. Vérifie le cache (hash du contenu)
    3. Recherche web enrichi (Tavily + Firecrawl)
    4. Appel LLM avec prompt structuré
    5. Validation Pydantic + sauvegarde DB
    6. Retourne la RoadmapSchema complète
    """
    logger.info(f"Génération roadmap pour projet {project_id}")

    # ── 1. Récupère le contenu du document depuis la DB ──
    doc_result = (
        supabase.table("uploaded_documents")
        .select("id, extracted_text, filename, status")
        .eq("project_id", project_id)
        .order("created_at", desc=True)
        .limit(10)
        .execute()
    )

    if not doc_result.data:
        raise ValueError(
            "No document found for this project. Please upload and ingest a file first."
        )

    # Roadmap depends on extracted_text, not on pgvector embeddings.
    # Keep supporting generation even if embedding/pgvector step failed.
    doc = next(
        (d for d in doc_result.data if (d.get("extracted_text") or "").strip()),
        None,
    )
    if not doc:
        raise ValueError(
            "No extracted text available yet for this project. "
            "Wait for parsing to finish and retry."
        )

    extracted_text = doc["extracted_text"]

    # ── 2. Vérification cache ────────────────────────────
    content_hash = _compute_content_hash(extracted_text)
    cached = _get_cached_roadmap(project_id, content_hash)
    if cached:
        logger.info(f"Cache hit roadmap pour hash {content_hash}")
        return _db_to_roadmap_schema(cached)

    # ── 3. Infos du projet (subject, exam_type, planning) ──
    project_result = (
        supabase.table("projects")
        .select("title, subject, target_exam_type, deadline, hours_per_day, days_per_week")
        .eq("id", project_id)
        .single()
        .execute()
    )
    project = project_result.data or {}
    subject = project.get("subject", "")
    exam_type = project.get("target_exam_type", "")

    study_plan_context = ""
    deadline = project.get("deadline")
    hours_per_day = project.get("hours_per_day", 2.0)
    days_per_week = project.get("days_per_week", 5)

    if deadline:
        try:
            deadline_date = date.fromisoformat(str(deadline))
            days_remaining = (deadline_date - date.today()).days
            total_hours = days_remaining * (days_per_week / 7) * hours_per_day
            study_plan_context = (
                f"Days until exam: {days_remaining}\n"
                f"Study hours per day: {hours_per_day}\n"
                f"Study days per week: {days_per_week}\n"
                f"Total estimated study hours available: {total_hours:.0f}h"
            )
        except Exception:
            pass

    # ── 4. Enrichissement web ────────────────────────────
    # FIX: _build_search_queries retourne list[str], study_plan_context est str
    # On NE les additionne PAS — on passe study_plan_context séparément au prompt
    search_queries = _build_search_queries(extracted_text, subject, exam_type)

    web_sources = []
    try:
        web_sources = await enrich_with_web(
            queries=search_queries,
            max_urls_to_crawl=2,
            search_depth="advanced",
        )
    except Exception as e:
        logger.warning(f"Web enrichment failed (continuing without): {e}")

    # ── 5. Appel LLM ─────────────────────────────────────
    user_prompt = _build_roadmap_user_prompt(
        doc_content=extracted_text,
        web_sources=web_sources,
        subject=subject,
        exam_type=exam_type,
        study_plan_context=study_plan_context,  # passé proprement ici
    )

    messages = [
        {"role": "system", "content": ROADMAP_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    raw_output = await llm_complete(
        messages=messages,
        task="roadmap",
        max_tokens=2048,
        response_format={"type": "json_object"},
    )

    # ── 6. Parse + Validation Pydantic ───────────────────
    roadmap_schema = _parse_and_validate_roadmap(raw_output, project_id)

    # ── 7. Sauvegarde en DB ──────────────────────────────
    # FIX: on passe user_id pour satisfaire la contrainte NOT NULL
    saved = _save_roadmap_to_db(roadmap_schema, project_id, user_id, content_hash)

    logger.info(
        f"✅ Roadmap générée: {len(roadmap_schema.chapters)} chapitres "
        f"pour projet {project_id}"
    )
    return saved


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _build_search_queries(
    extracted_text: str,
    subject: str,
    exam_type: str,
) -> list[str]:
    """Retourne list[str] — NE PAS concatener avec une str."""
    queries = []
    if subject and exam_type:
        queries.append(f"{subject} {exam_type} syllabus course outline")
    elif subject:
        queries.append(f"{subject} exam preparation topics overview")

    first_words = " ".join(extracted_text[:200].split()[:15])
    queries.append(f"{first_words} study guide chapters")

    if not queries:
        queries.append("exam preparation structured learning roadmap")

    return queries[:3]


def _parse_and_validate_roadmap(
    raw_output: str,
    project_id: str,
) -> RoadmapSchema:
    try:
        data = json.loads(raw_output)
        chapters = [
            ChapterSchema(
                order_index=ch["order_index"],
                title=ch["title"],
                objective=ch.get("objective", ""),
                importance=float(ch.get("importance", 1.0)),
                status="locked",
            )
            for ch in data.get("chapters", [])
        ]
        if chapters:
            chapters[0].status = "available"

        return RoadmapSchema(
            project_id=project_id,
            title=data.get("title", "Revision Roadmap"),
            status="ready",
            chapters=chapters,
        )

    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.error(f"Roadmap parse error: {e}\nRaw: {raw_output[:500]}")
        raise ValueError(f"LLM output invalide pour roadmap: {e}")


def _save_roadmap_to_db(
    roadmap: RoadmapSchema,
    project_id: str,
    user_id: str,           # FIX: ajouté — requis par la contrainte NOT NULL
    content_hash: str,
) -> RoadmapSchema:
    import uuid

    roadmap_id = str(uuid.uuid4())

    # FIX: user_id inclus dans l'insert
    supabase.table("roadmaps").insert(
        {
            "id": roadmap_id,
            "project_id": project_id,
            "user_id": user_id,
            "title": roadmap.title,
            "status": "ready",
            "doc_content_hash": content_hash,
        }
    ).execute()

    chapter_rows = [
        {
            "roadmap_id": roadmap_id,
            "order_index": ch.order_index,
            "title": ch.title,
            "objective": ch.objective,
            "importance": ch.importance,
            "status": ch.status,
        }
        for ch in roadmap.chapters
    ]
    chapters_result = supabase.table("chapters").insert(chapter_rows).execute()

    saved_chapters = [
        ChapterSchema(
            id=row["id"],
            roadmap_id=roadmap_id,
            order_index=row["order_index"],
            title=row["title"],
            objective=row["objective"],
            importance=row["importance"],
            status=row["status"],
        )
        for row in (chapters_result.data or [])
    ]

    roadmap.id = uuid.UUID(roadmap_id)
    roadmap.chapters = saved_chapters
    return roadmap


def _db_to_roadmap_schema(data: dict) -> RoadmapSchema:
    import uuid

    chapters = [
        ChapterSchema(
            id=uuid.UUID(ch["id"]),
            roadmap_id=uuid.UUID(ch["roadmap_id"]),
            order_index=ch["order_index"],
            title=ch["title"],
            objective=ch.get("objective", ""),
            importance=ch.get("importance", 1.0),
            status=ch.get("status", "locked"),
        )
        for ch in sorted(data.get("chapters", []), key=lambda x: x["order_index"])
    ]
    return RoadmapSchema(
        id=uuid.UUID(data["id"]),
        project_id=data["project_id"],
        title=data["title"],
        status=data["status"],
        chapters=chapters,
        doc_content_hash=data.get("doc_content_hash"),
    )