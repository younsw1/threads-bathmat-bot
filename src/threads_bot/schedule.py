from __future__ import annotations

import hashlib
import json
import random
import re
import subprocess
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

KST = timezone(timedelta(hours=9))

# 참여도가 높은 한국 쓰레드 시간대 (아침 출근길 / 점심 / 오후 / 저녁 - 저녁이 가장 참여도 높음)
# dict 순서 = 하루 중 시간 순서 (하루 최대 4건까지 이 4개 창에 분산)
WINDOWS: dict[str, tuple[time, time]] = {
    "morning": (time(7, 0), time(9, 0)),
    "lunch": (time(12, 0), time(13, 0)),
    "afternoon": (time(15, 0), time(17, 0)),
    "evening": (time(19, 0), time(22, 0)),
}

WINDOW_LABELS = {
    "morning": "아침(7~9시)",
    "lunch": "점심(12~13시)",
    "afternoon": "오후(15~17시)",
    "evening": "저녁(19~22시)",
}

ROOT = Path(__file__).resolve().parents[2]
QUEUE_PATH = ROOT / "data" / "queue.json"
SETTINGS_PATH = ROOT / "data" / "schedule_settings.json"
HISTORY_PATH = ROOT / "data" / "queue_history.json"
QUEUE_IMAGES_DIR = ROOT / "data" / "queue_images"

DEFAULT_SCHEDULE_SETTINGS = {"morning": False, "lunch": False, "afternoon": False, "evening": True}


def _window_bounds_today(window_name: str, now_kst: datetime) -> tuple[datetime, datetime]:
    start_t, end_t = WINDOWS[window_name]
    start = now_kst.replace(hour=start_t.hour, minute=start_t.minute, second=0, microsecond=0)
    end = now_kst.replace(hour=end_t.hour, minute=end_t.minute, second=0, microsecond=0)
    return start, end


def current_window(now_kst: datetime | None = None) -> str | None:
    """지금(KST)이 어느 시간대(window)에 속하는지 반환. 해당 없으면 None."""
    now = now_kst or datetime.now(KST)
    for name in WINDOWS:
        start, end = _window_bounds_today(name, now)
        if start <= now <= end:
            return name
    return None


def seconds_remaining_in_window(window_name: str, now_kst: datetime | None = None) -> float:
    now = now_kst or datetime.now(KST)
    _, end = _window_bounds_today(window_name, now)
    return max(0.0, (end - now).total_seconds())


def target_time_in_window(window_name: str, now_kst: datetime | None = None) -> datetime:
    """이 시간대·오늘 날짜에 대해 항상 같은 결과가 나오는(결정적) 무작위 목표 시각을 계산한다.
    GitHub Actions의 cron은 몇 시간씩 지연될 수 있어서, 한 번의 실행에서 sleep으로 기다리는
    대신 매 실행마다 '지금이 목표 시각을 지났는지'만 짧게 확인하는 방식을 쓴다 (여러 번
    실행돼도 항상 같은 목표 시각을 계산하므로 문제없다)."""
    now = now_kst or datetime.now(KST)
    start, end = _window_bounds_today(window_name, now)
    seed_str = f"{now.date().isoformat()}-{window_name}"
    seed = int(hashlib.sha256(seed_str.encode("utf-8")).hexdigest(), 16)
    rng = random.Random(seed)
    offset = rng.uniform(0, (end - start).total_seconds())
    return start + timedelta(seconds=offset)


def published_today_for_window(
    window_name: str, history: list[dict[str, Any]], now_kst: datetime | None = None
) -> bool:
    """오늘 이 시간대에 이미 발행이 성공적으로 이뤄졌는지 확인한다 (중복 발행 방지)."""
    now = now_kst or datetime.now(KST)
    today = now.date()
    for h in history:
        if h.get("window") != window_name:
            continue
        try:
            ts = datetime.fromisoformat(h["published_at"]).astimezone(KST)
        except (KeyError, ValueError):
            continue
        if ts.date() == today:
            return True
    return False


