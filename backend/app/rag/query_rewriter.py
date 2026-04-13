from app.ai.llm_client import llm_complete
import logging

logger = logging.getLogger(__name__)

REWRITE_SYSTEM_PROMPT = """You are a query optimization assistant for an educational RAG system.
Your task: rewrite the user's question into an optimal search query for semantic vector retrieval.

Rules:
- Extract the core concept or topic
- Add relevant educational keywords (definition, explanation, example, formula, method...)
- Keep it concise (max 20 words)
- Output ONLY the rewritten query, nothing else
"""


async def rewrite_query(
    user_question: str,
    chapter_context: str | None = None,
) -> str:
    """
    Reformule la question de l'utilisateur pour améliorer le recall RAG.
    Ex: "Je comprends pas" → "Definition and worked examples of [topic] from [chapter]"
    
    Améliore le recall de 25-40% selon le SDD.
    """
    context_hint = (
        f"\nCurrent chapter context: {chapter_context}" if chapter_context else ""
    )

    messages = [
        {"role": "system", "content": REWRITE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Original question: {user_question}{context_hint}",
        },
    ]

    try:
        rewritten = await llm_complete(
            messages=messages,
            task="query_rewriter",
            max_tokens=100,
        )
        rewritten = rewritten.strip()
        logger.info(f"Query rewrite: '{user_question[:50]}' → '{rewritten}'")
        return rewritten

    except Exception as e:
        logger.warning(f"Query rewrite failed, using original: {e}")
        return user_question  # Fallback gracieux