import httpx
from typing import Optional, Dict, Any


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
    api_key: str,
    parent_page_id: str,
    title: str,
    content: str,
) -> Optional[str]:
    if not api_key or not parent_page_id:
        return None
    client = NotionClient(api_key)
    try:
        return client.create_page(parent_page_id, title, content)
    finally:
        client.close()
