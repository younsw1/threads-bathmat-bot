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

from threads_bot import schedule  # noqa: E402
from threads_bot.threads_client import ThreadsApiError, ThreadsClient  # noqa: E402


def main() -> int:
    window = schedule.current_window()
    if window is None:
        print("[skip] 지금은 설정된 시간대(아침/점심/저녁) 밖입니다.")
        return 0

    settings = schedule.load_schedule_settings()
    if not settings.get(window):
        print(f"[skip] '{window}' 시간대는 비활성화되어 있습니다.")
        return 0

    queue = schedule.load_queue()
    if not queue:
        print("[skip] 대기열이 비어 있습니다.")
        return 0

    item = queue[0]
    print(f"[selected] queue_item_id={item['id']} product_id={item['product_id']}")

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
        return 1

    print(f"[published] post_id={post_id} reply_post_id={reply_post_id}")

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
