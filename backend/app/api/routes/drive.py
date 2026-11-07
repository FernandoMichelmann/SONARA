import base64, hashlib, json, logging, mimetypes, re, shutil, zipfile
from datetime import datetime, timedelta, timezone
import secrets
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
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from app.core.config import settings
from app.db import get_db
from app.dependencies import get_current_developer
from app.models import DriveConnection, DriveOAuthState, Track, User

router = APIRouter(prefix="/developer/drive", tags=["Importação Google Drive"])
logger = logging.getLogger("sonara.drive")
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".aac"}
MAX_FILE_BYTES = 500 * 1024 * 1024
MAX_TRACK_BYTES = 2 * 1024 * 1024 * 1024
MAX_TRACK_FILES = 100
MAX_FOLDER_SCAN_DEPTH = 5
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
            pageToken=token, orderBy="folder,name",
            supportsAllDrives=True, includeItemsFromAllDrives=True,
            fields="nextPageToken,files(id,name,mimeType,size,shortcutDetails)").execute()
        files.extend(result.get("files", []))
        token = result.get("nextPageToken")
        if not token: return files


def _audio_files_recursive(service, folder_id: str, depth: int = 0):
    """Find supported audio files inside a song folder, including nested stem folders."""
    found = []
    for item in _children(service, folder_id):
        mime_type = item.get("mimeType", "")
        name = item.get("name", "")
        if mime_type == "application/vnd.google-apps.folder":
            if depth < MAX_FOLDER_SCAN_DEPTH:
                found.extend(_audio_files_recursive(service, item["id"], depth + 1))
            continue
        if mime_type == "application/vnd.google-apps.shortcut":
            continue
        if Path(name).suffix.lower() in AUDIO_EXTENSIONS and not name.startswith("._"):
            found.append(item)
    return sorted(found, key=lambda item: item.get("name", "").casefold())


@router.get("/status")
def drive_status(_developer: User = Depends(get_current_developer), db: Session = Depends(get_db)):
    connection = db.get(DriveConnection, 1)
    return {"configured": _configured(), "connected": bool(connection), "email": connection.connected_email if connection else None}

