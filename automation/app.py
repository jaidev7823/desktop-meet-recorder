import os
import io
import json
import logging
import socket
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Dict

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, UploadFile

from pipeline import process_audio

app = FastAPI(title="BriefBridge API")
logger = logging.getLogger("briefbridge")
logging.basicConfig(level=logging.INFO)

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
ARTIFACTS_DIR = os.getenv("ARTIFACTS_DIR", "artifacts")
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "500"))
CHUNK_SIZE = 1024 * 1024
DRIVE_WATCH_ENABLED = os.getenv("DRIVE_WATCH_ENABLED", "true").lower() == "true"
DRIVE_FOLDER_NAME = os.getenv("DRIVE_FOLDER_NAME", "whatsapp_test")
DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID", "").strip()
DRIVE_POLL_SECONDS = int(os.getenv("DRIVE_POLL_SECONDS", "20"))
DRIVE_STATE_FILE = os.getenv(
    "DRIVE_STATE_FILE", os.path.join(ARTIFACTS_DIR, "drive_seen_files.json")
)
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(ARTIFACTS_DIR, exist_ok=True)

JOBS: Dict[str, Dict[str, Any]] = {}
SEEN_DRIVE_KEYS: set[str] = set()
JOBS_LOCK = threading.Lock()


def _iso_now() -> str:
    return datetime.utcnow().isoformat()


def _run_pipeline_job(job_id: str) -> None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return
        job["status"] = "processing"
        job["updated_at"] = _iso_now()

    try:
        result = process_audio(
            job["file_path"],
            output_prefix=f"job_{job_id}",
            output_dir=job["artifact_dir"],
        )
        with JOBS_LOCK:
            job["status"] = "synced_to_notion"
            job["result"] = result
            job["updated_at"] = _iso_now()
    except Exception as exc:
        with JOBS_LOCK:
            job["status"] = "failed"
            job["error"] = str(exc)
            job["updated_at"] = _iso_now()


def _extension_from_content_type(content_type: str) -> str:
    mapping = {
        "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/mp4": ".m4a",
        "audio/x-m4a": ".m4a",
        "audio/aac": ".aac",
        "audio/ogg": ".ogg",
    }
    base = content_type.split(";")[0].strip().lower()
    return mapping.get(base, ".bin")


def _safe_ext(name: str | None, fallback: str = ".bin") -> str:
    if not name:
        return fallback
    _, ext = os.path.splitext(name)
    if not ext:
        return fallback
    ext = ext.lower()
    return ext if len(ext) <= 10 else fallback


def _max_upload_bytes() -> int:
    return MAX_UPLOAD_MB * 1024 * 1024


def _load_seen_drive_keys() -> None:
    global SEEN_DRIVE_KEYS
    if not os.path.exists(DRIVE_STATE_FILE):
        SEEN_DRIVE_KEYS = set()
        return
    try:
        with open(DRIVE_STATE_FILE, "r", encoding="utf-8") as f:
            payload = json.load(f)
            keys = payload.get("seen_keys", [])
            if isinstance(keys, list):
                SEEN_DRIVE_KEYS = set(str(x) for x in keys)
            else:
                SEEN_DRIVE_KEYS = set()
    except Exception as exc:
        logger.warning("Failed to load drive state file: %s", exc)
        SEEN_DRIVE_KEYS = set()


def _persist_seen_drive_keys() -> None:
    os.makedirs(os.path.dirname(DRIVE_STATE_FILE) or ".", exist_ok=True)
    with open(DRIVE_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"seen_keys": sorted(SEEN_DRIVE_KEYS)}, f, indent=2)


def _drive_file_key(file_obj: Dict[str, Any]) -> str:
    return f'{file_obj.get("id", "")}:{file_obj.get("modifiedTime", "")}'


