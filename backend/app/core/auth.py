from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from app.core.config import settings

security = HTTPBearer()


def verify_supabase_jwt(
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> dict:
    """
    Valide le JWT Supabase sur chaque requête.
    Retourne le payload décodé contenant user_id (sub), email, etc.
    """
    token = credentials.credentials
    try:
        payload = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            options={"verify_aud": False},  # Supabase n'utilise pas audience
        )
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token invalide : user_id manquant",
            )
        return payload

    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token invalide : {str(e)}",
        )