from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
import json
import zipfile
import shutil
import mimetypes
import subprocess
import imageio_ffmpeg

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_developer
from app.models import HomepageFeatureSelection, PasswordResetToken, PaymentOrder, RevenueEntry, Track, TrackCategory, User

router = APIRouter(prefix="/developer", tags=["Administração do desenvolvedor"])
AUDIO_DIR = Path(__file__).resolve().parents[3] / "uploads" / "tracks"
COVER_DIR = Path(__file__).resolve().parents[3] / "uploads" / "covers"
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024
MAX_EXTRACTED_BYTES = 2 * 1024 * 1024 * 1024
MAX_STEM_FILES = 100
ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac"}
MAX_AUDIO_BYTES = 500 * 1024 * 1024

def is_macos_metadata_file(path: Path) -> bool:
    """Identifica arquivos auxiliares do macOS (AppleDouble), não são áudio."""
    if "__MACOSX" in path.parts or "._" in path.name:
        return True
    try:
        with path.open("rb") as source:
            return source.read(4) in (bytes.fromhex("00051607"), bytes.fromhex("00051600"))
    except OSError:
        return False



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
        "preview_start_seconds": getattr(track, "preview_start_seconds", 0),
        "preview_end_seconds": getattr(track, "preview_end_seconds", 30),
        "preview_duration_seconds": max(0, getattr(track, "preview_end_seconds", 30) - getattr(track, "preview_start_seconds", 0)),
        "preview_ready": bool(track.stems_path and (Path(track.stems_path).parent / "previews").is_dir() and any((Path(track.stems_path).parent / "previews").glob("*.mp3"))),
    }


class HomepageFeatureUpdate(BaseModel):
    launches: list[int] = Field(default_factory=list, max_length=12)
    most_downloaded: list[int] = Field(default_factory=list, max_length=14)


def _homepage_selection_payload(db: Session):
    selection = db.get(HomepageFeatureSelection, 1)
    if not selection:
        return {"launches": [], "most_downloaded": [], "configured": False}
    try:
        launches = json.loads(selection.launches_json or "[]")
        most_downloaded = json.loads(selection.most_downloaded_json or "[]")
    except (TypeError, json.JSONDecodeError):
        launches, most_downloaded = [], []
    return {"launches": launches, "most_downloaded": most_downloaded, "configured": True}


@router.get("/homepage-features")
def get_homepage_features(
    _developer: User = Depends(get_current_developer),
    db: Session = Depends(get_db),
):
    return _homepage_selection_payload(db)


@router.put("/homepage-features")
def update_homepage_features(
    payload: HomepageFeatureUpdate,
    _developer: User = Depends(get_current_developer),
    db: Session = Depends(get_db),
):
    launches = list(dict.fromkeys(payload.launches))
    most_downloaded = list(dict.fromkeys(payload.most_downloaded))
    requested_ids = set(launches + most_downloaded)
    if any(track_id <= 0 for track_id in requested_ids):
        raise HTTPException(status_code=422, detail="Seleção de tracks inválida.")
    valid_ids = set(db.scalars(select(Track.id).where(Track.id.in_(requested_ids), Track.is_published.is_(True))).all()) if requested_ids else set()
    if valid_ids != requested_ids:
        raise HTTPException(status_code=422, detail="Todas as tracks selecionadas precisam estar publicadas no catálogo.")
    selection = db.get(HomepageFeatureSelection, 1)
    if not selection:
        selection = HomepageFeatureSelection(id=1)
        db.add(selection)
    selection.launches_json = json.dumps(launches)
    selection.most_downloaded_json = json.dumps(most_downloaded)
    db.commit()
    return {"launches": launches, "most_downloaded": most_downloaded, "saved": True}


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


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    _developer: User = Depends(get_current_developer),
    db: Session = Depends(get_db),
):
    user = db.scalar(select(User).where(User.id == user_id, User.role == "user"))
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    # Preserve o histórico financeiro da plataforma, removendo apenas o vínculo
    # com a conta excluída. Não há outras tabelas pessoais relacionadas ao usuário.
    db.query(RevenueEntry).filter(RevenueEntry.created_by == user_id).update(
        {RevenueEntry.created_by: None},
        synchronize_session=False,
    )
    db.query(PasswordResetToken).filter(PasswordResetToken.user_id == user_id).delete(
        synchronize_session=False,
    )
    db.delete(user)
    db.commit()
    return {"id": user_id, "deleted": True, "message": "Usuário e dados da conta excluídos com sucesso."}


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
                # ZIPs do macOS podem conter arquivos AppleDouble, que não são áudio.
                if "__MACOSX" in parts or Path(raw_name).name.startswith("._"):
                    continue
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
        stem_files = sorted(
            path for path in stems_dir.iterdir()
            if path.is_file() and not is_macos_metadata_file(path)
            and path.suffix.lower() in ALLOWED_AUDIO_EXTENSIONS
        )
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
            category=selected[0] if selected else "Multitrack",
            categories_json=json.dumps(selected, ensure_ascii=False),
            original_filename=archive_name, storage_path=str(main_stem),
            stems_path=str(stems_dir),
            content_type=mimetypes.guess_type(main_stem.name)[0] or "application/octet-stream",
            file_size=archive_size, cover_path=str(saved_cover) if saved_cover else None,
            cover_content_type=mimetypes.guess_type(saved_cover.name)[0] if saved_cover else None,
            is_published=False,
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




