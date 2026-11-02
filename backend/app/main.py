import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from app.api.routes import auth, developer
from app.core.config import settings
from app.db import Base, SessionLocal, engine
from app.models import User
from app.security import hash_password

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sonara")

def bootstrap_developer():
    email = (settings.developer_email or "").strip().lower()
    password = settings.developer_password
    if not email or not password:
        logger.warning("Developer not bootstrapped: configure DEVELOPER_EMAIL and DEVELOPER_PASSWORD in backend/.env")
        return
    if len(password) < 14:
        raise RuntimeError("DEVELOPER_PASSWORD must contain at least 14 characters.")
    with SessionLocal() as db:
        developer = db.scalar(select(User).where(User.email == email))
        if developer:
            if developer.role != "developer":
                raise RuntimeError("Configured developer email is already assigned to a normal account.")
            developer.full_name = settings.developer_name
            developer.password_hash = hash_password(password)
            developer.is_active = True
        else:
            db.add(User(email=email, full_name=settings.developer_name,
                        password_hash=hash_password(password), role="developer", is_active=True))
        db.commit()

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    bootstrap_developer()
    yield

app = FastAPI(title=settings.app_name, version="0.1.0",
              description="API oficial da plataforma SONARA.", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                   allow_credentials=True, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                   allow_headers=["Authorization", "Content-Type"])

@app.get("/health")
def health():
    return {"status": "ok", "service": "sonara-api"}

app.include_router(auth.router, prefix=settings.api_v1_prefix)
app.include_router(developer.router, prefix=settings.api_v1_prefix)
