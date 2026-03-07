import base64
from typing import Any, Dict, Optional

import httpx


class NotionClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.notion.com/v1"
        self.version = "2022-06-28"
        self.client = httpx.Client(
            headers={
                "Authorization": f"Bearer {api_key}",
                "Notion-Version": self.version,
                "Content-Type": "application/json",
            }
        )

    def create_page(
        self,
        parent_page_id: str,
        title: str,
        content: str,
    ) -> Optional[str]:
        blocks = self._text_to_blocks(content)
        blocks.insert(0, self._heading_block(title))

        payload = {
            "parent": {"page_id": parent_page_id},
            "properties": {"title": {"title": [{"text": {"content": title}}]}},
            "children": blocks,
        }

        try:
            response = self.client.post(f"{self.base_url}/pages", json=payload)
            response.raise_for_status()
            data = response.json()
            return data.get("id")
        except Exception as e:
            print(f"Notion create page error: {e}")
            return None

    def append_blocks(self, page_id: str, content: str) -> bool:
        blocks = self._text_to_blocks(content)
        try:
            response = self.client.patch(
                f"{self.base_url}/blocks/{page_id}/children",
                json={"children": blocks},
            )
            response.raise_for_status()
            return True
        except Exception as e:
            print(f"Notion append blocks error: {e}")
            return False

    def _heading_block(self, text: str) -> Dict[str, Any]:
        return {
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": text}}]},
        }

    def _text_to_blocks(self, text: str) -> list:
        blocks = []
        paragraphs = text.split("\n\n")
        for para in paragraphs:
            if para.strip():
                blocks.append(
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [
                                {"type": "text", "text": {"content": para.strip()}}
                            ]
                        },
                    }
                )
        return blocks

    def close(self):
        self.client.close()


def create_notion_page(
    access_token: str,
    parent_page_id: Optional[str],
    title: str,
    content: str,
) -> Optional[str]:
    if not access_token:
        return None
    resolved_parent_id = parent_page_id or get_first_accessible_page_id(access_token)
    if not resolved_parent_id:
        return None

    client = NotionClient(access_token)
    try:
        return client.create_page(resolved_parent_id, title, content)
    finally:
        client.close()


def exchange_oauth_code(
    client_id: str, client_secret: str, code: str, redirect_uri: str
) -> Optional[Dict[str, Any]]:
    if not client_id or not client_secret or not code or not redirect_uri:
        return None

    basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode(
        "utf-8"
    )
    headers = {
        "Authorization": f"Basic {basic}",
        "Content-Type": "application/json",
    }
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }

    try:
        with httpx.Client(timeout=20) as client:
            response = client.post(
                "https://api.notion.com/v1/oauth/token",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
    except Exception as e:
        print(f"Notion OAuth exchange error: {e}")
        return None

    return {
        "access_token": data.get("access_token", ""),
        "workspace_id": data.get("workspace_id", ""),
        "workspace_name": data.get("workspace_name", ""),
        "workspace_icon": data.get("workspace_icon", ""),
        "bot_id": data.get("bot_id", ""),
    }


def get_first_accessible_page_id(access_token: str) -> Optional[str]:
    if not access_token:
        return None

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    payload = {
        "filter": {"value": "page", "property": "object"},
        "page_size": 10,
        "sort": {"direction": "descending", "timestamp": "last_edited_time"},
    }

    try:
        with httpx.Client(timeout=20) as client:
            response = client.post(
                "https://api.notion.com/v1/search",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
    except Exception as e:
        print(f"Notion search error: {e}")
        return None

    for item in data.get("results", []):
        if item.get("object") == "page" and item.get("id"):
            return item["id"]
    return None
