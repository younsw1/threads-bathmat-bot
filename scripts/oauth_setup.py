#!/usr/bin/env python
"""최초 1회 실행하는 Threads OAuth 설정 도우미.

절차:
  1. 이 스크립트를 --client-id --client-secret --redirect-uri 와 함께 실행
  2. 출력된 인증 URL을 브라우저에서 열고 로그인/동의
  3. 리다이렉트된 URL(?code=... 포함)을 콘솔에 붙여넣기
  4. 단기 토큰 -> 장기 토큰(60일)으로 교환한 결과가 출력됨
     -> THREADS_ACCESS_TOKEN, THREADS_USER_ID를 GitHub Secrets에 등록
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from threads_bot.threads_client import (  # noqa: E402
    build_authorize_url,
    exchange_code_for_short_lived_token,
    exchange_for_long_lived_token,
)


def extract_code(pasted: str) -> str:
    pasted = pasted.strip()
    if pasted.startswith("http"):
        query = parse_qs(urlparse(pasted).query)
        if "code" not in query:
            raise ValueError("붙여넣은 URL에 code 파라미터가 없습니다.")
        return query["code"][0]
    return pasted


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--client-id", required=True, help="Meta Developer 앱의 Threads App ID")
    parser.add_argument("--client-secret", required=True, help="Meta Developer 앱의 Threads App Secret")
    parser.add_argument("--redirect-uri", required=True, help="앱에 등록한 Redirect URI (예: https://localhost/callback)")
    args = parser.parse_args()

    auth_url = build_authorize_url(client_id=args.client_id, redirect_uri=args.redirect_uri)
    print("아래 URL을 브라우저에서 열고 로그인/동의하세요:\n")
    print(auth_url)
    print()

    pasted = input("동의 후 리다이렉트된 전체 URL(또는 code 값)을 붙여넣으세요: ")
    code = extract_code(pasted)

    short_lived = exchange_code_for_short_lived_token(
        client_id=args.client_id,
        client_secret=args.client_secret,
        redirect_uri=args.redirect_uri,
        code=code,
    )
    print(f"\n[단기 토큰 발급 완료] user_id={short_lived.get('user_id')}")

    long_lived = exchange_for_long_lived_token(
        client_secret=args.client_secret,
        short_lived_token=short_lived["access_token"],
    )

    print("\n" + "=" * 60)
    print("아래 값을 GitHub Secrets에 등록하세요:")
    print(f"  THREADS_ACCESS_TOKEN = {long_lived['access_token']}")
    print(f"  THREADS_USER_ID      = {short_lived.get('user_id')}")
    print(f"  (만료까지 약 {long_lived.get('expires_in', 0) // 86400}일 남음. "
          "refresh_token.yml 워크플로우가 자동 갱신합니다.)")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
