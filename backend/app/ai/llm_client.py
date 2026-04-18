import litellm
from litellm import acompletion, aembedding
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

# Configure LiteLLM avec toutes les clés API
litellm.groq_key = settings.groq_api_key

# Headers OpenRouter obligatoires
litellm.headers = {
    "HTTP-Referer": settings.frontend_url,
    "X-Title": "PassExamAI",
}


async def llm_complete(
    messages: list[dict],
    task: str = "chat",
    stream: bool = False,
    response_format: dict | None = None,
    max_tokens: int = 2048,
) -> str | object:
    """
    Router central LiteLLM.
    task : 'chat' | 'exercise' | 'roadmap' | 'lesson' | 'exam' | 'grader' | 'query_rewriter'
    """
    model_map = {
        "chat": settings.model_chat,
        "exercise": settings.model_exercise,
        "roadmap": settings.model_roadmap,
        "lesson": settings.model_lesson,
        "exam": settings.model_exam,
        "grader": settings.model_grader,
        "query_rewriter": settings.model_query_rewriter,
    }
    model = model_map.get(task, settings.model_chat)

    kwargs = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": stream,
    }

    # JSON mode si demandé (pour les sorties structurées)
    if response_format:
        kwargs["response_format"] = response_format

    try:
        response = await acompletion(**kwargs)
        if stream:
            return response  # Retourne l'async generator directement
        return response.choices[0].message.content

    except Exception as e:
        logger.error(f"LLM error (task={task}, model={model}): {e}")
        raise


async def get_embeddings(texts: list[str]) -> list[list[float]]:

    try:
        response = await aembedding(
            model=settings.model_embeddings,
            input=texts,
            api_key=settings.openai_api_key,
        )
        return [item["embedding"] for item in response.data]

    except Exception as e:
        logger.error(f"Embedding error: {e}")
        raise