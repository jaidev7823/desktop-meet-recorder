import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from typing import Dict, List

try:
    from database import (
        init_databases,
        get_integrations,
        save_integrations,
        save_recording,
        get_recordings,
        get_recording,
        update_recording,
        save_chat_message_db,
        get_chat_history,
    )
except Exception as e:
    print("Database import failed:", e)
    raise

try:
    from integrations import (
        create_notion_page,
        generate_summary_gemini,
        chat_with_gemini,
        transcribe_audio,
    )

    INTEGRATIONS_AVAILABLE = True
except Exception as e:
    print("Integrations import failed:", e)
    INTEGRATIONS_AVAILABLE = False
    create_notion_page = None
    generate_summary_gemini = None
    chat_with_gemini = None
    transcribe_audio = None

DETECTION_IMPORT_ERROR = None
RECORDING_IMPORT_ERROR = None

try:
    from detectors.meeting_detector import check_active_calls
except Exception as exc:
    DETECTION_IMPORT_ERROR = str(exc)

    def check_active_calls():
        return False, False, False


try:
    from obs.controller import start_recording, stop_recording
except Exception as exc:
    RECORDING_IMPORT_ERROR = str(exc)

    def start_recording():
        raise RuntimeError(f"Recording backend unavailable: {RECORDING_IMPORT_ERROR}")

    def stop_recording():
        raise RuntimeError(f"Recording backend unavailable: {RECORDING_IMPORT_ERROR}")


parser = argparse.ArgumentParser()
parser.add_argument("--ffmpeg", default="ffmpeg", help="Path to ffmpeg executable")
parser.add_argument("--mic", default="Microphone (Audio Array AM-C1 Device)")
parser.add_argument("--stereo", default="Stereo Mix (Realtek(R) Audio)")
args = parser.parse_args()

state_lock = threading.Lock()
state = {
    "recording": False,
    "auto_record": True,
    "mic": False,
    "meet": False,
    "whatsapp": False,
    "call": False,
}

os.environ["FFMPEG_PATH"] = args.ffmpeg
os.environ["MIC_DEVICE"] = args.mic
os.environ["STEREO_DEVICE"] = args.stereo

running = True


def emit(message_type: str, data: Dict):
    payload = {"type": message_type, "data": data}
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def emit_response(request_id: str, ok: bool, data=None, error: str = None):
    payload = {"type": "response", "requestId": request_id, "ok": ok}
    if data is not None:
        payload["data"] = data
    if error:
        payload["error"] = error
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def update_audio_devices(devices: Dict):
    mic = devices.get("mic") if isinstance(devices, dict) else None
    stereo = devices.get("stereo") if isinstance(devices, dict) else None

    if mic:
        os.environ["MIC_DEVICE"] = mic
    if stereo:
        os.environ["STEREO_DEVICE"] = stereo


def list_audio_devices(ffmpeg_path: str) -> Dict[str, List[str]]:
    default_mic = os.environ.get("MIC_DEVICE", args.mic)
    default_stereo = os.environ.get("STEREO_DEVICE", args.stereo)

    if sys.platform != "win32":
        return {"mics": [default_mic], "stereos": [default_stereo]}

    cmd = [
        ffmpeg_path,
        "-hide_banner",
        "-list_devices",
        "true",
        "-f",
        "dshow",
        "-i",
        "dummy",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
        )
        combined = f"{proc.stdout}\n{proc.stderr}"
        names = []
        for line in combined.splitlines():
            if "(audio)" not in line.lower():
                continue
            match = re.search(r'"([^"]+)"', line)
            if match:
                names.append(match.group(1).strip())

        # Preserve order while deduplicating.
        seen = set()
        unique = []
        for name in names:
            if name and name not in seen:
                seen.add(name)
                unique.append(name)

        mics = [n for n in unique if "stereo mix" not in n.lower()]
        stereos = [n for n in unique if "stereo mix" in n.lower()]

        if not mics and unique:
            mics = unique[:]
        if not stereos:
            stereos = [default_stereo]

        if default_mic not in mics:
            mics.insert(0, default_mic)
        if default_stereo not in stereos:
            stereos.insert(0, default_stereo)

        return {"mics": mics, "stereos": stereos}
    except Exception:
        return {"mics": [default_mic], "stereos": [default_stereo]}


def start_if_needed(trigger: str):
    with state_lock:
        if state["recording"]:
            return
    start_recording()
    with state_lock:
        state["recording"] = True
    emit("status", {"message": f"Recording started ({trigger})", "level": "info"})


def stop_if_needed(trigger: str):
    with state_lock:
        if not state["recording"]:
            return
    stop_recording()
    with state_lock:
        state["recording"] = False
    emit("status", {"message": f"Recording stopped ({trigger})", "level": "info"})


