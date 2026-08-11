#!/usr/bin/env python
"""GitHub Actions에서 실행되는 예약 발행 스크립트.

로컬 대시보드에서 미리 만들어둔(승인된) 글을 data/queue.json에서 하나 꺼내,
설정된 시간대(data/schedule_settings.json) 안의 랜덤한 시각까지 대기했다가
Threads에 그대로 발행한다. Claude API는 호출하지 않는다 (텍스트는 이미 확정본).
"""
from __future__ import annotations

import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from threads_bot import kakao_client, schedule  # noqa: E402
from threads_bot.threads_client import ThreadsApiError, ThreadsClient  # noqa: E402


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

    window = schedule.current_window()
    if not force:
        if window is None:
            print("[skip] 지금은 설정된 시간대(아침/점심/저녁) 밖입니다.")
            return 0
        settings = schedule.load_schedule_settings()
        if not settings.get(window):
            print(f"[skip] '{window}' 시간대는 비활성화되어 있습니다.")
            return 0
    else:
        print("[force] 시간대/대기 없이 즉시 발행 모드입니다 (테스트용).")
        window = window or "force"

    queue = schedule.load_queue()
    if not queue:
        print("[skip] 대기열이 비어 있습니다.")
        return 0

    item = queue[0]
    print(f"[selected] queue_item_id={item['id']} product_id={item['product_id']}")

    if force:
        print("[wait] force 모드라 대기 없이 바로 발행합니다.")
    else:
        remaining = schedule.seconds_remaining_in_window(window)
        delay = random.uniform(0, remaining)
        print(f"[wait] '{window}' 시간대 안에서 {delay:.0f}초 대기 후 발행합니다.")
        time.sleep(delay)

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
    _notify_kakao(f"✅ 예약 발행 완료 ('{window}' 시간대)\n{item['text'][:80]}")

    schedule.save_queue(queue[1:])
    schedule.append_history(
        {
            "queue_item_id": item["id"],
            "product_id": item["product_id"],
            "window": window,
            "published_at": datetime.now(timezone.utc).isoformat(),
            "post_id": post_id,
            "reply_post_id": reply_post_id,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
