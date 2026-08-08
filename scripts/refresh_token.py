#!/usr/bin/env python
"""장기 Threads 액세스 토큰을 갱신하고 GitHub Secret에 반영한다.

GitHub Actions의 refresh_token.yml에서 주기적으로 실행된다.
필요 환경변수:
  THREADS_ACCESS_TOKEN  - 현재 장기 토큰 (24시간 이상 지났고 아직 만료 전이어야 갱신 가능)
  GH_PAT                - repo 시크릿을 쓸 수 있는 GitHub Personal Access Token
  GITHUB_REPOSITORY      - "owner/repo" (GitHub Actions에서 자동 제공)
"""
from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

import requests
from nacl import encoding, public

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from threads_bot.threads_client import refresh_long_lived_token  # noqa: E402

GITHUB_API = "https://api.github.com"
SECRET_NAME = "THREADS_ACCESS_TOKEN"


def _encrypt_secret(public_key_b64: str, secret_value: str) -> str:
    public_key = public.PublicKey(public_key_b64.encode("utf-8"), encoding.Base64Encoder())
    sealed_box = public.SealedBox(public_key)
    encrypted = sealed_box.encrypt(secret_value.encode("utf-8"))
    return base64.b64encode(encrypted).decode("utf-8")


def update_github_secret(repo: str, pat: str, name: str, value: str) -> None:
    headers = {
        "Authorization": f"Bearer {pat}",
        "Accept": "application/vnd.github+json",
    }
    key_resp = requests.get(
        f"{GITHUB_API}/repos/{repo}/actions/secrets/public-key", headers=headers, timeout=30
    )
    key_resp.raise_for_status()
    key_data = key_resp.json()

    encrypted_value = _encrypt_secret(key_data["key"], value)

    put_resp = requests.put(
        f"{GITHUB_API}/repos/{repo}/actions/secrets/{name}",
        headers=headers,
        json={"encrypted_value": encrypted_value, "key_id": key_data["key_id"]},
        timeout=30,
    )
    put_resp.raise_for_status()


def main() -> int:
    current_token = os.environ["THREADS_ACCESS_TOKEN"]
    result = refresh_long_lived_token(current_token)
    new_token = result["access_token"]
    expires_in_days = result.get("expires_in", 0) // 86400
    print(f"[refresh] 새 토큰 발급 완료, 만료까지 약 {expires_in_days}일 남음")

    update_github_secret(
        repo=os.environ["GITHUB_REPOSITORY"],
        pat=os.environ["GH_PAT"],
        name=SECRET_NAME,
        value=new_token,
    )
    print(f"[refresh] GitHub Secret '{SECRET_NAME}' 갱신 완료")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
