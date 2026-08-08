#!/usr/bin/env python
"""쓰레드 자동 발행 엔트리포인트.

사용법:
  python scripts/publish.py --dry-run    # Claude로 글만 생성하고 출력, 실제 발행 안 함
  python scripts/publish.py              # 글 생성 + 실제 Threads 발행 + 이력 기록
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from threads_bot import history, reviews  # noqa: E402
from threads_bot.content_generator import generate  # noqa: E402
from threads_bot.persona import Persona  # noqa: E402
from threads_bot.product import Product  # noqa: E402
from threads_bot.threads_client import ThreadsClient  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Threads에 실제로 발행하지 않고 생성 결과만 출력합니다.",
    )
    args = parser.parse_args()

    persona = Persona.load()
    product = Product.load()
    recent_records = history.recent()
    review_sample = reviews.sample(exclude_ids=history.recent_review_ids())

    post = generate(
        persona=persona,
        product=product,
        reviews=review_sample,
        recent_records=recent_records,
    )

    print("=" * 60)
    print(f"[hook_category] {post.hook_category}")
    print(f"[topic_summary] {post.topic_summary}")
    print(f"[source_review_ids] {post.source_review_ids}")
    print(f"[length] {len(post.text)}자")
    print("-" * 60)
    print(post.text)
    print("=" * 60)
    reply_text = product.reply_link_text()
    print("[reply] 본문 발행 직후 아래 내용으로 답글이 달립니다:")
    print(reply_text)
    print("=" * 60)

    post_id = None
    if not args.dry_run:
        client = ThreadsClient(
            access_token=os.environ["THREADS_ACCESS_TOKEN"],
            user_id=os.environ["THREADS_USER_ID"],
        )
        limit = client.get_publishing_limit()
        print(f"[publishing_limit] {limit}")

        post_id = client.publish_text(post.text)
        print(f"[published] post_id={post_id}")

        reply_id = client.publish_text(reply_text, reply_to_id=post_id)
        print(f"[published reply] reply_id={reply_id}")

        history.append(
            history.PostRecord(
                timestamp=history.now_iso(),
                hook_category=post.hook_category,
                topic_summary=post.topic_summary,
                text=post.text,
                post_id=post_id,
                source_review_ids=post.source_review_ids,
            )
        )
    else:
        print("[dry-run] 실제 발행 및 이력 기록은 건너뜁니다.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
