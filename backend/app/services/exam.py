import uuid
import json
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from app.core.deps import get_current_user
from app.db.supabase_client import supabase
from app.ai.exam_generator import generate_exam
from app.ai.llm_client import llm_complete
from app.schemas.exam import ExamSchema, ExamGenerateRequest, ExamResult, SectionScore, ExamQuestionSchema
from pydantic import BaseModel
from typing import Optional

router = APIRouter()
logger = logging.getLogger(__name__)


class SubmitAnswerItem(BaseModel):
    question_id: str
    answer: str


class ExamSubmitRequest(BaseModel):
    answers: list[SubmitAnswerItem]


# ─────────────────────────────────────────────
# POST /exam/generate
# ─────────────────────────────────────────────
@router.post(
    "/generate",
    response_model=ExamSchema,
    summary="Génère un examen blanc complet",
)
async def generate_exam_endpoint(
    request: ExamGenerateRequest,
    current_user: dict = Depends(get_current_user),
):
    # Vérifie ownership via roadmap → project
    roadmap = (
        supabase.table("roadmaps")
        .select("id, project_id")
        .eq("id", str(request.roadmap_id))
        .single()
        .execute()
    )
    if not roadmap.data:
        raise HTTPException(status_code=404, detail="Roadmap introuvable")

    project = (
        supabase.table("projects")
        .select("id")
        .eq("id", roadmap.data["project_id"])
        .eq("user_id", current_user["user_id"])
        .single()
        .execute()
    )
    if not project.data:
        raise HTTPException(status_code=403, detail="Accès refusé")

    try:
        exam = await generate_exam(
            roadmap_id=str(request.roadmap_id),
            question_count=request.question_count,
            time_limit=request.time_limit,
        )
        return exam
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"Exam generation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────
# GET /exam/{id}
# ─────────────────────────────────────────────
@router.get(
    "/{exam_id}",
    response_model=ExamSchema,
    summary="Récupère un examen avec ses questions",
)
async def get_exam(
    exam_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
):
    exam_data = (
        supabase.table("mock_exams")
        .select("*, exam_questions(*)")
        .eq("id", str(exam_id))
        .single()
        .execute()
    )
    if not exam_data.data:
        raise HTTPException(status_code=404, detail="Exam introuvable")

    # Vérifie ownership
    roadmap = (
        supabase.table("roadmaps")
        .select("project_id")
        .eq("id", exam_data.data["roadmap_id"])
        .single()
        .execute()
    )
    project = (
        supabase.table("projects")
        .select("id")
        .eq("id", roadmap.data["project_id"])
        .eq("user_id", current_user["user_id"])
        .single()
        .execute()
    )
    if not project.data:
        raise HTTPException(status_code=403, detail="Accès refusé")

    return _db_to_exam_schema(exam_data.data)


# ─────────────────────────────────────────────
# POST /exam/{id}/submit
# ─────────────────────────────────────────────
@router.post(
    "/{exam_id}/submit",
    response_model=ExamResult,
    summary="Soumet les réponses et retourne le score final",
)
async def submit_exam(
    exam_id: uuid.UUID,
    request: ExamSubmitRequest,
    current_user: dict = Depends(get_current_user),
):
    # Récupère toutes les questions
    questions_result = (
        supabase.table("exam_questions")
        .select("*")
        .eq("mock_exam_id", str(exam_id))
        .execute()
    )
    questions = {str(q["id"]): q for q in (questions_result.data or [])}

    if not questions:
        raise HTTPException(status_code=404, detail="Aucune question trouvée")

    # ── Score par question ─────────────────────────────────
    total_score = 0.0
    max_score = 0.0
    chapter_scores: dict[str, dict] = {}  # chapter_id → {score, max_score, title}

    for item in request.answers:
        q = questions.get(item.question_id)
        if not q:
            continue

        max_pts = float(q.get("points", 1.0))
        max_score += max_pts
        chapter_id = q.get("chapter_id") or "unknown"

        if chapter_id not in chapter_scores:
            # Récupère le titre du chapitre
            ch_title = ""
            if chapter_id != "unknown":
                ch_result = (
                    supabase.table("chapters")
                    .select("title")
                    .eq("id", chapter_id)
                    .single()
                    .execute()
                )
                ch_title = ch_result.data.get("title", "") if ch_result.data else ""
            chapter_scores[chapter_id] = {
                "score": 0.0, "max": 0.0, "title": ch_title
            }

        chapter_scores[chapter_id]["max"] += max_pts

        # Scoring MCQ déterministe
        if q["question_type"] == "mcq":
            correct = (q.get("correct_answer") or "").strip().upper()
            given = item.answer.strip().upper()
            if given == correct:
                total_score += max_pts
                chapter_scores[chapter_id]["score"] += max_pts

        # Scoring LLM pour short_answer / structured
        else:
            pts = await _score_open_answer(q, item.answer, max_pts)
            total_score += pts
            chapter_scores[chapter_id]["score"] += pts

    # ── Feedback global ────────────────────────────────────
    percentage = (total_score / max_score * 100) if max_score > 0 else 0
    feedback = await _generate_exam_feedback(percentage, chapter_scores)

    # ── Sauvegarde la soumission ───────────────────────────
    submission = supabase.table("exam_submissions").insert({
        "mock_exam_id": str(exam_id),
        "user_id": current_user["user_id"],
        "total_score": round(total_score, 2),
        "section_scores": {
            cid: {"score": v["score"], "max": v["max"], "title": v["title"]}
            for cid, v in chapter_scores.items()
        },
        "feedback": feedback,
    }).execute()

    submission_id = submission.data[0]["id"] if submission.data else str(uuid.uuid4())

    section_scores = [
        SectionScore(
            chapter_id=cid,
            chapter_title=v["title"],
            score=round(v["score"], 2),
            max_score=v["max"],
        )
        for cid, v in chapter_scores.items()
    ]

    return ExamResult(
        submission_id=uuid.UUID(submission_id),
        total_score=round(total_score, 2),
        max_score=max_score,
        percentage=round(percentage, 1),
        section_scores=section_scores,
        feedback=feedback,
    )


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

