from pathlib import Path
import json
import mimetypes
import subprocess
import imageio_ffmpeg
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
    # A publicação é controlada por Track.is_published.
    # Não esconda a track inteira por ausência/erro nos arquivos de prévia:
    # isso fazia a música sumir silenciosamente do site público.
    return {"items": [{
        "id": track.id, "title": track.title, "artist": track.artist,
        "musical_key": track.musical_key, "bpm": track.bpm,
        "time_signature": getattr(track, "time_signature", "4/4"),
        "category": track.category,
        "categories": json.loads(track.categories_json or "[]") if getattr(track, "categories_json", None) else ([track.category] if track.category else []),
        "file_size": track.file_size, "preview_start_seconds": track.preview_start_seconds, "preview_duration_seconds": 30, "audio_url": f"/api/v1/tracks/{track.id}/audio", "mix_url": f"/api/v1/tracks/{track.id}/mix",
        "zip_download_url": f"/api/v1/tracks/{track.id}/download",
        "cover_url": f"/api/v1/tracks/{track.id}/cover" if track.cover_path else None,
        "stems": [{"name": p.stem.removesuffix(".mp3"), "url": f"/api/v1/tracks/{track.id}/clips/{p.name}"} for p in sorted((Path(track.stems_path).parent / "previews").glob("*.mp3"))] if track.stems_path and (Path(track.stems_path).parent / "previews").is_dir() else [],
    } for track in tracks]}



@router.get("/tracks/{track_id}/clips/{clip_name}")
def stream_track_clip(track_id: int, clip_name: str, db: Session = Depends(get_db)):
    track = db.get(Track, track_id)
    if not track or not track.is_published or not track.stems_path:
        raise HTTPException(status_code=404, detail="Trecho não encontrado.")
    folder = Path(track.stems_path).parent / "previews"
    clip = folder / clip_name
    if clip.parent.resolve() != folder.resolve() or not clip.is_file() or clip.suffix.lower() != ".mp3":
        raise HTTPException(status_code=404, detail="Trecho indisponível.")
    return FileResponse(clip, media_type="audio/mpeg", content_disposition_type="inline")


@router.get("/tracks/{track_id}/mix")
def stream_track_mix(track_id: int, db: Session = Depends(get_db)):
    """Serve uma única mixagem pronta, evitando dezenas de streams simultâneos."""
    track = db.get(Track, track_id)
    if not track or not track.is_published or not track.stems_path:
        raise HTTPException(status_code=404, detail="Mixagem não encontrada.")
    preview_dir = (Path(track.stems_path).resolve().parent / "previews").resolve()
    if not preview_dir.is_dir():
        raise HTTPException(status_code=404, detail="Prévia indisponível.")
    mix_path = preview_dir / "mix.mp3"
    if not mix_path.is_file() or mix_path.stat().st_size == 0:
        sources = sorted(p for p in preview_dir.glob("*.mp3") if p.is_file() and p.name != "mix.mp3")
        if not sources:
            raise HTTPException(status_code=404, detail="Nenhuma prévia de instrumento disponível.")
        temp_path = preview_dir / "mix-generating.mp3"
        command = [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y"]
        for source in sources:
            command.extend(["-i", str(source)])
        labels = "".join(f"[{i}:a:0]" for i in range(len(sources)))
        graph = f"{labels}amix=inputs={len(sources)}:duration=longest:dropout_transition=0:normalize=1[mix]"
        command.extend(["-filter_complex", graph, "-map", "[mix]", "-codec:a", "libmp3lame", "-b:a", "192k", "-ar", "44100", "-ac", "2", str(temp_path)])
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=240)
            if result.returncode != 0 or not temp_path.is_file() or temp_path.stat().st_size == 0:
                raise RuntimeError((result.stderr or "Falha ao gerar mixagem.")[-1200:])
            temp_path.replace(mix_path)
        except subprocess.TimeoutExpired:
            temp_path.unlink(missing_ok=True)
            raise HTTPException(status_code=504, detail="A mixagem excedeu o tempo limite.")
        except Exception as error:
            temp_path.unlink(missing_ok=True)
            raise HTTPException(status_code=422, detail=f"Não foi possível preparar o áudio: {error}")
    return FileResponse(mix_path, media_type="audio/mpeg", content_disposition_type="inline")


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
    preview_dir = (Path(track.stems_path).resolve().parent / "previews").resolve()
    preview_name = Path(stem_name).stem + ".mp3"
    path = (preview_dir / preview_name).resolve()
    if path.parent != preview_dir or not path.is_file():
        raise HTTPException(status_code=404, detail="Prévia de 30 segundos não encontrada.")
    return FileResponse(path, media_type="audio/mpeg", content_disposition_type="inline")


@router.get("/tracks/{track_id}/audio")
def stream_published_track(track_id: int, db: Session = Depends(get_db)):
    track = db.get(Track, track_id)
    if not track or not track.is_published:
        raise HTTPException(status_code=404, detail="Áudio não encontrado.")
    preview_dir = (Path(track.stems_path).resolve().parent / "previews").resolve() if track.stems_path else None
    if not preview_dir or not preview_dir.is_dir():
        raise HTTPException(status_code=404, detail="Prévia de 30 segundos indisponível.")
    path = (preview_dir / (Path(track.storage_path).stem + ".mp3")).resolve()
    if path.parent != preview_dir or not path.is_file():
        previews = sorted(preview_dir.glob("*.mp3"))
        if not previews:
            raise HTTPException(status_code=404, detail="Prévia de 30 segundos indisponível.")
        path = previews[0]
    return FileResponse(path, media_type="audio/mpeg", content_disposition_type="inline")
