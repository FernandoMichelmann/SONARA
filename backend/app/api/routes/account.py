from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, delete
import json
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user
from app.models import Track, User, UserDownload, UserFavorite, UserPlaylist

router = APIRouter(prefix="/account", tags=["Área pessoal"])


def _require_customer(user: User) -> User:
    if user.role != "user":
        raise HTTPException(status_code=403, detail="Recurso disponível apenas para contas de clientes.")
    return user


def _track_payload(track: Track) -> dict:
    return {
        "id": track.id,
        "title": track.title,
        "artist": track.artist,
        "musical_key": track.musical_key,
        "bpm": track.bpm,
        "category": track.category,
        "cover_url": f"/api/v1/tracks/{track.id}/cover" if track.cover_path else None,
    }


@router.get("/favorites")
def list_favorites(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_customer(user)
    rows = db.execute(
        select(UserFavorite, Track)
        .join(Track, Track.id == UserFavorite.track_id)
        .where(UserFavorite.user_id == user.id, Track.is_published.is_(True))
        .order_by(UserFavorite.created_at.desc())
    ).all()
    return {"items": [{**_track_payload(track), "saved_at": favorite.created_at} for favorite, track in rows]}


@router.post("/favorites/{track_id}")
def add_favorite(track_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_customer(user)
    track = db.scalar(select(Track).where(Track.id == track_id, Track.is_published.is_(True)))
    if not track:
        raise HTTPException(status_code=404, detail="Música não encontrada no catálogo.")
    existing = db.scalar(select(UserFavorite).where(
        UserFavorite.user_id == user.id, UserFavorite.track_id == track_id
    ))
    if not existing:
        db.add(UserFavorite(user_id=user.id, track_id=track_id))
        db.commit()
    return {"message": "Adicionada aos favoritos.", "track_id": track_id}


@router.delete("/favorites/{track_id}")
def remove_favorite(track_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_customer(user)
    db.execute(delete(UserFavorite).where(
        UserFavorite.user_id == user.id, UserFavorite.track_id == track_id
    ))
    db.commit()
    return {"message": "Removida dos favoritos.", "track_id": track_id}


@router.get("/downloads")
def list_download_history(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_customer(user)
    rows = db.execute(
        select(UserDownload, Track)
        .join(Track, Track.id == UserDownload.track_id)
        .where(UserDownload.user_id == user.id)
        .order_by(UserDownload.requested_at.desc())
    ).all()
    return {"items": [{**_track_payload(track), "requested_at": item.requested_at} for item, track in rows]}


@router.post("/downloads/{track_id}")
def register_download_request(track_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_customer(user)
    track = db.scalar(select(Track).where(Track.id == track_id, Track.is_published.is_(True)))
    if not track:
        raise HTTPException(status_code=404, detail="Música não encontrada no catálogo.")
    db.add(UserDownload(user_id=user.id, track_id=track_id))
    db.commit()
    return {
        "message": "Solicitação adicionada ao seu histórico de downloads.",
        "track": _track_payload(track),
        "download_available": False,
    }


@router.get("/playlists")
def list_playlists(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_customer(user)
    rows = db.scalars(select(UserPlaylist).where(UserPlaylist.user_id == user.id).order_by(UserPlaylist.created_at.desc())).all()
    return {"items": [{"id": row.id, "name": row.name, "track_ids": json.loads(row.track_ids_json or "[]"), "created_at": row.created_at} for row in rows]}


@router.post("/playlists")
def create_playlist(payload: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_customer(user)
    name = str(payload.get("name", "")).strip()
    if not name or len(name) > 80:
        raise HTTPException(status_code=422, detail="Informe um nome de até 80 caracteres.")
    playlist = UserPlaylist(user_id=user.id, name=name, track_ids_json="[]")
    db.add(playlist)
    db.commit()
    db.refresh(playlist)
    return {"id": playlist.id, "name": playlist.name, "track_ids": []}


@router.post("/playlists/{playlist_id}/tracks/{track_id}")
def add_track_to_playlist(playlist_id: int, track_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_customer(user)
    playlist = db.scalar(select(UserPlaylist).where(UserPlaylist.id == playlist_id, UserPlaylist.user_id == user.id))
    track = db.scalar(select(Track).where(Track.id == track_id, Track.is_published.is_(True)))
    if not playlist or not track:
        raise HTTPException(status_code=404, detail="Playlist ou música não encontrada.")
    ids = json.loads(playlist.track_ids_json or "[]")
    if track_id not in ids:
        ids.append(track_id)
        playlist.track_ids_json = json.dumps(ids)
        db.commit()
    return {"message": "Música adicionada à playlist.", "track_ids": ids}


@router.delete("/playlists/{playlist_id}")
def delete_playlist(playlist_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_customer(user)
    playlist = db.scalar(select(UserPlaylist).where(UserPlaylist.id == playlist_id, UserPlaylist.user_id == user.id))
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist não encontrada.")
    db.delete(playlist)
    db.commit()
    return {"message": "Playlist removida."}
