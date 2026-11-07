import base64, hashlib, json, logging, mimetypes, re, shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import jwt
from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.config import settings
from app.db import get_db
from app.dependencies import get_current_developer
from app.models import DriveConnection, Track, User

router = APIRouter(prefix="/developer/drive", tags=["Importação Google Drive"])
logger = logging.getLogger("sonara.drive")
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".aac"}
MAX_FILE_BYTES = 500 * 1024 * 1024
MAX_TRACK_BYTES = 2 * 1024 * 1024 * 1024
MAX_TRACK_FILES = 100
AUDIO_DIR = Path(__file__).resolve().parents[3] / "uploads" / "tracks"

def _fernet():
    digest = hashlib.sha256((settings.jwt_secret_key or "").encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))

def _configured():
    return bool(settings.google_drive_client_id and settings.google_drive_client_secret and settings.google_drive_redirect_uri)

def _client_config():
    if not _configured():
        raise HTTPException(status_code=503, detail="Configure GOOGLE_DRIVE_CLIENT_ID, GOOGLE_DRIVE_CLIENT_SECRET e GOOGLE_DRIVE_REDIRECT_URI no backend/.env.")
    return {"web": {"client_id": settings.google_drive_client_id, "client_secret": settings.google_drive_client_secret,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": [settings.google_drive_redirect_uri]}}

def _credentials(db: Session):
    connection = db.get(DriveConnection, 1)
    if not connection:
        raise HTTPException(status_code=409, detail="Conecte o Google Drive antes de importar.")
    try:
        raw = _fernet().decrypt(connection.credentials_encrypted.encode()).decode()
        credentials = Credentials.from_authorized_user_info(json.loads(raw), SCOPES)
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(GoogleRequest())
            connection.credentials_encrypted = _fernet().encrypt(credentials.to_json().encode()).decode()
            connection.updated_at = datetime.now(timezone.utc)
            db.commit()
        if not credentials.valid:
            raise ValueError("Credencial expirada.")
        return credentials
    except Exception as error:
        logger.exception("Falha ao recuperar a conexão Google Drive")
        raise HTTPException(status_code=401, detail="A conexão com o Google Drive expirou. Conecte novamente.") from error

def _service(db: Session):
    return build("drive", "v3", credentials=_credentials(db), cache_discovery=False)

def _children(service, parent_id):
    files, token = [], None
    while True:
        result = service.files().list(q=f"'{parent_id}' in parents and trashed = false", pageSize=1000,
            pageToken=token, orderBy="folder,name", fields="nextPageToken,files(id,name,mimeType,size)").execute()
        files.extend(result.get("files", []))
        token = result.get("nextPageToken")
        if not token: return files

@router.get("/status")
def drive_status(_developer: User = Depends(get_current_developer), db: Session = Depends(get_db)):
    connection = db.get(DriveConnection, 1)
    return {"configured": _configured(), "connected": bool(connection), "email": connection.connected_email if connection else None}

@router.get("/connect")
def drive_connect(developer: User = Depends(get_current_developer)):
    state = jwt.encode({"developer_id": developer.id, "purpose": "sonara-drive-oauth", "iat": datetime.now(timezone.utc)},
        settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES, state=state)
    flow.redirect_uri = settings.google_drive_redirect_uri
    url, _ = flow.authorization_url(access_type="offline", include_granted_scopes="true", prompt="consent")
    return {"authorization_url": url}

@router.get("/callback")
def drive_callback(code: str, state: str, db: Session = Depends(get_db)):
    try:
        claims = jwt.decode(state, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        if claims.get("purpose") != "sonara-drive-oauth": raise ValueError("Estado OAuth inválido.")
        owner = db.get(User, int(claims["developer_id"]))
        if not owner or owner.role != "developer" or not owner.is_active: raise ValueError("Acesso administrativo inválido.")
        flow = Flow.from_client_config(_client_config(), scopes=SCOPES, state=state)
        flow.redirect_uri = settings.google_drive_redirect_uri
        flow.fetch_token(code=code)
        credentials = flow.credentials
        if not credentials.refresh_token: raise ValueError("O Google não retornou refresh token.")
        service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        profile = service.about().get(fields="user(emailAddress)").execute()
        connection = db.get(DriveConnection, 1)
        encrypted = _fernet().encrypt(credentials.to_json().encode()).decode()
        if connection:
            connection.credentials_encrypted = encrypted
            connection.connected_email = profile.get("user", {}).get("emailAddress")
            connection.updated_at = datetime.now(timezone.utc)
        else:
            db.add(DriveConnection(id=1, credentials_encrypted=encrypted, connected_email=profile.get("user", {}).get("emailAddress")))
        db.commit()
        return RedirectResponse(settings.frontend_base_url.rstrip("/") + "/developer.html?drive=connected", status_code=303)
    except Exception:
        db.rollback()
        logger.exception("Falha no callback OAuth Google Drive")
        return RedirectResponse(settings.frontend_base_url.rstrip("/") + "/developer.html?drive=error", status_code=303)

@router.delete("/connection")
def disconnect_drive(_developer: User = Depends(get_current_developer), db: Session = Depends(get_db)):
    connection = db.get(DriveConnection, 1)
    if connection: db.delete(connection); db.commit()
    return {"connected": False}

@router.get("/folders")
def drive_folders(parent_id: str = Query(min_length=5, max_length=200),
    _developer: User = Depends(get_current_developer), db: Session = Depends(get_db)):
    service = _service(db)
    parent = service.files().get(fileId=parent_id, fields="id,name,mimeType").execute()
    if parent.get("mimeType") != "application/vnd.google-apps.folder":
        raise HTTPException(status_code=422, detail="O link informado não é uma pasta do Google Drive.")
    folders = [x for x in _children(service, parent_id) if x.get("mimeType") == "application/vnd.google-apps.folder"]
    result = []
    for folder in folders:
        audio = [x for x in _children(service, folder["id"]) if x.get("mimeType") != "application/vnd.google-apps.folder"
            and Path(x.get("name", "")).suffix.lower() in AUDIO_EXTENSIONS and not x.get("name", "").startswith("._")]
        result.append({"id": folder["id"], "name": folder["name"], "audio_count": len(audio),
            "total_bytes": sum(int(x.get("size") or 0) for x in audio),
            "already_imported": bool(db.scalar(select(Track.id).where(Track.source_drive_folder_id == folder["id"])))})
    return {"parent": parent["name"], "folders": result, "total": len(result)}

class DriveImportRequest(BaseModel):
    folder_ids: list[str] = Field(min_length=1, max_length=100)

@router.post("/import")
def import_drive_folders(payload: DriveImportRequest, _developer: User = Depends(get_current_developer), db: Session = Depends(get_db)):
    service = _service(db)
    imported, skipped, errors = [], [], []
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    for folder_id in dict.fromkeys(payload.folder_ids):
        existing = db.scalar(select(Track).where(Track.source_drive_folder_id == folder_id))
        if existing:
            skipped.append({"folder_id": folder_id, "title": existing.title, "reason": "Já importada"}); continue
        track_dir = AUDIO_DIR / uuid4().hex
        stems_dir = track_dir / "stems"
        try:
            folder = service.files().get(fileId=folder_id, fields="id,name,mimeType").execute()
            if folder.get("mimeType") != "application/vnd.google-apps.folder": raise ValueError("O item selecionado não é uma pasta.")
            audio = [x for x in _children(service, folder_id) if x.get("mimeType") != "application/vnd.google-apps.folder"
                and Path(x.get("name", "")).suffix.lower() in AUDIO_EXTENSIONS and not x.get("name", "").startswith("._")]
            if not audio: raise ValueError("Nenhum arquivo de áudio compatível encontrado.")
            if len(audio) > MAX_TRACK_FILES or sum(int(x.get("size") or 0) for x in audio) > MAX_TRACK_BYTES:
                raise ValueError("A pasta excede o limite de 100 arquivos ou 2 GB.")
            stems_dir.mkdir(parents=True, exist_ok=False)
            downloaded, total = [], 0
            for index, item in enumerate(audio, 1):
                if int(item.get("size") or 0) > MAX_FILE_BYTES: raise ValueError("Um arquivo excede 500 MB.")
                name = re.sub(r"[^\w.() -]", "_", Path(item["name"]).name).strip() or f"stem-{index}"
                destination = stems_dir / f"{index:02d}_{name}"
                request = service.files().get_media(fileId=item["id"])
                with destination.open("wb") as target:
                    downloader = MediaIoBaseDownload(target, request, chunksize=8 * 1024 * 1024)
                    done = False
                    while not done:
                        _, done = downloader.next_chunk()
                        if destination.stat().st_size > MAX_FILE_BYTES: raise ValueError("Um arquivo excedeu 500 MB durante o download.")
                total += destination.stat().st_size
                if total > MAX_TRACK_BYTES: raise ValueError("A pasta excede 2 GB após o download.")
                downloaded.append(destination)
            main_stem = next((p for p in downloaded if any(w in p.stem.lower() for w in ("mix", "full", "stereo", "master"))), downloaded[0])
            track = Track(title=folder["name"][:180], artist="", musical_key="", bpm=None, time_signature="4/4",
                category="Multitrack", categories_json=json.dumps(["Multitrack"], ensure_ascii=False),
                original_filename=(folder["name"] + " (Google Drive)")[:255], storage_path=str(main_stem),
                stems_path=str(stems_dir), content_type=mimetypes.guess_type(main_stem.name)[0] or "application/octet-stream",
                file_size=total, source_drive_folder_id=folder_id, is_published=False)
            db.add(track); db.commit(); db.refresh(track)
            imported.append({"id": track.id, "title": track.title, "stems": len(downloaded)})
        except Exception as error:
            db.rollback(); shutil.rmtree(track_dir, ignore_errors=True)
            logger.exception("Falha ao importar pasta do Drive %s", folder_id)
            errors.append({"folder_id": folder_id, "message": str(error)[:300]})
    return {"imported": imported, "skipped": skipped, "errors": errors}
