import json
import uuid
import logging
from app.ai.llm_client import llm_complete
from app.db.supabase_client import supabase
from app.rag.retrieval import retrieve_for_chapter
from app.schemas.exam import ExamSchema, ExamQuestionSchema

logger = logging.getLogger(__name__)

EXAM_SYSTEM_PROMPT = """You are an expert exam paper writer.
Create a comprehensive mock exam based on the provided chapters and document content.

Output ONLY valid JSON object:
{
  "title": "string — exam title",
  "questions": [
    {
      "question_type": "mcq",
      "chapter_index": 0,
      "prompt": "string",
      "options": [
        {"label": "A", "content": "string"},
        {"label": "B", "content": "string"},
        {"label": "C", "content": "string"},
        {"label": "D", "content": "string"}
      ],
      "correct_answer": "A",
      "points": 1.0,
      "order_index": 1
    },
    {
      "question_type": "short_answer",
      "chapter_index": 1,
      "prompt": "string",
      "rubric": [
        {"description": "string", "points": 2.0}
      ],
      "points": 2.0,
      "order_index": 2
    }
  ]
}

Rules:
- Distribute questions proportionally by chapter importance
- Mix types: ~60% MCQ, ~25% short_answer, ~15% structured
- chapter_index refers to the index of the chapter in the input list
- All text in English
- questions must be grounded in the provided document content
"""


async def generate_exam(
    roadmap_id: str,
    question_count: int = 10,
    time_limit: int | None = None,
) -> ExamSchema:
    """
    Génère un examen blanc complet à partir d'une roadmap.
    Distribution des questions proportionnelle à l'importance des chapitres.
    """
    # ── 1. Récupère la roadmap et ses chapitres ────────────
    roadmap_result = (
        supabase.table("roadmaps")
        .select("id, title, project_id, chapters(*)")
        .eq("id", roadmap_id)
        .single()
        .execute()
    )
    if not roadmap_result.data:
        raise ValueError(f"Roadmap {roadmap_id} introuvable")

    roadmap_data = roadmap_result.data
    project_id = roadmap_data["project_id"]
    chapters = sorted(
        roadmap_data.get("chapters", []),
        key=lambda c: c["order_index"],
    )

    if not chapters:
        raise ValueError("Cette roadmap n'a pas de chapitres")

    # ── 2. Calcule la distribution des questions par chapitre ──
    total_importance = sum(c.get("importance", 1.0) for c in chapters)
    question_distribution = []
    remaining = question_count

    for i, ch in enumerate(chapters[:-1]):
        weight = ch.get("importance", 1.0) / total_importance
        count = max(1, round(question_count * weight))
        count = min(count, remaining - (len(chapters) - 1 - i))
        question_distribution.append(count)
        remaining -= count
    question_distribution.append(max(1, remaining))  # Dernier chapitre

    # ── 3. Récupère les chunks RAG par chapitre ────────────
    chapters_context = []
    for i, ch in enumerate(chapters):
        chunks = await retrieve_for_chapter(
            chapter_title=ch["title"],
            project_id=project_id,
            top_k=4,
        )
        context = "\n".join(
            c.get("content", "")[:800] for c in chunks[:3]
        )
        chapters_context.append({
            "index": i,
            "title": ch["title"],
            "objective": ch.get("objective", ""),
            "importance": ch.get("importance", 1.0),
            "question_count": question_distribution[i],
            "context": context,
        })

    # ── 4. Construit le prompt ─────────────────────────────
    chapters_summary = "\n\n".join(
        f"Chapter {c['index']+1}: {c['title']}\n"
        f"Objective: {c['objective']}\n"
        f"Questions to generate: {c['question_count']}\n"
        f"Importance: {c['importance']}\n"
        f"Content:\n{c['context'][:1000]}"
        for c in chapters_context
    )

    user_prompt = f"""Generate a mock exam with {question_count} total questions.

Chapters and their content:
{chapters_summary}

Total questions: {question_count}
Distribute questions as specified per chapter (question_count field).
"""

    messages = [
        {"role": "system", "content": EXAM_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    # ── 5. Appel LLM ──────────────────────────────────────
    raw = await llm_complete(
        messages=messages,
        task="exam",
        max_tokens=4000,
        response_format={"type": "json_object"},
    )

    # ── 6. Parse + Validation ──────────────────────────────
    exam_schema = _parse_exam(raw, roadmap_id, chapters, question_count, time_limit)

    # ── 7. Sauvegarde en DB ────────────────────────────────
    saved = _save_exam(exam_schema, roadmap_id, chapters)
    logger.info(f"✅ Exam généré: {len(saved.questions)} questions pour roadmap {roadmap_id}")
    return saved


def _parse_exam(
    raw: str,
    roadmap_id: str,
    chapters: list[dict],
    question_count: int,
    time_limit: int | None,
) -> ExamSchema:
    try:
        data = json.loads(raw)
        questions_raw = data.get("questions", [])

        questions = []
        for i, q in enumerate(questions_raw):
            chapter_index = q.get("chapter_index", 0)
            chapter_id = chapters[chapter_index]["id"] if chapter_index < len(chapters) else None

            options = None
            if q.get("options"):
                from app.schemas.exam import ExamQuestionSchema
                from app.schemas.exercise import MCQOption, RubricStep
                options = [MCQOption(label=o["label"], content=o["content"]) for o in q["options"]]

            rubric = None
            if q.get("rubric"):
                from app.schemas.exercise import RubricStep
                rubric = [RubricStep(description=s["description"], points=float(s["points"])) for s in q["rubric"]]

            questions.append(ExamQuestionSchema(
                chapter_id=uuid.UUID(chapter_id) if chapter_id else None,
                question_type=q["question_type"],
                prompt=q["prompt"],
                options=options,
                correct_answer=q.get("correct_answer"),
                rubric=rubric,
                points=float(q.get("points", 1.0)),
                order_index=i + 1,
            ))

        return ExamSchema(
            roadmap_id=uuid.UUID(roadmap_id),
            title=data.get("title", "Mock Exam"),
            time_limit=time_limit,
            question_count=len(questions),
            questions=questions,
        )

    except Exception as e:
        logger.error(f"Exam parse error: {e}\nRaw: {raw[:500]}")
        raise ValueError(f"LLM output invalide pour exam: {e}")


def _save_exam(exam: ExamSchema, roadmap_id: str, chapters: list[dict]) -> ExamSchema:
    exam_id = str(uuid.uuid4())

    supabase.table("mock_exams").insert({
        "id": exam_id,
        "roadmap_id": roadmap_id,
        "title": exam.title,
        "time_limit": exam.time_limit,
        "question_count": exam.question_count,
    }).execute()

    if exam.questions:
        question_rows = [
            {
                "mock_exam_id": exam_id,
                "chapter_id": str(q.chapter_id) if q.chapter_id else None,
                "question_type": q.question_type,
                "prompt": q.prompt,
                "options": [o.model_dump() for o in (q.options or [])],
                "correct_answer": q.correct_answer,
                "rubric": [r.model_dump() for r in (q.rubric or [])],
                "points": q.points,
                "order_index": q.order_index,
            }
            for q in exam.questions
        ]
        q_result = supabase.table("exam_questions").insert(question_rows).execute()
        for q, row in zip(exam.questions, (q_result.data or [])):
            q.id = uuid.UUID(row["id"])

    exam.id = uuid.UUID(exam_id)
    return exam