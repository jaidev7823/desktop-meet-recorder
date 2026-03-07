import google.generativeai as genai
from typing import Optional, List, Dict


class GeminiService:
    def __init__(self, api_key: str, model_name: str = "gemini-2.0-flash"):
        self.api_key = api_key
        self.model_name = model_name
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model_name)

    def generate_summary(self, transcript: str) -> Optional[str]:
        if not transcript:
            return None

        prompt = f"""You are a meeting assistant. Please provide a concise summary of the following meeting transcript. 
Include key topics discussed, important decisions, and action items if any.

Transcript:
{transcript}

Please provide a well-structured summary:"""

        try:
            response = self.model.generate_content(prompt)
            return response.text if hasattr(response, "text") else None
        except Exception as e:
            print(f"Gemini generate summary error: {e}")
            return None

    def chat(
        self, message: str, history: Optional[List[Dict[str, str]]] = None
    ) -> Optional[str]:
        if not message:
            return None

        chat = self.model.start_chat(history=history or [])
        try:
            response = chat.send_message(message)
            return response.text if hasattr(response, "text") else None
        except Exception as e:
            print(f"Gemini chat error: {e}")
            return None

    def generate_embeddings(self, text: str) -> Optional[List[float]]:
        try:
            result = genai.embed_content(
                model="models/embedding-001",
                content=text,
                task_type="semantic_similarity",
            )
            return result.get("embedding")
        except Exception as e:
            print(f"Gemini embedding error: {e}")
            return None


def generate_summary_gemini(api_key: str, transcript: str) -> Optional[str]:
    if not api_key or not transcript:
        return None
    service = GeminiService(api_key)
    return service.generate_summary(transcript)


def chat_with_gemini(
    api_key: str, message: str, history: Optional[List[Dict[str, str]]] = None
) -> Optional[str]:
    if not api_key or not message:
        return None
    service = GeminiService(api_key)
    return service.chat(message, history)
