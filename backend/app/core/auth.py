import httpx
import json
import time
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.core.config import settings

security = HTTPBearer()

def _debug_log(hypothesis_id: str, location: str, message: str, data: dict) -> None:
    # region agent log
    try:
        with open("/home/bedane/dev/Projects AI/passexamai/.cursor/debug-a1f71d.log", "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "sessionId": "a1f71d",
                "runId": "run1",
                "hypothesisId": hypothesis_id,
                "location": location,
                "message": message,
                "data": data,
                "timestamp": int(time.time() * 1000),
            }, ensure_ascii=True) + "\n")
    except Exception:
        pass
    # endregion


async def verify_supabase_jwt(
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> dict:
    token = credentials.credentials

    url = f"{settings.supabase_url}/auth/v1/user"

    headers = {
        "Authorization": f"Bearer {token}",
        "apikey": settings.supabase_anon_key,  # IMPORTANT: publishable/anon pour /auth/v1/user
    }
    _debug_log("H1", "auth.py:74", "verify_supabase_jwt_start", {
        "url": url,
        "has_token": bool(token),
        "timeout_s": 10,
    })

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=headers)
    except httpx.TimeoutException as exc:
        _debug_log("H1", "auth.py:84", "verify_supabase_jwt_http_exception", {
            "exc_type": type(exc).__name__,
            "exc": str(exc)[:300],
        })
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service timeout. Please retry.",
        )
    except httpx.HTTPError as exc:
        _debug_log("H1", "auth.py:93", "verify_supabase_jwt_http_error", {
            "exc_type": type(exc).__name__,
            "exc": str(exc)[:300],
        })
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service unavailable. Please retry.",
        )

    if resp.status_code != 200:
        _debug_log("H3", "auth.py:91", "verify_supabase_jwt_non_200", {
            "status_code": resp.status_code,
            "response_excerpt": resp.text[:200],
        })
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token invalide (Supabase): {resp.text}",
        )

    data = resp.json()

    # Supabase renvoie un objet user; selon le contexte, le "id" du user est souvent dans `id`
    user_id = data.get("id") or data.get("sub")
    if not user_id:
        _debug_log("H2", "auth.py:104", "verify_supabase_jwt_missing_user_id", {
            "keys": list(data.keys())[:20],
        })
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token validé mais user id manquant: {data}",
        )
    _debug_log("H2", "auth.py:111", "verify_supabase_jwt_success", {
        "has_email": bool(data.get("email")),
        "user_id_len": len(str(user_id)),
    })

    return {
        "sub": user_id,
        "email": data.get("email", ""),
    }