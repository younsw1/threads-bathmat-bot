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
    naver_client_secret TEXT,
    naver_store_slug TEXT,
    naver_sync_page INTEGER DEFAULT 0,
    kakao_client_id TEXT,
    kakao_client_secret TEXT,
    kakao_redirect_uri TEXT,
    kakao_access_token TEXT,
    kakao_refresh_token TEXT,
    kakao_notify_enabled INTEGER NOT NULL DEFAULT 0,
    openai_api_key TEXT
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'review' CHECK (mode IN ('review', 'promo')),
    naver_product_no TEXT,
    origin_product_no TEXT,
    price INTEGER,
    thumbnail_url TEXT,
    image_urls TEXT DEFAULT '[]',
    smartstore_url TEXT,
    category TEXT,
    reg_date TEXT,
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
    source_review_ids TEXT DEFAULT '[]',
    topic_tag TEXT,
    is_favorite INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS scheduled_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'ready', 'published', 'failed')),
    text TEXT NOT NULL,
    topic_tag TEXT,
    hook_category TEXT,
    topic_summary TEXT,
    image_url TEXT,
    reply_text TEXT,
    source_review_ids TEXT DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    published_at TEXT,
    post_id TEXT,
    reply_post_id TEXT
);

CREATE TABLE IF NOT EXISTS generated_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    prompt TEXT,
    parent_id INTEGER REFERENCES generated_images(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
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
        _migrate(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    """기존 DB에 없는 컬럼을 뒤늦게 추가한다 (ALTER TABLE ADD COLUMN, 있으면 무시)."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(settings)")}
    if "naver_store_slug" not in existing:
        conn.execute("ALTER TABLE settings ADD COLUMN naver_store_slug TEXT")
    if "naver_sync_page" not in existing:
        conn.execute("ALTER TABLE settings ADD COLUMN naver_sync_page INTEGER DEFAULT 0")
    if "schedule_windows" not in existing:
        conn.execute(
            "ALTER TABLE settings ADD COLUMN schedule_windows TEXT DEFAULT "
            "'{\"morning\":false,\"lunch\":false,\"evening\":true}'"
        )
    if "kakao_client_id" not in existing:
        conn.execute("ALTER TABLE settings ADD COLUMN kakao_client_id TEXT")
    if "kakao_client_secret" not in existing:
        conn.execute("ALTER TABLE settings ADD COLUMN kakao_client_secret TEXT")
    if "kakao_redirect_uri" not in existing:
        conn.execute("ALTER TABLE settings ADD COLUMN kakao_redirect_uri TEXT")
    if "kakao_access_token" not in existing:
        conn.execute("ALTER TABLE settings ADD COLUMN kakao_access_token TEXT")
    if "kakao_refresh_token" not in existing:
        conn.execute("ALTER TABLE settings ADD COLUMN kakao_refresh_token TEXT")
    if "kakao_notify_enabled" not in existing:
        conn.execute("ALTER TABLE settings ADD COLUMN kakao_notify_enabled INTEGER NOT NULL DEFAULT 0")
    if "openai_api_key" not in existing:
        conn.execute("ALTER TABLE settings ADD COLUMN openai_api_key TEXT")

    product_cols = {row[1] for row in conn.execute("PRAGMA table_info(products)")}
    if "origin_product_no" not in product_cols:
        conn.execute("ALTER TABLE products ADD COLUMN origin_product_no TEXT")
    if "reg_date" not in product_cols:
        conn.execute("ALTER TABLE products ADD COLUMN reg_date TEXT")

    post_cols = {row[1] for row in conn.execute("PRAGMA table_info(posts)")}
    if "topic_tag" not in post_cols:
        conn.execute("ALTER TABLE posts ADD COLUMN topic_tag TEXT")
    if "is_favorite" not in post_cols:
        conn.execute("ALTER TABLE posts ADD COLUMN is_favorite INTEGER NOT NULL DEFAULT 0")


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


def list_unpublished_products(path: Path = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    """아직 한 번도 발행되지 않은 상품만 반환한다 (발행된 상품은 '발행된 상품' 페이지에서 관리)."""
    with connect(path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM products
            WHERE id NOT IN (SELECT DISTINCT product_id FROM posts)
            ORDER BY created_at DESC
            """
        ).fetchall()
        return [_product_row_to_dict(r) for r in rows]


def list_published_products(path: Path = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    """한 번이라도 발행된 적 있는 상품만, 최근 발행일 순으로 반환한다."""
    with connect(path) as conn:
        rows = conn.execute(
            """
            SELECT products.*, COUNT(posts.id) AS post_count, MAX(posts.timestamp) AS last_published_at
            FROM products
            JOIN posts ON posts.product_id = products.id
            GROUP BY products.id
            ORDER BY last_published_at DESC
            """
        ).fetchall()
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


def set_post_favorite(post_id: int, is_favorite: bool, path: Path = DEFAULT_DB_PATH) -> None:
    with connect(path) as conn:
        conn.execute(
            "UPDATE posts SET is_favorite = ? WHERE id = ?", (1 if is_favorite else 0, post_id)
        )


def list_favorite_posts(limit: int = 5, path: Path = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    """상품에 상관없이, 즐겨찾기한 발행글을 최신순으로 반환한다 (문체 학습용 예시)."""
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT * FROM posts WHERE is_favorite = 1 ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


# --- scheduled_queue -------------------------------------------------------

def _queue_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["source_review_ids"] = json.loads(d.get("source_review_ids") or "[]")
    return d


def add_queue_item(data: dict[str, Any], path: Path = DEFAULT_DB_PATH) -> int:
    data = dict(data)
    if "source_review_ids" in data and not isinstance(data["source_review_ids"], str):
        data["source_review_ids"] = json.dumps(data["source_review_ids"], ensure_ascii=False)
    cols = ", ".join(data.keys())
    placeholders = ", ".join("?" for _ in data)
    with connect(path) as conn:
        cur = conn.execute(
            f"INSERT INTO scheduled_queue ({cols}) VALUES ({placeholders})", list(data.values())
        )
        return cur.lastrowid


def list_queue_items(path: Path = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    with connect(path) as conn:
        rows = conn.execute(
            """
            SELECT scheduled_queue.*, products.name AS product_name
            FROM scheduled_queue JOIN products ON products.id = scheduled_queue.product_id
            ORDER BY scheduled_queue.created_at DESC
            """
        ).fetchall()
        return [_queue_row_to_dict(r) for r in rows]


def get_queue_item(item_id: int, path: Path = DEFAULT_DB_PATH) -> dict[str, Any] | None:
    with connect(path) as conn:
        row = conn.execute("SELECT * FROM scheduled_queue WHERE id = ?", (item_id,)).fetchone()
        return _queue_row_to_dict(row) if row else None


def update_queue_item(item_id: int, values: dict[str, Any], path: Path = DEFAULT_DB_PATH) -> None:
    values = dict(values)
    if "source_review_ids" in values and not isinstance(values["source_review_ids"], str):
        values["source_review_ids"] = json.dumps(values["source_review_ids"], ensure_ascii=False)
    if not values:
        return
    cols = ", ".join(f"{k} = ?" for k in values)
    with connect(path) as conn:
        conn.execute(
            f"UPDATE scheduled_queue SET {cols} WHERE id = ?", list(values.values()) + [item_id]
        )


def delete_queue_item(item_id: int, path: Path = DEFAULT_DB_PATH) -> None:
    with connect(path) as conn:
        conn.execute("DELETE FROM scheduled_queue WHERE id = ?", (item_id,))


# --- generated_images -------------------------------------------------

def add_generated_image(
    product_id: int, file_path: str, prompt: str | None = None,
    parent_id: int | None = None, path: Path = DEFAULT_DB_PATH,
) -> int:
    with connect(path) as conn:
        cur = conn.execute(
            "INSERT INTO generated_images (product_id, file_path, prompt, parent_id) "
            "VALUES (?, ?, ?, ?)",
            (product_id, file_path, prompt, parent_id),
        )
        return cur.lastrowid


def list_generated_images(product_id: int, path: Path = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT * FROM generated_images WHERE product_id = ? ORDER BY created_at DESC",
            (product_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_generated_image(image_id: int, path: Path = DEFAULT_DB_PATH) -> dict[str, Any] | None:
    with connect(path) as conn:
        row = conn.execute(
            "SELECT * FROM generated_images WHERE id = ?", (image_id,)
        ).fetchone()
        return dict(row) if row else None


def delete_generated_image(image_id: int, path: Path = DEFAULT_DB_PATH) -> None:
    with connect(path) as conn:
        conn.execute("DELETE FROM generated_images WHERE id = ?", (image_id,))
