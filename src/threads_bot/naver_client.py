from __future__ import annotations

import base64
import re
import time
from dataclasses import dataclass
from html import unescape
from typing import Any

import bcrypt
import requests

_IMG_SRC_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)


def _extract_detail_image_urls(html: str) -> list[str]:
    """상세설명 HTML(detailContent)에 삽입된 <img> 태그에서 이미지 URL을 뽑아낸다."""
    if not html:
        return []
    urls: list[str] = []
    seen: set[str] = set()
    for match in _IMG_SRC_RE.finditer(html):
        url = unescape(match.group(1)).strip()
        if url.startswith("//"):
            url = "https:" + url
        if not url.startswith("http") or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls

API_BASE = "https://api.commerce.naver.com/external"
TOKEN_URL = f"{API_BASE}/v1/oauth2/token"
PRODUCTS_SEARCH_URL = f"{API_BASE}/v1/products/search"
SELLER_CHANNELS_URL = f"{API_BASE}/v1/seller/channels"
ORIGIN_PRODUCT_URL = f"{API_BASE}/v2/products/origin-products"


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

    def get_store_url(self, token: str | None = None) -> str | None:
        """스토어의 스마트스토어 URL(예: https://smartstore.naver.com/xxxx)을 조회한다."""
        token = token or self.get_access_token()
        resp = requests.get(
            SELLER_CHANNELS_URL, headers={"Authorization": f"Bearer {token}"}, timeout=30
        )
        if resp.status_code >= 400:
            raise NaverApiError(f"채널 정보 조회 실패: {resp.status_code} {resp.text}")
        channels = resp.json()
        if not channels:
            return None
        return channels[0].get("url")

    def get_product_images(self, origin_product_no: str, token: str | None = None) -> dict[str, list[str]]:
        """상품 목록 조회는 대표 이미지 1장만 주므로, 전체 이미지가 필요하면
        원상품 상세조회로 대표 이미지 + 추가 이미지 + 상세설명(detailContent)에 들어간
        이미지까지 가져온다. {"gallery": [...], "detail": [...]} 형태로 반환한다."""
        token = token or self.get_access_token()
        resp = requests.get(
            f"{ORIGIN_PRODUCT_URL}/{origin_product_no}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        if resp.status_code >= 400:
            raise NaverApiError(f"상품 상세 조회 실패: {resp.status_code} {resp.text}")
        origin_product = resp.json().get("originProduct") or {}
        images = origin_product.get("images") or {}
        gallery: list[str] = []
        rep = images.get("representativeImage") or {}
        if rep.get("url"):
            gallery.append(rep["url"])
        for extra in images.get("optionalImages") or []:
            if extra.get("url"):
                gallery.append(extra["url"])
        detail = _extract_detail_image_urls(origin_product.get("detailContent") or "")
        detail = [url for url in detail if url not in gallery]
        return {"gallery": gallery, "detail": detail}

    def list_products(self, page: int = 1, size: int = 50) -> dict[str, Any]:
        """상품 목록을 최근 등록순(productNo DESC)으로 정규화해서 반환한다.
        {"items": [...], "total_elements": N, "total_pages": N} 형태.

        주의: 네이버 커머스API 응답 스키마 문서를 직접 확인하지 못해, 흔히 쓰이는
        필드명 후보들을 방어적으로 시도한다. 실제 응답이 다르면 _normalize_item만
        수정하면 된다. (POST + JSON body 방식, GET 아님 — 상품 검색류 API는 대부분 POST)
        """
        token = self.get_access_token()
        resp = requests.post(
            PRODUCTS_SEARCH_URL,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "page": page,
                "size": size,
                "orderType": "NO",  # productNo DESC -> 최근 등록 상품부터
                "productStatusTypes": ["SALE", "OUTOFSTOCK", "WAIT"],
            },
            timeout=30,
        )
        if resp.status_code >= 400:
            raise NaverApiError(f"상품 목록 조회 실패: {resp.status_code} {resp.text}")
        data = resp.json()
        items = (
            data.get("contents")
            or data.get("products")
            or data.get("data")
            or data.get("channelProducts")
            or []
        )
        return {
            "items": [_normalize_item(item) for item in items],
            "total_elements": data.get("totalElements", 0),
            "total_pages": data.get("totalPages", 0),
        }


def _normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    # 실제 응답 구조: {originProductNo, channelProducts: [{name, salePrice, ...}]}
    channel_products = item.get("channelProducts") or []
    channel_product = channel_products[0] if channel_products else item

    def pick(*keys: str, default=None):
        for k in keys:
            if k in channel_product and channel_product[k] not in (None, ""):
                return channel_product[k]
            if k in item and item[k] not in (None, ""):
                return item[k]
        return default

    image_urls: list[str] = []
    rep = channel_product.get("representativeImage") or {}
    if rep.get("url"):
        image_urls.append(rep["url"])
    for extra in channel_product.get("optionalImages") or []:
        if extra.get("url"):
            image_urls.append(extra["url"])
    thumbnail = image_urls[0] if image_urls else None

    return {
        "naver_product_no": str(
            pick("channelProductNo", "originProductNo", "productNo", default="")
        ),
        "origin_product_no": str(pick("originProductNo", default="")),
        "name": pick("name", "productName", default="(이름 없음)"),
        "price": pick("discountedPrice", "salePrice", "price", default=None),
        "thumbnail_url": thumbnail,
        "image_urls": image_urls,
        "category": pick("wholeCategoryName", "categoryName", default=""),
        "reg_date": pick("regDate", default=""),
        "raw": item,
    }