@router.delete("/tracks/{track_id}")
def delete_track(
    track_id: int,
    _developer: User = Depends(get_current_developer),
    db: Session = Depends(get_db),
):
    track = db.get(Track, track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Track não encontrada.")

    # Remova somente a pasta exclusiva desta track dentro de uploads/tracks.
    track_dir = Path(track.stems_path).resolve().parent if track.stems_path else None
    uploads_root = AUDIO_DIR.resolve()
    if track_dir is None or track_dir.parent != uploads_root:
        raise HTTPException(status_code=409, detail="Não foi possível validar a pasta desta track com segurança.")

    cover_path = Path(track.cover_path).resolve() if track.cover_path else None
    db.delete(track)
    db.commit()

    shutil.rmtree(track_dir, ignore_errors=True)
    if cover_path and cover_path.parent == COVER_DIR.resolve():
        cover_path.unlink(missing_ok=True)

    return {"id": track_id, "deleted": True, "message": "Track excluída com sucesso."}


@router.get("/tracks/{track_id}/preview-source")
def get_track_preview_source(
    track_id: int,
    _developer: User = Depends(get_current_developer),
    db: Session = Depends(get_db),
):
    track = db.get(Track, track_id)
    if not track or not track.stems_path:
        raise HTTPException(status_code=404, detail="Multitrack não encontrada.")

    stems_dir = Path(track.stems_path).resolve()
    uploads_root = AUDIO_DIR.resolve()
    if stems_dir.parent.parent != uploads_root or not stems_dir.is_dir():
        raise HTTPException(status_code=404, detail="Pasta de stems indisponível.")

    source_stems = sorted(
        path for path in stems_dir.iterdir()
        if path.is_file() and path.suffix.lower() in ALLOWED_AUDIO_EXTENSIONS
        and not is_macos_metadata_file(path)
    )
    if not source_stems:
        raise HTTPException(status_code=404, detail="Nenhuma faixa de áudio foi encontrada.")

    # Cria uma mixagem temporária de TODOS os stems, preservando o início comum
    # para que o desenvolvedor escolha o trecho ouvindo a música completa.
    reference_mix = stems_dir.parent / (".preview-reference-" + uuid4().hex + ".mp3")
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    for source in source_stems:
        command.extend(["-i", str(source)])

    inputs = "".join(f"[{index}:a:0]" for index in range(len(source_stems)))
    filter_graph = (
        f"{inputs}amix=inputs={len(source_stems)}:duration=longest:"
        "dropout_transition=0:normalize=1[mix]"
    )
    command.extend([
        "-filter_complex", filter_graph, "-map", "[mix]",
        "-codec:a", "libmp3lame", "-q:a", "3", "-ar", "44100",
        str(reference_mix),
    ])

    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=300)
        if result.returncode != 0 or not reference_mix.is_file() or reference_mix.stat().st_size == 0:
            raise RuntimeError((result.stderr or "Falha ao mixar os stems.")[-1000:])
    except subprocess.TimeoutExpired:
        reference_mix.unlink(missing_ok=True)
        raise HTTPException(status_code=504, detail="A mixagem dos stems excedeu o tempo limite.")
    except Exception as error:
        reference_mix.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"Não foi possível mixar todos os instrumentos: {error}")

    return FileResponse(
        reference_mix,
        media_type="audio/mpeg",
        filename="preview-reference.mp3",
        background=BackgroundTask(reference_mix.unlink, missing_ok=True),
    )


