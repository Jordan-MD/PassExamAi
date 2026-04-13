from supabase import create_client, Client
from app.core.config import settings
from functools import lru_cache


@lru_cache
def get_supabase_client() -> Client:
    """Client avec service_role pour contourner RLS depuis le backend."""
    return create_client(
        settings.supabase_url,
        settings.supabase_service_role_key,  # Service role = accès complet
    )


supabase: Client = get_supabase_client()