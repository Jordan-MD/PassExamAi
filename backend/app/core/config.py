from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Supabase
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    supabase_jwt_secret: str

    # LLM
    openai_api_key: str
    gemini_api_key: str
    groq_api_key: str
    openrouter_api_key: str

    # Parsing
    llama_parse_api_key: str

    # Web Search
    tavily_api_key: str
    firecrawl_api_key: str

    # App
    environment: str = "development"
    backend_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:3000"

    # LLM Routing — modèles par tâche
    model_chat: str = "groq/llama-3.3-70b-versatile"
    model_exercise: str = "groq/llama-3.3-70b-versatile"
    model_roadmap: str = "openrouter/google/gemini-flash-1.5"
    model_lesson: str = "openrouter/anthropic/claude-haiku-3-5"
    model_exam: str = "openrouter/openai/gpt-4o-mini"
    model_grader: str = "openrouter/anthropic/claude-haiku-3-5"
    model_query_rewriter: str = "groq/llama-3.3-70b-versatile"
    model_embeddings: str = "text-embedding-3-small"

    # RAG
    chunk_size: int = 512
    chunk_overlap: int = 50
    top_k_retrieval: int = 10
    top_k_final: int = 3


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()