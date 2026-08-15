#!/usr/bin/env python
"""GitHub Actions에서 자주(예: 15분마다) 실행되는 예약 발행 스크립트.

로컬 대시보드에서 미리 만들어둔(승인된) 글을 data/queue.json에서 하나 꺼내, 설정된
시간대(data/schedule_settings.json) 안에서 그날그날 정해지는 목표 시각이 지나면 Threads에
그대로 발행한다. Claude API는 호출하지 않는다 (텍스트는 이미 확정본).

GitHub Actions의 schedule(cron) 트리거는 몇 시간씩 지연될 수 있어서, 한 번의 실행 안에서
sleep으로 목표 시각까지 대기하지 않는다. 대신 자주 깨어나서 "지금이 목표 시각을 지났는가"만
짧게 확인한다 (목표 시각은 날짜+시간대로 결정되므로 여러 번 실행돼도 항상 같다).
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from threads_bot import instagram_client, kakao_client, schedule  # noqa: E402
from threads_bot.threads_client import ThreadsApiError, ThreadsClient  # noqa: E402


def _publish_instagram(item: dict, image_urls: list[str]) -> str | None:
    """Threads 발행이 끝난 뒤 Instagram도 함께 예약된 항목이면 발행한다.
    실패해도 이미 성공한 Threads 발행에는 영향을 주지 않고 조용히 넘어간다."""
    if not item.get("publish_instagram") or not image_urls:
        return None
    access_token = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
    ig_user_id = os.environ.get("INSTAGRAM_BUSINESS_ID")
    if not access_token or not ig_user_id:
        print("[instagram] INSTAGRAM_ACCESS_TOKEN/INSTAGRAM_BUSINESS_ID 미설정, 건너뜁니다.")
        return None
    try:
        client = instagram_client.InstagramClient(access_token=access_token, ig_user_id=ig_user_id)
        caption = item.get("instagram_caption") or item["text"]
        ig_post_id = client.publish_post(caption, image_urls)
        if item.get("reply_text"):
            client.comment(ig_post_id, item["reply_text"])
        print(f"[instagram] 발행 완료 post_id={ig_post_id}")
        return ig_post_id
    except instagram_client.InstagramApiError as e:
        print(f"[instagram] 발행 실패(무시, Threads 발행은 유지됨): {e}")
        return None


def _select_queue_item(queue: list[dict], today: str) -> dict | None:
    """대기열 순서대로, 오늘(today, KST 기준 YYYY-MM-DD) 발행 가능한 첫 항목을 고른다.
    scheduled_date가 없거나 오늘이거나 이미 지난 날짜(놓친 경우 그냥 지금 발행)인 항목만
    대상이고, 아직 오지 않은 미래 날짜로 지정된 항목은 그 날짜가 될 때까지 건너뛴다."""
    for item in queue:
        d = item.get("scheduled_date")
        if not d or d <= today:
            return item
    return None


def _notify_kakao(text: str) -> None:
    """KAKAO_* 시크릿이 설정돼 있으면 카카오톡 '나에게 보내기'로 알린다.
    설정 안 돼 있거나 실패해도 조용히 넘어간다 (알림 때문에 발행 자체가 실패로 처리되면 안 됨)."""
    client_id = os.environ.get("KAKAO_CLIENT_ID")
    client_secret = os.environ.get("KAKAO_CLIENT_SECRET", "")
    refresh_token = os.environ.get("KAKAO_REFRESH_TOKEN")
    if not client_id or not refresh_token:
        return
    try:
        data = kakao_client.refresh_access_token(client_id, client_secret, refresh_token)
        kakao_client.KakaoClient(access_token=data["access_token"]).send_text_to_me(text)
        print("[kakao] 알림 발송 완료")
    except kakao_client.KakaoApiError as e:
        print(f"[kakao] 알림 발송 실패(무시): {e}")


def main() -> int:
    force = os.environ.get("FORCE_PUBLISH", "").strip().lower() == "true"
    now = datetime.now(schedule.KST)

    if force:
        window = schedule.current_window(now) or "force"
        print("[force] 시간대/목표 시각 확인 없이 즉시 발행 모드입니다 (테스트용).")
    else:
        window = schedule.current_window(now)
        if window is None:
            print("[skip] 지금은 설정된 시간대(아침/점심/오후/저녁) 밖입니다.")
            return 0

        settings = schedule.load_schedule_settings()
        if not settings.get(window):
            print(f"[skip] '{window}' 시간대는 비활성화되어 있습니다.")
            return 0

        history = schedule.load_json(schedule.HISTORY_PATH, [])
        if schedule.published_today_for_window(window, history, now):
            print(f"[skip] 오늘 '{window}' 시간대에는 이미 발행했습니다.")
            return 0

        target = schedule.target_time_in_window(window, now)
        if now < target:
            print(f"[skip] '{window}' 목표 시각({target.strftime('%H:%M:%S')}) 전입니다 (지금 {now.strftime('%H:%M:%S')}).")
            return 0
        print(f"[ready] '{window}' 목표 시각({target.strftime('%H:%M:%S')})을 지났습니다 -> 발행 진행")

    queue = schedule.load_queue()
    if not queue:
        print("[skip] 대기열이 비어 있습니다.")
        return 0

    item = _select_queue_item(queue, now.date().isoformat())
    if item is None:
        print("[skip] 대기열에 오늘 발행 가능한 항목이 없습니다 (모두 미래 날짜로 예약됨).")
        return 0
    print(f"[selected] queue_item_id={item['id']} product_id={item['product_id']}")

    client = ThreadsClient(
        access_token=os.environ["THREADS_ACCESS_TOKEN"],
        user_id=os.environ["THREADS_USER_ID"],
    )
    image_urls = [item["image_url"]] if item.get("image_url") else []

    try:
        post_id = client.publish_post(
            item["text"], image_urls=image_urls, topic_tag=item.get("topic_tag") or None
        )
        reply_post_id = None
        if item.get("reply_text"):
            reply_post_id = client.publish_text(item["reply_text"], reply_to_id=post_id)
    except ThreadsApiError as e:
        print(f"[error] 발행 실패: {e}")
        _notify_kakao(f"⚠️ 예약 발행 실패\nqueue_item_id={item['id']}\n오류: {e}")
        return 1

    print(f"[published] post_id={post_id} reply_post_id={reply_post_id}")
    instagram_post_id = _publish_instagram(item, image_urls)
    kakao_note = f"✅ 예약 발행 완료 ('{window}' 시간대)\n{item['text'][:80]}"
    if instagram_post_id:
        kakao_note += "\n📸 Instagram에도 함께 발행됨"
    _notify_kakao(kakao_note)

    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        temp_image = schedule.QUEUE_IMAGES_DIR / f"{item['id']}{ext}"
        if temp_image.exists():
            temp_image.unlink()
            print(f"[cleanup] {temp_image} 삭제 (발행 완료, 더 이상 공개 호스팅 불필요)")

    schedule.save_queue([i for i in queue if i["id"] != item["id"]])
    schedule.append_history(
        {
            "queue_item_id": item["id"],
            "product_id": item["product_id"],
            "window": window,
            "published_at": datetime.now(timezone.utc).isoformat(),
            "post_id": post_id,
            "reply_post_id": reply_post_id,
            "instagram_post_id": instagram_post_id,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
