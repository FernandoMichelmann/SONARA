from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
import json
import zipfile
import shutil
import mimetypes

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_developer
from app.models import RevenueEntry, Track, TrackCategory, User

router = APIRouter(prefix="/developer", tags=["Administração do desenvolvedor"])
AUDIO_DIR = Path(__file__).resolve().parents[3] / "uploads" / "tracks"
COVER_DIR = Path(__file__).resolve().parents[3] / "uploads" / "covers"
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024
MAX_EXTRACTED_BYTES = 2 * 1024 * 1024 * 1024
MAX_STEM_FILES = 100
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
    try:
        categories = json.loads(track.categories_json or "[]")
    except (TypeError, json.JSONDecodeError):
        categories = [track.category] if track.category else []
    stems_dir = Path(track.stems_path) if track.stems_path else None
    stems = [{"name": p.name, "size": p.stat().st_size} for p in sorted(stems_dir.iterdir()) if p.is_file()] if stems_dir and stems_dir.is_dir() else []
    return {
        "id": track.id, "title": track.title, "artist": track.artist,
        "musical_key": track.musical_key, "bpm": track.bpm,
        "time_signature": getattr(track, "time_signature", "4/4"),
        "category": track.category, "categories": categories,
        "original_filename": track.original_filename,
        "file_size": track.file_size, "is_published": track.is_published,
        "created_at": track.created_at.isoformat() if track.created_at else None,
        "audio_url": f"/api/v1/tracks/{track.id}/audio" if track.is_published else None,
        "cover_url": f"/api/v1/tracks/{track.id}/cover" if track.cover_path else None,
        "stems": stems,
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


@router.get("/track-categories")
def list_track_categories(
    _developer: User = Depends(get_current_developer),
    db: Session = Depends(get_db),
):
    categories = db.scalars(select(TrackCategory).order_by(TrackCategory.name.asc())).all()
    if not categories:
        for name in ["Gospel", "Rock", "Nacional", "Internacional"]:
            db.add(TrackCategory(name=name))
        db.commit()
        categories = db.scalars(select(TrackCategory).order_by(TrackCategory.name.asc())).all()
    return {"items": [{"id": item.id, "name": item.name} for item in categories]}


@router.post("/track-categories", status_code=status.HTTP_201_CREATED)
def create_track_category(
    payload: dict,
    _developer: User = Depends(get_current_developer),
    db: Session = Depends(get_db),
):
    name = str(payload.get("name", "")).strip()
    if not name or len(name) > 60:
        raise HTTPException(status_code=422, detail="Informe uma categoria com até 60 caracteres.")
    existing = db.scalar(select(TrackCategory).where(func.lower(TrackCategory.name) == name.lower()))
    if existing:
        return {"id": existing.id, "name": existing.name}
    item = TrackCategory(name=name)
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"id": item.id, "name": item.name}


