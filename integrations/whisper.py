import os
import threading
from typing import Any, Dict, List, Optional, Tuple

try:
    from faster_whisper import WhisperModel

    FASTER_WHISPER_AVAILABLE = True
except ImportError:
    WhisperModel = None
    FASTER_WHISPER_AVAILABLE = False

try:
    from openai import OpenAI

    OPENAI_AVAILABLE = True
except ImportError:
    OpenAI = None
    OPENAI_AVAILABLE = False

_MODEL_CACHE: Dict[Tuple[str, str, str], Any] = {}
_MODEL_LOCK = threading.Lock()


def _pick_device_and_compute() -> tuple[str, str]:
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"


def _resolve_model_name(model_name: Optional[str]) -> str:
    return (model_name or os.getenv("WHISPER_MODEL") or "base").strip()


def _get_local_model(model_name: Optional[str] = None) -> Any:
    if not FASTER_WHISPER_AVAILABLE:
        raise RuntimeError("faster_whisper package not installed")

    resolved_model = _resolve_model_name(model_name)
    device, compute_type = _pick_device_and_compute()
    cache_key = (resolved_model, device, compute_type)

    with _MODEL_LOCK:
        if cache_key not in _MODEL_CACHE:
            _MODEL_CACHE[cache_key] = WhisperModel(
                resolved_model,
                device=device,
                compute_type=compute_type,
            )
        return _MODEL_CACHE[cache_key]


def _normalize_segments(segments: Any) -> tuple[str, str, List[Dict[str, Any]]]:
    items: List[Dict[str, Any]] = []
    timestamped_lines: List[str] = []
    plain_lines: List[str] = []

    for segment in segments:
        text = (segment.text or "").strip()
        if not text:
            continue
        item = {
            "start": float(segment.start),
            "end": float(segment.end),
            "text": text,
        }
        items.append(item)
        plain_lines.append(text)
        timestamped_lines.append(
            f"[{item['start']:.2f}s -> {item['end']:.2f}s] {item['text']}"
        )

    transcript = " ".join(plain_lines).strip()
    timestamped_transcript = "\n".join(timestamped_lines).strip()
    return transcript, timestamped_transcript, items


class WhisperLocal:
    def __init__(self, model_name: str = "base"):
        self.model_name = _resolve_model_name(model_name)
        self.model = _get_local_model(self.model_name)

    def transcribe_detailed(self, audio_path: str) -> Optional[Dict[str, Any]]:
        if not os.path.exists(audio_path):
            return None

        try:
            segments, info = self.model.transcribe(
                audio_path,
                beam_size=5,
                vad_filter=True,
                condition_on_previous_text=False,
            )
            transcript, timestamped_transcript, segment_items = _normalize_segments(
                segments
            )
            return {
                "transcript": transcript,
                "timestamped_transcript": timestamped_transcript,
                "segments": segment_items,
                "language": getattr(info, "language", None),
                "language_probability": getattr(info, "language_probability", None),
                "model_name": self.model_name,
            }
        except Exception as exc:
            print(f"Whisper local transcribe error: {exc}")
            return None

    def transcribe(self, audio_path: str) -> Optional[str]:
        result = self.transcribe_detailed(audio_path)
        return result.get("transcript") if result else None


class WhisperAPI:
    def __init__(self, api_key: str):
        if not OPENAI_AVAILABLE:
            raise RuntimeError("openai package not installed")
        self.client = OpenAI(api_key=api_key)

    def transcribe(self, audio_path: str) -> Optional[str]:
        if not os.path.exists(audio_path):
            return None
        try:
            with open(audio_path, "rb") as audio_file:
                response = self.client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                )
            return response.text if hasattr(response, "text") else None
        except Exception as exc:
            print(f"Whisper API transcribe error: {exc}")
            return None


def transcribe_audio_detailed(
    audio_path: str,
    mode: str = "local",
    api_key: Optional[str] = None,
    model_name: str = "base",
) -> Optional[Dict[str, Any]]:
    if not audio_path:
        return None

    if mode == "api":
        transcript = WhisperAPI(api_key or "").transcribe(audio_path) if api_key else None
        return {"transcript": transcript, "timestamped_transcript": "", "segments": []} if transcript else None

    service = WhisperLocal(model_name)
    return service.transcribe_detailed(audio_path)


def transcribe_audio(
    audio_path: str,
    mode: str = "local",
    api_key: Optional[str] = None,
    model_name: str = "base",
) -> Optional[str]:
    result = transcribe_audio_detailed(audio_path, mode, api_key, model_name)
    return result.get("transcript") if result else None
