import logging
from typing import Optional, AsyncGenerator
from app.db.supabase_client import supabase
from app.ai.lesson_generator import generate_lesson
from app.ai.exercise_generator import generate_exercises
from app.ai.grader import grade_answer
from app.ai.llm_client import llm_complete
from app.rag.query_rewriter import rewrite_query
from app.rag.gap_detector import enrich_if_needed
from app.schemas.lesson import LessonSchema
from app.schemas.exercise import GradingResult

logger = logging.getLogger(__name__)

TUTOR_SYSTEM_PROMPT = """You are a focused, expert AI tutor helping a student prepare for an exam.
You answer questions strictly within the scope of the current chapter.
Ground your answers in the provided document chunks and web sources.
Always cite which source supports each key claim.
Keep answers clear, structured, and educational.
If you use a web source, mention the URL.
"""


class ChapterService:

    @staticmethod
    def get_chapter_with_project(chapter_id: str, user_id: str) -> tuple[dict, str]:
        ch = (
            supabase.table("chapters")
            .select("id, title, objective, roadmap_id, status")
            .eq("id", chapter_id)
            .single()
            .execute()
        )
        if not ch.data:
            raise ValueError("Chapitre introuvable")

        roadmap = (
            supabase.table("roadmaps")
            .select("id, project_id")
            .eq("id", ch.data["roadmap_id"])
            .single()
            .execute()
        )
        if not roadmap.data:
            raise ValueError("Roadmap introuvable")

        project = (
            supabase.table("projects")
            .select("id")
            .eq("id", roadmap.data["project_id"])
            .eq("user_id", user_id)
            .single()
            .execute()
        )
        if not project.data:
            raise PermissionError("Accès refusé")

        return ch.data, roadmap.data["project_id"]

    # ── Lesson ───────────────────────────────────────────

    @staticmethod
    async def get_or_create_lesson(
        chapter_id: str,
        user_id: str,
        use_web_enrichment: bool = True,
    ) -> LessonSchema:
        chapter, project_id = ChapterService.get_chapter_with_project(
            chapter_id, user_id
        )
        ChapterService._mark_in_progress(chapter_id, user_id)  # ← maintenant dans la classe
        return await generate_lesson(
            chapter_id=chapter_id,
            project_id=project_id,
            use_web_enrichment=use_web_enrichment,
        )

    # ── Chat (gap detector + streaming) ──────────────────

    @staticmethod
    async def build_chat_messages(
        chapter_id: str,
        user_id: str,
        message: str,
        history: list,
    ) -> list[dict]:
        chapter, project_id = ChapterService.get_chapter_with_project(
            chapter_id, user_id
        )
        chapter_title = chapter["title"]

        rewritten_query = await rewrite_query(
            user_question=message,
            chapter_context=chapter_title,
        )

        # ✅ Gap detector : web uniquement si RAG insuffisant
        rag_chunks, web_sources, web_was_used = await enrich_if_needed(
            query=rewritten_query,
            project_id=project_id,
            chapter_hint=chapter_title,
            top_k=3,
            context_label="chat",
        )

        rag_context = (
            "\n\n".join(
                f"[Doc chunk {i+1} — score {c.get('similarity', 0):.2f}]: "
                f"{c.get('content', '')[:800]}"
                for i, c in enumerate(rag_chunks)
            ) or "No relevant content found in your documents."
        )

        web_context = ""
        if web_was_used and web_sources:
            web_context = "\n\n".join(
                f"[Web: {s.get('title', '')}] {s.get('content', '')[:500]} "
                f"({s.get('url', '')})"
                for s in web_sources[:2]
            )

        context_block = (
            f"Current chapter: {chapter_title}\n"
            f"Objective: {chapter.get('objective', '')}\n\n"
            f"--- Content from YOUR study materials ---\n{rag_context}"
            + (f"\n\n--- Supplementary web sources ---\n{web_context}" if web_context else "")
        )

        recent_history = history[-6:]
        return [
            {"role": "system", "content": TUTOR_SYSTEM_PROMPT},
            {"role": "user", "content": f"[Context]\n{context_block}"},
            *[{"role": m.role, "content": m.content} for m in recent_history],
            {"role": "user", "content": message},
        ]

    @staticmethod
    async def stream_chat(
        chapter_id: str,
        user_id: str,
        message: str,
        history: list,
    ) -> AsyncGenerator[str, None]:
        messages = await ChapterService.build_chat_messages(
            chapter_id, user_id, message, history
        )
        try:
            stream = await llm_complete(
                messages=messages, task="chat", stream=True, max_tokens=1500
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except Exception as e:
            logger.error(f"Chat stream error: {e}")
            yield f"\n[Error: {str(e)}]"

    # ── Exercises ─────────────────────────────────────────

    @staticmethod
    async def get_or_create_exercises(
        chapter_id: str,
        user_id: str,
        count: int = 5,
        types: Optional[list[str]] = None,
    ) -> list:
        chapter, project_id = ChapterService.get_chapter_with_project(
            chapter_id, user_id
        )
        # ✅ generate_exercises() gère déjà le cache en interne
        return await generate_exercises(
            chapter_id=chapter_id,
            project_id=project_id,
            count=count,
            types=types,
        )

    # ── Grading ───────────────────────────────────────────

    @staticmethod
    async def grade(
        exercise_id: str, user_id: str, student_answer: str
    ) -> GradingResult:
        return await grade_answer(
            exercise_id=exercise_id,
            user_id=user_id,
            student_answer=student_answer,
        )

    # ── Completion ────────────────────────────────────────

    @staticmethod
    def complete_chapter(chapter_id: str, user_id: str) -> dict:
        ChapterService.get_chapter_with_project(chapter_id, user_id)

        current = (
            supabase.table("chapters")
            .select("order_index, roadmap_id")
            .eq("id", chapter_id)
            .single()
            .execute()
        )
        current_order = current.data["order_index"]
        roadmap_id = current.data["roadmap_id"]

        supabase.table("chapters").update({"status": "completed"}).eq(
            "id", chapter_id
        ).execute()
        supabase.table("progress").upsert(
            {"user_id": user_id, "chapter_id": chapter_id, "completion_status": "completed"},
            on_conflict="user_id,chapter_id",
        ).execute()

        next_ch = (
            supabase.table("chapters")
            .select("id")
            .eq("roadmap_id", roadmap_id)
            .eq("order_index", current_order + 1)
            .single()
            .execute()
        )
        if next_ch.data:
            supabase.table("chapters").update({"status": "available"}).eq(
                "id", next_ch.data["id"]
            ).execute()

        return {"status": "completed", "chapter_id": chapter_id}

    # ── Private helpers ───────────────────────────────────

    @staticmethod
    def _mark_in_progress(chapter_id: str, user_id: str) -> None:
        """Ne régresse pas un chapitre déjà 'completed'."""
        current = (
            supabase.table("chapters")
            .select("status")
            .eq("id", chapter_id)
            .single()
            .execute()
        )
        if current.data and current.data.get("status") == "completed":
            return

        supabase.table("chapters").update({"status": "in_progress"}).eq(
            "id", chapter_id
        ).execute()
        supabase.table("progress").upsert(
            {"user_id": user_id, "chapter_id": chapter_id, "completion_status": "in_progress"},
            on_conflict="user_id,chapter_id",
        ).execute()