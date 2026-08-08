#!/usr/bin/env python
"""로컬 Threads 자동 발행 대시보드.

실행: python webapp/app.py  (브라우저에서 http://127.0.0.1:8765 자동으로 열림)
사용자 각자의 Meta/Claude/네이버 API 키를 로컬 SQLite(data/app.db)에 저장해서 쓰는
BYOK(Bring Your Own Key) 로컬 앱입니다. 중앙 서버로 데이터가 전송되지 않습니다.
"""
from __future__ import annotations

import os
import sys
import threading
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import anthropic
from flask import Flask, flash, redirect, render_template, request, session, url_for

from threads_bot import db, naver_client
from threads_bot.content_generator import generate
from threads_bot.persona import Persona
from threads_bot.product import Product
from threads_bot.threads_client import ThreadsApiError, ThreadsClient

app = Flask(__name__)
app.secret_key = os.environ.get("WEBAPP_SECRET_KEY", "local-dev-only-not-secret")

REQUIRED_SETTINGS = ("anthropic_api_key", "threads_access_token", "threads_user_id")


def _settings_ready() -> bool:
    s = db.get_settings()
    return all(s.get(k) for k in REQUIRED_SETTINGS)


@app.route("/")
def index():
    return redirect(url_for("products") if _settings_ready() else url_for("setup"))


# --- 설정 ------------------------------------------------------------

@app.route("/setup", methods=["GET", "POST"])
def setup():
    if request.method == "POST":
        db.update_settings(
            {
                "anthropic_api_key": request.form.get("anthropic_api_key", "").strip(),
                "threads_app_id": request.form.get("threads_app_id", "").strip(),
                "threads_app_secret": request.form.get("threads_app_secret", "").strip(),
                "threads_access_token": request.form.get("threads_access_token", "").strip(),
                "threads_user_id": request.form.get("threads_user_id", "").strip(),
                "naver_client_id": request.form.get("naver_client_id", "").strip(),
                "naver_client_secret": request.form.get("naver_client_secret", "").strip(),
            }
        )
        flash("설정을 저장했습니다.", "success")
        return redirect(url_for("setup"))

    settings = db.get_settings()
    return render_template("setup.html", settings=settings)


@app.route("/setup/test/threads", methods=["POST"])
def test_threads():
    settings = db.get_settings()
    try:
        client = ThreadsClient(
            access_token=settings.get("threads_access_token", ""),
            user_id=settings.get("threads_user_id", ""),
        )
        limit = client.get_publishing_limit()
        usage = limit["data"][0]["quota_usage"]
        total = limit["data"][0]["config"]["quota_total"]
        flash(f"Threads 연결 성공 (오늘 발행 {usage}/{total}건 사용)", "success")
    except (ThreadsApiError, KeyError, IndexError) as e:
        flash(f"Threads 연결 실패: {e}", "error")
    return redirect(url_for("setup"))


@app.route("/setup/test/claude", methods=["POST"])
def test_claude():
    settings = db.get_settings()
    try:
        client = anthropic.Anthropic(api_key=settings.get("anthropic_api_key", ""))
        client.messages.create(
            model="claude-sonnet-5",
            max_tokens=8,
            messages=[{"role": "user", "content": "ping"}],
        )
        flash("Claude API 연결 성공", "success")
    except Exception as e:  # noqa: BLE001
        flash(f"Claude API 연결 실패: {e}", "error")
    return redirect(url_for("setup"))


@app.route("/setup/test/naver", methods=["POST"])
def test_naver():
    settings = db.get_settings()
    try:
        client = naver_client.NaverCommerceClient(
            client_id=settings.get("naver_client_id", ""),
            client_secret=settings.get("naver_client_secret", ""),
        )
        client.get_access_token()
        flash("네이버 커머스API 연결 성공", "success")
    except naver_client.NaverApiError as e:
        flash(f"네이버 커머스API 연결 실패: {e}", "error")
    return redirect(url_for("setup"))


# --- 상품 목록 ---------------------------------------------------------

@app.route("/products")
def products():
    return render_template("products.html", products=db.list_products())