async def _score_open_answer(question: dict, answer: str, max_pts: float) -> float:
    """Note une réponse ouverte avec le LLM. Retourne les points obtenus."""
    rubric = question.get("rubric") or []
    rubric_text = "\n".join(
        f"- {s['description']} ({s['points']} pts)" for s in rubric
    ) or "Award points proportionally based on correctness."

    messages = [
        {
            "role": "system",
            "content": (
                "You are a strict exam grader. "
                "Output ONLY a JSON object: {\"score\": float, \"max\": float} "
                "where score is points awarded out of max."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Question: {question['prompt']}\n"
                f"Rubric (max {max_pts} pts):\n{rubric_text}\n"
                f"Student answer: {answer}\n"
                "Grade it."
            ),
        },
    ]
    try:
        raw = await llm_complete(
            messages=messages, task="grader",
            max_tokens=100,
            response_format={"type": "json_object"},
        )
        data = json.loads(raw)
        return min(float(data.get("score", 0)), max_pts)
    except Exception:
        return 0.0


async def _generate_exam_feedback(
    percentage: float, chapter_scores: dict
) -> str:
    """Génère un feedback global personnalisé sur les résultats de l'examen."""
    weak_chapters = [
        v["title"]
        for v in chapter_scores.values()
        if v["max"] > 0 and (v["score"] / v["max"]) < 0.5
    ]

    messages = [
        {
            "role": "system",
            "content": (
                "You are a supportive academic coach. "
                "Write a 3-4 sentence exam feedback in English. "
                "Be specific about weak areas. Be encouraging but honest."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Student scored {percentage:.1f}% overall.\n"
                f"Weak chapters (< 50%): {', '.join(weak_chapters) or 'None'}.\n"
                "Write the feedback."
            ),
        },
    ]
    try:
        return await llm_complete(messages=messages, task="grader", max_tokens=300)
    except Exception:
        return f"You scored {percentage:.1f}%. Keep studying and reviewing weak areas."


def _db_to_exam_schema(data: dict) -> ExamSchema:
    from app.schemas.exercise import MCQOption, RubricStep
    questions = []
    for q in sorted(data.get("exam_questions", []), key=lambda x: x.get("order_index", 0)):
        options = [MCQOption(**o) for o in (q.get("options") or [])] or None
        rubric = [RubricStep(**r) for r in (q.get("rubric") or [])] or None
        questions.append(
            ExamQuestionSchema(
                id=uuid.UUID(q["id"]),
                chapter_id=uuid.UUID(q["chapter_id"]) if q.get("chapter_id") else None,
                question_type=q["question_type"],
                prompt=q["prompt"],
                options=options,
                correct_answer=q.get("correct_answer"),
                rubric=rubric,
                points=q.get("points", 1.0),
                order_index=q.get("order_index", 0),
            )
        )
    return ExamSchema(
        id=uuid.UUID(data["id"]),
        roadmap_id=uuid.UUID(data["roadmap_id"]),
        title=data["title"],
        time_limit=data.get("time_limit"),
        question_count=data.get("question_count", len(questions)),
        questions=questions,
    )