import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from faster_whisper import WhisperModel

load_dotenv()

_MODEL: Optional[WhisperModel] = None


def _pick_device_and_compute() -> tuple[str, str]:
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"


def _get_whisper_model() -> WhisperModel:
    global _MODEL
    if _MODEL is None:
        device, compute_type = _pick_device_and_compute()
        _MODEL = WhisperModel("large", device=device, compute_type=compute_type)
    return _MODEL


def _clean_json_block(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    return cleaned


def _parse_gemini_output(raw: str) -> Dict[str, Any]:
    parsed = json.loads(_clean_json_block(raw))
    if "title" not in parsed or "summary" not in parsed:
        raise ValueError("Gemini response missing required keys: title and summary")
    tasks = parsed.get("tasks", [])
    if not isinstance(tasks, list):
        tasks = []
    parsed["tasks"] = [str(task).strip() for task in tasks if str(task).strip()]
    parsed["title"] = str(parsed["title"]).strip()
    parsed["summary"] = str(parsed["summary"]).strip()
    return parsed


def _transcribe(audio_path: str) -> Dict[str, Any]:
    model = _get_whisper_model()
    segments, info = model.transcribe(audio_path, beam_size=5)

    timestamped_lines: List[str] = []
    plain_lines: List[str] = []
    for segment in segments:
        timestamped_lines.append(
            f"[{segment.start:.2f}s -> {segment.end:.2f}s] {segment.text.strip()}"
        )
        plain_lines.append(segment.text.strip())

    transcript = " ".join(line for line in plain_lines if line).strip()
    return {
        "language": info.language,
        "language_probability": info.language_probability,
        "transcript": transcript,
        "timestamped_transcript": "\n".join(timestamped_lines).strip(),
    }


def _summarize_with_gemini(transcript: str) -> Dict[str, Any]:
    from google import genai

    gemini_api_key = os.getenv("GEMINI_API_KEY")
    if not gemini_api_key:
        raise ValueError("Missing GEMINI_API_KEY")

    prompt = f"""
You are an operations assistant.

Return ONLY valid JSON with this structure:
{{
  "title": "Short headline (Client - Topic)",
  "summary": "3-5 sentence summary",
  "tasks": ["task 1", "task 2", "task 3"]
}}

Transcript:
\"\"\"
{transcript}
\"\"\"
"""

    gemini = genai.Client(api_key=gemini_api_key)
    response = gemini.models.generate_content(
        model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        contents=prompt,
    )
    raw_text = (response.text or "").strip()
    if not raw_text:
        raise ValueError("Gemini returned an empty response")

    return _parse_gemini_output(raw_text)


def _write_to_notion(title: str, summary: str, tasks: List[str], transcript: str) -> str:
    from notion_client import Client as NotionClient

    token = os.getenv("NOTION_TOKEN")
    database_id = os.getenv("NOTION_DATABASE_ID")
    if not token:
        raise ValueError("Missing NOTION_TOKEN")
    if not database_id:
        raise ValueError("Missing NOTION_DATABASE_ID")

    notion = NotionClient(auth=token)
    now_iso = datetime.utcnow().isoformat()

    response = notion.pages.create(
        parent={"database_id": database_id},
        properties={
            "Title": {"title": [{"text": {"content": title}}]},
            "Call Time": {"date": {"start": now_iso}},
            "Status": {"multi_select": [{"name": "Pending"}]},
        },
        children=[
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": "Summary"}}]
                },
            },
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": summary}}]
                },
            },
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": "Tasks"}}]
                },
            },
            *[
                {
                    "object": "block",
                    "type": "to_do",
                    "to_do": {
                        "rich_text": [{"type": "text", "text": {"content": task}}],
                        "checked": False,
                    },
                }
                for task in tasks
            ],
            {
                "object": "block",
                "type": "toggle",
                "toggle": {
                    "rich_text": [
                        {"type": "text", "text": {"content": "Full Transcript"}}
                    ],
                    "children": [
                        {
                            "object": "block",
                            "type": "paragraph",
                            "paragraph": {
                                "rich_text": [
                                    {
                                        "type": "text",
                                        "text": {"content": transcript[:1900]},
                                    }
                                ]
                            },
                        }
                    ],
                },
            },
        ],
    )
    return response["id"]


def process_audio(
    audio_path: str,
    output_prefix: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> Dict[str, Any]:
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    stt = _transcribe(audio_path)
    transcript = stt["transcript"]

    parsed = _summarize_with_gemini(transcript)

    base_dir = output_dir or "."
    os.makedirs(base_dir, exist_ok=True)

    if output_prefix:
        transcript_path = os.path.join(base_dir, f"{output_prefix}_transcript.txt")
        summary_path = os.path.join(base_dir, f"{output_prefix}_summary.txt")
        debug_path = os.path.join(base_dir, f"{output_prefix}_debug_transcript.txt")
    else:
        transcript_path = os.path.join(base_dir, "output.txt")
        summary_path = os.path.join(base_dir, "summary.txt")
        debug_path = os.path.join(base_dir, "debug_transcript.txt")

    with open(transcript_path, "w", encoding="utf-8") as f:
        f.write(transcript)
        f.write(stt["timestamped_transcript"] + "\n")

    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(parsed["summary"] + "\n\nTasks:\n")
        for task in parsed["tasks"]:
            f.write(f"- {task}\n")

    notion_page_id = _write_to_notion(
        title=parsed["title"],
        summary=parsed["summary"],
        tasks=parsed["tasks"],
        transcript=transcript,
    )

    return {
        "audio_path": audio_path,
        "language": stt["language"],
        "language_probability": stt["language_probability"],
        "title": parsed["title"],
        "summary": parsed["summary"],
        "tasks": parsed["tasks"],
        "notion_page_id": notion_page_id,
        "artifacts": {
            "transcript_path": transcript_path,
            "summary_path": summary_path,
            "debug_path": debug_path,
        },
    }
