from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PRODUCT_PATH = Path(__file__).resolve().parents[2] / "config" / "product.yaml"


@dataclass
class Product:
    raw: dict[str, Any]

    @classmethod
    def load(cls, path: Path = DEFAULT_PRODUCT_PATH) -> "Product":
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls(raw=data)

    def to_context_block(self) -> str:
        r = self.raw
        points = "\n".join(f"  - {p}" for p in r.get("key_selling_points", []) if p)
        return f"""[홍보 대상 상품 정보]
상품명: {r.get('name') or '(미입력)'}
카테고리: {r.get('category') or '(미입력)'}
누적 후기 수: {r.get('review_count', 0)}개
평균 평점: {r.get('rating', 0)}
핵심 셀링포인트:
{points or '  - (미입력)'}
글 말미 CTA: "{r.get('cta_text', '')}\""""
