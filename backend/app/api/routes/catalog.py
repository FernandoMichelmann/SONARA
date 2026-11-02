from pathlib import Path
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
        "musical_key": track.musical_key, "bpm": track.bpm, "category": track.category,
        "file_size": track.file_size, "audio_url": f"/api/v1/tracks/{track.id}/audio",
    } for track in tracks]}


@router.get("/tracks/{track_id}/audio")
def stream_published_track(track_id: int, db: Session = Depends(get_db)):
    track = db.get(Track, track_id)
    if not track or not track.is_published:
        raise HTTPException(status_code=404, detail="Áudio não encontrado.")
    path = Path(track.storage_path).resolve()
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Arquivo de áudio indisponível no servidor.")
    return FileResponse(path, media_type=track.content_type, filename=track.original_filename)
