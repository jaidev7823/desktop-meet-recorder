import whisper
import torch
import requests
import os
import sys
from faster_whisper import WhisperModel

# ---------- CONFIG ----------
OLLAMA_BASE = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "ministral-3:latest")
OLLAMA_URL = f"{OLLAMA_BASE}/api/generate"

# ---------- TRANSCRIPTION ----------
print("CUDA:", torch.cuda.is_available())
model = whisper.load_model("large")

result = model.transcribe("uploads/test_audio.wav")
transcript = result["text"]

with open("output.txt", "w", encoding="utf-8") as f:
    f.write(transcript)

# ---------- OLLAMA SUMMARY ----------
prompt = f"Summarize clearly and concisely:\n\n{transcript}"

def generate(model_name):
    return requests.post(
        OLLAMA_URL,
        json={"model": model_name, "prompt": prompt, "stream": False},
        timeout=60,
    )

def installed_models():
    try:
        r = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=10)
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return []

try:
    response = generate(OLLAMA_MODEL)

    if response.status_code == 404:
        models = installed_models()
        if not models:
            raise RuntimeError("No Ollama models installed.")
        print(f"Model not found. Using '{models[0]}' instead.")
        response = generate(models[0])

    response.raise_for_status()
    summary = response.json().get("response")

    if not summary:
        raise RuntimeError("No summary returned from Ollama.")

except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)

with open("summary.txt", "w", encoding="utf-8") as f:
    f.write(summary)

print("Done. Summary saved to summary.txt")