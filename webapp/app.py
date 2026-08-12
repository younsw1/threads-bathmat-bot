#!/usr/bin/env python
"""로컬 Threads 자동 발행 대시보드.

실행: python webapp/app.py  (브라우저에서 http://127.0.0.1:8765 자동으로 열림)
사용자 각자의 Meta/Claude/네이버 API 키를 로컬 SQLite(data/app.db)에 저장해서 쓰는
BYOK(Bring Your Own Key) 로컬 앱입니다. 중앙 서버로 데이터가 전송되지 않습니다.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import uuid
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import anthropic
import markdown
import requests
from flask import Flask, flash, redirect, render_template, request, session, url_for

from threads_bot import db, kakao_client, naver_client, openai_client, schedule
from threads_bot.content_generator import generate, suggest_selling_points
from threads_bot.persona import Persona
from threads_bot.product import Product
from threads_bot.threads_client import ThreadsApiError, ThreadsClient

REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATED_IMAGES_DIR = REPO_ROOT / "webapp" / "static" / "generated"

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
                "naver_store_slug": request.form.get("naver_store_slug", "").strip(),
                "kakao_client_id": request.form.get("kakao_client_id", "").strip(),
                "kakao_client_secret": request.form.get("kakao_client_secret", "").strip(),
                "kakao_redirect_uri": request.form.get("kakao_redirect_uri", "").strip(),
                "kakao_notify_enabled": 1 if request.form.get("kakao_notify_enabled") == "on" else 0,
                "openai_api_key": request.form.get("openai_api_key", "").strip(),
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
            access_token=settings.get("threads_access_token") or "",
            user_id=settings.get("threads_user_id") or "",
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
        client = anthropic.Anthropic(api_key=settings.get("anthropic_api_key") or "")
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
            client_id=settings.get("naver_client_id") or "",
            client_secret=settings.get("naver_client_secret") or "",
        )
        client.get_access_token()
        flash("네이버 커머스API 연결 성공", "success")
    except naver_client.NaverApiError as e:
        flash(f"네이버 커머스API 연결 실패: {e}", "error")
    return redirect(url_for("setup"))


@app.route("/setup/kakao/authorize")
def kakao_authorize():
    settings = db.get_settings()
    if not settings.get("kakao_client_id") or not settings.get("kakao_redirect_uri"):
        flash("먼저 카카오 REST API 키와 Redirect URI를 입력하고 저장해주세요.", "error")
        return redirect(url_for("setup"))
    url = kakao_client.build_authorize_url(
        settings["kakao_client_id"], settings["kakao_redirect_uri"]
    )
    return redirect(url)


@app.route("/setup/kakao/exchange", methods=["POST"])
def kakao_exchange():
    pasted = request.form.get("code", "").strip()
    if not pasted:
        flash("코드를 입력해주세요.", "error")
        return redirect(url_for("setup"))
    if pasted.startswith("http"):
        from urllib.parse import parse_qs, urlparse

        query = parse_qs(urlparse(pasted).query)
        pasted = query.get("code", [""])[0]
    if not pasted:
        flash("붙여넣은 값에서 code를 찾지 못했습니다.", "error")
        return redirect(url_for("setup"))

    settings = db.get_settings()
    try:
        data = kakao_client.exchange_code_for_token(
            client_id=settings["kakao_client_id"],
            client_secret=settings.get("kakao_client_secret") or "",
            redirect_uri=settings["kakao_redirect_uri"],
            code=pasted,
        )
    except kakao_client.KakaoApiError as e:
        flash(f"카카오 토큰 발급 실패: {e}", "error")
        return redirect(url_for("setup"))

    db.update_settings(
        {
            "kakao_access_token": data["access_token"],
            "kakao_refresh_token": data["refresh_token"],
        }
    )
    flash("카카오 인증 완료! 아래 '카카오 테스트'로 확인해보세요.", "success")
    return redirect(url_for("setup"))


def _kakao_refresh(settings: dict) -> str:
    """리프레시 토큰으로 최신 액세스 토큰을 받아오고 DB에 저장한 뒤 반환한다."""
    data = kakao_client.refresh_access_token(
        client_id=settings["kakao_client_id"],
        client_secret=settings.get("kakao_client_secret") or "",
        refresh_token=settings["kakao_refresh_token"],
    )
    updates = {"kakao_access_token": data["access_token"]}
    if data.get("refresh_token"):  # 카카오가 새 리프레시 토큰을 줄 때만 갱신
        updates["kakao_refresh_token"] = data["refresh_token"]
    db.update_settings(updates)
    return data["access_token"]


def notify_kakao(text: str, web_url: str | None = None) -> None:
    """설정에서 알림이 켜져 있으면 카카오톡 '나에게 보내기'로 발송한다. 실패해도 조용히 무시한다
    (알림 실패가 발행 자체를 막으면 안 되므로)."""
    settings = db.get_settings()
    if not settings.get("kakao_notify_enabled") or not settings.get("kakao_refresh_token"):
        return
    try:
        access_token = _kakao_refresh(settings)
        kakao_client.KakaoClient(access_token=access_token).send_text_to_me(text, web_url=web_url)
    except kakao_client.KakaoApiError as e:
        print(f"[kakao] 알림 발송 실패(무시하고 계속 진행): {e}")


@app.route("/setup/kakao/test", methods=["POST"])
def test_kakao():
    settings = db.get_settings()
    if not settings.get("kakao_refresh_token"):
        flash("먼저 카카오 인증을 완료해주세요.", "error")
        return redirect(url_for("setup"))
    try:
        access_token = _kakao_refresh(settings)
        kakao_client.KakaoClient(access_token=access_token).send_text_to_me(
            "Threads 대시보드 카카오 알림 테스트입니다. 이 메시지가 보이면 연동 성공!"
        )
        flash("카카오톡으로 테스트 메시지를 보냈습니다. 확인해보세요.", "success")
    except kakao_client.KakaoApiError as e:
        flash(f"카카오 테스트 실패: {e}", "error")
    return redirect(url_for("setup"))


@app.route("/manual")
def manual():
    manual_path = REPO_ROOT / "사용설명서.md"
    text = manual_path.read_text(encoding="utf-8") if manual_path.exists() else "설명서 파일을 찾을 수 없습니다."
    html = markdown.markdown(text, extensions=["tables", "fenced_code", "toc"])
    return render_template("manual.html", manual_html=html)


# --- 상품 목록 ---------------------------------------------------------

@app.route("/products")
def products():
    return render_template(
        "products.html",
        products=db.list_unpublished_products(),
        pending_product_ids=db.list_pending_queue_product_ids(),
    )


@app.route("/products/published")
def published_products():
    return render_template("products_published.html", products=db.list_published_products())


@app.route("/products/sync", methods=["POST"])
def sync_products():
    settings = db.get_settings()
    if not settings.get("naver_client_id") or not settings.get("naver_client_secret"):
        flash("먼저 설정 화면에서 네이버 커머스API 키를 입력해주세요.", "error")
        return redirect(url_for("setup"))
    next_page = (settings.get("naver_sync_page") or 0) + 1
    try:
        client = naver_client.NaverCommerceClient(
            client_id=settings["naver_client_id"], client_secret=settings["naver_client_secret"]
        )
        store_url = client.get_store_url()  # 예: https://smartstore.naver.com/chaummadang
        result = client.list_products(page=next_page)
    except naver_client.NaverApiError as e:
        flash(f"상품 목록 조회 실패: {e}", "error")
        return redirect(url_for("products"))

    if store_url:
        db.update_settings({"naver_store_slug": store_url.rstrip("/").rsplit("/", 1)[-1]})
    store_base = (store_url or "").rstrip("/")

    existing = {p["naver_product_no"]: p for p in db.list_products() if p.get("naver_product_no")}
    created, updated = 0, 0
    for item in result["items"]:
        smartstore_url = (
            f"{store_base}/products/{item['naver_product_no']}"
            if store_base and item.get("naver_product_no")
            else ""
        )
        payload = {
            "name": item["name"],
            "naver_product_no": item["naver_product_no"],
            "origin_product_no": item["origin_product_no"],
            "price": item["price"],
            "thumbnail_url": item["thumbnail_url"],
            "image_urls": item["image_urls"],
            "category": item["category"],
            "reg_date": item["reg_date"],
            "smartstore_url": smartstore_url,
        }
        if item["naver_product_no"] in existing:
            db.update_product(existing[item["naver_product_no"]]["id"], payload)
            updated += 1
        else:
            payload.setdefault("mode", "promo")
            db.create_product(payload)
            created += 1

    db.update_settings({"naver_sync_page": next_page})
    fetched_so_far = next_page * 50
    total = result.get("total_elements", 0)
    flash(
        f"네이버 상품 동기화 완료 (신규 {created}건, 갱신 {updated}건) "
        f"— 최근 등록순으로 약 {min(fetched_so_far, total)}/{total}건 불러옴",
        "success",
    )
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


# --- AI 이미지 생성/수정 --------------------------------------------------

def _build_lifestyle_prompt(product_row: dict) -> str:
    name = product_row.get("name") or "상품"
    category = product_row.get("category") or ""
    points = ", ".join(product_row.get("key_selling_points") or [])
    return (
        f"첨부한 사진 속 '{name}' 상품의 실제 디자인·색상·형태·로고를 절대 바꾸지 말고 그대로 유지한 채, "
        "실제 사람이 이 상품을 자연스럽게 실사용하는 라이프스타일 스냅샷으로 합성/편집해줘. "
        f"카테고리: {category}. "
        + (f"강조할 특징: {points}. " if points else "")
        + "광고 카탈로그 이미지가 아니라 SNS에 올릴 법한 자연스러운 순간처럼 배경과 상황만 새로 구성하고, "
        "상품 자체의 생김새는 원본 사진과 동일해야 한다. 텍스트나 워터마크, 로고 추가는 하지 않는다."
    )


def _download_image(url: str) -> tuple[bytes, str]:
    resp = requests.get(url, timeout=30)
    if resp.status_code >= 400:
        raise ValueError(f"이미지를 불러오지 못했습니다 ({resp.status_code}): {url}")
    content_type = resp.headers.get("Content-Type", "image/png").split(";")[0].strip()
    return resp.content, content_type


def _save_generated_images(product_id: int, image_bytes_list: list[bytes], prompt: str,
                            parent_id: int | None = None) -> int:
    out_dir = GENERATED_IMAGES_DIR / str(product_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    for img_bytes in image_bytes_list:
        filename = f"{uuid.uuid4().hex}.png"
        (out_dir / filename).write_bytes(img_bytes)
        db.add_generated_image(product_id, f"{product_id}/{filename}", prompt=prompt, parent_id=parent_id)
    return len(image_bytes_list)


@app.route("/products/<int:product_id>/ai-images")
def ai_images(product_id: int):
    product = db.get_product(product_id)
    if not product:
        flash("상품을 찾을 수 없습니다.", "error")
        return redirect(url_for("products"))
    images = db.list_generated_images(product_id)
    return render_template("ai_images.html", product=product, images=images)


@app.route("/products/<int:product_id>/ai-images/generate", methods=["POST"])
def ai_images_generate(product_id: int):
    settings = db.get_settings()
    if not settings.get("openai_api_key"):
        flash("먼저 설정 화면에서 OpenAI API 키를 입력해주세요.", "error")
        return redirect(url_for("setup"))
    product = db.get_product(product_id)
    if not product:
        flash("상품을 찾을 수 없습니다.", "error")
        return redirect(url_for("products"))

    source_url = request.form.get("source_image_url") or product.get("thumbnail_url")
    if not source_url:
        flash("기반으로 삼을 실제 상품 사진이 없습니다. 먼저 '네이버에서 이미지 더 가져오기'로 사진을 가져와주세요.", "error")
        return redirect(url_for("product_detail", product_id=product_id))

    try:
        source_bytes, mime_type = _download_image(source_url)
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("ai_images", product_id=product_id))

    prompt = _build_lifestyle_prompt(product)
    client = openai_client.OpenAIImageClient(api_key=settings["openai_api_key"])
    try:
        images = client.edit(prompt, source_bytes, n=2, mime_type=mime_type)
    except openai_client.OpenAIApiError as e:
        flash(f"이미지 생성 실패: {e}", "error")
        return redirect(url_for("ai_images", product_id=product_id))

    count = _save_generated_images(product_id, images, prompt)
    flash(f"실제 상품 사진을 기반으로 AI 이미지 {count}장을 생성했습니다.", "success")
    return redirect(url_for("ai_images", product_id=product_id))


@app.route("/products/<int:product_id>/ai-images/<int:image_id>/edit", methods=["POST"])
def ai_images_edit(product_id: int, image_id: int):
    direction = request.form.get("direction", "").strip()
    if not direction:
        flash("어떻게 수정할지 방향을 입력해주세요.", "error")
        return redirect(url_for("ai_images", product_id=product_id))

    settings = db.get_settings()
    image = db.get_generated_image(image_id)
    if not image or image["product_id"] != product_id:
        flash("이미지를 찾을 수 없습니다.", "error")
        return redirect(url_for("ai_images", product_id=product_id))

    src_path = GENERATED_IMAGES_DIR / image["file_path"]
    if not src_path.exists():
        flash("원본 이미지 파일을 찾을 수 없습니다.", "error")
        return redirect(url_for("ai_images", product_id=product_id))

    client = openai_client.OpenAIImageClient(api_key=settings["openai_api_key"])
    try:
        results = client.edit(direction, src_path.read_bytes())
    except openai_client.OpenAIApiError as e:
        flash(f"이미지 수정 실패: {e}", "error")
        return redirect(url_for("ai_images", product_id=product_id))

    _save_generated_images(product_id, results, direction, parent_id=image_id)
    flash("수정된 이미지를 새로 추가했습니다 (원본은 그대로 남아있습니다).", "success")
    return redirect(url_for("ai_images", product_id=product_id))


@app.route("/products/<int:product_id>/ai-images/<int:image_id>/delete", methods=["POST"])
def ai_images_delete(product_id: int, image_id: int):
    image = db.get_generated_image(image_id)
    if image and image["product_id"] == product_id:
        file_path = GENERATED_IMAGES_DIR / image["file_path"]
        if file_path.exists():
            file_path.unlink()
        db.delete_generated_image(image_id)
        flash("이미지를 삭제했습니다.", "success")
    return redirect(url_for("ai_images", product_id=product_id))


@app.route("/products/<int:product_id>/ai-images/<int:image_id>/use", methods=["POST"])
def ai_images_use(product_id: int, image_id: int):
    image = db.get_generated_image(image_id)
    product = db.get_product(product_id)
    if not image or not product or image["product_id"] != product_id:
        flash("이미지를 찾을 수 없습니다.", "error")
        return redirect(url_for("ai_images", product_id=product_id))

    local_url = url_for("static", filename=f"generated/{image['file_path']}")
    image_urls = list(product.get("image_urls") or [])
    if local_url not in image_urls:
        image_urls.insert(0, local_url)
    db.update_product(product_id, {"image_urls": image_urls, "thumbnail_url": local_url})
    flash(
        "상품 이미지로 지정했습니다. ⚠️ 지금은 이 컴퓨터에만 있는 로컬 주소라, "
        "실제 Threads 발행(특히 GitHub Actions 예약 발행)에 쓰려면 별도로 공개 호스팅에 "
        "올려야 합니다 — 다음에 필요하시면 안내해드릴게요.",
        "success",
    )
    return redirect(url_for("products"))


@app.route("/products/<int:product_id>/fetch-images", methods=["POST"])
def fetch_images(product_id: int):
    settings = db.get_settings()
    product = db.get_product(product_id)
    if not product:
        flash("상품을 찾을 수 없습니다.", "error")
        return redirect(url_for("products"))
    if not product.get("origin_product_no"):
        flash("네이버 상품이 아니라 원상품 번호가 없어 이미지를 추가로 가져올 수 없습니다.", "error")
        return redirect(url_for("product_detail", product_id=product_id))

    try:
        client = naver_client.NaverCommerceClient(
            client_id=settings["naver_client_id"], client_secret=settings["naver_client_secret"]
        )
        images = client.get_product_images(product["origin_product_no"])
    except naver_client.NaverApiError as e:
        flash(f"이미지 조회 실패: {e}", "error")
        return redirect(url_for("product_detail", product_id=product_id))

    gallery, detail = images["gallery"], images["detail"]
    combined = list(dict.fromkeys(gallery + detail))
    db.update_product(product_id, {"image_urls": combined, "detail_image_urls": detail})
    flash(f"대표/추가 이미지 {len(gallery)}장 + 상세페이지 이미지 {len(detail)}장을 가져왔습니다.", "success")
    return redirect(url_for("product_detail", product_id=product_id))


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


@app.route("/products/<int:product_id>/suggest-selling-points", methods=["POST"])
def suggest_points(product_id: int):
    settings = db.get_settings()
    product_row = db.get_product(product_id)
    if not product_row:
        flash("상품을 찾을 수 없습니다.", "error")
        return redirect(url_for("products"))

    product = Product(raw=product_row)
    reviews = db.list_reviews(product_id) if product_row["mode"] == "review" else []
    client = anthropic.Anthropic(api_key=settings["anthropic_api_key"])

    try:
        points = suggest_selling_points(product=product, reviews=reviews, client=client)
    except Exception as e:  # noqa: BLE001
        flash(f"셀링포인트 추천 실패: {e}", "error")
        return redirect(url_for("product_detail", product_id=product_id))

    db.update_product(product_id, {"key_selling_points": points})
    flash("AI가 추천한 셀링포인트 3개로 채웠습니다. 필요하면 수정 후 저장하세요.", "success")
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
    style_examples = db.list_favorite_posts(limit=5)
    client = anthropic.Anthropic(api_key=settings["anthropic_api_key"])

    try:
        post = generate(persona=persona, product=product, reviews=reviews,
                         recent_records=recent_records, client=client,
                         style_examples=style_examples)
    except Exception as e:  # noqa: BLE001
        flash(f"글 생성 실패: {e}", "error")
        return redirect(url_for("product_detail", product_id=product_id))

    session[f"draft_{product_id}"] = {
        "hook_category": post.hook_category,
        "topic_summary": post.topic_summary,
        "text": post.text,
        "source_review_ids": post.source_review_ids,
        "topic_tag": post.topic_tag,
        "selected_images": [product_row["thumbnail_url"]] if product_row.get("thumbnail_url") else [],
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


@app.route("/products/<int:product_id>/preview/edit-text", methods=["POST"])
def edit_draft_text(product_id: int):
    draft = session.get(f"draft_{product_id}")
    if not draft:
        flash("먼저 글을 생성해주세요.", "error")
        return redirect(url_for("product_detail", product_id=product_id))
    text = request.form.get("text", "").strip()
    if not text:
        flash("본문이 비어 있어 저장하지 않았습니다.", "error")
        return redirect(url_for("preview", product_id=product_id))
    draft["text"] = text
    session[f"draft_{product_id}"] = draft
    flash("본문을 수정했습니다.", "success")
    return redirect(url_for("preview", product_id=product_id))


@app.route("/products/<int:product_id>/preview/select-image", methods=["POST"])
def select_image(product_id: int):
    draft = session.get(f"draft_{product_id}")
    if draft:
        selected = request.form.getlist("image_url")
        if len(selected) > 20:
            flash("이미지는 최대 20장까지 선택할 수 있습니다 (Threads 캐러셀 제한).", "error")
            selected = selected[:20]
        draft["selected_images"] = selected
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
    image_urls = draft.get("selected_images") or [] if request.form.get("use_image") == "on" else []

    has_local_images = any(u.startswith("/static/generated/") for u in image_urls)
    if has_local_images:
        image_urls = [
            _publicize_image_url(f"direct-{product_id}-{i}", u) for i, u in enumerate(image_urls)
        ]
        add = _run_git("add", "data/queue_images")
        if add.returncode != 0:
            flash(f"AI 이미지 공개 업로드 실패(git add): {add.stderr}", "error")
            return redirect(url_for("preview", product_id=product_id))
        commit = _run_git("commit", "-m", f"Publicize AI image for direct publish (product {product_id})")
        if commit.returncode != 0 and "nothing to commit" not in (commit.stdout + commit.stderr):
            flash(f"AI 이미지 공개 업로드 실패(git commit): {commit.stderr}", "error")
            return redirect(url_for("preview", product_id=product_id))
        push = _run_git("push")
        if push.returncode != 0:
            flash(f"AI 이미지 공개 업로드 실패(git push): {push.stderr}", "error")
            return redirect(url_for("preview", product_id=product_id))

    try:
        post_id = client.publish_post(
            draft["text"], image_urls=image_urls, topic_tag=draft.get("topic_tag") or None
        )
        reply_post_id = None
        reply_text = None
        if product["link_placement"] == "reply" and product.get("smartstore_url"):
            reply_text = f"🔗 상품 보러가기\n{product['smartstore_url']}"
            reply_post_id = client.publish_text(reply_text, reply_to_id=post_id)
    except ThreadsApiError as e:
        notify_kakao(f"⚠️ Threads 발행 실패\n상품: {product['name']}\n오류: {e}")
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
            "topic_tag": draft.get("topic_tag"),
        }
    )
    notify_kakao(
        f"✅ Threads 발행 완료\n상품: {product['name']}\n{draft['text'][:80]}",
        web_url=product.get("smartstore_url"),
    )

    if has_local_images:
        for i in range(len(image_urls)):
            for ext in (".png", ".jpg", ".jpeg", ".webp"):
                temp_image = schedule.QUEUE_IMAGES_DIR / f"direct-{product_id}-{i}{ext}"
                if temp_image.exists():
                    temp_image.unlink()
        cleanup_add = _run_git("add", "data/queue_images")
        if cleanup_add.returncode == 0:
            cleanup_commit = _run_git(
                "commit", "-m", f"Clean up direct-publish temp image (product {product_id})"
            )
            if cleanup_commit.returncode == 0:
                _run_git("push")

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


@app.route("/posts/<int:post_id>/favorite", methods=["POST"])
def toggle_post_favorite(post_id: int):
    make_favorite = request.form.get("value") == "1"
    db.set_post_favorite(post_id, make_favorite)
    flash(
        "글 스타일 예시로 즐겨찾기에 추가했습니다." if make_favorite else "즐겨찾기에서 뺐습니다.",
        "success",
    )
    return redirect(request.referrer or url_for("products"))


# --- 예약 발행 대기열 --------------------------------------------------

def _run_git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8"
    )


def _reply_text_for(product_row: dict) -> str | None:
    if product_row["link_placement"] == "reply" and product_row.get("smartstore_url"):
        return f"🔗 상품 보러가기\n{product_row['smartstore_url']}"
    return None


@app.route("/products/<int:product_id>/queue/add", methods=["POST"])
def queue_add(product_id: int):
    settings = db.get_settings()
    product_row = db.get_product(product_id)
    if not product_row:
        flash("상품을 찾을 수 없습니다.", "error")
        return redirect(url_for("products"))

    persona = Persona.load()
    product = Product(raw=product_row)
    reviews = db.list_reviews(product_id) if product_row["mode"] == "review" else []
    recent_records = db.recent_posts(product_id)
    style_examples = db.list_favorite_posts(limit=5)
    client = anthropic.Anthropic(api_key=settings["anthropic_api_key"])

    try:
        post = generate(persona=persona, product=product, reviews=reviews,
                         recent_records=recent_records, client=client,
                         style_examples=style_examples)
    except Exception as e:  # noqa: BLE001
        flash(f"글 생성 실패: {e}", "error")
        return redirect(url_for("product_detail", product_id=product_id))

    db.add_queue_item(
        {
            "product_id": product_id,
            "status": "draft",
            "text": post.text,
            "topic_tag": post.topic_tag,
            "hook_category": post.hook_category,
            "topic_summary": post.topic_summary,
            "image_url": product_row.get("thumbnail_url"),
            "reply_text": _reply_text_for(product_row),
            "source_review_ids": post.source_review_ids,
        }
    )
    flash("대기열에 초안을 추가했습니다. 검토 후 승인해주세요.", "success")
    return redirect(url_for("queue_list"))


@app.route("/queue")
def queue_list():
    items = db.list_queue_items()
    settings = db.get_settings()
    try:
        windows = json.loads(settings.get("schedule_windows") or "{}")
    except json.JSONDecodeError:
        windows = {}
    windows = {**schedule.DEFAULT_SCHEDULE_SETTINGS, **windows}

    ready_ordered = sorted(
        (i for i in items if i["status"] == "ready"), key=lambda i: i["created_at"]
    )
    slots = schedule.upcoming_window_starts(windows, len(ready_ordered))
    eta_by_id = {
        item["id"]: f"{dt.strftime('%m/%d')} {schedule.WINDOW_LABELS[name]} 무렵"
        for item, (name, dt) in zip(ready_ordered, slots)
    }

    return render_template("queue.html", items=items, windows=windows, eta_by_id=eta_by_id)


@app.route("/queue/settings", methods=["POST"])
def queue_settings():
    windows = {
        "morning": request.form.get("morning") == "on",
        "lunch": request.form.get("lunch") == "on",
        "afternoon": request.form.get("afternoon") == "on",
        "evening": request.form.get("evening") == "on",
    }
    db.update_settings({"schedule_windows": json.dumps(windows, ensure_ascii=False)})
    flash("시간대 설정을 저장했습니다.", "success")
    return redirect(url_for("queue_list"))


@app.route("/queue/<int:item_id>/edit", methods=["POST"])
def queue_edit(item_id: int):
    text = request.form.get("text", "").strip()
    if not text:
        flash("본문이 비어 있어 저장하지 않았습니다.", "error")
        return redirect(url_for("queue_list"))
    db.update_queue_item(item_id, {"text": text, "status": "draft"})
    flash("텍스트를 저장했습니다. 다시 검토 후 승인해주세요.", "success")
    return redirect(url_for("queue_list"))


@app.route("/queue/<int:item_id>/approve", methods=["POST"])
def queue_approve(item_id: int):
    db.update_queue_item(item_id, {"status": "ready"})
    flash("승인했습니다. 'GitHub에 반영'을 눌러야 실제 예약 발행 대상이 됩니다.", "success")
    return redirect(url_for("queue_list"))


@app.route("/queue/<int:item_id>/regenerate", methods=["POST"])
def queue_regenerate(item_id: int):
    item = db.get_queue_item(item_id)
    if not item:
        flash("항목을 찾을 수 없습니다.", "error")
        return redirect(url_for("queue_list"))

    settings = db.get_settings()
    product_row = db.get_product(item["product_id"])
    persona = Persona.load()
    product = Product(raw=product_row)
    reviews = db.list_reviews(item["product_id"]) if product_row["mode"] == "review" else []
    recent_records = db.recent_posts(item["product_id"])
    style_examples = db.list_favorite_posts(limit=5)
    client = anthropic.Anthropic(api_key=settings["anthropic_api_key"])

    try:
        post = generate(persona=persona, product=product, reviews=reviews,
                         recent_records=recent_records, client=client,
                         style_examples=style_examples)
    except Exception as e:  # noqa: BLE001
        flash(f"재생성 실패: {e}", "error")
        return redirect(url_for("queue_list"))

    db.update_queue_item(
        item_id,
        {
            "text": post.text,
            "topic_tag": post.topic_tag,
            "hook_category": post.hook_category,
            "topic_summary": post.topic_summary,
            "source_review_ids": post.source_review_ids,
            "status": "draft",
        },
    )
    flash("다시 생성했습니다. 검토 후 다시 승인해주세요.", "success")
    return redirect(url_for("queue_list"))


@app.route("/queue/<int:item_id>/delete", methods=["POST"])
def queue_delete(item_id: int):
    db.delete_queue_item(item_id)
    flash("대기열에서 삭제했습니다.", "success")
    return redirect(url_for("queue_list"))


def _publicize_image_url(item_id: int, image_url: str | None) -> str | None:
    """상품 이미지가 이 컴퓨터에만 있는 AI 생성 이미지(/static/generated/...)라면,
    Threads/GitHub Actions가 읽을 수 있도록 data/queue_images/에 복사해 GitHub에 커밋될
    공개 raw.githubusercontent.com 주소로 바꿔준다. 발행이 끝나면 scheduled_publish.py가
    이 사본을 다시 지운다 (저장소에 이미지가 계속 쌓이지 않도록)."""
    if not image_url or not image_url.startswith("/static/generated/"):
        return image_url
    local_path = REPO_ROOT / "webapp" / image_url.lstrip("/")
    if not local_path.exists():
        return image_url

    schedule.QUEUE_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    dest_path = schedule.QUEUE_IMAGES_DIR / f"{item_id}{local_path.suffix or '.png'}"
    dest_path.write_bytes(local_path.read_bytes())
    return schedule.raw_github_url(f"data/queue_images/{dest_path.name}") or image_url


@app.route("/queue/sync-to-github", methods=["POST"])
def queue_sync_to_github():
    ready_items = sorted(
        (i for i in db.list_queue_items() if i["status"] == "ready"),
        key=lambda i: i["created_at"],
    )
    if not ready_items:
        flash("GitHub에 반영할 승인된(ready) 항목이 없습니다.", "error")
        return redirect(url_for("queue_list"))

    queue_export = [
        {
            "id": item["id"],
            "product_id": item["product_id"],
            "text": item["text"],
            "topic_tag": item["topic_tag"],
            "hook_category": item["hook_category"],
            "topic_summary": item["topic_summary"],
            "image_url": _publicize_image_url(item["id"], item["image_url"]),
            "reply_text": item["reply_text"],
            "source_review_ids": item["source_review_ids"],
        }
        for item in ready_items
    ]
    schedule.save_queue(queue_export)

    settings = db.get_settings()
    try:
        windows = json.loads(settings.get("schedule_windows") or "{}")
    except json.JSONDecodeError:
        windows = {}
    schedule.save_schedule_settings({**schedule.DEFAULT_SCHEDULE_SETTINGS, **windows})

    add = _run_git("add", "data/queue.json", "data/schedule_settings.json", "data/queue_images")
    if add.returncode != 0:
        flash(f"git add 실패: {add.stderr}", "error")
        return redirect(url_for("queue_list"))
    commit = _run_git("commit", "-m", f"Update schedule queue ({len(queue_export)}건)")
    if commit.returncode != 0 and "nothing to commit" not in (commit.stdout + commit.stderr):
        flash(f"git commit 실패: {commit.stderr}", "error")
        return redirect(url_for("queue_list"))
    push = _run_git("push")
    if push.returncode != 0:
        flash(f"git push 실패: {push.stderr}", "error")
        return redirect(url_for("queue_list"))

    flash(f"GitHub에 {len(queue_export)}건 반영했습니다. 설정한 시간대에 랜덤 발행됩니다.", "success")
    return redirect(url_for("queue_list"))


@app.route("/queue/pull-from-github", methods=["POST"])
def queue_pull_from_github():
    pull = _run_git("pull")
    if pull.returncode != 0:
        flash(f"git pull 실패: {pull.stderr}", "error")
        return redirect(url_for("queue_list"))

    history = schedule.load_json(schedule.HISTORY_PATH, [])
    imported = 0
    for entry in history:
        item_id = entry.get("queue_item_id")
        if item_id is None:
            continue
        item = db.get_queue_item(item_id)
        if not item or item["status"] == "published":
            continue
        db.add_post(
            {
                "product_id": item["product_id"],
                "timestamp": entry["published_at"],
                "hook_category": item["hook_category"],
                "topic_summary": item["topic_summary"],
                "text": item["text"],
                "reply_text": item["reply_text"],
                "post_id": entry.get("post_id"),
                "reply_post_id": entry.get("reply_post_id"),
                "source_review_ids": item["source_review_ids"],
                "topic_tag": item["topic_tag"],
            }
        )
        db.update_queue_item(
            item_id,
            {
                "status": "published",
                "published_at": entry["published_at"],
                "post_id": entry.get("post_id"),
                "reply_post_id": entry.get("reply_post_id"),
            },
        )
        imported += 1

    flash(f"GitHub에서 결과를 가져왔습니다 ({imported}건 새로 반영).", "success")
    return redirect(url_for("queue_list"))


def _open_browser(port: int) -> None:
    webbrowser.open(f"http://127.0.0.1:{port}")


if __name__ == "__main__":
    db.init_db()
    port = int(os.environ.get("WEBAPP_PORT", "8765"))
    threading.Timer(1.0, _open_browser, args=(port,)).start()
    app.run(host="127.0.0.1", port=port, debug=False)
