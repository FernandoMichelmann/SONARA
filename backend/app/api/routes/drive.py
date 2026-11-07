import base64, hashlib, json, logging, mimetypes, re, shutil, tempfile, zipfile
import rarfile
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
IMPORT_PROGRESS: dict[str, dict] = {}
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".aac"}
MAX_FILE_BYTES = 500 * 1024 * 1024
MAX_TRACK_BYTES = 2 * 1024 * 1024 * 1024
MAX_TRACK_FILES = 100
MAX_FOLDER_SCAN_DEPTH = 5
DRIVE_DOWNLOAD_CHUNK_BYTES = 32 * 1024 * 1024
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



def _rar_files_recursive(service, folder_id: str, depth: int = 0):
    found = []
    for item in _children(service, folder_id):
        mime_type, name = item.get("mimeType", ""), item.get("name", "")
        if mime_type == "application/vnd.google-apps.folder":
            if depth < MAX_FOLDER_SCAN_DEPTH:
                found.extend(_rar_files_recursive(service, item["id"], depth + 1))
        elif mime_type != "application/vnd.google-apps.shortcut" and Path(name).suffix.lower() == ".rar":
            found.append(item)
    return found


def _scan_media_recursive(service, folder_id: str, depth: int = 0):
    """Scan audio and ZIP/RAR archives in one Drive traversal."""
    audio, archives = [], []
    for item in _children(service, folder_id):
        mime_type = item.get("mimeType", "")
        name = item.get("name", "")
        if mime_type == "application/vnd.google-apps.folder":
            if depth < MAX_FOLDER_SCAN_DEPTH:
                nested_audio, nested_archives = _scan_media_recursive(service, item["id"], depth + 1)
                audio.extend(nested_audio)
                archives.extend(nested_archives)
            continue
        if mime_type == "application/vnd.google-apps.shortcut" or name.startswith("._"):
            continue
        extension = Path(name).suffix.lower()
        if extension in AUDIO_EXTENSIONS:
            audio.append(item)
        elif extension in {".rar", ".zip"}:
            archives.append(item)
    audio.sort(key=lambda item: item.get("name", "").casefold())
    archives.sort(key=lambda item: item.get("name", "").casefold())
    return audio, archives


def _download_drive_file(service, file_id: str, destination: Path, max_bytes: int):
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    with destination.open("wb") as target:
        downloader = MediaIoBaseDownload(target, request, chunksize=DRIVE_DOWNLOAD_CHUNK_BYTES)
        done = False
        while not done:
            _, done = downloader.next_chunk()
            if destination.stat().st_size > max_bytes:
                raise ValueError("O arquivo excede o limite permitido para importação.")



def _extract_archive_audio(archive_path: Path, stems_dir: Path, start_index: int, current_total: int,
                          progress_callback=None):
    """Extract supported audio from ZIP/RAR archives using safe output filenames."""

    is_rar = archive_path.suffix.lower() == ".rar"
    try:
        archive = rarfile.RarFile(archive_path) if is_rar else zipfile.ZipFile(archive_path)
        with archive:
            entries = [entry for entry in archive.infolist()
                if not (entry.isdir() if is_rar else entry.is_dir())
                and Path(entry.filename).suffix.lower() in AUDIO_EXTENSIONS
                and not Path(entry.filename).name.startswith("._")]
            if not entries:
                raise ValueError(f"O arquivo {archive_path.name} não contém áudio compatível.")
            if start_index - 1 + len(entries) > MAX_TRACK_FILES:
                raise ValueError("A multitrack excede o limite de 100 arquivos de áudio.")
            if sum(entry.file_size for entry in entries) + current_total > MAX_TRACK_BYTES:
                raise ValueError("O conteúdo dos arquivos compactados excede 2 GB.")
            downloaded, total, index = [], current_total, start_index
            for entry in entries:
                if entry.file_size > MAX_FILE_BYTES:
                    raise ValueError("Um arquivo de áudio compactado excede 500 MB.")
                safe_name = re.sub(r"[^\\w.() -]", "_", Path(entry.filename).name).strip() or f"stem-{index}"
                destination = stems_dir / f"{index:02d}_{safe_name}"
                written = 0
                opener = archive.open(entry) if is_rar else archive.open(entry, "r")
                with opener as source_file, destination.open("wb") as target:
                    while True:
                        chunk = source_file.read(8 * 1024 * 1024)
                        if not chunk:
                            break
                        written += len(chunk)
                        total += len(chunk)
                        if written > MAX_FILE_BYTES or total > MAX_TRACK_BYTES:
                            raise ValueError("O conteúdo extraído excedeu os limites permitidos.")
                        target.write(chunk)
                        if progress_callback:
                            progress_callback(
                                f"Extraindo {Path(entry.filename).name}: "
                                f"{min(100, int(written / max(1, entry.file_size) * 100))}%"
                            )
                if written != entry.file_size:
                    raise ValueError("Um arquivo de áudio compactado foi extraído incompleto.")
                downloaded.append(destination)
                index += 1
            return downloaded, total, index
    except (rarfile.Error, zipfile.BadZipFile, OSError) as error:
        raise ValueError(f"Não foi possível abrir {archive_path.name}. O arquivo pode estar danificado, protegido por senha ou exigir um extrator RAR.") from error

