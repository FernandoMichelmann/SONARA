import base64
import hashlib
import json
import logging
import mimetypes
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from telethon.sync import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession

from app.api.routes.drive import AUDIO_DIR, MAX_TRACK_BYTES, MAX_TRACK_FILES, _extract_archive_audio
from app.core.config import settings
from app.db import get_db
from app.dependencies import get_current_developer
from app.models import TelegramConnection, Track, User

router = APIRouter(prefix="/developer/telegram", tags=["Importação Telegram"])
logger = logging.getLogger("sonara.telegram")
ARCHIVE_EXTENSIONS = {".zip", ".rar"}
PENDING_AUTH: dict[int, dict] = {}
TELEGRAM_IMPORT_PROGRESS: dict[str, dict] = {}


def _configured():
    return bool(settings.telegram_api_id and settings.telegram_api_hash)


def _require_configured():
    if not _configured():
        raise HTTPException(status_code=503, detail="Configure TELEGRAM_API_ID e TELEGRAM_API_HASH no backend/.env. Gere as credenciais em my.telegram.org.")


def _fernet():
    digest = hashlib.sha256((settings.jwt_secret_key or "").encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _client(session_string: str = ""):
    _require_configured()
    return TelegramClient(StringSession(session_string), int(settings.telegram_api_id), settings.telegram_api_hash)


def _saved_session(db: Session):
    connection = db.get(TelegramConnection, 1)
    if not connection:
        raise HTTPException(status_code=409, detail="Conecte sua conta do Telegram antes de continuar.")
    try:
        return _fernet().decrypt(connection.session_encrypted.encode()).decode()
    except Exception as error:
        logger.exception("Falha ao descriptografar a sessão do Telegram")
        raise HTTPException(status_code=500, detail="Não foi possível recuperar a sessão do Telegram. Conecte novamente.") from error


class PhoneRequest(BaseModel):
    phone: str = Field(min_length=8, max_length=32)


class VerifyRequest(BaseModel):
    code: str = Field(min_length=3, max_length=16)
    password: str | None = Field(default=None, max_length=256)


class ImportRequest(BaseModel):
    chat_id: int
    message_ids: list[int] = Field(min_length=1, max_length=30)
    job_id: str = Field(min_length=8, max_length=80)


@router.get("/status")
def telegram_status(_developer: User = Depends(get_current_developer), db: Session = Depends(get_db)):
    connection = db.get(TelegramConnection, 1)
    return {
        "configured": _configured(),
        "connected": bool(connection),
        "account": connection.account_label if connection else None,
        "pending_code": False,
    }


@router.post("/auth/start")
def start_telegram_auth(payload: PhoneRequest, developer: User = Depends(get_current_developer)):
    _require_configured()
    phone = re.sub(r"[^+0-9]", "", payload.phone)
    client = _client()
    try:
        client.connect()
        sent = client.send_code_request(phone)
        PENDING_AUTH[developer.id] = {
            "session": client.session.save(),
            "phone": phone,
            "phone_code_hash": sent.phone_code_hash,
        }
        return {"code_sent": True, "phone": phone}
    except Exception as error:
        logger.exception("Falha ao solicitar código do Telegram")
        raise HTTPException(status_code=400, detail="O Telegram não conseguiu enviar o código. Confira o número e tente novamente.") from error
    finally:
        client.disconnect()


@router.post("/auth/verify")
def verify_telegram_auth(payload: VerifyRequest, developer: User = Depends(get_current_developer), db: Session = Depends(get_db)):
    pending = PENDING_AUTH.get(developer.id)
    if not pending:
        raise HTTPException(status_code=409, detail="Solicite um novo código do Telegram antes de confirmar.")
    client = _client(pending["session"])
    try:
        client.connect()
        try:
            client.sign_in(phone=pending["phone"], code=payload.code.strip(),
                phone_code_hash=pending["phone_code_hash"])
        except SessionPasswordNeededError:
            if not payload.password:
                raise HTTPException(status_code=428, detail="Sua conta utiliza verificação em duas etapas. Informe a senha 2FA do Telegram.")
            client.sign_in(password=payload.password)
        me = client.get_me()
        label = me.username and ("@" + me.username) or me.first_name or pending["phone"]
        encrypted = _fernet().encrypt(client.session.save().encode()).decode()
        connection = db.get(TelegramConnection, 1)
        if connection:
            connection.session_encrypted = encrypted
            connection.account_label = label
            connection.updated_at = datetime.now(timezone.utc)
        else:
            db.add(TelegramConnection(id=1, session_encrypted=encrypted, account_label=label))
        db.commit()
        PENDING_AUTH.pop(developer.id, None)
        return {"connected": True, "account": label}
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("Falha ao validar código do Telegram")
        raise HTTPException(status_code=400, detail="Código inválido, expirado ou senha 2FA incorreta. Confira os dados e tente novamente.") from error
    finally:
        client.disconnect()


@router.delete("/connection")
def disconnect_telegram(_developer: User = Depends(get_current_developer), db: Session = Depends(get_db)):
    connection = db.get(TelegramConnection, 1)
    if connection:
        db.delete(connection)
        db.commit()
    return {"connected": False}


@router.get("/groups")
def list_telegram_groups(_developer: User = Depends(get_current_developer), db: Session = Depends(get_db)):
    client = _client(_saved_session(db))
    try:
        client.connect()
        groups = []
        for dialog in client.iter_dialogs(limit=500):
            entity = dialog.entity
            if not (dialog.is_group or (dialog.is_channel and getattr(entity, "megagroup", False))):
                continue
            groups.append({"id": int(dialog.id), "title": dialog.name or "Grupo sem nome",
                "members": getattr(entity, "participants_count", None)})
        return {"items": groups}
    except Exception as error:
        logger.exception("Falha ao listar grupos do Telegram")
        raise HTTPException(status_code=502, detail="Não foi possível consultar os grupos do Telegram.") from error
    finally:
        client.disconnect()


@router.get("/files")
def list_telegram_archives(chat_id: int, offset_id: int = 0, limit: int = 50,
    _developer: User = Depends(get_current_developer), db: Session = Depends(get_db)):
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=422, detail="O limite deve ficar entre 1 e 100 arquivos.")
    client = _client(_saved_session(db))
    try:
        client.connect()
        entity = client.get_entity(chat_id)
        items = []
        scanned = 0
        last_message_id = None
        for message in client.iter_messages(entity, limit=limit, offset_id=offset_id or 0):
            scanned += 1
            last_message_id = int(message.id)
            document = message.document
            if not document:
                continue
            name = message.file.name or ""
            extension = Path(name).suffix.lower()
            if extension not in ARCHIVE_EXTENSIONS:
                continue
            size = int(message.file.size or 0)
            items.append({"message_id": int(message.id), "name": name or f"arquivo-{message.id}{extension}",
                "extension": extension.lstrip(".").upper(), "size": size,
                "date": message.date.isoformat() if message.date else None,
                "already_imported": bool(db.scalar(select(Track.id).where(
                    Track.source_telegram_message_id == f"{chat_id}:{message.id}")))})
        return {"items": items, "next_offset_id": last_message_id if scanned == limit else None}
    except Exception as error:
        logger.exception("Falha ao listar arquivos do grupo Telegram")
        raise HTTPException(status_code=502, detail="Não foi possível listar os arquivos deste grupo.") from error
    finally:
        client.disconnect()


