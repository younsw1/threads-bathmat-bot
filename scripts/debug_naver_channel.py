#!/usr/bin/env python
"""판매자/채널 정보(스토어 URL 슬러그를 포함할 만한) 엔드포인트를 여러 개 시도해본다."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import requests  # noqa: E402
from threads_bot import db  # noqa: E402
from threads_bot.naver_client import NaverCommerceClient, API_BASE  # noqa: E402

settings = db.get_settings()
client = NaverCommerceClient(
    client_id=settings["naver_client_id"], client_secret=settings["naver_client_secret"]
)
token = client.get_access_token()
headers = {"Authorization": f"Bearer {token}"}

candidates = [
    "/v1/seller/account",
    "/v1/seller/channels",
    "/v1/seller-channels",
    "/v1/seller/info",
    "/v2/seller/channels",
    "/v1/channels",
    "/v1/seller/channel",
]

for path in candidates:
    url = f"{API_BASE}{path}"
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        print(f"{resp.status_code}  {path}")
        if resp.status_code == 200:
            print("  ->", resp.text[:500])
    except Exception as e:  # noqa: BLE001
        print(f"ERR  {path}  {e}")