@router.post("/tracks/{track_id}/preview")
def create_track_preview(
    track_id: int,
    start_seconds: int = Form(0, ge=0, le=86400),
    end_seconds: int = Form(..., ge=1, le=86430),
    publish_after: bool = Form(False),
    _developer: User = Depends(get_current_developer),
    db: Session = Depends(get_db),
):
    track = db.get(Track, track_id)
    if not track or not track.stems_path:
        raise HTTPException(status_code=404, detail="Multitrack não encontrada.")
    duration_seconds = end_seconds - start_seconds
    if duration_seconds < 1 or duration_seconds > 30:
        raise HTTPException(status_code=422, detail="A prévia deve ter entre 1 e 30 segundos. Confira o início e o fim.")
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    stems_dir = Path(track.stems_path).resolve()
    preview_dir = stems_dir.parent / "previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    source_stems = sorted(
        path for path in stems_dir.iterdir()
        if path.is_file() and path.suffix.lower() in ALLOWED_AUDIO_EXTENSIONS
        and not is_macos_metadata_file(path)
    )
    if not source_stems:
        raise HTTPException(status_code=404, detail="Nenhum instrumento foi encontrado.")
    generated = []
    try:
        for source in source_stems:
            output = preview_dir / (source.stem + ".mp3")
            command = [
                ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-ss", str(start_seconds), "-i", str(source),
                "-t", str(duration_seconds), "-vn", "-codec:a", "libmp3lame",
                "-b:a", "160k", "-ar", "44100", "-ac", "2",
                "-metadata", "title=" + track.title, str(output),
            ]
            result = subprocess.run(command, capture_output=True, text=True, timeout=180)
            if result.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
                raise RuntimeError(f"Falha ao gerar prévia de {source.name}: {(result.stderr or '')[-500:]}")
            generated.append(output)
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="O processamento das prévias excedeu o tempo limite.")
    except Exception as error:
        for output in generated:
            output.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"Não foi possível gerar as prévias. Verifique o áudio selecionado e tente novamente. {error}")

    # Invalida a mixagem pública anterior para que ela nunca continue servindo o recorte antigo.
    (preview_dir / "mix.mp3").unlink(missing_ok=True)
    track.preview_start_seconds = start_seconds
    track.preview_end_seconds = end_seconds
    track.is_published = bool(publish_after)
    db.commit()
    db.refresh(track)
    return {
        "id": track.id, "preview_start_seconds": start_seconds,
        "preview_end_seconds": end_seconds, "duration_seconds": duration_seconds,
        "published": track.is_published, "preview_count": len(generated)
    }


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
            track.category = selected[0] if selected else "Multitrack"
        except (ValueError, json.JSONDecodeError):
            raise HTTPException(status_code=422, detail="Categorias inválidas.")
    if is_published is not None:
        if is_published:
            preview_dir = Path(track.stems_path).parent / "previews" if track.stems_path else None
            previews = list(preview_dir.glob("*.mp3")) if preview_dir and preview_dir.is_dir() else []
            if not previews:
                raise HTTPException(status_code=409, detail="Antes de publicar, configure e gere a prévia de 30 segundos desta multitrack.")
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
    # Soma os lançamentos manuais recebidos com os pedidos efetivamente
    # confirmados pela InfinitePay. Valores dos pedidos são armazenados em centavos.
    manual_received = db.scalar(
        select(func.coalesce(func.sum(RevenueEntry.amount), 0))
        .where(RevenueEntry.status == "received")
    ) or Decimal("0.00")
    payment_received_cents = db.scalar(
        select(func.coalesce(func.sum(
            func.coalesce(PaymentOrder.paid_amount_cents, PaymentOrder.amount_cents)
        ), 0))
        .where(PaymentOrder.status == "paid")
    ) or 0
    pending = db.scalar(
        select(func.coalesce(func.sum(RevenueEntry.amount), 0))
        .where(RevenueEntry.status == "pending")
    ) or Decimal("0.00")
    manual_count = db.scalar(select(func.count(RevenueEntry.id))) or 0
    paid_orders_count = db.scalar(
        select(func.count(PaymentOrder.id)).where(PaymentOrder.status == "paid")
    ) or 0
    received = Decimal(str(manual_received)) + (Decimal(payment_received_cents) / Decimal("100"))
    return {
        "received_total": str(received.quantize(Decimal("0.01"))),
        "pending_total": str(pending),
        "entries_count": manual_count + paid_orders_count,
        "paid_orders_count": paid_orders_count,
        "payment_received_total": str((Decimal(payment_received_cents) / Decimal("100")).quantize(Decimal("0.01"))),
        "currency": "BRL",
    }
