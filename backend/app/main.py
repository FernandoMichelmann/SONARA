import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, inspect, text
from app.api.routes import account, admin, auth, catalog, developer, payments, drive, telegram
from app.core.config import settings
from app.db import Base, SessionLocal, engine
from app.models import RevenueEntry, Track, TrackCategory, User
from app.security import hash_password

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sonara")

def migrate_track_columns():
    """Additive migration that preserves all existing track records."""
    additions = {
        "categories_json": "TEXT NOT NULL DEFAULT '[]'",
        "time_signature": "VARCHAR(12) NOT NULL DEFAULT '4/4'",
        "stems_path": "VARCHAR(600) NOT NULL DEFAULT ''",
        "preview_start_seconds": "INTEGER NOT NULL DEFAULT 0",
        "preview_end_seconds": "INTEGER NOT NULL DEFAULT 30",
        "cover_path": "VARCHAR(600)",
        "cover_content_type": "VARCHAR(120)",
        "source_drive_folder_id": "VARCHAR(160)",
        "source_telegram_message_id": "VARCHAR(180)",
    }
    with engine.begin() as connection:
        existing = {column["name"] for column in inspect(engine).get_columns("tracks")}
        for column, definition in additions.items():
            if column not in existing:
                connection.execute(text(f"ALTER TABLE tracks ADD COLUMN {column} {definition}"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_tracks_source_drive_folder_id ON tracks (source_drive_folder_id)"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_tracks_source_telegram_message_id ON tracks (source_telegram_message_id)"))

def migrate_user_profile_columns():
    """Add profile fields without deleting or rewriting existing accounts."""
    additions = {
        "address": "VARCHAR(240)",
        "birth_date": "DATE",
        "cpf_hash": "VARCHAR(64)",
        "language": "VARCHAR(2) NOT NULL DEFAULT 'pt'",
        "lifetime_access": "BOOLEAN NOT NULL DEFAULT FALSE",
        "lifetime_access_at": "TIMESTAMP",
    }
    with engine.begin() as connection:
        existing = {column["name"] for column in inspect(engine).get_columns("users")}
        for column, definition in additions.items():
            if column not in existing:
                connection.execute(text(f"ALTER TABLE users ADD COLUMN {column} {definition}"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_cpf_hash ON users (cpf_hash)"))


def bootstrap_developer():
    email = (settings.developer_email or "").strip().lower()
    password = settings.developer_password
    if not email or not password or email == "owner@example.com" or password.startswith("CHANGE_THIS"):
        raise RuntimeError("Configure a real DEVELOPER_EMAIL and DEVELOPER_PASSWORD in backend/.env before starting SONARA.")
    if len(password) < 14:
        raise RuntimeError("DEVELOPER_PASSWORD must contain at least 14 characters.")
    if len(settings.jwt_secret_key) < 32 or settings.jwt_secret_key.startswith("CHANGE_THIS"):
        raise RuntimeError("Configure a random JWT_SECRET_KEY with at least 32 characters in backend/.env.")
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
    migrate_track_columns()
    migrate_user_profile_columns()
    bootstrap_developer()
    yield

app = FastAPI(title=settings.app_name, version="0.1.0",
              description="API oficial da plataforma SONARA.", lifespan=lifespan)
# Keep the production GitHub Pages frontend authorized even when backend/.env
# contains a custom CORS_ORIGINS value. Preserve all additional configured origins.
configured_origins = [
    origin.strip().rstrip("/")
    for origin in settings.cors_origins.split(",")
    if origin.strip()
]
required_origins = ["https://fernandomichelmann.github.io"]
allowed_origins = list(dict.fromkeys(configured_origins + required_origins))

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

@app.get("/health")
def health():
    return {"status": "ok", "service": "sonara-api"}

app.include_router(auth.router, prefix=settings.api_v1_prefix)
app.include_router(developer.router, prefix=settings.api_v1_prefix)
app.include_router(admin.router, prefix=settings.api_v1_prefix)
app.include_router(catalog.router, prefix=settings.api_v1_prefix)
app.include_router(account.router, prefix=settings.api_v1_prefix)
app.include_router(payments.router, prefix=settings.api_v1_prefix)
app.include_router(drive.router, prefix=settings.api_v1_prefix)
app.include_router(telegram.router, prefix=settings.api_v1_prefix)
