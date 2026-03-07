import os
from typing import Optional

try:
    import whisper

    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False

try:
    from openai import OpenAI

    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


class WhisperLocal:
    def __init__(self, model_name: str = "base"):
        if not WHISPER_AVAILABLE:
            raise RuntimeError("whisper package not installed")
        self.model = whisper.load_model(model_name)

    def transcribe(self, audio_path: str) -> Optional[str]:
        if not os.path.exists(audio_path):
            return None
        try:
            result = self.model.transcribe(audio_path, language="en")
            return result.get("text", "")
        except Exception as e:
            print(f"Whisper local transcribe error: {e}")
            return None


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
        except Exception as e:
            print(f"Whisper API transcribe error: {e}")
            return None


def transcribe_audio(
    audio_path: str,
    mode: str = "local",
    api_key: Optional[str] = None,
    model_name: str = "base",
) -> Optional[str]:
    if not audio_path:
        return None

    if mode == "api":
        if not api_key:
            return None
        service = WhisperAPI(api_key)
    else:
        service = WhisperLocal(model_name)

    return service.transcribe(audio_path)
