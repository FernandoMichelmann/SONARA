import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import User
from app.security import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)

def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
                     db: Session = Depends(get_db)) -> User:
    unauthorized = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Sessão ausente ou inválida.", headers={"WWW-Authenticate": "Bearer"})
    if credentials is None:
        raise unauthorized
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = int(payload["sub"])
        role = payload.get("role")
    except (jwt.InvalidTokenError, ValueError, KeyError, TypeError):
        raise unauthorized
    user = db.get(User, user_id)
    if not user or not user.is_active or user.role != role:
        raise unauthorized
    return user

def get_current_developer(user: User = Depends(get_current_user)) -> User:
    if user.role != "developer":
        raise HTTPException(status_code=403, detail="Acesso exclusivo ao desenvolvedor.")
    return user
