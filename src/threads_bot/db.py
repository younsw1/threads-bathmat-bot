from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "app.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    anthropic_api_key TEXT,
    threads_app_id TEXT,
    threads_app_secret TEXT,
    threads_access_token TEXT,
    threads_user_id TEXT,
    threads_token_expires_at TEXT,
    naver_client_id TEXT,
    naver_client_secret TEXT
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'review' CHECK (mode IN ('review', 'promo')),
    naver_product_no TEXT,
    price INTEGER,
    thumbnail_url TEXT,
    image_urls TEXT DEFAULT '[]',
    smartstore_url TEXT,
    category TEXT,
    review_count INTEGER DEFAULT 0,
    rating REAL DEFAULT 0,
    key_selling_points TEXT DEFAULT '[]',
    cta_text TEXT DEFAULT '',
    link_placement TEXT NOT NULL DEFAULT 'reply' CHECK (link_placement IN ('reply', 'inline')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    rating INTEGER,
    tag TEXT
);

CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    timestamp TEXT NOT NULL,
    hook_category TEXT,
    topic_summary TEXT,
    text TEXT NOT NULL,
    reply_text TEXT,
    post_id TEXT,
    reply_post_id TEXT,
    source_review_ids TEXT DEFAULT '[]'
);
"""


@contextmanager
def connect(path: Path = DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(path: Path = DEFAULT_DB_PATH) -> None:
    with connect(path) as conn:
        conn.executescript(SCHEMA)
        conn.execute("INSERT OR IGNORE INTO settings (id) VALUES (1)")


# --- settings -----------------------------------------------------------

def get_settings(path: Path = DEFAULT_DB_PATH) -> dict[str, Any]:
    with connect(path) as conn:
        row = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
        return dict(row) if row else {}


def update_settings(values: dict[str, Any], path: Path = DEFAULT_DB_PATH) -> None:
    if not values:
        return
    cols = ", ".join(f"{k} = ?" for k in values)
    with connect(path) as conn:
        conn.execute(f"UPDATE settings SET {cols} WHERE id = 1", list(values.values()))


# --- products -------------------------------------------------------------

_JSON_PRODUCT_FIELDS = ("key_selling_points", "image_urls")


def create_product(data: dict[str, Any], path: Path = DEFAULT_DB_PATH) -> int:
    data = dict(data)
    for field in _JSON_PRODUCT_FIELDS:
        if field in data and not isinstance(data[field], str):
            data[field] = json.dumps(data[field], ensure_ascii=False)
    cols = ", ".join(data.keys())
    placeholders = ", ".join("?" for _ in data)
    with connect(path) as conn:
        cur = conn.execute(
            f"INSERT INTO products ({cols}) VALUES ({placeholders})", list(data.values())
        )
        return cur.lastrowid


def list_products(path: Path = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    with connect(path) as conn:
        rows = conn.execute("SELECT * FROM products ORDER BY created_at DESC").fetchall()
        return [_product_row_to_dict(r) for r in rows]


def get_product(product_id: int, path: Path = DEFAULT_DB_PATH) -> dict[str, Any] | None:
    with connect(path) as conn:
        row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        return _product_row_to_dict(row) if row else None


def update_product(product_id: int, values: dict[str, Any], path: Path = DEFAULT_DB_PATH) -> None:
    values = dict(values)
    for field in _JSON_PRODUCT_FIELDS:
        if field in values and not isinstance(values[field], str):
            values[field] = json.dumps(values[field], ensure_ascii=False)
    if not values:
        return
    cols = ", ".join(f"{k} = ?" for k in values)
    with connect(path) as conn:
        conn.execute(
            f"UPDATE products SET {cols} WHERE id = ?", list(values.values()) + [product_id]
        )


def _product_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for field in _JSON_PRODUCT_FIELDS:
        d[field] = json.loads(d.get(field) or "[]")
    return d


# --- reviews --------------------------------------------------------------

def add_review(product_id: int, text: str, rating: int | None = None, tag: str | None = None,
                path: Path = DEFAULT_DB_PATH) -> int:
    with connect(path) as conn:
        cur = conn.execute(
            "INSERT INTO reviews (product_id, text, rating, tag) VALUES (?, ?, ?, ?)",
            (product_id, text, rating, tag),
        )
        return cur.lastrowid


def list_reviews(product_id: int, path: Path = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT * FROM reviews WHERE product_id = ? ORDER BY id", (product_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def delete_review(review_id: int, path: Path = DEFAULT_DB_PATH) -> None:
    with connect(path) as conn:
        conn.execute("DELETE FROM reviews WHERE id = ?", (review_id,))


# --- posts ------------------------------------------------------------

def add_post(data: dict[str, Any], path: Path = DEFAULT_DB_PATH) -> int:
    data = dict(data)
    if "source_review_ids" in data and not isinstance(data["source_review_ids"], str):
        data["source_review_ids"] = json.dumps(data["source_review_ids"], ensure_ascii=False)
    cols = ", ".join(data.keys())
    placeholders = ", ".join("?" for _ in data)
    with connect(path) as conn:
        cur = conn.execute(
            f"INSERT INTO posts ({cols}) VALUES ({placeholders})", list(data.values())
        )
        return cur.lastrowid


def list_posts(product_id: int, path: Path = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT * FROM posts WHERE product_id = ? ORDER BY timestamp DESC", (product_id,)
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["source_review_ids"] = json.loads(d.get("source_review_ids") or "[]")
            result.append(d)
        return result


def recent_posts(product_id: int, n: int = 14, path: Path = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    return list_posts(product_id, path)[:n]


def recent_review_ids(product_id: int, n: int = 14, path: Path = DEFAULT_DB_PATH) -> set[str]:
    ids: set[str] = set()
    for p in recent_posts(product_id, n, path):
        ids.update(str(i) for i in p.get("source_review_ids") or [])
    return ids