@app.route("/products/sync", methods=["POST"])
def sync_products():
    settings = db.get_settings()
    if not settings.get("naver_client_id") or not settings.get("naver_client_secret"):
        flash("먼저 설정 화면에서 네이버 커머스API 키를 입력해주세요.", "error")
        return redirect(url_for("setup"))
    try:
        client = naver_client.NaverCommerceClient(
            client_id=settings["naver_client_id"], client_secret=settings["naver_client_secret"]
        )
        items = client.list_products()
    except naver_client.NaverApiError as e:
        flash(f"상품 목록 조회 실패: {e}", "error")
        return redirect(url_for("products"))

    existing = {p["naver_product_no"]: p for p in db.list_products() if p.get("naver_product_no")}
    created, updated = 0, 0
    for item in items:
        payload = {
            "name": item["name"],
            "naver_product_no": item["naver_product_no"],
            "price": item["price"],
            "thumbnail_url": item["thumbnail_url"],
            "image_urls": item["image_urls"],
            "category": item["category"],
        }
        if item["naver_product_no"] in existing:
            db.update_product(existing[item["naver_product_no"]]["id"], payload)
            updated += 1
        else:
            payload.setdefault("mode", "promo")
            db.create_product(payload)
            created += 1
    flash(f"네이버 상품 동기화 완료 (신규 {created}건, 갱신 {updated}건)", "success")
    return redirect(url_for("products"))


@app.route("/products/new", methods=["GET", "POST"])
def new_product():
    if request.method == "POST":
        product_id = db.create_product(
            {
                "name": request.form["name"].strip(),
                "mode": request.form.get("mode", "review"),
                "category": request.form.get("category", "").strip(),
                "smartstore_url": request.form.get("smartstore_url", "").strip(),
                "cta_text": request.form.get("cta_text", "궁금하신 분은 댓글에 남겨둔 링크 확인해주세요"),
            }
        )
        flash("상품을 추가했습니다.", "success")
        return redirect(url_for("product_detail", product_id=product_id))
    return render_template("product_new.html")


# --- 상품 상세 ---------------------------------------------------------

@app.route("/products/<int:product_id>")
def product_detail(product_id: int):
    product = db.get_product(product_id)
    if not product:
        flash("상품을 찾을 수 없습니다.", "error")
        return redirect(url_for("products"))
    reviews = db.list_reviews(product_id)
    return render_template("product_detail.html", product=product, reviews=reviews)


@app.route("/products/<int:product_id>/update", methods=["POST"])
def update_product(product_id: int):
    points = [p.strip() for p in request.form.get("key_selling_points", "").splitlines() if p.strip()]
    db.update_product(
        product_id,
        {
            "mode": request.form.get("mode", "review"),
            "link_placement": request.form.get("link_placement", "reply"),
            "smartstore_url": request.form.get("smartstore_url", "").strip(),
            "cta_text": request.form.get("cta_text", "").strip(),
            "key_selling_points": points,
        },
    )
    flash("상품 설정을 저장했습니다.", "success")
    return redirect(url_for("product_detail", product_id=product_id))


@app.route("/products/<int:product_id>/reviews/add", methods=["POST"])
def add_review(product_id: int):
    text = request.form.get("text", "").strip()
    if text:
        rating = request.form.get("rating") or None
        db.add_review(product_id, text=text, rating=int(rating) if rating else None,
                      tag=request.form.get("tag", "").strip() or None)
        flash("후기를 추가했습니다.", "success")
    return redirect(url_for("product_detail", product_id=product_id))


@app.route("/products/<int:product_id>/reviews/<int:review_id>/delete", methods=["POST"])
def delete_review(product_id: int, review_id: int):
    db.delete_review(review_id)
    flash("후기를 삭제했습니다.", "success")
    return redirect(url_for("product_detail", product_id=product_id))


# --- 생성 / 미리보기 / 발행 ----------------------------------------------

