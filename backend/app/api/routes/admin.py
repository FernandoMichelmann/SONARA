from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_developer
from app.models import RevenueEntry, Track, User

router = APIRouter(prefix="/developer", tags=["Administração do desenvolvedor"])
AUDIO_DIR = Path(__file__).resolve().parents[3] / "uploads" / "tracks"
ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac"}
MAX_AUDIO_BYTES = 500 * 1024 * 1024


class UserStatusUpdate(BaseModel):
    is_active: bool


class RevenueCreate(BaseModel):
    description: str = Field(min_length=2, max_length=240)
    source: str = Field(default="Manual", min_length=2, max_length=80)
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    status: str = Field(default="received", pattern="^(received|pending)$")
    occurred_at: datetime | None = None


def track_payload(track: Track):
    return {
        "id": track.id, "title": track.title, "artist": track.artist,
        "musical_key": track.musical_key, "bpm": track.bpm,
        "category": track.category, "original_filename": track.original_filename,
        "file_size": track.file_size, "is_published": track.is_published,
        "created_at": track.created_at.isoformat() if track.created_at else None,
        "audio_url": f"/api/v1/tracks/{track.id}/audio" if track.is_published else None,
    }


@router.get("/users")
def list_users(
    q: str = Query(default="", max_length=254),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    _developer: User = Depends(get_current_developer),
    db: Session = Depends(get_db),
):
    base = select(User).where(User.role == "user")
    if q.strip():
        term = f"%{q.strip().lower()}%"
        base = base.where(
            func.lower(User.email).like(term) | func.lower(User.full_name).like(term)
        )
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    users = db.scalars(base.order_by(User.created_at.desc()).offset(skip).limit(limit)).all()
    return {
        "total": total,
        "items": [{
            "id": user.id, "full_name": user.full_name, "email": user.email,
            "is_active": user.is_active, "created_at": user.created_at.isoformat(),
        } for user in users],
    }


@router.patch("/users/{user_id}/status")
def update_user_status(
    user_id: int,
    payload: UserStatusUpdate,
    _developer: User = Depends(get_current_developer),
    db: Session = Depends(get_db),
):
    user = db.scalar(select(User).where(User.id == user_id, User.role == "user"))
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    user.is_active = payload.is_active
    db.commit()
    return {"id": user.id, "is_active": user.is_active}


@router.get("/tracks")
def list_tracks(
    q: str = Query(default="", max_length=180),
    _developer: User = Depends(get_current_developer),
    db: Session = Depends(get_db),
):
    statement = select(Track)
    if q.strip():
        term = f"%{q.strip().lower()}%"
        statement = statement.where(func.lower(Track.title).like(term) | func.lower(Track.artist).like(term))
    tracks = db.scalars(statement.order_by(Track.created_at.desc())).all()
    return {"total": len(tracks), "items": [track_payload(track) for track in tracks]}


@router.post("/tracks", status_code=status.HTTP_201_CREATED)
async def upload_track(
    title: str = Form(min_length=1, max_length=180),
    artist: str = Form(default="", max_length=180),
    musical_key: str = Form(default="", max_length=20),
    bpm: int | None = Form(default=None, ge=1, le=400),
    category: str = Form(default="Multitrack", max_length=80),
    is_published: bool = Form(default=False),
    audio: UploadFile = File(...),
    developer: User = Depends(get_current_developer),
    db: Session = Depends(get_db),
):
    original_name = Path(audio.filename or "audio").name
    extension = Path(original_name).suffix.lower()
    if extension not in ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Formato não permitido. Envie MP3, WAV, FLAC, M4A, OGG ou AAC.")

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    stored_path = AUDIO_DIR / f"{uuid4().hex}{extension}"
    size = 0
    try:
        with stored_path.open("wb") as destination:
            while chunk := await audio.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_AUDIO_BYTES:
                    raise HTTPException(status_code=413, detail="O arquivo excede o limite de 500 MB.")
                destination.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="O arquivo enviado está vazio.")
        track = Track(
            title=title.strip(), artist=artist.strip(), musical_key=musical_key.strip(),
            bpm=bpm, category=category.strip() or "Multitrack",
            original_filename=original_name, storage_path=str(stored_path),
            content_type=audio.content_type or "application/octet-stream",
            file_size=size, is_published=is_published,
        )
        db.add(track)
        db.commit()
        db.refresh(track)
        return track_payload(track)
    except HTTPException:
        stored_path.unlink(missing_ok=True)
        raise
    except Exception:
        stored_path.unlink(missing_ok=True)
        db.rollback()
        raise
    finally:
        await audio.close()


@router.patch("/tracks/{track_id}")
def update_track(
    track_id: int,
    title: str | None = Form(default=None, max_length=180),
    artist: str | None = Form(default=None, max_length=180),
    musical_key: str | None = Form(default=None, max_length=20),
    bpm: int | None = Form(default=None, ge=1, le=400),
    category: str | None = Form(default=None, max_length=80),
    is_published: bool | None = Form(default=None),
    _developer: User = Depends(get_current_developer),
    db: Session = Depends(get_db),
):
    track = db.get(Track, track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Track não encontrada.")
    if title is not None:
        track.title = title.strip()
    if artist is not None:
        track.artist = artist.strip()
    if musical_key is not None:
        track.musical_key = musical_key.strip()
    if bpm is not None:
        track.bpm = bpm
    if category is not None:
        track.category = category.strip()
    if is_published is not None:
        track.is_published = is_published
    db.commit()
    db.refresh(track)
    return track_payload(track)


@router.get("/revenues")
def list_revenues(
    limit: int = Query(default=100, ge=1, le=500),
    _developer: User = Depends(get_current_developer),
    db: Session = Depends(get_db),
):
    entries = db.scalars(select(RevenueEntry).order_by(RevenueEntry.occurred_at.desc()).limit(limit)).all()
    return {"items": [{
        "id": item.id, "description": item.description, "source": item.source,
        "amount": str(item.amount), "currency": item.currency, "status": item.status,
        "occurred_at": item.occurred_at.isoformat(),
    } for item in entries]}


@router.post("/revenues", status_code=status.HTTP_201_CREATED)
def create_revenue(
    payload: RevenueCreate,
    developer: User = Depends(get_current_developer),
    db: Session = Depends(get_db),
):
    occurred_at = payload.occurred_at or datetime.now(timezone.utc)
    entry = RevenueEntry(
        description=payload.description.strip(), source=payload.source.strip(),
        amount=payload.amount, status=payload.status, occurred_at=occurred_at,
        created_by=developer.id,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return {
        "id": entry.id, "description": entry.description, "source": entry.source,
        "amount": str(entry.amount), "currency": entry.currency, "status": entry.status,
        "occurred_at": entry.occurred_at.isoformat(),
    }


@router.get("/revenue-summary")
def revenue_summary(
    _developer: User = Depends(get_current_developer),
    db: Session = Depends(get_db),
):
    received = db.scalar(select(func.coalesce(func.sum(RevenueEntry.amount), 0)).where(RevenueEntry.status == "received"))
    pending = db.scalar(select(func.coalesce(func.sum(RevenueEntry.amount), 0)).where(RevenueEntry.status == "pending"))
    count = db.scalar(select(func.count(RevenueEntry.id))) or 0
    return {
        "received_total": str(received),
        "pending_total": str(pending),
        "entries_count": count,
        "currency": "BRL",
        "note": "Valores baseados nos lançamentos registrados; ainda não sincronizados com um gateway de pagamento.",
    }