def _register_job(file_path: str, file_size_bytes: int, source: Dict[str, Any]) -> str:
    job_id = uuid.uuid4().hex
    artifact_dir = os.path.join(ARTIFACTS_DIR, job_id)
    os.makedirs(artifact_dir, exist_ok=True)

    with JOBS_LOCK:
        JOBS[job_id] = {
            "job_id": job_id,
            "file_path": file_path,
            "artifact_dir": artifact_dir,
            "file_size_bytes": file_size_bytes,
            "status": "queued",
            "source": source,
            "created_at": _iso_now(),
            "updated_at": _iso_now(),
        }
    return job_id


def _run_pipeline_job_threaded(job_id: str) -> None:
    threading.Thread(target=_run_pipeline_job, args=(job_id,), daemon=True).start()


def _drive_auth_and_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds_file = os.getenv("GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE", "").strip()
    if not creds_file:
        raise ValueError("Missing GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE")
    if not os.path.exists(creds_file):
        raise ValueError(f"Service account file not found: {creds_file}")

    credentials = service_account.Credentials.from_service_account_file(
        creds_file,
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
    )
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def _resolve_drive_folder_id(service) -> str:
    if DRIVE_FOLDER_ID:
        return DRIVE_FOLDER_ID
    escaped_name = DRIVE_FOLDER_NAME.replace("'", "\\'")
    query = (
        "mimeType='application/vnd.google-apps.folder' and "
        f"name='{escaped_name}' and trashed=false"
    )
    response = (
        service.files()
        .list(
            q=query,
            spaces="drive",
            pageSize=1,
            fields="files(id,name)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
    )
    files = response.get("files", [])
    if not files:
        raise ValueError(f"Drive folder not found: {DRIVE_FOLDER_NAME}")
    return files[0]["id"]


def _drive_ext_from_file(file_obj: Dict[str, Any]) -> str:
    name = file_obj.get("name", "")
    ext = _safe_ext(name, fallback="")
    if ext:
        return ext
    mime = str(file_obj.get("mimeType") or "").lower()
    return _extension_from_content_type(mime)


def _download_drive_file(service, file_obj: Dict[str, Any]) -> tuple[str, int]:
    from googleapiclient.http import MediaIoBaseDownload

    ext = _drive_ext_from_file(file_obj)
    tmp_job_id = uuid.uuid4().hex
    file_path = os.path.join(UPLOAD_DIR, f"{tmp_job_id}{ext}")

    request = service.files().get_media(fileId=file_obj["id"], supportsAllDrives=True)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()

    content = buffer.getvalue()
    if not content:
        raise ValueError("Downloaded file is empty")

    with open(file_path, "wb") as f:
        f.write(content)

    return file_path, len(content)


def _is_network_unreachable_error(exc: BaseException) -> bool:
    current: BaseException | None = exc
    while current:
        if isinstance(current, (OSError, socket.gaierror)) and getattr(current, "errno", None) == 101:
            return True
        message = str(current).lower()
        if (
            "network is unreachable" in message
            or "temporary failure in name resolution" in message
            or "name or service not known" in message
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


def _poll_drive_folder_loop() -> None:
    logger.info("Starting Drive watcher loop")
    _load_seen_drive_keys()
    service = None
    folder_id = ""

    while True:
        try:
            if service is None:
                service = _drive_auth_and_service()
                folder_id = _resolve_drive_folder_id(service)
                logger.info("Watching Google Drive folder id=%s", folder_id)

            query = f"'{folder_id}' in parents and trashed=false"
            response = (
                service.files()
                .list(
                    q=query,
                    spaces="drive",
                    pageSize=100,
                    fields="files(id,name,mimeType,size,createdTime,modifiedTime)",
                    orderBy="modifiedTime asc",
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute()
            )
            files = response.get("files", [])

            for file_obj in files:
                if file_obj.get("mimeType") == "application/vnd.google-apps.folder":
                    continue
                seen_key = _drive_file_key(file_obj)
                if seen_key in SEEN_DRIVE_KEYS:
                    continue

                file_path, file_size_bytes = _download_drive_file(service, file_obj)
                source = {
                    "type": "google_drive",
                    "folder_name": DRIVE_FOLDER_NAME,
                    "folder_id": folder_id,
                    "file_id": file_obj.get("id"),
                    "file_name": file_obj.get("name"),
                    "modified_time": file_obj.get("modifiedTime"),
                }
                job_id = _register_job(file_path, file_size_bytes, source=source)
                _run_pipeline_job_threaded(job_id)

                SEEN_DRIVE_KEYS.add(seen_key)
                _persist_seen_drive_keys()
                logger.info(
                    "Queued Drive file: %s (%s) as job %s",
                    file_obj.get("name"),
                    file_obj.get("id"),
                    job_id,
                )
        except Exception as exc:
            if _is_network_unreachable_error(exc):
                logger.warning(
                    "Drive watcher offline (network unreachable). Retrying in %s seconds.",
                    max(5, DRIVE_POLL_SECONDS),
                )
            else:
                logger.exception("Drive watcher iteration failed: %s", exc)
            service = None
            folder_id = ""

        time.sleep(max(5, DRIVE_POLL_SECONDS))


@app.post("/upload-audio")
async def upload_audio(
    request: Request,
    background_tasks: BackgroundTasks,
    auto_process: bool = True,
):
    content_type = request.headers.get("content-type", "")
    max_bytes = _max_upload_bytes()
    bytes_written = 0

    job_id = uuid.uuid4().hex
    artifact_dir = os.path.join(ARTIFACTS_DIR, job_id)
    os.makedirs(artifact_dir, exist_ok=True)

    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        uploaded: UploadFile | None = None
        for value in form.values():
            if isinstance(value, UploadFile):
                uploaded = value
                break
        if uploaded is None:
            raise HTTPException(status_code=400, detail="No file found in multipart form-data")

        ext = _safe_ext(uploaded.filename, fallback=".mp3")
        file_path = os.path.join(UPLOAD_DIR, f"{job_id}{ext}")
        with open(file_path, "wb") as out:
            while True:
                chunk = await uploaded.read(CHUNK_SIZE)
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File too large. Max allowed is {MAX_UPLOAD_MB} MB.",
                    )
                out.write(chunk)
        await uploaded.close()
    else:
        ext = _extension_from_content_type(content_type)
        file_path = os.path.join(UPLOAD_DIR, f"{job_id}{ext}")
        with open(file_path, "wb") as out:
            async for chunk in request.stream():
                if not chunk:
                    continue
                bytes_written += len(chunk)
                if bytes_written > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File too large. Max allowed is {MAX_UPLOAD_MB} MB.",
                    )
                out.write(chunk)

    if bytes_written == 0:
        raise HTTPException(status_code=400, detail="Empty upload")

    with JOBS_LOCK:
        JOBS[job_id] = {
            "job_id": job_id,
            "file_path": file_path,
            "artifact_dir": artifact_dir,
            "file_size_bytes": bytes_written,
            "status": "uploaded",
            "source": {"type": "http_upload"},
            "created_at": _iso_now(),
            "updated_at": _iso_now(),
        }

    if auto_process:
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "queued"
        background_tasks.add_task(_run_pipeline_job, job_id)

    return {
        "job_id": job_id,
        "status": JOBS[job_id]["status"],
        "file_path": file_path,
        "file_size_bytes": bytes_written,
        "message": "Upload received" + (", processing started" if auto_process else ""),
    }


@app.post("/process/{job_id}")
def process_job(job_id: str, background_tasks: BackgroundTasks):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] in {"queued", "processing"}:
        return {"job_id": job_id, "status": job["status"], "message": "Already running"}

    with JOBS_LOCK:
        job["status"] = "queued"
        job["updated_at"] = _iso_now()
        job.pop("error", None)

    background_tasks.add_task(_run_pipeline_job, job_id)
    return {"job_id": job_id, "status": job["status"], "message": "Processing started"}


@app.get("/status/{job_id}")
def get_status(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.on_event("startup")
def start_drive_watcher() -> None:
    if not DRIVE_WATCH_ENABLED:
        logger.info("Drive watcher disabled via DRIVE_WATCH_ENABLED=false")
        return
    threading.Thread(target=_poll_drive_folder_loop, daemon=True).start()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
