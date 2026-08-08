from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_HISTORY_PATH = Path(__file__).resolve().parents[2] / "data" / "post_history.json"
RECENT_WINDOW = 14


@dataclass
class PostRecord:
    timestamp: str
    hook_category: str
    topic_summary: str
    text: str
    post_id: str | None = None
    source_review_ids: list[str] | None = None


def load(path: Path = DEFAULT_HISTORY_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def recent(path: Path = DEFAULT_HISTORY_PATH, n: int = RECENT_WINDOW) -> list[dict[str, Any]]:
    return load(path)[-n:]


def append(record: PostRecord, path: Path = DEFAULT_HISTORY_PATH) -> None:
    records = load(path)
    records.append(
        {
            "timestamp": record.timestamp,
            "hook_category": record.hook_category,
            "topic_summary": record.topic_summary,
            "text": record.text,
            "post_id": record.post_id,
            "source_review_ids": record.source_review_ids or [],
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def recent_review_ids(path: Path = DEFAULT_HISTORY_PATH, n: int = RECENT_WINDOW) -> set[str]:
    ids: set[str] = set()
    for record in recent(path, n):
        ids.update(record.get("source_review_ids") or [])
    return ids
