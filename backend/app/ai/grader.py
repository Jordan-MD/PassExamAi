import json
import logging
from app.ai.llm_client import llm_complete
from app.db.supabase_client import supabase
from app.schemas.exercise import GradingResult

logger = logging.getLogger(__name__)

GRADER_SYSTEM_PROMPT = """You are a strict but fair exam grader.
Evaluate the student's answer against the rubric.

Output ONLY valid JSON:
{
  "score": 75.0,
  "is_correct": false,
  "feedback": "string — detailed, constructive feedback (2-4 sentences)",
  "correct_answer": "string — what the correct answer should be",
  "improvement_suggestions": ["string", "string"]
}

Rules:
- score: 0 to 100
- is_correct: true only if score >= 70
- feedback: explain WHY points were lost, not just WHAT was wrong
- improvement_suggestions: 1 to 3 concrete study tips
"""


async def grade_answer(
    exercise_id: str,
    user_id: str,
    student_answer: str,
) -> GradingResult:
    """
    Note la réponse d'un étudiant à un exercice.
    MCQ : scoring déterministe.
    Short answer / Structured : LLM avec rubric.
    Sauvegarde le résultat dans la table attempts.
    """
    # Récupère l'exercice
    ex_result = (
        supabase.table("exercises")
        .select("*")
        .eq("id", exercise_id)
        .single()
        .execute()
    )
    if not ex_result.data:
        raise ValueError(f"Exercice {exercise_id} introuvable")

    ex = ex_result.data
    question_type = ex["question_type"]

    # ── MCQ : déterministe ───────────────────────────────
    if question_type == "mcq":
        result = _grade_mcq(ex, student_answer)

    # ── Short answer / Structured : LLM ──────────────────
    else:
        result = await _grade_with_llm(ex, student_answer)

    # ── Sauvegarde l'attempt ─────────────────────────────
    supabase.table("attempts").insert({
        "exercise_id": exercise_id,
        "user_id": user_id,
        "answer": student_answer,
        "score": result.score,
        "feedback": result.feedback,
        "is_correct": result.is_correct,
    }).execute()

    import uuid
    result.exercise_id = uuid.UUID(exercise_id)
    return result


def _grade_mcq(ex: dict, student_answer: str) -> GradingResult:
    """Scoring MCQ déterministe — pas besoin de LLM."""
    correct = (ex.get("correct_answer") or "").strip().upper()
    given = student_answer.strip().upper()
    is_correct = given == correct
    score = 100.0 if is_correct else 0.0

    # Trouve le contenu de la bonne option pour le feedback
    correct_content = ""
    for opt in (ex.get("options") or []):
        if opt.get("label", "").upper() == correct:
            correct_content = opt.get("content", "")
            break

    feedback = (
        f"Correct! The answer is {correct}."
        if is_correct
        else f"Incorrect. The correct answer is {correct}: {correct_content}"
    )

    return GradingResult(
        score=score,
        is_correct=is_correct,
        feedback=feedback,
        correct_answer=f"{correct}: {correct_content}",
        improvement_suggestions=(
            [] if is_correct
            else ["Review this concept in your lesson", "Try the related exercises again"]
        ),
    )


async def _grade_with_llm(ex: dict, student_answer: str) -> GradingResult:
    """Notation LLM pour short_answer et structured."""
    rubric = ex.get("expected_answer_schema") or []
    rubric_text = "\n".join(
        f"- {step['description']} ({step['points']} pts)"
        for step in rubric
    ) or "Award points based on correctness and completeness."

    user_prompt = f"""Question: {ex['prompt']}

Grading rubric:
{rubric_text}

Student answer: {student_answer}

Grade this answer.
"""

    messages = [
        {"role": "system", "content": GRADER_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    raw = await llm_complete(
        messages=messages,
        task="grader",
        max_tokens=600,
        response_format={"type": "json_object"},
    )

    try:
        data = json.loads(raw)
        return GradingResult(
            score=float(data["score"]),
            is_correct=bool(data["is_correct"]),
            feedback=data["feedback"],
            correct_answer=data.get("correct_answer", ""),
            improvement_suggestions=data.get("improvement_suggestions", []),
        )
    except Exception as e:
        raise ValueError(f"Grader parse error: {e}")