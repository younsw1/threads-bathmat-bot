from __future__ import annotations

from dataclasses import dataclass

import requests

GRAPH_BASE = "https://graph.threads.net/v1.0"
OAUTH_AUTHORIZE_URL = "https://threads.net/oauth/authorize"
OAUTH_TOKEN_URL = "https://graph.threads.net/oauth/access_token"
EXCHANGE_TOKEN_URL = "https://graph.threads.net/access_token"
REFRESH_TOKEN_URL = "https://graph.threads.net/refresh_access_token"

TEXT_MAX_LEN = 500


class ThreadsApiError(RuntimeError):
    pass


def _raise_for_error(resp: requests.Response) -> None:
    if resp.status_code >= 400:
        raise ThreadsApiError(f"Threads API error {resp.status_code}: {resp.text}")


@dataclass
class ThreadsClient:
    access_token: str
    user_id: str

    def get_publishing_limit(self) -> dict:
        resp = requests.get(
            f"{GRAPH_BASE}/{self.user_id}/threads_publishing_limit",
            params={
                "fields": "quota_usage,config",
                "access_token": self.access_token,
            },
            timeout=30,
        )
        _raise_for_error(resp)
        return resp.json()

    def create_container(self, text: str) -> str:
        if len(text) > TEXT_MAX_LEN:
            raise ValueError(f"본문이 {TEXT_MAX_LEN}자를 초과합니다 ({len(text)}자).")
        resp = requests.post(
            f"{GRAPH_BASE}/{self.user_id}/threads",
            data={
                "media_type": "TEXT",
                "text": text,
                "access_token": self.access_token,
            },
            timeout=30,
        )
        _raise_for_error(resp)
        return resp.json()["id"]

    def publish(self, creation_id: str) -> str:
        resp = requests.post(
            f"{GRAPH_BASE}/{self.user_id}/threads_publish",
            data={
                "creation_id": creation_id,
                "access_token": self.access_token,
            },
            timeout=30,
        )
        _raise_for_error(resp)
        return resp.json()["id"]

    def publish_text(self, text: str) -> str:
        """컨테이너 생성 후 즉시 발행까지 한번에 수행."""
        creation_id = self.create_container(text)
        return self.publish(creation_id)


def build_authorize_url(client_id: str, redirect_uri: str, scope: str = "threads_basic,threads_content_publish") -> str:
    from urllib.parse import urlencode

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "response_type": "code",
    }
    return f"{OAUTH_AUTHORIZE_URL}?{urlencode(params)}"


def exchange_code_for_short_lived_token(
    client_id: str, client_secret: str, redirect_uri: str, code: str
) -> dict:
    resp = requests.post(
        OAUTH_TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
            "code": code,
        },
        timeout=30,
    )
    _raise_for_error(resp)
    return resp.json()  # {"access_token": ..., "user_id": ...}


def exchange_for_long_lived_token(client_secret: str, short_lived_token: str) -> dict:
    resp = requests.get(
        EXCHANGE_TOKEN_URL,
        params={
            "grant_type": "th_exchange_token",
            "client_secret": client_secret,
            "access_token": short_lived_token,
        },
        timeout=30,
    )
    _raise_for_error(resp)
    return resp.json()  # {"access_token": ..., "token_type": "bearer", "expires_in": 5184000}


def refresh_long_lived_token(current_token: str) -> dict:
    resp = requests.get(
        REFRESH_TOKEN_URL,
        params={
            "grant_type": "th_refresh_token",
            "access_token": current_token,
        },
        timeout=30,
    )
    _raise_for_error(resp)
    return resp.json()  # {"access_token": ..., "token_type": "bearer", "expires_in": 5184000}