def todays_publish_plan(now_kst: datetime | None = None) -> list[dict[str, Any]]:
    """오늘 아직 지나지 않은, 활성화된 시간대별로 지금 이 순간의 대기열 스냅샷 기준
    몇 번째 항목이 발행될지 예측한다 (홈 화면 요약용). 실제 발행은 그 시간대의 무작위
    시각에 대기열 맨 앞부터 순서대로 소비하는 방식이라, 대기열이 나중에 바뀌면 이 예측도
    달라질 수 있는 근사치다. 이미 끝나버린(놓친) 시간대는 목록에서 빠진다."""
    now = now_kst or datetime.now(KST)
    settings = load_schedule_settings()
    history = load_json(HISTORY_PATH, [])
    queue = load_queue()

    remaining_windows = []
    for name in WINDOWS:  # dict 순서 = 하루 중 시간 순서
        if not settings.get(name):
            continue
        if published_today_for_window(name, history, now):
            continue
        _, end = _window_bounds_today(name, now)
        if now > end:
            continue  # 이미 지나버려서 오늘은 더 이상 발행되지 않을 시간대
        remaining_windows.append(name)

    plan = []
    for i, window_name in enumerate(remaining_windows):
        plan.append({"window": window_name, "item": queue[i] if i < len(queue) else None})
    return plan


def upcoming_window_starts(
    enabled: dict[str, bool], count: int, now_kst: datetime | None = None
) -> list[tuple[str, datetime]]:
    """활성화된 시간대들의 앞으로의 시작 시각을 시간순으로 count개 반환한다.
    대기열 항목이 대략 언제 발행될지 예측 표시하는 용도 (실제 발행 시각은 그 창 안에서
    무작위이므로 어디까지나 근사치)."""
    now = now_kst or datetime.now(KST)
    enabled_names = [w for w in WINDOWS if enabled.get(w)]
    if not enabled_names or count <= 0:
        return []
    results: list[tuple[str, datetime]] = []
    day_offset = 0
    while len(results) < count and day_offset < 30:
        for name in enabled_names:
            start_t, _ = WINDOWS[name]
            candidate = (now + timedelta(days=day_offset)).replace(
                hour=start_t.hour, minute=start_t.minute, second=0, microsecond=0
            )
            if candidate <= now:
                continue
            results.append((name, candidate))
            if len(results) >= count:
                break
        day_offset += 1
    return results


def raw_github_url(rel_path: str) -> str | None:
    """git remote origin(GitHub) 주소로부터 raw.githubusercontent.com 공개 URL을 만든다.
    로컬 전용 이미지(webapp/static/generated/...)를 GitHub에 커밋해 Threads가 읽을 수 있는
    공개 주소로 바꿀 때 쓴다. origin이 GitHub가 아니면 None."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=ROOT, capture_output=True, text=True, timeout=10,
        )
    except OSError:
        return None
    url = result.stdout.strip()
    match = re.search(r"github\.com[:/]([^/]+)/(.+?)(\.git)?$", url)
    if not match:
        return None
    owner, repo = match.group(1), match.group(2)
    return f"https://raw.githubusercontent.com/{owner}/{repo}/main/{rel_path}"


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_schedule_settings(path: Path = SETTINGS_PATH) -> dict[str, bool]:
    return load_json(path, dict(DEFAULT_SCHEDULE_SETTINGS))


def save_schedule_settings(settings: dict[str, bool], path: Path = SETTINGS_PATH) -> None:
    save_json(path, settings)


def load_queue(path: Path = QUEUE_PATH) -> list[dict[str, Any]]:
    return load_json(path, [])


def save_queue(items: list[dict[str, Any]], path: Path = QUEUE_PATH) -> None:
    save_json(path, items)


def append_history(entry: dict[str, Any], path: Path = HISTORY_PATH) -> None:
    history = load_json(path, [])
    history.append(entry)
    save_json(path, history)
