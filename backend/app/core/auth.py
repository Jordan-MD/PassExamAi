import logging
from typing import Optional

import jwt as pyjwt
from jwt import PyJWKClient, ExpiredSignatureError, InvalidTokenError
from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings

logger = logging.getLogger(__name__)
security = HTTPBearer(auto_error=True)

# ── JWKS client : récupère la clé publique Supabase une fois, la cache ──────
# Fonctionne pour ES256 (nouveaux projets) ET HS256 (anciens projets)
_jwks_client: Optional[PyJWKClient] = None

def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        jwks_url = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
        logger.info(f"Initialisation JWKS client → {jwks_url}")
        _jwks_client = PyJWKClient(jwks_url, cache_keys=True)
    return _jwks_client


def _decode_supabase_token(token: str) -> dict:
    """
    Décode un JWT Supabase via JWKS (ES256) avec fallback HS256.
    
    Supabase nouveaux projets → ES256, clé publique via JWKS endpoint
    Supabase anciens projets  → HS256, secret symétrique
    """
    # ── Tentative 1 : ES256 via JWKS (nouveaux projets Supabase) ────────────
    try:
        client = _get_jwks_client()
        signing_key = client.get_signing_key_from_jwt(token)
        payload = pyjwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256", "RS256"],
            audience="authenticated",
            options={"verify_exp": True},
        )
        logger.debug(f"Token validé via JWKS — sub={payload.get('sub', '?')}")
        return payload

    except ExpiredSignatureError:
        logger.info("Token expiré")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expiré. Reconnectez-vous.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as jwks_error:
        logger.debug(f"JWKS échoué ({type(jwks_error).__name__}), tentative HS256...")

    # ── Tentative 2 : HS256 via secret local (anciens projets) ──────────────
    try:
        payload = pyjwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
            options={"verify_exp": True},
        )
        logger.debug(f"Token validé via HS256 — sub={payload.get('sub', '?')}")
        return payload

    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expiré. Reconnectez-vous.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except InvalidTokenError as e:
        logger.warning(f"Token invalide (HS256 + JWKS tous les deux échoués) : {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_user_from_token(
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> dict:
    payload = _decode_supabase_token(credentials.credentials)

    user_id: Optional[str] = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token sans identifiant utilisateur.",
        )

    return {
        "user_id": user_id,
        "email": payload.get("email", ""),
        "role": payload.get("role", "authenticated"),
    }


verify_supabase_jwt = get_user_from_token