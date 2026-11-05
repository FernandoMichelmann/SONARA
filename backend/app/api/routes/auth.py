from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from hashlib import sha256
import logging
import secrets
import smtplib
import ssl
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import PasswordResetToken, User
from app.schemas import TokenResponse, UserLogin, UserRegister, UserResponse
from app.security import create_access_token, hash_password, verify_password
from app.core.config import settings
from app.dependencies import get_current_user

router = APIRouter(prefix="/auth", tags=["Autenticação"])
logger = logging.getLogger("sonara.auth")


def _email_is_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_username and settings.smtp_password
                and (settings.smtp_from_email or settings.smtp_username))


def _send_password_reset_email(recipient: str, name: str, reset_url: str) -> None:
    message = EmailMessage()
    sender = settings.smtp_from_email or settings.smtp_username
    message["Subject"] = "Redefina sua senha da SONARA"
    message["From"] = f"{settings.smtp_from_name} <{sender}>"
    message["To"] = recipient
    message.set_content(
        f"Olá, {name}.\n\nRecebemos uma solicitação para redefinir a senha da sua conta SONARA. "
        f"Acesse o link abaixo em até 30 minutos para criar uma nova senha:\n\n{reset_url}"
        "\n\nSe você não solicitou esta alteração, ignore este e-mail.\nEquipe SONARA"
    )
    if settings.smtp_use_ssl:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20,
                              context=ssl.create_default_context()) as server:
            server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(message)
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as server:
            server.ehlo()
            if settings.smtp_use_tls:
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
            server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(message)


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: UserRegister, db: Session = Depends(get_db)):
    email = str(payload.email).lower().strip()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="Já existe uma conta com este e-mail.")
    user = User(
        email=email,
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        role="user",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

@router.post("/login", response_model=TokenResponse)
def login(payload: UserLogin, db: Session = Depends(get_db)):
    email = str(payload.email).lower().strip()
    user = db.scalar(select(User).where(User.email == email, User.role == "user"))
    if not user or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="E-mail ou senha inválidos.")
    return TokenResponse(access_token=create_access_token(user.id, user.role))

@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)):
    if user.role != "user":
        raise HTTPException(status_code=403, detail="Esta sessão não pertence a uma conta de usuário.")
    return user



@router.post("/forgot-password")
def forgot_password(payload: dict, db: Session = Depends(get_db)):
    # A resposta não revela se o endereço possui cadastro.
    if not _email_is_configured():
        raise HTTPException(status_code=503, detail="O envio de e-mails ainda não está configurado na SONARA.")

    from pydantic import EmailStr, TypeAdapter, ValidationError
    try:
        email = str(TypeAdapter(EmailStr).validate_python(payload.get("email", ""))).lower().strip()
    except ValidationError:
        raise HTTPException(status_code=422, detail="Informe um e-mail válido.")

    user = db.scalar(select(User).where(
        User.email == email, User.role == "user", User.is_active.is_(True)
    ))
    generic_response = {"message": "Se o e-mail estiver cadastrado, você receberá um link para redefinir sua senha."}
    if not user:
        return generic_response

    now = datetime.now(timezone.utc)
    recent = db.scalar(select(PasswordResetToken).where(
        PasswordResetToken.user_id == user.id,
    ).order_by(PasswordResetToken.created_at.desc()))
    if recent:
        recent_created_at = recent.created_at
        if recent_created_at.tzinfo is None:
            recent_created_at = recent_created_at.replace(tzinfo=timezone.utc)
        if recent_created_at >= now - timedelta(seconds=60):
            return generic_response

    db.execute(delete(PasswordResetToken).where(PasswordResetToken.user_id == user.id))
    raw_token = secrets.token_urlsafe(32)
    token_hash = sha256(raw_token.encode("utf-8")).hexdigest()
    db.add(PasswordResetToken(
        user_id=user.id, token_hash=token_hash,
        expires_at=now + timedelta(minutes=30),
    ))
    db.commit()

    reset_url = f"{settings.frontend_base_url.rstrip('/')}/?reset_token={quote(raw_token)}"
    try:
        _send_password_reset_email(user.email, user.full_name, reset_url)
    except Exception:
        logger.exception("Falha ao enviar e-mail de redefinição de senha.")
        db.execute(delete(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash))
        db.commit()
        raise HTTPException(status_code=503, detail="Não foi possível enviar o e-mail agora. Tente novamente mais tarde.")
    return generic_response


@router.post("/reset-password")
def reset_password(payload: dict, db: Session = Depends(get_db)):
    raw_token = str(payload.get("token") or "").strip()
    new_password = str(payload.get("new_password") or "")
    if len(new_password) < 10 or len(new_password) > 128:
        raise HTTPException(status_code=422, detail="A nova senha deve ter entre 10 e 128 caracteres.")
    if not raw_token or len(raw_token) > 200:
        raise HTTPException(status_code=400, detail="Link inválido ou expirado. Solicite uma nova redefinição.")

    token_hash = sha256(raw_token.encode("utf-8")).hexdigest()
    reset = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash))
    now = datetime.now(timezone.utc)
    if not reset or reset.used_at is not None:
        raise HTTPException(status_code=400, detail="Link inválido ou expirado. Solicite uma nova redefinição.")

    expires_at = reset.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now:
        db.delete(reset)
        db.commit()
        raise HTTPException(status_code=400, detail="Link inválido ou expirado. Solicite uma nova redefinição.")

    user = db.scalar(select(User).where(
        User.id == reset.user_id, User.role == "user", User.is_active.is_(True)
    ))
    if not user:
        db.delete(reset)
        db.commit()
        raise HTTPException(status_code=400, detail="Link inválido ou expirado. Solicite uma nova redefinição.")

    user.password_hash = hash_password(new_password)
    reset.used_at = now
    db.execute(delete(PasswordResetToken).where(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.id != reset.id,
    ))
    db.commit()
    return {"message": "Senha redefinida com sucesso. Você já pode entrar na SONARA."}
