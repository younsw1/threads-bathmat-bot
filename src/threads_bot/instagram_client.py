from __future__ import annotations

import time
from dataclasses import dataclass

import requests

GRAPH_BASE = "https://graph.facebook.com/v21.0"

CAPTION_MAX_LEN = 2200  # Instagram 캡션 글자 수 제한


class InstagramApiError(RuntimeError):
    pass


def _raise_for_error(resp: requests.Response) -> None:
    if resp.status_code >= 400:
        try:
            message = resp.json().get("error", {}).get("message", resp.text)
        except ValueError:
            message = resp.text
        raise InstagramApiError(f"Instagram API 오류 {resp.status_code}: {message}")


@dataclass
class InstagramClient:
    access_token: str
    ig_user_id: str

    def __post_init__(self) -> None:
        # Threads 클라이언트와 같은 이유: 값이 복사 과정에서 깨진 채 저장되면
        # 원인을 알기 어려운 API 오류로만 나타나므로 여기서 먼저 걸러낸다.
        self.access_token = (self.access_token or "").strip()
        self.ig_user_id = (self.ig_user_id or "").strip()
        if not self.ig_user_id.isdigit():
            raise InstagramApiError(
                f"Instagram 비즈니스 계정 ID가 숫자로만 이루어져 있지 않습니다 (길이={len(self.ig_user_id)}). "
                "값이 손상된 채 저장됐을 가능성이 높습니다. 다시 확인해주세요."
            )
        if len(self.access_token) < 50 or any(c.isspace() for c in self.access_token):
            raise InstagramApiError(
                f"Instagram 액세스 토큰 형식이 올바르지 않습니다 (길이={len(self.access_token)}). "
                "값이 손상된 채 저장됐을 가능성이 높습니다. 다시 확인해주세요."
            )

    def get_account_info(self) -> dict:
        resp = requests.get(
            f"{GRAPH_BASE}/{self.ig_user_id}",
            params={"fields": "username,media_count", "access_token": self.access_token},
            timeout=30,
        )
        _raise_for_error(resp)
        return resp.json()

    def create_container(self, image_url: str, caption: str) -> str:
        resp = requests.post(
            f"{GRAPH_BASE}/{self.ig_user_id}/media",
            data={
                "image_url": image_url,
                "caption": caption[:CAPTION_MAX_LEN],
                "access_token": self.access_token,
            },
            timeout=30,
        )
        _raise_for_error(resp)
        return resp.json()["id"]

    def create_carousel_item(self, image_url: str) -> str:
        resp = requests.post(
            f"{GRAPH_BASE}/{self.ig_user_id}/media",
            data={
                "image_url": image_url,
                "is_carousel_item": "true",
                "access_token": self.access_token,
            },
            timeout=30,
        )
        _raise_for_error(resp)
        return resp.json()["id"]

    def create_carousel_container(self, item_ids: list[str], caption: str) -> str:
        resp = requests.post(
            f"{GRAPH_BASE}/{self.ig_user_id}/media",
            data={
                "media_type": "CAROUSEL",
                "children": ",".join(item_ids),
                "caption": caption[:CAPTION_MAX_LEN],
                "access_token": self.access_token,
            },
            timeout=30,
        )
        _raise_for_error(resp)
        return resp.json()["id"]

    def wait_until_container_ready(
        self, creation_id: str, timeout: float = 90.0, interval: float = 3.0
    ) -> None:
        """Instagram도 Threads처럼 컨테이너가 IN_PROGRESS -> FINISHED로 바뀔 때까지
        기다려야 한다 (사진 다운로드/처리에 Threads보다 시간이 더 걸리는 편)."""
        time.sleep(2.0)
        deadline = time.monotonic() + timeout
        last_status: str | None = None
        while time.monotonic() < deadline:
            resp = requests.get(
                f"{GRAPH_BASE}/{creation_id}",
                params={"fields": "status_code", "access_token": self.access_token},
                timeout=30,
            )
            if resp.status_code >= 400:
                time.sleep(interval)
                continue
            status = resp.json().get("status_code")
            if status in (None, "FINISHED"):
                return
            if status == "ERROR":
                raise InstagramApiError(f"컨테이너 처리 실패 (creation_id={creation_id})")
            last_status = status
            time.sleep(interval)
        raise InstagramApiError(
            f"컨테이너 처리 대기 시간 초과 (creation_id={creation_id}, 마지막 상태: {last_status})"
        )

    def publish(self, creation_id: str) -> str:
        resp = requests.post(
            f"{GRAPH_BASE}/{self.ig_user_id}/media_publish",
            data={"creation_id": creation_id, "access_token": self.access_token},
            timeout=30,
        )
        _raise_for_error(resp)
        return resp.json()["id"]

    def comment(self, media_id: str, text: str) -> str:
        """발행된 게시물에 댓글을 단다. Instagram 캡션의 링크는 클릭이 안 되기 때문에,
        Threads의 '답글로 링크 달기'와 비슷하게 링크 안내를 댓글로 남기는 용도."""
        resp = requests.post(
            f"{GRAPH_BASE}/{media_id}/comments",
            data={"message": text, "access_token": self.access_token},
            timeout=30,
        )
        _raise_for_error(resp)
        return resp.json()["id"]

    def publish_post(self, caption: str, image_urls: list[str]) -> str:
        """이미지 개수에 따라 단일 이미지/캐러셀로 발행한다. Instagram은 Threads와 달리
        텍스트만으로는 발행할 수 없어 사진이 최소 1장 필요하다."""
        if not image_urls:
            raise InstagramApiError("Instagram은 사진 없이 텍스트만 발행할 수 없습니다.")
        if len(image_urls) == 1:
            creation_id = self.create_container(image_urls[0], caption)
        else:
            item_ids = []
            for url in image_urls[:10]:  # Instagram 캐러셀 최대 10장
                item_id = self.create_carousel_item(url)
                self.wait_until_container_ready(item_id)
                item_ids.append(item_id)
            creation_id = self.create_carousel_container(item_ids, caption)
        self.wait_until_container_ready(creation_id)
        return self.publish(creation_id)
