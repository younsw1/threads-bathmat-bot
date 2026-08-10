#!/usr/bin/env python
"""네이버 커머스API 상품 목록 원본 응답을 파일로 덤프한다 (필드 매핑 디버깅용).
설정 화면에 저장된 client_id/secret을 그대로 사용한다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from threads_bot import db  # noqa: E402
from threads_bot.naver_client import NaverCommerceClient, PRODUCTS_SEARCH_URL  # noqa: E402
import requests  # noqa: E402

settings = db.get_settings()
client = NaverCommerceClient(
    client_id=settings["naver_client_id"], client_secret=settings["naver_client_secret"]
)
token = client.get_access_token()
resp = requests.post(
    PRODUCTS_SEARCH_URL,
    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    json={"page": 1, "size": 2, "orderType": "NO", "productStatusTypes": ["SALE", "OUTOFSTOCK", "WAIT"]},
    timeout=30,
)

out = Path(__file__).resolve().parents[1] / "data" / "_naver_debug_response.json"
out.write_text(json.dumps(resp.json(), ensure_ascii=False, indent=2), encoding="utf-8")
print(f"status={resp.status_code} saved to {out}")
