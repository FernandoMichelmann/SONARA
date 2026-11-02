from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db import get_db
from app.dependencies import get_current_developer
from app.models import User
from app.schemas import TokenResponse, UserLogin
from app.security import create_access_token, verify_password

router = APIRouter(prefix="/developer", tags=["Desenvolvedor"])

@router.post("/login", response_model=TokenResponse)
def developer_login(payload: UserLogin, db: Session = Depends(get_db)):
    email = str(payload.email).lower().strip()
    user = db.scalar(select(User).where(User.email == email, User.role == "developer"))
    if not user or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Credenciais inválidas ou acesso não autorizado.")
    return TokenResponse(access_token=create_access_token(user.id, user.role))

@router.get("/me")
def developer_me(user: User = Depends(get_current_developer)):
    return {"id": user.id, "email": user.email, "name": user.full_name, "role": user.role}
