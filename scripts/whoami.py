#!/usr/bin/env python
"""THREADS_ACCESS_TOKEN으로 본인 Threads user_id/username을 조회한다.
토큰 값 자체는 출력하지 않는다.
"""
from __future__ import annotations

import os
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")

GRAPH_BASE = "https://graph.threads.net/v1.0"


def main() -> int:
    token = os.environ["THREADS_ACCESS_TOKEN"]
    resp = requests.get(
        f"{GRAPH_BASE}/me",
        params={"fields": "id,username", "access_token": token},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    print(f"id={data['id']}")
    print(f"username={data.get('username')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