def _rar_audio_entries(archive_path: Path):
    try:
        with rarfile.RarFile(archive_path) as archive:
            return [entry for entry in archive.infolist()
                if not entry.isdir() and Path(entry.filename).suffix.lower() in AUDIO_EXTENSIONS
                and not Path(entry.filename).name.startswith("._")]
    except rarfile.Error as error:
        raise ValueError("Não foi possível ler o RAR. Verifique se não está protegido por senha ou danificado e se o extrator RAR está instalado no backend.") from error


def _inspect_rar(service, item):
    size = int(item.get("size") or 0)
    if size <= 0 or size > MAX_TRACK_BYTES:
        raise ValueError("O RAR está vazio ou excede o limite de 2 GB.")
    with tempfile.TemporaryDirectory(prefix="sonara-rar-scan-") as temporary:
        archive_path = Path(temporary) / "scan.rar"
        _download_drive_file(service, item["id"], archive_path, MAX_TRACK_BYTES)
        entries = _rar_audio_entries(archive_path)
        if len(entries) > MAX_TRACK_FILES or sum(entry.file_size for entry in entries) > MAX_TRACK_BYTES:
            raise ValueError("O RAR excede o limite de 100 arquivos de áudio ou 2 GB.")
        return len(entries), sum(entry.file_size for entry in entries)


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
            audio, archives = _scan_media_recursive(service, item["id"])
            # ZIP/RAR contents are validated and extracted only after import starts.
            items.append({"id": item["id"], "name": name, "item_type": "folder",
                "audio_count": len(audio),
                "total_bytes": sum(int(x.get("size") or 0) for x in audio),
                "archive_count": len(archives),
                "already_imported": bool(db.scalar(select(Track.id).where(Track.source_drive_folder_id == item["id"])))})
        elif Path(name).suffix.lower() == ".rar":
            items.append({"id": item["id"], "name": name, "item_type": "rar",
                "audio_count": None, "archive_count": 1, "total_bytes": int(item.get("size") or 0),
                "already_imported": bool(db.scalar(select(Track.id).where(Track.source_drive_folder_id == item["id"])))})
        elif Path(name).suffix.lower() == ".zip" or item.get("mimeType") == "application/zip":
            items.append({"id": item["id"], "name": name, "item_type": "zip",
                "audio_count": None, "total_bytes": int(item.get("size") or 0),
                "already_imported": bool(db.scalar(select(Track.id).where(Track.source_drive_folder_id == item["id"])))})
    # Only count audio files directly in the selected root; subfolders are listed separately.
    root_audio = [item for item in _children(service, parent_id)
        if item.get("mimeType") != "application/vnd.google-apps.folder"
        and item.get("mimeType") != "application/vnd.google-apps.shortcut"
        and Path(item.get("name", "")).suffix.lower() in AUDIO_EXTENSIONS
        and not item.get("name", "").startswith("._")]
    if root_audio:
        items.insert(0, {"id": parent_id, "name": parent["name"] + " (áudios na pasta principal)",
            "item_type": "folder", "audio_count": len(root_audio),
            "total_bytes": sum(int(x.get("size") or 0) for x in root_audio),
            "already_imported": bool(db.scalar(select(Track.id).where(Track.source_drive_folder_id == parent_id)))})
    return {"parent": parent["name"], "folders": items, "total": len(items)}


class DriveImportRequest(BaseModel):
    folder_ids: list[str] = Field(min_length=1, max_length=100)
    job_id: str = Field(min_length=8, max_length=80)

@router.get("/import-progress/{job_id}")
def get_import_progress(job_id: str, _developer: User = Depends(get_current_developer)):
    progress = IMPORT_PROGRESS.get(job_id)
    if not progress:
        raise HTTPException(status_code=404, detail="Progresso da importação não encontrado.")
    return dict(progress)

