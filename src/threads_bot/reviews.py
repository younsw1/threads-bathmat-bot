from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

DEFAULT_REVIEWS_PATH = Path(__file__).resolve().parents[2] / "data" / "reviews.json"
SAMPLE_SIZE = 4


def load(path: Path = DEFAULT_REVIEWS_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def sample(
    path: Path = DEFAULT_REVIEWS_PATH,
    n: int = SAMPLE_SIZE,
    exclude_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """최근에 이미 인용한 후기를 제외하고 무작위로 n개를 뽑는다."""
    reviews = load(path)
    exclude_ids = exclude_ids or set()
    pool = [r for r in reviews if r["id"] not in exclude_ids] or reviews
    if not pool:
        return []
    return random.sample(pool, k=min(n, len(pool)))
