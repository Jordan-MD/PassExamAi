import json
import logging
from app.ai.llm_client import llm_complete
from app.db.supabase_client import supabase
from app.rag.retrieval import retrieve_for_chapter
from app.schemas.exercise import ExerciseSchema, MCQOption, RubricStep

logger = logging.getLogger(__name__)

EXERCISE_SYSTEM_PROMPT = """You are an expert exam question writer.
Generate exercises for a student preparing for an exam chapter.

Output ONLY valid JSON object with this structure (no markdown, no explanation):
{
  "exercises": [
    {
      "question_type": "mcq",
      "prompt": "string — the question",
      "options": [
        {"label": "A", "content": "string"},
        {"label": "B", "content": "string"},
        {"label": "C", "content": "string"},
        {"label": "D", "content": "string"}
    },
    "correct_answer": "A",
    "difficulty": 2
  ],
  {
    "question_type": "short_answer",
    "prompt": "string — the question",
    "expected_answer_schema": [
      {"description": "string — what to award points for", "points": 2.0}
    ],
    "difficulty": 2
  },
  {
    "question_type": "structured",
    "prompt": "string — multi-part question",
    "expected_answer_schema": [
      {"description": "Part (a): ...", "points": 3.0},
      {"description": "Part (b): ...", "points": 4.0}
    ],
    "difficulty": 3
  }
}

Rules:
- Base ALL questions strictly on the provided document content — no outside facts
- difficulty: 1=easy, 2=medium, 3=hard
- MCQ: exactly 4 options, one clearly correct
- All text in English
"""


async def generate_exercises(
    chapter_id: str,
    project_id: str,
    count: int = 5,
    types: list[str] | None = None,
) -> list[ExerciseSchema]:
    """
    Génère des exercices pour un chapitre.
    types : ["mcq", "short_answer", "structured"] — None = mix automatique
    Utilise RAG only (pas de web — les exercices doivent rester dans le programme)
    """
    if types is None:
        types = ["mcq", "mcq", "short_answer", "short_answer", "structured"]

    # Récupère le chapitre
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

    # RAG uniquement — pas de web pour les exercices
    rag_chunks = await retrieve_for_chapter(
        chapter_title=title,
        project_id=project_id,
        top_k=6,
    )

    rag_context = "\n\n".join(
        f"[Chunk {i+1}]\n{c.get('content', '')[:1200]}"
        for i, c in enumerate(rag_chunks[:5])
    )

    type_distribution = ", ".join(types[:count])
    user_prompt = f"""Chapter: {title}
Objective: {objective}
Generate {count} exercises. Type distribution: {type_distribution}

Document content (use ONLY this as source):
{rag_context if rag_context else "No chunks available — generate based on chapter title."}
"""

    messages = [
        {"role": "system", "content": EXERCISE_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    raw = await llm_complete(
        messages=messages,
        task="exercise",
        max_tokens=2500,
        response_format={"type": "json_object"},
    )

    exercises = _parse_exercises(raw, chapter_id)

    # Sauvegarde en DB
    saved = _save_exercises(exercises, chapter_id)
    logger.info(f"✅ {len(saved)} exercices générés pour chapitre {chapter_id}")
    return saved


def _parse_exercises(raw: str, chapter_id: str) -> list[ExerciseSchema]:
    import uuid
    try:
        # Le LLM peut retourner soit un array direct, soit {"exercises": [...]}
        data = json.loads(raw)
        if isinstance(data, dict):
            data = data.get("exercises", data.get("questions", []))

        result = []
        for item in data:
            options = None
            if item.get("options"):
                options = [
                    MCQOption(label=o["label"], content=o["content"])
                    for o in item["options"]
                ]

            rubric = None
            if item.get("expected_answer_schema"):
                rubric = [
                    RubricStep(
                        description=s["description"],
                        points=float(s["points"]),
                    )
                    for s in item["expected_answer_schema"]
                ]

            result.append(ExerciseSchema(
                chapter_id=uuid.UUID(chapter_id),
                question_type=item["question_type"],
                prompt=item["prompt"],
                options=options,
                correct_answer=item.get("correct_answer"),
                expected_answer_schema=rubric,
                difficulty=item.get("difficulty", 2),
            ))
        return result
    except Exception as e:
        raise ValueError(f"Exercise parse error: {e}\nRaw: {raw[:300]}")


def _save_exercises(exercises: list[ExerciseSchema], chapter_id: str) -> list[ExerciseSchema]:
    import uuid
    if not exercises:
        return []
    rows = [
        {
            "chapter_id": chapter_id,
            "question_type": ex.question_type,
            "prompt": ex.prompt,
            "options": [o.model_dump() for o in (ex.options or [])],
            "correct_answer": ex.correct_answer,
            "expected_answer_schema": [s.model_dump() for s in (ex.expected_answer_schema or [])],
            "difficulty": ex.difficulty,
        }
        for ex in exercises
    ]
    result = supabase.table("exercises").insert(rows).execute()
    for ex, row in zip(exercises, (result.data or [])):
        ex.id = uuid.UUID(row["id"])
    return exercises