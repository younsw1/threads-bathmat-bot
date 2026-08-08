#!/usr/bin/env python
"""기존 config/product.yaml + data/reviews.json + data/post_history.json(욕실매트)을
새 SQLite DB(data/app.db)의 products/reviews/posts 테이블로 1회성 이전한다.
이미 app.db에 상품이 있으면 아무것도 하지 않는다 (중복 방지).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from threads_bot import db  # noqa: E402
from threads_bot.product import Product  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REVIEWS_PATH = ROOT / "data" / "reviews.json"
HISTORY_PATH = ROOT / "data" / "post_history.json"


def main() -> int:
    db.init_db()

    if db.list_products():
        print("이미 products 테이블에 데이터가 있어 마이그레이션을 건너뜁니다.")
        return 0

    product = Product.load()
    r = product.raw
    product_id = db.create_product(
        {
            "name": r.get("name") or "(이름 없음)",
            "mode": "review",
            "price": None,
            "thumbnail_url": None,
            "smartstore_url": r.get("smartstore_url", ""),
            "category": r.get("category", ""),
            "review_count": r.get("review_count", 0),
            "rating": r.get("rating", 0),
            "key_selling_points": r.get("key_selling_points", []),
            "cta_text": r.get("cta_text", ""),
            "link_placement": "reply",
        }
    )
    print(f"[product] id={product_id} name={r.get('name')}")

    if REVIEWS_PATH.exists():
        reviews = json.loads(REVIEWS_PATH.read_text(encoding="utf-8"))
        for rv in reviews:
            db.add_review(product_id, text=rv["text"], rating=rv.get("rating"), tag=rv.get("tag"))
        print(f"[reviews] {len(reviews)}건 이전")

    if HISTORY_PATH.exists():
        history = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        for h in history:
            db.add_post(
                {
                    "product_id": product_id,
                    "timestamp": h["timestamp"],
                    "hook_category": h.get("hook_category"),
                    "topic_summary": h.get("topic_summary"),
                    "text": h["text"],
                    "reply_text": None,
                    "post_id": h.get("post_id"),
                    "reply_post_id": None,
                    "source_review_ids": h.get("source_review_ids", []),
                }
            )
        print(f"[posts] {len(history)}건 이전")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
