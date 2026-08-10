#!/usr/bin/env python
"""상품 상세(원상품) API 응답을 파일로 덤프한다 (이미지 필드 구조 확인용)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import requests  # noqa: E402
from threads_bot import db  # noqa: E402
from threads_bot.naver_client import NaverCommerceClient, API_BASE  # noqa: E402

ORIGIN_PRODUCT_NO = sys.argv[1] if len(sys.argv) > 1 else "13648640127"

settings = db.get_settings()
client = NaverCommerceClient(
    client_id=settings["naver_client_id"], client_secret=settings["naver_client_secret"]
)
token = client.get_access_token()
resp = requests.get(
    f"{API_BASE}/v2/products/origin-products/{ORIGIN_PRODUCT_NO}",
    headers={"Authorization": f"Bearer {token}"},
    timeout=30,
)

out = Path(__file__).resolve().parents[1] / "data" / "_naver_debug_detail.json"
print(f"status={resp.status_code}")
out.write_text(json.dumps(resp.json(), ensure_ascii=False, indent=2), encoding="utf-8")
print(f"saved to {out}")