@router.post("/import")
def import_drive_folders(payload: DriveImportRequest, _developer: User = Depends(get_current_developer), db: Session = Depends(get_db)):
    service = _service(db)
    imported, skipped, errors = [], [], []
    progress = {"job_id": payload.job_id, "status": "processing", "total": len(set(payload.folder_ids)),
        "completed": 0, "item_percent": 0, "current": "Preparando importação...", "imported": 0, "skipped": 0, "errors": 0}
    IMPORT_PROGRESS[payload.job_id] = progress
    def update_progress(current=None, total=None, item_percent=None):
        if item_percent is not None:
            progress["item_percent"] = max(0, min(100, int(item_percent)))
        if current is not None:
            progress["current"] = str(current)[:240]
        if total is not None:
            progress["total"] = max(progress["completed"], int(total))
        progress["imported"] = len(imported)
        progress["skipped"] = len(skipped)
        progress["errors"] = len(errors)
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    def download_file(file_id: str, destination: Path, max_bytes: int, expected_size: int = 0,
                      progress_callback=None):
        request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
        with destination.open("wb") as target:
            downloader = MediaIoBaseDownload(target, request, chunksize=DRIVE_DOWNLOAD_CHUNK_BYTES)
            done = False
            while not done:
                status, done = downloader.next_chunk()
                current_size = destination.stat().st_size
                if current_size > max_bytes:
                    raise ValueError("O arquivo excede o limite permitido para importação.")
                if progress_callback and expected_size > 0:
                    percent = min(100, int(current_size / expected_size * 100))
                    progress_callback(f"Baixando arquivo do Google Drive: {percent}%")

    def save_track(title: str, artist: str, source_key: str, source_name: str,
                   track_dir: Path, stems_dir: Path, downloaded: list[Path], total: int):
        existing_track = db.scalar(select(Track).where(Track.source_drive_folder_id == source_key))
        if existing_track:
            shutil.rmtree(track_dir, ignore_errors=True)
            skipped.append({"id": existing_track.id, "folder_id": source_key,
                "title": existing_track.title, "reason": "Já importada"})
            return
        if not downloaded:
            raise ValueError("O arquivo não contém áudio compatível.")
        main_stem = next((p for p in downloaded if any(
            word in p.stem.lower() for word in ("mix", "full", "stereo", "master"))), downloaded[0])
        track = Track(title=title[:180], artist=artist[:180], musical_key="", bpm=None,
            time_signature="4/4", category="Multitrack",
            categories_json=json.dumps(["Multitrack"], ensure_ascii=False),
            original_filename=(source_name + " (Google Drive)")[:255],
            storage_path=str(main_stem), stems_path=str(stems_dir),
            content_type=mimetypes.guess_type(main_stem.name)[0] or "application/octet-stream",
            file_size=total, source_drive_folder_id=source_key, is_published=False)
        db.add(track)
        db.commit()
        db.refresh(track)
        track_data = {
            "id": track.id, "title": track.title, "artist": track.artist,
            "musical_key": track.musical_key, "bpm": track.bpm,
            "time_signature": track.time_signature, "category": track.category,
            "categories": ["Multitrack"], "original_filename": track.original_filename,
            "file_size": track.file_size, "is_published": track.is_published,
            "created_at": track.created_at.isoformat() if track.created_at else None,
            "audio_url": None, "cover_url": None,
            "stems": [{"name": item.name, "size": item.stat().st_size}
                for item in sorted(stems_dir.iterdir()) if item.is_file()],
            "preview_start_seconds": 0, "preview_end_seconds": 30,
            "preview_duration_seconds": 30, "preview_ready": False,
        }
        imported.append({"id": track.id, "title": track.title,
            "stems": len(downloaded), "track": track_data})

    def import_archive(archive_item: dict, artist: str):
        source_key = archive_item["id"]
        existing_track = db.scalar(select(Track).where(Track.source_drive_folder_id == source_key))
        if existing_track:
            skipped.append({"id": existing_track.id, "folder_id": source_key,
                "title": existing_track.title, "reason": "Já importada"})
            return
        track_dir = AUDIO_DIR / uuid4().hex
        stems_dir = track_dir / "stems"
        track_dir.mkdir(parents=True, exist_ok=False)
        stems_dir.mkdir(parents=True, exist_ok=False)
        archive_name = archive_item.get("name", "multitrack.zip")
        extension = Path(archive_name).suffix.lower()
        archive_path = track_dir / ("source" + extension)
        try:
            expected_size = int(archive_item.get("size") or 0)
            download_file(
                source_key, archive_path, MAX_TRACK_BYTES, expected_size,
                lambda message: update_progress("Importando: " + archive_name + " · " + message, item_percent=int(message.rsplit(" ", 1)[-1].rstrip("%"))),
            )
            downloaded, total, _ = _extract_archive_audio(
                archive_path, stems_dir, 1, 0,
                lambda message: update_progress("Importando: " + archive_name + " · " + message),
            )
            archive_path.unlink(missing_ok=True)
            save_track(Path(archive_name).stem, artist, source_key, archive_name,
                track_dir, stems_dir, downloaded, total)
        except Exception:
            db.rollback()
            shutil.rmtree(track_dir, ignore_errors=True)
            raise

    for source_id in dict.fromkeys(payload.folder_ids):
        try:
            source = service.files().get(fileId=source_id,
                fields="id,name,mimeType,size", supportsAllDrives=True).execute()
            is_folder = source.get("mimeType") == "application/vnd.google-apps.folder"
            extension = Path(source.get("name", "")).suffix.lower()
            is_archive = extension in {".zip", ".rar"} or source.get("mimeType") == "application/zip"
            if not is_folder and not is_archive:
                raise ValueError("O item selecionado não é uma pasta, ZIP ou RAR.")

            if is_folder:
                update_progress("Analisando pasta: " + source.get("name", "pasta"))
                audio, archives = _scan_media_recursive(service, source_id)
                progress["total"] += max(0, len(archives) + (1 if audio else 0) - 1)
                if not audio and not archives:
                    raise ValueError("Nenhum áudio ou arquivo ZIP/RAR encontrado na pasta.")
                # Cada arquivo compactado representa uma música independente.
                for archive_item in archives:
                    update_progress("Importando: " + archive_item.get("name", "arquivo compactado"), item_percent=0)
                    try:
                        import_archive(archive_item, source["name"])
                    except Exception as error:
                        db.rollback()
                        logger.exception("Falha ao importar arquivo compactado %s", archive_item.get("id"))
                        errors.append({"folder_id": archive_item.get("id"),
                            "message": str(error)[:300]})
                    progress["completed"] += 1
                    update_progress(item_percent=0)
                # Áudios soltos, se existirem, formam uma multitrack separada.
                if audio:
                    loose_key = "folder-audio:" + source_id
                    if db.scalar(select(Track).where(Track.source_drive_folder_id == loose_key)):
                        existing_track = db.scalar(select(Track).where(Track.source_drive_folder_id == loose_key))
                        skipped.append({"id": existing_track.id, "folder_id": loose_key,
                            "title": existing_track.title, "reason": "Já importada"})
                    else:
                        track_dir = AUDIO_DIR / uuid4().hex
                        stems_dir = track_dir / "stems"
                        stems_dir.mkdir(parents=True, exist_ok=False)
                        downloaded, total = [], 0
                        try:
                            if len(audio) > MAX_TRACK_FILES:
                                raise ValueError("A pasta excede o limite de 100 arquivos de áudio.")
                            update_progress("Importando áudios avulsos: " + source["name"])
                            for index, item in enumerate(audio, 1):
                                name = re.sub(r"[^\w.() -]", "_", Path(item["name"]).name).strip() or f"stem-{index}"
                                destination = stems_dir / f"{index:02d}_{name}"
                                download_file(item["id"], destination, MAX_FILE_BYTES)
                                total += destination.stat().st_size
                                if total > MAX_TRACK_BYTES:
                                    raise ValueError("A pasta excede 2 GB após o download.")
                                downloaded.append(destination)
                            save_track(source["name"] + " (áudios avulsos)", source["name"],
                                loose_key, source["name"], track_dir, stems_dir, downloaded, total)
                        except Exception as error:
                            db.rollback()
                            shutil.rmtree(track_dir, ignore_errors=True)
                            errors.append({"folder_id": source_id, "message": str(error)[:300]})
                        progress["completed"] += 1
                        update_progress()
            else:
                update_progress("Importando: " + source.get("name", "arquivo"), item_percent=0)
                import_archive(source, "")
                progress["completed"] += 1
                update_progress(item_percent=0)
        except Exception as error:
            db.rollback()
            logger.exception("Falha ao importar item do Drive %s", source_id)
            errors.append({"folder_id": source_id, "message": str(error)[:300]})
            progress["completed"] += 1
            update_progress()
    progress["status"] = "completed"
    progress["current"] = "Importação concluída."
    update_progress()
    return {"imported": imported, "skipped": skipped, "errors": errors}