def detection_loop():
    last_snapshot = None

    while running:
        try:
            mic_active, meet_active, whatsapp_active = check_active_calls()

            with state_lock:
                state["mic"] = bool(mic_active)
                state["meet"] = bool(meet_active)
                state["whatsapp"] = bool(whatsapp_active)
                state["call"] = bool(meet_active or whatsapp_active)

                snapshot = {
                    "mic": state["mic"],
                    "meet": state["meet"],
                    "whatsapp": state["whatsapp"],
                    "recording": state["recording"],
                    "autoRecord": state["auto_record"],
                    "call": state["call"],
                }
                auto_record = state["auto_record"]
                should_start = state["call"] and not state["recording"]
                should_stop = (not state["call"]) and state["recording"]

            if auto_record and should_start:
                trigger = "Google Meet" if meet_active else "WhatsApp"
                start_if_needed(f"auto: {trigger}")
            if auto_record and should_stop:
                stop_if_needed("auto: no active call")

            with state_lock:
                snapshot["recording"] = state["recording"]

            if snapshot != last_snapshot:
                emit("detection", snapshot)
                last_snapshot = snapshot

        except Exception as exc:
            emit("error", {"message": f"Detection loop error: {exc}"})

        time.sleep(3)


def command_loop():
    global running

    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue

        request_id = None
        try:
            message = json.loads(line)
            request_id = str(message.get("requestId", ""))
            action = message.get("action")

            if action == "start_recording":
                update_audio_devices(message.get("devices") or {})
                start_if_needed("manual")
                emit_response(request_id, True)
                continue

            if action == "stop_recording":
                stop_if_needed("manual")
                emit_response(request_id, True)
                continue

            if action == "set_auto_record":
                enabled = bool(message.get("enabled", True))
                with state_lock:
                    state["auto_record"] = enabled
                    snapshot = {
                        "mic": state["mic"],
                        "meet": state["meet"],
                        "whatsapp": state["whatsapp"],
                        "recording": state["recording"],
                        "autoRecord": state["auto_record"],
                        "call": state["call"],
                    }
                emit("detection", snapshot)
                emit_response(request_id, True)
                continue

            if action == "get_audio_devices":
                devices = list_audio_devices(args.ffmpeg)
                emit_response(request_id, True, devices)
                continue

            if action == "get_integrations" and get_integrations:
                data = get_integrations()
                emit_response(request_id, True, data)
                continue

            if action == "save_integrations" and save_integrations:
                data = message.get("data", {})
                notion_parent_page_id = data.get("notion", {}).get(
                    "parentPageId", ""
                ) or data.get("notion", {}).get("notionId", "")
                save_integrations(
                    notion_enabled=data.get("notion", {}).get("enabled", False),
                    notion_api_key=data.get("notion", {}).get("apiKey", ""),
                    notion_parent_page_id=notion_parent_page_id,
                    notion_id=notion_parent_page_id,
                    gemini_enabled=data.get("gemini", {}).get("enabled", False),
                    gemini_api_key=data.get("gemini", {}).get("apiKey", ""),
                    whisper_mode=data.get("whisper", {}).get("mode", "local"),
                    whisper_api_key=data.get("whisper", {}).get("apiKey", ""),
                )
                emit_response(request_id, True)
                continue

            if action == "save_recording" and save_recording:
                rec_data = message.get("data", {})
                recording_id = save_recording(
                    filename=rec_data.get("filename", ""),
                    filepath=rec_data.get("filepath", ""),
                    duration_seconds=rec_data.get("duration", 0),
                )
                emit_response(request_id, True, {"id": recording_id})
                continue

            if action == "get_recordings" and get_recordings:
                recordings = get_recordings(limit=message.get("limit", 50))
                emit_response(request_id, True, {"recordings": recordings})
                continue

            if (
                action == "transcribe_audio"
                and transcribe_audio
                and INTEGRATIONS_AVAILABLE
            ):
                data = message.get("data", {})
                audio_path = data.get("audioPath", "")
                mode = data.get("mode", "local")
                api_key = data.get("apiKey", "")

                if not audio_path:
                    emit_response(request_id, False, error="No audio path provided")
                    continue

                transcript = transcribe_audio(audio_path, mode, api_key or None)
                if transcript:
                    emit_response(request_id, True, {"transcript": transcript})
                else:
                    emit_response(request_id, False, error="Transcription failed")
                continue

            if (
                action == "summarize_with_gemini"
                and generate_summary_gemini
                and INTEGRATIONS_AVAILABLE
            ):
                data = message.get("data", {})
                transcript = data.get("transcript", "")
                api_key = data.get("apiKey", "")

                if not api_key:
                    integrations_data = get_integrations() if get_integrations else {}
                    api_key = integrations_data.get("gemini_api_key", "")

                if not api_key:
                    emit_response(
                        request_id, False, error="No Gemini API key configured"
                    )
                    continue

                summary = generate_summary_gemini(api_key, transcript)
                if summary:
                    emit_response(request_id, True, {"summary": summary})
                else:
                    emit_response(request_id, False, error="Summary generation failed")
                continue

            if (
                action == "chat_with_gemini"
                and chat_with_gemini
                and INTEGRATIONS_AVAILABLE
            ):
                data = message.get("data", {})
                user_message = data.get("message", "")
                api_key = data.get("apiKey", "")
                recording_id = data.get("recordingId")

                if not api_key:
                    integrations_data = get_integrations() if get_integrations else {}
                    api_key = integrations_data.get("gemini_api_key", "")

                if not api_key:
                    emit_response(
                        request_id, False, error="No Gemini API key configured"
                    )
                    continue

                history = None
                if recording_id and get_chat_history:
                    raw_history = get_chat_history(limit=20)
                    history = [
                        {"role": msg["role"], "parts": [msg["content"]]}
                        for msg in reversed(raw_history)
                        if msg.get("recording_id") == recording_id
                        or msg.get("recording_id") is None
                    ]

                response = chat_with_gemini(api_key, user_message, history)
                if response:
                    if save_chat_message_db and recording_id:
                        save_chat_message_db("user", user_message, recording_id)
                        save_chat_message_db("assistant", response, recording_id)
                    emit_response(request_id, True, {"response": response})
                else:
                    emit_response(request_id, False, error="Chat failed")
                continue

            if (
                action == "create_notion_page"
                and create_notion_page
                and INTEGRATIONS_AVAILABLE
            ):
                data = message.get("data", {})
                title = data.get("title", "")
                content = data.get("content", "")
                parent_page_id = data.get("parentPageId", "")
                api_key = data.get("apiKey", "")

                if not api_key:
                    integrations_data = get_integrations() if get_integrations else {}
                    api_key = integrations_data.get("notion_api_key", "")
                if not parent_page_id:
                    integrations_data = get_integrations() if get_integrations else {}
                    parent_page_id = integrations_data.get("notion_parent_page_id", "")

                if not api_key or not parent_page_id:
                    emit_response(
                        request_id,
                        False,
                        error="Notion API key or parent page ID not configured",
                    )
                    continue

                page_id = create_notion_page(api_key, parent_page_id, title, content)
                if page_id:
                    emit_response(request_id, True, {"pageId": page_id})
                else:
                    emit_response(
                        request_id, False, error="Failed to create Notion page"
                    )
                continue

            if action == "process_recording" and INTEGRATIONS_AVAILABLE:
                data = message.get("data", {})
                recording_id = data.get("recordingId")
                audio_path = data.get("audioPath", "")

                if not recording_id or not audio_path:
                    emit_response(
                        request_id, False, error="Missing recording ID or audio path"
                    )
                    continue

                integrations_data = get_integrations() if get_integrations else {}
                results = {"recordingId": recording_id}

                if transcribe_audio:
                    mode = integrations_data.get("whisper_mode", "local")
                    api_key = integrations_data.get("whisper_api_key", "")
                    transcript = transcribe_audio(audio_path, mode, api_key or None)
                    if transcript:
                        results["transcript"] = transcript
                        if update_recording:
                            update_recording(recording_id, transcript=transcript)

                if (
                    generate_summary_gemini
                    and integrations_data.get("gemini_enabled")
                    and integrations_data.get("gemini_api_key")
                ):
                    transcript = results.get("transcript", "")
                    if transcript:
                        summary = generate_summary_gemini(
                            integrations_data["gemini_api_key"], transcript
                        )
                        if summary:
                            results["summary"] = summary
                            if update_recording:
                                update_recording(recording_id, gemini_summary=summary)

                if (
                    create_notion_page
                    and integrations_data.get("notion_enabled")
                    and integrations_data.get("notion_api_key")
                ):
                    parent_id = data.get("notionParentPageId") or integrations_data.get(
                        "notion_parent_page_id"
                    )
                    if parent_id:
                        transcript = results.get("transcript", "")
                        summary = results.get("summary", "")
                        content = (
                            f"Summary:\n{summary}\n\nTranscript:\n{transcript}"
                            if summary
                            else transcript
                        )
                        page_id = create_notion_page(
                            integrations_data["notion_api_key"],
                            parent_id,
                            f"Meeting Recording {recording_id}",
                            content,
                        )
                        if page_id:
                            results["notionPageId"] = page_id
                            if update_recording:
                                update_recording(recording_id, notion_page_id=page_id)

                emit_response(request_id, True, results)
                continue

            emit_response(request_id, False, error=f"Unknown action: {action}")
        except Exception as exc:
            emit_response(request_id or "", False, error=str(exc))

    running = False


def main():
    print("init_databases =", init_databases)

    if init_databases:
        try:
            init_databases()
        except Exception as e:
            emit("error", {"message": f"Database init error: {e}"})

    emit("status", {"message": "Python monitoring started", "level": "info"})
    if DETECTION_IMPORT_ERROR:
        emit("error", {"message": f"Detector import error: {DETECTION_IMPORT_ERROR}"})
    if RECORDING_IMPORT_ERROR:
        emit("error", {"message": f"Recording import error: {RECORDING_IMPORT_ERROR}"})

    thread = threading.Thread(target=detection_loop, daemon=True)
    thread.start()

    command_loop()

    # stdin closed, shut down gracefully
    try:
        stop_if_needed("shutdown")
    except Exception:
        pass


if __name__ == "__main__":
    main()
