from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.core.auth import verify_supabase_jwt
from app.db.supabase_client import get_supabase_client

security = HTTPBearer()


def get_current_user(
    payload: dict = Depends(verify_supabase_jwt),
) -> dict:
    """
    Dependency injectable dans toutes les routes.
    Usage : current_user: dict = Depends(get_current_user)
    Retourne : {"user_id": "...", "email": "..."}
    """
    return {
        "user_id": payload["sub"],
        "email": payload.get("email", ""),
    }