@router.get("/import-progress/{job_id}")
def get_telegram_import_progress(job_id: str, _developer: User = Depends(get_current_developer)):
    progress = TELEGRAM_IMPORT_PROGRESS.get(job_id)
    if not progress:
        raise HTTPException(status_code=404, detail="Progresso da importação não encontrado.")
    return dict(progress)


@router.post("/import")
def import_telegram_archives(payload: ImportRequest, _developer: User = Depends(get_current_developer),
    db: Session = Depends(get_db)):
    imported, skipped, errors = [], [], []
    progress = {
        "job_id": payload.job_id, "status": "processing",
        "total": len(set(payload.message_ids)), "completed": 0, "item_percent": 0,
        "current": "Preparando conexão com o Telegram...", "imported": 0, "skipped": 0, "errors": 0,
    }
    TELEGRAM_IMPORT_PROGRESS[payload.job_id] = progress

    def update_progress(current=None, item_percent=None):
        if current is not None:
            progress["current"] = str(current)[:240]
        if item_percent is not None:
            progress["item_percent"] = max(0, min(100, int(item_percent)))
        progress["imported"] = len(imported)
        progress["skipped"] = len(skipped)
        progress["errors"] = len(errors)

    client = _client(_saved_session(db))
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    try:
        client.connect()
        entity = client.get_entity(payload.chat_id)
        message_ids = list(dict.fromkeys(payload.message_ids))
        progress["total"] = len(message_ids)
        for index, message_id in enumerate(message_ids, 1):
            source_key = f"{payload.chat_id}:{message_id}"
            update_progress(f"Preparando arquivo {index} de {len(message_ids)}...")
            existing = db.scalar(select(Track).where(Track.source_telegram_message_id == source_key))
            if existing:
                skipped.append({"id": existing.id, "title": existing.title, "message_id": message_id})
                progress["completed"] += 1
                update_progress(f"Arquivo {index} de {len(message_ids)} já estava importado.", 0)
                continue
            archive_name = f"Mensagem {message_id}"
            track_dir = AUDIO_DIR / uuid4().hex
            stems_dir = track_dir / "stems"
            track_dir.mkdir(parents=True, exist_ok=False)
            stems_dir.mkdir(parents=True, exist_ok=False)
            try:
                message = client.get_messages(entity, ids=message_id)
                if not message or not message.document:
                    raise ValueError("A mensagem não contém um arquivo.")
                archive_name = message.file.name or f"telegram-{message_id}.zip"
                extension = Path(archive_name).suffix.lower()
                if extension not in ARCHIVE_EXTENSIONS:
                    raise ValueError("Somente arquivos ZIP e RAR podem ser importados.")
                file_size = int(message.file.size or 0)
                if file_size <= 0 or file_size > MAX_TRACK_BYTES:
                    raise ValueError("O arquivo está vazio ou excede o limite de 2 GB.")
                archive_path = track_dir / ("source" + extension)
                update_progress(f"Baixando {archive_name} do Telegram...", 0)

                def download_progress(received, total_bytes):
                    percent = int(received / max(1, total_bytes) * 100)
                    update_progress(f"Baixando {archive_name} · {percent}%", percent)

                client.download_media(message, file=str(archive_path), progress_callback=download_progress)
                if not archive_path.exists() or archive_path.stat().st_size <= 0:
                    raise ValueError("O Telegram não entregou o arquivo completo.")
                update_progress(f"Extraindo os áudios de {archive_name}...", 0)

                def extraction_progress(message_text):
                    import re as _re
                    match = _re.search(r"(\d+)%", str(message_text))
                    update_progress(str(message_text), int(match.group(1)) if match else 0)

                downloaded, total, _ = _extract_archive_audio(
                    archive_path, stems_dir, 1, 0, extraction_progress
                )
                archive_path.unlink(missing_ok=True)
                if not downloaded:
                    raise ValueError("O arquivo compactado não contém áudios compatíveis.")
                if len(downloaded) > MAX_TRACK_FILES:
                    raise ValueError("A multitrack excede o limite de arquivos de áudio.")
                main_stem = next((item for item in downloaded if any(
                    word in item.stem.lower() for word in ("mix", "full", "stereo", "master"))), downloaded[0])
                track = Track(title=Path(archive_name).stem[:180], artist="", musical_key="", bpm=None,
                    time_signature="4/4", category="Multitrack",
                    categories_json=json.dumps(["Multitrack"], ensure_ascii=False),
                    original_filename=(archive_name + " (Telegram)")[:255],
                    storage_path=str(main_stem), stems_path=str(stems_dir),
                    content_type=mimetypes.guess_type(main_stem.name)[0] or "application/octet-stream",
                    file_size=total, source_telegram_message_id=source_key, is_published=False)
                db.add(track)
                db.commit()
                db.refresh(track)
                imported.append({"id": track.id, "title": track.title, "stems": len(downloaded)})
                update_progress(f"{archive_name} importado com sucesso.", 100)
            except Exception as error:
                db.rollback()
                shutil.rmtree(track_dir, ignore_errors=True)
                logger.exception("Falha ao importar mensagem %s do Telegram", message_id)
                errors.append({"message_id": message_id, "name": archive_name, "message": str(error)[:280]})
                update_progress(f"Erro em {archive_name}: {str(error)[:150]}", 0)
            progress["completed"] += 1
            update_progress()
        progress["status"] = "completed"
        progress["current"] = "Importação concluída."
        progress["item_percent"] = 100
        update_progress()
        return {"imported": imported, "skipped": skipped, "errors": errors}
    except Exception as error:
        progress["status"] = "failed"
        progress["current"] = "A importação foi interrompida: " + str(error)[:180]
        update_progress()
        raise
    finally:
        client.disconnect()
