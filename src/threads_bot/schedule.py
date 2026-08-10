from __future__ import annotations

import json
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
