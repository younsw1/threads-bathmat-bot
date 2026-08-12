from __future__ import annotations

import base64
from dataclasses import dataclass

import requests

API_BASE = "https://api.openai.com/v1"
MODEL = "gpt-image-1"


class OpenAIApiError(RuntimeError):
    pass


@dataclass
class OpenAIImageClient:
    api_key: str

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def generate(
        self, prompt: str, size: str = "1024x1024", quality: str = "medium", n: int = 1
    ) -> list[bytes]:
        resp = requests.post(
            f"{API_BASE}/images/generations",
            headers=self._headers(),
            json={"model": MODEL, "prompt": prompt, "size": size, "quality": quality, "n": n},
            timeout=120,
        )
        return self._extract_images(resp)

    def edit(
        self,
        prompt: str,
        image_bytes: bytes,
        size: str = "1024x1024",
        n: int = 1,
        mime_type: str = "image/png",
    ) -> list[bytes]:
        ext = "jpg" if mime_type in ("image/jpeg", "image/jpg") else "png"
        resp = requests.post(
            f"{API_BASE}/images/edits",
            headers=self._headers(),
            data={"model": MODEL, "prompt": prompt, "size": size, "n": n},
            files={"image": (f"image.{ext}", image_bytes, mime_type)},
            timeout=120,
        )
        return self._extract_images(resp)

    def _extract_images(self, resp: requests.Response) -> list[bytes]:
        if resp.status_code >= 400:
            raise OpenAIApiError(f"OpenAI 이미지 API 오류 {resp.status_code}: {resp.text}")
        data = resp.json()
        images: list[bytes] = []
        for item in data.get("data", []):
            if item.get("b64_json"):
                images.append(base64.b64decode(item["b64_json"]))
            elif item.get("url"):
                img_resp = requests.get(item["url"], timeout=60)
                if img_resp.status_code < 400:
                    images.append(img_resp.content)
        if not images:
            raise OpenAIApiError(f"이미지 데이터를 받지 못했습니다: {resp.text[:300]}")
        return images
