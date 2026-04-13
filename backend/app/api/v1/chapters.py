import uuid
import json
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from app.core.deps import get_current_user
from app.db.supabase_client import supabase
from app.ai.lesson_generator import generate_lesson
from app.ai.exercise_generator import generate_exercises
from app.ai.grader import grade_answer
from app.ai.llm_client import llm_complete
from app.rag.retrieval import retrieve_chunks
from app.rag.query_rewriter import rewrite_query
from app.web.tavily_client import tavily_search
from app.schemas.lesson import LessonSchema
from app.schemas.exercise import ExerciseSchema, GradingResult
from pydantic import BaseModel
from typing import Optional

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Schémas de requête inline ────────────────────────────

class LessonRequest(BaseModel):
    use_web_enrichment: bool = True

class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str

class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []
    chapter_context: Optional[str] = None

class ExerciseRequest(BaseModel):
    count: int = 5
    types: Optional[list[str]] = None

class GradeRequest(BaseModel):
    answer: str


# ── Helper : vérifie ownership d'un chapitre ────────────

def _get_chapter_and_project(chapter_id: str, user_id: str) -> tuple[dict, str]:
    """
    Récupère le chapitre et vérifie que l'utilisateur y a accès.
    Retourne (chapter_data, project_id).
    """
    ch = (
        supabase.table("chapters")
        .select("id, title, objective, roadmap_id, status")
        .eq("id", chapter_id)
        .single()
        .execute()
    )
    if not ch.data:
        raise HTTPException(status_code=404, detail="Chapitre introuvable")

    roadmap = (
        supabase.table("roadmaps")
        .select("id, project_id")
        .eq("id", ch.data["roadmap_id"])
        .single()
        .execute()
    )
    if not roadmap.data:
        raise HTTPException(status_code=404, detail="Roadmap introuvable")

    project = (
        supabase.table("projects")
        .select("id")
        .eq("id", roadmap.data["project_id"])
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    if not project.data:
        raise HTTPException(status_code=403, detail="Accès refusé")

    return ch.data, roadmap.data["project_id"]


# ─────────────────────────────────────────────
# POST /chapters/{id}/lesson
# ─────────────────────────────────────────────

@router.post(
    "/{chapter_id}/lesson",
    response_model=LessonSchema,
    summary="Génère ou récupère la leçon d'un chapitre",
)
async def get_or_generate_lesson(
    chapter_id: uuid.UUID,
    request: LessonRequest,
    current_user: dict = Depends(get_current_user),
):
    chapter, project_id = _get_chapter_and_project(
        str(chapter_id), current_user["user_id"]
    )

    # Met à jour le statut du chapitre à in_progress
    supabase.table("chapters").update({"status": "in_progress"}).eq(
        "id", str(chapter_id)
    ).execute()
    supabase.table("progress").upsert({
        "user_id": current_user["user_id"],
        "chapter_id": str(chapter_id),
        "completion_status": "in_progress",
    }, on_conflict="user_id,chapter_id").execute()

    lesson = await generate_lesson(
        chapter_id=str(chapter_id),
        project_id=project_id,
        use_web_enrichment=request.use_web_enrichment,
    )
    return lesson


# ─────────────────────────────────────────────
# POST /chapters/{id}/chat   ← STREAMING ⭐
# ─────────────────────────────────────────────

TUTOR_SYSTEM_PROMPT = """You are a focused, expert AI tutor helping a student prepare for an exam.
You answer questions strictly within the scope of the current chapter.
Ground your answers in the provided document chunks and web sources.
Always cite which source supports each key claim.
Keep answers clear, structured, and educational.
If you use a web source, mention the URL.
"""

@router.post(
    "/{chapter_id}/chat",
    summary="Tuteur IA contextuel — réponse en streaming",
)
async def chapter_chat(
    chapter_id: uuid.UUID,
    request: ChatRequest,
    current_user: dict = Depends(get_current_user),
):
    chapter, project_id = _get_chapter_and_project(
        str(chapter_id), current_user["user_id"]
    )

    chapter_title = chapter["title"]

    # ── 1. Query rewriting ───────────────────────────────
    rewritten_query = await rewrite_query(
        user_question=request.message,
        chapter_context=chapter_title,
    )

    # ── 2. RAG retrieval ─────────────────────────────────
    rag_chunks = await retrieve_chunks(
        query=rewritten_query,
        project_id=project_id,
        chapter_hint=chapter_title,
        top_k=3,
    )

    rag_context = "\n\n".join(
        f"[Doc chunk {i+1}]: {c.get('content', '')[:800]}"
        for i, c in enumerate(rag_chunks)
    )

    # ── 3. Tavily web search ─────────────────────────────
    web_context = ""
    try:
        web_results = await tavily_search(
            query=f"{chapter_title} {rewritten_query}",
            max_results=2,
            search_depth="basic",  # Rapide pour le chat interactif
        )
        if web_results:
            web_parts = [
                f"[Web: {r['title']}] {r['content'][:500]} (source: {r['url']})"
                for r in web_results
            ]
            web_context = "\n\n".join(web_parts)
    except Exception as e:
        logger.warning(f"Tavily chat search failed: {e}")

    # ── 4. Construit les messages avec historique ─────────
    # Garde uniquement les 3 derniers échanges (gestion du contexte budget)
    recent_history = request.history[-6:]  # 3 paires user/assistant

    context_block = f"""Current chapter: {chapter_title}
Objective: {chapter.get('objective', '')}

Document context:
{rag_context if rag_context else "No relevant chunks found."}

Web context:
{web_context if web_context else "No web results."}
"""

    messages = [
        {"role": "system", "content": TUTOR_SYSTEM_PROMPT},
        {"role": "user", "content": f"[Context]\n{context_block}"},
        # Injecte l'historique récent
        *[{"role": m.role, "content": m.content} for m in recent_history],
        # Question actuelle
        {"role": "user", "content": request.message},
    ]

    # ── 5. Streaming LLM ─────────────────────────────────
    async def stream_response():
        try:
            stream = await llm_complete(
                messages=messages,
                task="chat",
                stream=True,
                max_tokens=1500,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except Exception as e:
            logger.error(f"Chat stream error: {e}")
            yield f"\n[Error: {str(e)}]"

    return StreamingResponse(
        stream_response(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ─────────────────────────────────────────────
# POST /chapters/{id}/exercises
# ─────────────────────────────────────────────

@router.post(
    "/{chapter_id}/exercises",
    response_model=list[ExerciseSchema],
    summary="Génère des exercices pour un chapitre",
)
async def get_exercises(
    chapter_id: uuid.UUID,
    request: ExerciseRequest,
    current_user: dict = Depends(get_current_user),
):
    chapter, project_id = _get_chapter_and_project(
        str(chapter_id), current_user["user_id"]
    )

    # Vérifie si des exercices existent déjà pour ce chapitre
    existing = (
        supabase.table("exercises")
        .select("*")
        .eq("chapter_id", str(chapter_id))
        .execute()
    )
    if existing.data:
        logger.info(f"Cache hit exercices pour chapitre {chapter_id}")
        return existing.data

    exercises = await generate_exercises(
        chapter_id=str(chapter_id),
        project_id=project_id,
        count=request.count,
        types=request.types,
    )
    return exercises


# ─────────────────────────────────────────────
# POST /exercises/{id}/grade
# (placé dans chapters router par convention)
# ─────────────────────────────────────────────

@router.post(
    "/exercises/{exercise_id}/grade",
    response_model=GradingResult,
    summary="Note la réponse d'un étudiant",
)
async def grade_exercise(
    exercise_id: uuid.UUID,
    request: GradeRequest,
    current_user: dict = Depends(get_current_user),
):
    result = await grade_answer(
        exercise_id=str(exercise_id),
        user_id=current_user["user_id"],
        student_answer=request.answer,
    )
    return result


# ─────────────────────────────────────────────
# POST /chapters/{id}/complete
# ─────────────────────────────────────────────

@router.post(
    "/{chapter_id}/complete",
    summary="Marque un chapitre comme terminé",
)
async def complete_chapter(chapter_id: uuid.UUID, current_user: dict = Depends(get_current_user)):
    chapter, _ = _get_chapter_and_project(str(chapter_id), current_user["user_id"])

    # Récupère le order_index SÉPARÉMENT d'abord
    current_chapter = (
        supabase.table("chapters")
        .select("order_index, roadmap_id")
        .eq("id", str(chapter_id))
        .single()
        .execute()
    )
    current_order = current_chapter.data["order_index"]

    supabase.table("chapters").update({"status": "completed"}).eq("id", str(chapter_id)).execute()
    supabase.table("progress").upsert({
        "user_id": current_user["user_id"],
        "chapter_id": str(chapter_id),
        "completion_status": "completed",
    }, on_conflict="user_id,chapter_id").execute()

    # Maintenant on peut chercher le suivant
    next_ch = (
        supabase.table("chapters")
        .select("id")
        .eq("roadmap_id", current_chapter.data["roadmap_id"])
        .eq("order_index", current_order + 1)
        .single()
        .execute()
    )
    if next_ch.data:
        supabase.table("chapters").update({"status": "available"}).eq(
            "id", next_ch.data["id"]
        ).execute()

    return {"status": "completed", "chapter_id": str(chapter_id)}