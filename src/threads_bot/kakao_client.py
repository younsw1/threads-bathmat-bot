from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import requests

AUTHORIZE_URL = "https://kauth.kakao.com/oauth/authorize"
TOKEN_URL = "https://kauth.kakao.com/oauth/token"
SEND_TO_ME_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"


class KakaoApiError(RuntimeError):
    pass


def _raise_for_error(resp: requests.Response) -> None:
    if resp.status_code >= 400:
        raise KakaoApiError(f"카카오 API 오류 {resp.status_code}: {resp.text}")


def build_authorize_url(client_id: str, redirect_uri: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "talk_message",
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def exchange_code_for_token(
    client_id: str, client_secret: str, redirect_uri: str, code: str
) -> dict[str, Any]:
    resp = requests.post(
        TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"},
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "code": code,
        },
        timeout=30,
    )
    _raise_for_error(resp)
    return resp.json()  # {"access_token", "refresh_token", "expires_in", "refresh_token_expires_in", ...}


def refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> dict[str, Any]:
    resp = requests.post(
        TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"},
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        },
        timeout=30,
    )
    _raise_for_error(resp)
    return resp.json()  # {"access_token", "expires_in", "refresh_token"?(있을 때만), ...}


@dataclass
class KakaoClient:
    access_token: str

    def send_text_to_me(self, text: str, web_url: str | None = None) -> dict[str, Any]:
        text = text[:200]  # 카카오 텍스트 템플릿 최대 200자
        template_object: dict[str, Any] = {"object_type": "text", "text": text}
        if web_url:
            template_object["link"] = {"web_url": web_url, "mobile_web_url": web_url}
            template_object["button_title"] = "확인하기"
        resp = requests.post(
            SEND_TO_ME_URL,
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
            },
            data={"template_object": _to_json(template_object)},
            timeout=30,
        )
        _raise_for_error(resp)
        return resp.json()


def _to_json(obj: dict[str, Any]) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)
