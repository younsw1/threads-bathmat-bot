from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from typing import Any

import bcrypt
import requests

API_BASE = "https://api.commerce.naver.com/external"
TOKEN_URL = f"{API_BASE}/v1/oauth2/token"
PRODUCTS_SEARCH_URL = f"{API_BASE}/v1/products/search"


class NaverApiError(RuntimeError):
    pass


def _build_client_secret_sign(client_id: str, client_secret: str, timestamp_ms: int) -> str:
    password = f"{client_id}_{timestamp_ms}"
    hashed = bcrypt.hashpw(password.encode("utf-8"), client_secret.encode("utf-8"))
    return base64.b64encode(hashed).decode("utf-8")


@dataclass
class NaverCommerceClient:
    client_id: str
    client_secret: str

    def get_access_token(self) -> str:
        timestamp_ms = int(time.time() * 1000)
        client_secret_sign = _build_client_secret_sign(self.client_id, self.client_secret, timestamp_ms)
        resp = requests.post(
            TOKEN_URL,
            headers={"content-type": "application/x-www-form-urlencoded"},
            data={
                "client_id": self.client_id,
                "timestamp": timestamp_ms,
                "client_secret_sign": client_secret_sign,
                "grant_type": "client_credentials",
                "type": "SELF",
            },
            timeout=30,
        )
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400 or "access_token" not in data:
            raise NaverApiError(f"네이버 토큰 발급 실패: {resp.status_code} {data}")
        return data["access_token"]

    def list_products(self, page: int = 1, size: int = 50) -> list[dict[str, Any]]:
        """상품 목록을 (id, name, price, thumbnail_url) 형태로 정규화해서 반환한다.

        주의: 네이버 커머스API 응답 스키마 문서를 직접 확인하지 못해, 흔히 쓰이는
        필드명 후보들을 방어적으로 시도한다. 실제 응답이 다르면 _normalize_item만
        수정하면 된다.
        """
        token = self.get_access_token()
        resp = requests.get(
            PRODUCTS_SEARCH_URL,
            headers={"Authorization": f"Bearer {token}"},
            params={"page": page, "size": size},
            timeout=30,
        )
        if resp.status_code >= 400:
            raise NaverApiError(f"상품 목록 조회 실패: {resp.status_code} {resp.text}")
        data = resp.json()
        items = data.get("contents") or data.get("products") or data.get("data") or []
        return [_normalize_item(item) for item in items]


def _normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    channel_product = item.get("channelProduct") or item.get("originProduct") or item

    def pick(*keys: str, default=None):
        for k in keys:
            if k in channel_product and channel_product[k] not in (None, ""):
                return channel_product[k]
            if k in item and item[k] not in (None, ""):
                return item[k]
        return default

    thumbnail = pick("representativeImageUrl")
    image_urls: list[str] = []
    images = pick("images") or {}
    if isinstance(images, dict):
        rep = images.get("representativeImage") or {}
        if rep.get("url"):
            image_urls.append(rep["url"])
        for extra in images.get("optionalImages") or []:
            if extra.get("url"):
                image_urls.append(extra["url"])
    elif isinstance(images, list):
        image_urls = [im.get("url") for im in images if im.get("url")]
    if not thumbnail and image_urls:
        thumbnail = image_urls[0]
    if thumbnail and thumbnail not in image_urls:
        image_urls.insert(0, thumbnail)

    return {
        "naver_product_no": str(pick("originProductNo", "channelProductNo", "productNo", default="")),
        "name": pick("name", "productName", default="(이름 없음)"),
        "price": pick("salePrice", "price", "discountedPrice", default=None),
        "thumbnail_url": thumbnail,
        "image_urls": image_urls,
        "category": pick("categoryName", "wholeCategoryName", default=""),
        "raw": item,
    }