@router.post("/tracks", status_code=status.HTTP_201_CREATED)
async def upload_track(
    title: str = Form(min_length=1, max_length=180),
    artist: str = Form(default="", max_length=180),
    musical_key: str = Form(default="", max_length=20),
    bpm: int | None = Form(default=None, ge=1, le=400),
    time_signature: str = Form(default="4/4", max_length=12),
    categories: str = Form(default="[]"),
    is_published: bool = Form(default=False),
    archive: UploadFile = File(...),
    cover: UploadFile | None = File(default=None),
    developer: User = Depends(get_current_developer),
    db: Session = Depends(get_db),
):
    archive_name = Path(archive.filename or "multitrack.zip").name
    if Path(archive_name).suffix.lower() != ".zip":
        raise HTTPException(status_code=415, detail="Envie o pacote de áudio em formato ZIP.")
    try:
        selected = json.loads(categories)
        if not isinstance(selected, list):
            raise ValueError()
        selected = list(dict.fromkeys(str(item).strip() for item in selected if str(item).strip()))
    except (ValueError, json.JSONDecodeError):
        raise HTTPException(status_code=422, detail="Categorias inválidas.")
    if len(selected) > 20:
        raise HTTPException(status_code=422, detail="Selecione no máximo 20 categorias.")

    track_key = uuid4().hex
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    track_dir = AUDIO_DIR / track_key
    track_dir.mkdir(parents=True, exist_ok=True)
    archive_path = track_dir / "source.zip"
    saved_cover = None
    try:
        archive_size = 0
        with archive_path.open("wb") as destination:
            while chunk := await archive.read(1024 * 1024):
                archive_size += len(chunk)
                if archive_size > MAX_ARCHIVE_BYTES:
                    raise HTTPException(status_code=413, detail="O ZIP excede o limite de 1 GB.")
                destination.write(chunk)
        if archive_size == 0:
            raise HTTPException(status_code=400, detail="O ZIP enviado está vazio.")

        stems_dir = track_dir / "stems"
        stems_dir.mkdir()
        total_uncompressed = 0
        extracted_count = 0
        with zipfile.ZipFile(archive_path) as zipped:
            for member in zipped.infolist():
                if member.is_dir():
                    continue
                raw_name = member.filename.replace("\\", "/")
                parts = Path(raw_name).parts
                if raw_name.startswith("/") or ".." in parts or not parts:
                    raise HTTPException(status_code=400, detail="O ZIP contém um caminho inválido.")
                if Path(raw_name).suffix.lower() not in ALLOWED_AUDIO_EXTENSIONS:
                    continue
                if member.flag_bits & 0x1:
                    raise HTTPException(status_code=400, detail="O ZIP contém arquivos protegidos por senha.")
                extracted_count += 1
                total_uncompressed += member.file_size
                if extracted_count > MAX_STEM_FILES or total_uncompressed > MAX_EXTRACTED_BYTES:
                    raise HTTPException(status_code=413, detail="O ZIP excede 100 stems ou 2 GB extraídos.")
                destination_path = stems_dir / (f"{extracted_count:02d}_" + Path(raw_name).name)
                with zipped.open(member) as source, destination_path.open("wb") as destination:
                    shutil.copyfileobj(source, destination, length=1024 * 1024)
        stem_files = sorted(path for path in stems_dir.iterdir() if path.is_file())
        if not stem_files:
            raise HTTPException(status_code=400, detail="Nenhum arquivo de áudio compatível foi encontrado dentro do ZIP.")

        if cover and cover.filename:
            cover_extension = Path(cover.filename).suffix.lower()
            if cover_extension not in ALLOWED_IMAGE_EXTENSIONS:
                raise HTTPException(status_code=415, detail="A capa deve ser JPG, PNG ou WEBP.")
            COVER_DIR.mkdir(parents=True, exist_ok=True)
            saved_cover = COVER_DIR / (track_key + cover_extension)
            cover_size = 0
            with saved_cover.open("wb") as destination:
                while chunk := await cover.read(1024 * 1024):
                    cover_size += len(chunk)
                    if cover_size > 12 * 1024 * 1024:
                        raise HTTPException(status_code=413, detail="A capa excede 12 MB.")
                    destination.write(chunk)

        main_stem = next((path for path in stem_files if any(word in path.stem.lower() for word in ("mix", "full", "stereo", "master"))), stem_files[0])
        track = Track(
            title=title.strip(), artist=artist.strip(), musical_key=musical_key.strip(),
            bpm=bpm, time_signature=time_signature.strip() or "4/4",
            category=", ".join(selected) or "Multitrack",
            categories_json=json.dumps(selected, ensure_ascii=False),
            original_filename=archive_name, storage_path=str(main_stem),
            stems_path=str(stems_dir),
            content_type=mimetypes.guess_type(main_stem.name)[0] or "application/octet-stream",
            file_size=archive_size, cover_path=str(saved_cover) if saved_cover else None,
            cover_content_type=mimetypes.guess_type(saved_cover.name)[0] if saved_cover else None,
            is_published=is_published,
        )
        db.add(track)
        db.commit()
        db.refresh(track)
        return track_payload(track)
    except zipfile.BadZipFile:
        db.rollback()
        shutil.rmtree(track_dir, ignore_errors=True)
        if saved_cover: saved_cover.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="O arquivo enviado não é um ZIP válido.")
    except Exception:
        db.rollback()
        shutil.rmtree(track_dir, ignore_errors=True)
        if saved_cover: saved_cover.unlink(missing_ok=True)
        raise
    finally:
        await archive.close()
        if cover: await cover.close()


@router.patch("/tracks/{track_id}")
def update_track(
    track_id: int,
    title: str | None = Form(default=None, max_length=180),
    artist: str | None = Form(default=None, max_length=180),
    musical_key: str | None = Form(default=None, max_length=20),
    bpm: int | None = Form(default=None, ge=1, le=400),
    category: str | None = Form(default=None, max_length=240),
    time_signature: str | None = Form(default=None, max_length=12),
    categories: str | None = Form(default=None),
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
    if time_signature is not None:
        track.time_signature = time_signature.strip()
    if categories is not None:
        try:
            selected = json.loads(categories)
            if not isinstance(selected, list): raise ValueError()
            track.categories_json = json.dumps(selected, ensure_ascii=False)
            track.category = ", ".join(selected)
        except (ValueError, json.JSONDecodeError):
            raise HTTPException(status_code=422, detail="Categorias inválidas.")
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