@app.route("/products/<int:product_id>/generate", methods=["POST"])
def generate_draft(product_id: int):
    settings = db.get_settings()
    product_row = db.get_product(product_id)
    if not product_row:
        flash("상품을 찾을 수 없습니다.", "error")
        return redirect(url_for("products"))

    persona = Persona.load()
    product = Product(raw=product_row)
    reviews = db.list_reviews(product_id) if product_row["mode"] == "review" else []
    recent_records = db.recent_posts(product_id)
    client = anthropic.Anthropic(api_key=settings["anthropic_api_key"])

    try:
        post = generate(persona=persona, product=product, reviews=reviews,
                         recent_records=recent_records, client=client)
    except Exception as e:  # noqa: BLE001
        flash(f"글 생성 실패: {e}", "error")
        return redirect(url_for("product_detail", product_id=product_id))

    session[f"draft_{product_id}"] = {
        "hook_category": post.hook_category,
        "topic_summary": post.topic_summary,
        "text": post.text,
        "source_review_ids": post.source_review_ids,
        "selected_image": product_row.get("thumbnail_url"),
    }
    return redirect(url_for("preview", product_id=product_id))


@app.route("/products/<int:product_id>/preview")
def preview(product_id: int):
    product = db.get_product(product_id)
    draft = session.get(f"draft_{product_id}")
    if not product or not draft:
        flash("먼저 글을 생성해주세요.", "error")
        return redirect(url_for("product_detail", product_id=product_id))
    reply_text = None
    if product["link_placement"] == "reply" and product.get("smartstore_url"):
        reply_text = f"🔗 상품 보러가기\n{product['smartstore_url']}"
    return render_template("preview.html", product=product, draft=draft, reply_text=reply_text)


@app.route("/products/<int:product_id>/preview/select-image", methods=["POST"])
def select_image(product_id: int):
    draft = session.get(f"draft_{product_id}")
    if draft:
        draft["selected_image"] = request.form.get("image_url") or None
        session[f"draft_{product_id}"] = draft
    return redirect(url_for("preview", product_id=product_id))


@app.route("/products/<int:product_id>/publish", methods=["POST"])
def publish(product_id: int):
    settings = db.get_settings()
    product = db.get_product(product_id)
    draft = session.get(f"draft_{product_id}")
    if not product or not draft:
        flash("먼저 글을 생성해주세요.", "error")
        return redirect(url_for("product_detail", product_id=product_id))

    client = ThreadsClient(
        access_token=settings["threads_access_token"], user_id=settings["threads_user_id"]
    )
    image_url = draft.get("selected_image") if request.form.get("use_image") == "on" else None

    try:
        post_id = client.publish_text(draft["text"], image_url=image_url)
        reply_post_id = None
        reply_text = None
        if product["link_placement"] == "reply" and product.get("smartstore_url"):
            reply_text = f"🔗 상품 보러가기\n{product['smartstore_url']}"
            reply_post_id = client.publish_text(reply_text, reply_to_id=post_id)
    except ThreadsApiError as e:
        flash(f"발행 실패: {e}", "error")
        return redirect(url_for("preview", product_id=product_id))

    db.add_post(
        {
            "product_id": product_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "hook_category": draft["hook_category"],
            "topic_summary": draft["topic_summary"],
            "text": draft["text"],
            "reply_text": reply_text,
            "post_id": post_id,
            "reply_post_id": reply_post_id,
            "source_review_ids": draft["source_review_ids"],
        }
    )
    session.pop(f"draft_{product_id}", None)
    flash("Threads에 발행했습니다.", "success")
    return redirect(url_for("product_history", product_id=product_id))


@app.route("/products/<int:product_id>/history")
def product_history(product_id: int):
    product = db.get_product(product_id)
    if not product:
        flash("상품을 찾을 수 없습니다.", "error")
        return redirect(url_for("products"))
    posts = db.list_posts(product_id)
    return render_template("history.html", product=product, posts=posts)


def _open_browser(port: int) -> None:
    webbrowser.open(f"http://127.0.0.1:{port}")


if __name__ == "__main__":
    db.init_db()
    port = int(os.environ.get("WEBAPP_PORT", "8765"))
    threading.Timer(1.0, _open_browser, args=(port,)).start()
    app.run(host="127.0.0.1", port=port, debug=False)
