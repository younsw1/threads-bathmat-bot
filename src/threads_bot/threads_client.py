from __future__ import annotations

import time
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

    def create_container(
        self,
        text: str,
        reply_to_id: str | None = None,
        image_url: str | None = None,
        topic_tag: str | None = None,
    ) -> str:
        if len(text) > TEXT_MAX_LEN:
            raise ValueError(f"본문이 {TEXT_MAX_LEN}자를 초과합니다 ({len(text)}자).")
        data = {
            "media_type": "IMAGE" if image_url else "TEXT",
            "text": text,
            "access_token": self.access_token,
        }
        if image_url:
            data["image_url"] = image_url
        if reply_to_id:
            data["reply_to_id"] = reply_to_id
        if topic_tag:
            data["topic_tag"] = topic_tag
        resp = requests.post(
            f"{GRAPH_BASE}/{self.user_id}/threads",
            data=data,
            timeout=30,
        )
        _raise_for_error(resp)
        return resp.json()["id"]

    def create_carousel_item(self, image_url: str) -> str:
        """캐러셀에 들어갈 이미지 1장을 캐러셀 아이템 컨테이너로 만든다."""
        resp = requests.post(
            f"{GRAPH_BASE}/{self.user_id}/threads",
            data={
                "media_type": "IMAGE",
                "image_url": image_url,
                "is_carousel_item": "true",
                "access_token": self.access_token,
            },
            timeout=30,
        )
        _raise_for_error(resp)
        return resp.json()["id"]

    def create_carousel_container(
        self,
        item_ids: list[str],
        text: str,
        reply_to_id: str | None = None,
        topic_tag: str | None = None,
    ) -> str:
        if len(text) > TEXT_MAX_LEN:
            raise ValueError(f"본문이 {TEXT_MAX_LEN}자를 초과합니다 ({len(text)}자).")
        data = {
            "media_type": "CAROUSEL",
            "children": ",".join(item_ids),
            "text": text,
            "access_token": self.access_token,
        }
        if reply_to_id:
            data["reply_to_id"] = reply_to_id
        if topic_tag:
            data["topic_tag"] = topic_tag
        resp = requests.post(
            f"{GRAPH_BASE}/{self.user_id}/threads",
            data=data,
            timeout=30,
        )
        _raise_for_error(resp)
        return resp.json()["id"]

    def wait_until_container_ready(
        self, creation_id: str, timeout: float = 60.0, interval: float = 3.0
    ) -> None:
        """컨테이너 생성 직후 바로 publish하면 아직 Meta 서버에 전파(indexing)되기 전이라
        'media not found'(code 24)로 실패하는 경우가 있다. 공식 문서 권장대로 상태가
        FINISHED가 될 때까지 재시도한다 (조회 자체가 실패해도 propagation 지연일 수 있으므로
        타임아웃 전까지는 포기하지 않는다)."""
        time.sleep(2.0)  # 생성 직후 최소 지연
        deadline = time.monotonic() + timeout
        last_error: str | None = None
        while time.monotonic() < deadline:
            resp = requests.get(
                f"{GRAPH_BASE}/{creation_id}",
                params={"fields": "status,error_message", "access_token": self.access_token},
                timeout=30,
            )
            if resp.status_code >= 400:
                last_error = resp.text
                time.sleep(interval)
                continue
            data = resp.json()
            status = data.get("status")
            if status in (None, "FINISHED"):
                return
            if status in ("ERROR", "EXPIRED"):
                raise ThreadsApiError(f"컨테이너 처리 실패: {data}")
            last_error = f"status={status}"
            time.sleep(interval)
        raise ThreadsApiError(
            f"컨테이너 처리 대기 시간 초과 (creation_id={creation_id}, 마지막 상태: {last_error})"
        )

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

    def publish_text(
        self,
        text: str,
        reply_to_id: str | None = None,
        image_url: str | None = None,
        topic_tag: str | None = None,
    ) -> str:
        """컨테이너 생성 -> 처리 완료 대기 -> 발행까지 한번에 수행 (텍스트/이미지 1장)."""
        creation_id = self.create_container(
            text, reply_to_id=reply_to_id, image_url=image_url, topic_tag=topic_tag
        )
        self.wait_until_container_ready(creation_id)
        return self.publish(creation_id)

    def publish_carousel(
        self,
        text: str,
        image_urls: list[str],
        reply_to_id: str | None = None,
        topic_tag: str | None = None,
    ) -> str:
        """이미지 2~20장을 캐러셀로 발행한다."""
        if not (2 <= len(image_urls) <= 20):
            raise ValueError(f"캐러셀은 이미지 2~20장이 필요합니다 (받은 개수: {len(image_urls)}).")
        item_ids = []
        for url in image_urls:
            item_id = self.create_carousel_item(url)
            self.wait_until_container_ready(item_id)
            item_ids.append(item_id)
        creation_id = self.create_carousel_container(
            item_ids, text, reply_to_id=reply_to_id, topic_tag=topic_tag
        )
        self.wait_until_container_ready(creation_id)
        return self.publish(creation_id)

    def publish_post(
        self,
        text: str,
        image_urls: list[str] | None = None,
        reply_to_id: str | None = None,
        topic_tag: str | None = None,
    ) -> str:
        """이미지 개수에 따라 텍스트/단일 이미지/캐러셀 중 알맞은 방식으로 발행한다."""
        image_urls = image_urls or []
        if len(image_urls) >= 2:
            return self.publish_carousel(
                text, image_urls, reply_to_id=reply_to_id, topic_tag=topic_tag
            )
        return self.publish_text(
            text,
            reply_to_id=reply_to_id,
            image_url=image_urls[0] if image_urls else None,
            topic_tag=topic_tag,
        )


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
