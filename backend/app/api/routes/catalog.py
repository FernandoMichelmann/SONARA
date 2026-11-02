from pathlib import Path
import json
import mimetypes
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Track

router = APIRouter(tags=["Catálogo de áudio"])


@router.get("/catalog/tracks")
def public_track_catalog(db: Session = Depends(get_db)):
    tracks = db.scalars(
        select(Track).where(Track.is_published.is_(True)).order_by(Track.created_at.desc())
    ).all()
    return {"items": [{
        "id": track.id, "title": track.title, "artist": track.artist,
        "musical_key": track.musical_key, "bpm": track.bpm,
        "time_signature": getattr(track, "time_signature", "4/4"),
        "category": track.category,
        "categories": json.loads(track.categories_json or "[]") if getattr(track, "categories_json", None) else ([track.category] if track.category else []),
        "file_size": track.file_size, "preview_start_seconds": track.preview_start_seconds, "preview_duration_seconds": 30, "audio_url": f"/api/v1/tracks/{track.id}/audio",
        "zip_download_url": f"/api/v1/tracks/{track.id}/download",
        "cover_url": f"/api/v1/tracks/{track.id}/cover" if track.cover_path else None,
        "stems": [{"name": p.name, "url": f"/api/v1/tracks/{track.id}/stems/{p.name}"} for p in sorted(Path(track.stems_path).iterdir()) if p.is_file()] if track.stems_path and Path(track.stems_path).is_dir() else [],
    } for track in tracks]}


@router.get("/tracks/{track_id}/download")
def download_track_multitrack(track_id: int, db: Session = Depends(get_db)):
    track = db.get(Track, track_id)
    if not track or not track.is_published or not track.stems_path:
        raise HTTPException(status_code=404, detail="Multitrack não encontrado.")
    stems_dir = Path(track.stems_path).resolve()
    archive_path = (stems_dir.parent / "source.zip").resolve()
    if archive_path.parent != stems_dir.parent or not archive_path.is_file():
        raise HTTPException(status_code=404, detail="Pacote ZIP original indisponível.")
    safe_title = "".join(char if char.isalnum() or char in "-_ " else "" for char in track.title).strip() or f"SONARA-{track.id}"
    return FileResponse(
        archive_path,
        media_type="application/zip",
        filename=f"{safe_title}-Multitrack.zip",
        content_disposition_type="attachment",
    )


@router.get("/tracks/{track_id}/cover")
def stream_track_cover(track_id: int, db: Session = Depends(get_db)):
    track = db.get(Track, track_id)
    if not track or not track.is_published or not track.cover_path:
        raise HTTPException(status_code=404, detail="Capa não encontrada.")
    path = Path(track.cover_path).resolve()
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Capa indisponível.")
    return FileResponse(path, media_type=track.cover_content_type or "image/jpeg")


@router.get("/tracks/{track_id}/stems/{stem_name}")
def stream_track_stem(track_id: int, stem_name: str, db: Session = Depends(get_db)):
    track = db.get(Track, track_id)
    if not track or not track.is_published or not track.stems_path:
        raise HTTPException(status_code=404, detail="Stem não encontrado.")
    base = Path(track.stems_path).resolve()
    path = (base / Path(stem_name).name).resolve()
    if path.parent != base or not path.is_file():
        raise HTTPException(status_code=404, detail="Stem não encontrado.")
    return FileResponse(path, media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream", filename=path.name, content_disposition_type="inline")


@router.get("/tracks/{track_id}/audio")
def stream_published_track(track_id: int, db: Session = Depends(get_db)):
    track = db.get(Track, track_id)
    if not track or not track.is_published:
        raise HTTPException(status_code=404, detail="Áudio não encontrado.")
    path = Path(track.storage_path).resolve()
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Arquivo de áudio indisponível no servidor.")
    return FileResponse(path, media_type=track.content_type, filename=path.name, content_disposition_type="inline")