@router.get("/connect")
def drive_connect(developer: User = Depends(get_current_developer), db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    state_id = secrets.token_urlsafe(24)
    state = jwt.encode({"developer_id": developer.id, "purpose": "sonara-drive-oauth", "jti": state_id,
        "iat": now, "exp": now + timedelta(minutes=10)}, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES, state=state)
    flow.redirect_uri = settings.google_drive_redirect_uri
    url, _ = flow.authorization_url(access_type="offline", include_granted_scopes="true", prompt="consent")
    if not flow.code_verifier:
        raise HTTPException(status_code=500, detail="Não foi possível iniciar a verificação segura do Google.")
    db.execute(delete(DriveOAuthState).where(DriveOAuthState.developer_id == developer.id))
    db.add(DriveOAuthState(state_id=state_id, developer_id=developer.id,
        code_verifier_encrypted=_fernet().encrypt(flow.code_verifier.encode()).decode(),
        expires_at=now + timedelta(minutes=10)))
    db.commit()
    return {"authorization_url": url}

@router.get("/callback")
def drive_callback(code: str, state: str, db: Session = Depends(get_db)):
    try:
        claims = jwt.decode(state, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        if claims.get("purpose") != "sonara-drive-oauth": raise ValueError("Estado OAuth inválido.")
        owner = db.get(User, int(claims["developer_id"]))
        if not owner or owner.role != "developer" or not owner.is_active: raise ValueError("Acesso administrativo inválido.")
        oauth_state = db.get(DriveOAuthState, claims.get("jti"))
        if not oauth_state or oauth_state.developer_id != owner.id:
            raise ValueError("Estado OAuth expirado ou já utilizado. Inicie a conexão novamente.")
        if oauth_state.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
            db.delete(oauth_state)
            db.commit()
            raise ValueError("Estado OAuth expirado. Inicie a conexão novamente.")
        code_verifier = _fernet().decrypt(oauth_state.code_verifier_encrypted.encode()).decode()
        flow = Flow.from_client_config(_client_config(), scopes=SCOPES, state=state,
            code_verifier=code_verifier, autogenerate_code_verifier=False)
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
        db.delete(oauth_state)
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
    parent = service.files().get(fileId=parent_id, fields="id,name,mimeType", supportsAllDrives=True).execute()
    if parent.get("mimeType") != "application/vnd.google-apps.folder":
        raise HTTPException(status_code=422, detail="O link informado não é uma pasta do Google Drive.")
    items = []
    for item in _children(service, parent_id):
        name = item.get("name", "")
        if item.get("mimeType") == "application/vnd.google-apps.folder":
            audio = _audio_files_recursive(service, item["id"])
            items.append({"id": item["id"], "name": name, "item_type": "folder",
                "audio_count": len(audio), "total_bytes": sum(int(x.get("size") or 0) for x in audio),
                "already_imported": bool(db.scalar(select(Track.id).where(Track.source_drive_folder_id == item["id"])))})
        elif Path(name).suffix.lower() == ".zip" or item.get("mimeType") == "application/zip":
            items.append({"id": item["id"], "name": name, "item_type": "zip",
                "audio_count": None, "total_bytes": int(item.get("size") or 0),
                "already_imported": bool(db.scalar(select(Track.id).where(Track.source_drive_folder_id == item["id"])))})
    # Também permite importar áudios colocados diretamente na pasta principal.
    root_audio = _audio_files_recursive(service, parent_id, depth=MAX_FOLDER_SCAN_DEPTH)
    if root_audio:
        items.insert(0, {"id": parent_id, "name": parent["name"] + " (áudios na pasta principal)",
            "item_type": "folder", "audio_count": len(root_audio),
            "total_bytes": sum(int(x.get("size") or 0) for x in root_audio),
            "already_imported": bool(db.scalar(select(Track.id).where(Track.source_drive_folder_id == parent_id)))})
    return {"parent": parent["name"], "folders": items, "total": len(items)}


class DriveImportRequest(BaseModel):
    folder_ids: list[str] = Field(min_length=1, max_length=100)

@router.post("/import")
def import_drive_folders(payload: DriveImportRequest, _developer: User = Depends(get_current_developer), db: Session = Depends(get_db)):
    service = _service(db)
    imported, skipped, errors = [], [], []
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    def download_file(file_id: str, destination: Path, max_bytes: int):
        request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
        with destination.open("wb") as target:
            downloader = MediaIoBaseDownload(target, request, chunksize=8 * 1024 * 1024)
            done = False
            while not done:
                _, done = downloader.next_chunk()
                if destination.stat().st_size > max_bytes:
                    raise ValueError("O arquivo excede o limite permitido para importação.")

    for source_id in dict.fromkeys(payload.folder_ids):
        existing = db.scalar(select(Track).where(Track.source_drive_folder_id == source_id))
        if existing:
            skipped.append({"id": existing.id, "folder_id": source_id, "title": existing.title, "reason": "Já importada"})
            continue
        track_dir = AUDIO_DIR / uuid4().hex
        stems_dir = track_dir / "stems"
        try:
            source = service.files().get(fileId=source_id, fields="id,name,mimeType,size", supportsAllDrives=True).execute()
            is_folder = source.get("mimeType") == "application/vnd.google-apps.folder"
            is_zip = Path(source.get("name", "")).suffix.lower() == ".zip" or source.get("mimeType") == "application/zip"
            if not is_folder and not is_zip:
                raise ValueError("O item selecionado não é uma pasta nem um arquivo ZIP.")
            stems_dir.mkdir(parents=True, exist_ok=False)
            downloaded = []
            total = 0

            if is_folder:
                audio = _audio_files_recursive(service, source_id)
                rar_archives = _rar_files_recursive(service, source_id)
                if not audio and not rar_archives:
                    raise ValueError("Nenhum áudio ou arquivo RAR encontrado na pasta.")
                if len(audio) > MAX_TRACK_FILES:
                    raise ValueError("A pasta excede o limite de 100 arquivos de áudio.")
                index = 1
                for item in audio:
                    name = re.sub(r"[^\w.() -]", "_", Path(item["name"]).name).strip() or f"stem-{index}"
                    destination = stems_dir / f"{index:02d}_{name}"
                    download_file(item["id"], destination, MAX_FILE_BYTES)
                    total += destination.stat().st_size
                    if total > MAX_TRACK_BYTES:
                        raise ValueError("A pasta excede 2 GB após o download.")
                    downloaded.append(destination)
                    index += 1
                for rar_item in rar_archives:
                    archive = track_dir / f"source-{index}.rar"
                    download_file(rar_item["id"], archive, MAX_TRACK_BYTES)
                    with rarfile.RarFile(archive) as rar:
                        entries = [entry for entry in rar.infolist()
                            if not entry.isdir() and Path(entry.filename).suffix.lower() in AUDIO_EXTENSIONS
                            and not Path(entry.filename).name.startswith("._")]
                        if len(downloaded) + len(entries) > MAX_TRACK_FILES:
                            raise ValueError("A pasta excede o limite de 100 arquivos de áudio.")
                        if sum(entry.file_size for entry in entries) + total > MAX_TRACK_BYTES:
                            raise ValueError("O conteúdo dos RARs excede 2 GB.")
                        for entry in entries:
                            if entry.file_size > MAX_FILE_BYTES:
                                raise ValueError("Um arquivo de áudio do RAR excede 500 MB.")
                            safe_name = re.sub(r"[^\w.() -]", "_", Path(entry.filename).name).strip() or f"stem-{index}"
                            destination = stems_dir / f"{index:02d}_{safe_name}"
                            written = 0
                            with rar.open(entry) as source_file, destination.open("wb") as target:
                                while True:
                                    chunk = source_file.read(8 * 1024 * 1024)
                                    if not chunk:
                                        break
                                    written += len(chunk)
                                    total += len(chunk)
                                    if written > MAX_FILE_BYTES or total > MAX_TRACK_BYTES:
                                        raise ValueError("O conteúdo extraído do RAR excedeu os limites permitidos.")
                                    target.write(chunk)
                            downloaded.append(destination)
                            index += 1
                    archive.unlink(missing_ok=True)
                if not downloaded:
                    raise ValueError("Os RARs não contêm arquivos de áudio compatíveis.")
                title = source["name"]
            elif is_rar:
                archive = track_dir / "source.rar"
                download_file(source_id, archive, MAX_TRACK_BYTES)
                with rarfile.RarFile(archive) as rar:
                    entries = [entry for entry in rar.infolist()
                        if not entry.isdir() and Path(entry.filename).suffix.lower() in AUDIO_EXTENSIONS
                        and not Path(entry.filename).name.startswith("._")]
                    if not entries:
                        raise ValueError("O RAR não contém arquivos de áudio compatíveis.")
                    if len(entries) > MAX_TRACK_FILES or sum(entry.file_size for entry in entries) > MAX_TRACK_BYTES:
                        raise ValueError("O RAR excede o limite de 100 arquivos de áudio ou 2 GB.")
                    for index, entry in enumerate(entries, 1):
                        if entry.file_size > MAX_FILE_BYTES:
                            raise ValueError("Um arquivo de áudio do RAR excede 500 MB.")
                        safe_name = re.sub(r"[^\w.() -]", "_", Path(entry.filename).name).strip() or f"stem-{index}"
                        destination = stems_dir / f"{index:02d}_{safe_name}"
                        written = 0
                        with rar.open(entry) as source_file, destination.open("wb") as target:
                            while True:
                                chunk = source_file.read(8 * 1024 * 1024)
                                if not chunk:
                                    break
                                written += len(chunk)
                                total += len(chunk)
                                if written > MAX_FILE_BYTES or total > MAX_TRACK_BYTES:
                                    raise ValueError("O conteúdo extraído do RAR excedeu os limites permitidos.")
                                target.write(chunk)
                        downloaded.append(destination)
                archive.unlink(missing_ok=True)
                title = Path(source["name"]).stem
            else:
                archive = track_dir / "source.zip"
                download_file(source_id, archive, MAX_TRACK_BYTES)
                with zipfile.ZipFile(archive) as zipped:
                    audio_entries = [entry for entry in zipped.infolist()
                        if not entry.is_dir() and Path(entry.filename).suffix.lower() in AUDIO_EXTENSIONS
                        and not Path(entry.filename).name.startswith("._")]
                    if not audio_entries:
                        raise ValueError("O ZIP não contém arquivos de áudio compatíveis.")
                    if len(audio_entries) > MAX_TRACK_FILES:
                        raise ValueError("O ZIP contém mais de 100 arquivos de áudio.")
                    declared_total = sum(entry.file_size for entry in audio_entries)
                    if declared_total > MAX_TRACK_BYTES:
                        raise ValueError("O conteúdo do ZIP excede o limite de 2 GB.")
                    for index, entry in enumerate(audio_entries, 1):
                        if entry.file_size > MAX_FILE_BYTES:
                            raise ValueError("Um arquivo de áudio do ZIP excede 500 MB.")
                        safe_name = re.sub(r"[^\w.() -]", "_", Path(entry.filename).name).strip() or f"stem-{index}"
                        destination = stems_dir / f"{index:02d}_{safe_name}"
                        written = 0
                        with zipped.open(entry, "r") as source_file, destination.open("wb") as target:
                            while True:
                                chunk = source_file.read(8 * 1024 * 1024)
                                if not chunk:
                                    break
                                written += len(chunk)
                                total += len(chunk)
                                if written > MAX_FILE_BYTES or total > MAX_TRACK_BYTES:
                                    raise ValueError("O conteúdo extraído do ZIP excedeu os limites permitidos.")
                                target.write(chunk)
                        downloaded.append(destination)
                archive.unlink(missing_ok=True)
                title = Path(source["name"]).stem

            main_stem = next((p for p in downloaded if any(w in p.stem.lower() for w in ("mix", "full", "stereo", "master"))), downloaded[0])
            track = Track(title=title[:180], artist="", musical_key="", bpm=None, time_signature="4/4",
                category="Multitrack", categories_json=json.dumps(["Multitrack"], ensure_ascii=False),
                original_filename=(source["name"] + " (Google Drive)")[:255], storage_path=str(main_stem),
                stems_path=str(stems_dir), content_type=mimetypes.guess_type(main_stem.name)[0] or "application/octet-stream",
                file_size=total, source_drive_folder_id=source_id, is_published=False)
            db.add(track)
            db.commit()
            db.refresh(track)
            track_data = {
                "id": track.id,
                "title": track.title,
                "artist": track.artist,
                "musical_key": track.musical_key,
                "bpm": track.bpm,
                "time_signature": track.time_signature,
                "category": track.category,
                "categories": ["Multitrack"],
                "original_filename": track.original_filename,
                "file_size": track.file_size,
                "is_published": track.is_published,
                "created_at": track.created_at.isoformat() if track.created_at else None,
                "audio_url": None,
                "cover_url": None,
                "stems": [
                    {"name": item.name, "size": item.stat().st_size}
                    for item in sorted(stems_dir.iterdir()) if item.is_file()
                ],
                "preview_start_seconds": 0,
                "preview_end_seconds": 30,
                "preview_duration_seconds": 30,
                "preview_ready": False,
            }
            imported.append({
                "id": track.id,
                "title": track.title,
                "stems": len(downloaded),
                "track": track_data,
            })
        except Exception as error:
            db.rollback()
            shutil.rmtree(track_dir, ignore_errors=True)
            logger.exception("Falha ao importar item do Drive %s", source_id)
            errors.append({"folder_id": source_id, "message": str(error)[:300]})
    return {"imported": imported, "skipped": skipped, "errors": errors}
