"""
Routes Chapters — PassExamAI
Toute la logique métier est dans ChapterService.
Le router est un thin pass-through : auth → service → réponse HTTP.
"""
import uuid
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.core.deps import get_current_user
from app.services.chapter_service import ChapterService
from app.schemas.lesson import LessonSchema, LessonRequest
from app.schemas.exercise import ExerciseSchema, GradingResult, ExerciseRequest, GradeRequest
from app.schemas.chat import ChatMessage, ChatRequest

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Helper : convertit les exceptions service → HTTP ──────────────────────────
def _handle_service_errors(func):
    """Décorateur pour la gestion uniforme des erreurs de service."""
    import functools

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
    return wrapper


# ── Lesson ────────────────────────────────────────────────────────────────────

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
    try:
        return await ChapterService.get_or_create_lesson(
            chapter_id=str(chapter_id),
            user_id=current_user["user_id"],
            use_web_enrichment=request.use_web_enrichment,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Lesson generation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Chat (tuteur IA streaming) ─────────────────────────────────────────────────

@router.post(
    "/{chapter_id}/chat",
    summary="Tuteur IA contextuel — réponse en streaming SSE",
)
async def chapter_chat(
    chapter_id: uuid.UUID,
    request: ChatRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Délègue entièrement à ChapterService.stream_chat().
    Le router ne connaît pas le RAG, les embeddings, ni le LLM.
    """
    try:
        # Valide l'accès et prépare le générateur de stream
        generator = ChapterService.stream_chat(
            chapter_id=str(chapter_id),
            user_id=current_user["user_id"],
            message=request.message,
            history=request.history,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ── Exercises ─────────────────────────────────────────────────────────────────

@router.post(
    "/{chapter_id}/exercises",
    response_model=list[ExerciseSchema],
    summary="Génère ou récupère les exercices d'un chapitre",
)
async def get_exercises(
    chapter_id: uuid.UUID,
    request: ExerciseRequest,
    current_user: dict = Depends(get_current_user),
):
    try:
        return await ChapterService.get_or_create_exercises(
            chapter_id=str(chapter_id),
            user_id=current_user["user_id"],
            count=request.count,
            types=request.types,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Exercise generation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Grading ───────────────────────────────────────────────────────────────────

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
    try:
        return await ChapterService.grade(
            exercise_id=str(exercise_id),
            user_id=current_user["user_id"],
            student_answer=request.answer,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Grading error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Completion ────────────────────────────────────────────────────────────────

@router.post(
    "/{chapter_id}/complete",
    summary="Marque un chapitre comme terminé et déverrouille le suivant",
)
async def complete_chapter(
    chapter_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
):
    try:
        return ChapterService.complete_chapter(
            chapter_id=str(chapter_id),
            user_id=current_user["user_id"],
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))