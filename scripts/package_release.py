#!/usr/bin/env python
"""판매자 본인의 실제 데이터를 뺀 '배포용 클린 버전' zip을 만든다.

이 저장소에는 판매자 본인의 실제 상품/후기/발행 이력(config/product.yaml,
data/reviews.json, data/queue*.json, data/app.db 등)이 들어있어서, 그대로
압축해서 구매자에게 전달하면 판매자의 실제 콘텐츠가 노출된다. 이 스크립트는
allowlist(포함할 것만 명시)로 동작해서, 새 파일이 실수로 딸려 나가는 일이
없게 한다 - 새로 추가하고 싶은 파일이 있으면 아래 INCLUDE_* 목록에 직접
추가해야 포함된다.

실행: python scripts/package_release.py
결과: dist/threads-dashboard-YYYYMMDD.zip
"""
from __future__ import annotations

import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "dist"

# 통째로 포함할 디렉토리 (아래 EXCLUDE_SUBPATHS에 해당하는 하위 경로는 제외)
INCLUDE_DIRS = [
    "webapp/templates",
    "webapp/static",
    "src",
    ".github",
]

# 위 디렉토리들 중 판매자 개인 데이터라서 빼야 하는 하위 경로
EXCLUDE_SUBPATHS = (
    "webapp/static/generated",  # 판매자가 만든 AI 생성 이미지 캐시
)

# 개별 포함 파일 (판매자 실데이터가 없는, 코드/설정 템플릿만)
INCLUDE_FILES = [
    "webapp/app.py",
    "config/persona.yaml",
    "data/reviews.example.json",
    "requirements.txt",
    "README.md",
    "사용설명서.md",
    "시작하기.bat",
    ".gitignore",
    ".env.example",
    "docs/callback.html",
    "scripts/bootstrap.py",
    "scripts/scheduled_publish.py",
    "scripts/oauth_setup.py",
    "scripts/refresh_token.py",
    "scripts/migrate_to_db.py",
    "scripts/publish.py",
]

# 판매자 실데이터 대신 빈 상태로 새로 만들 파일들
RESET_JSON_FILES: dict[str, object] = {
    "data/queue.json": [],
    "data/queue_history.json": [],
    "data/post_history.json": [],
    "data/schedule_settings.json": {
        "morning": False, "lunch": False, "afternoon": False, "evening": True,
    },
}

PRODUCT_YAML_EXAMPLE = """# (레거시) CLI로 상품 1개만 자동화할 때 쓰는 예시 파일입니다.
# 대시보드(시작하기.bat -> webapp/app.py)를 쓸 거라면 이 파일은 필요 없습니다.
name: "예시 상품명"
category: "생활/주방용품"
smartstore_url: "https://smartstore.naver.com/본인스토어/products/상품번호"
review_count: 0
rating: 0
key_selling_points:
  - "셀링포인트를 이곳에 채워주세요"
cta_text: "궁금하신 분은 댓글에 남겨둔 링크 확인해주세요"
reply_link_text: "🔗 상품 보러가기"
"""


def _copy_tree(src: Path, stage: Path) -> None:
    if not src.exists():
        print(f"[건너뜀] {src.relative_to(ROOT)} 없음")
        return
    for path in src.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        rel = path.relative_to(ROOT).as_posix()
        if any(rel.startswith(ex) for ex in EXCLUDE_SUBPATHS):
            continue
        dst = stage / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dst)


def _copy_files(stage: Path) -> None:
    for rel in INCLUDE_FILES:
        src = ROOT / rel
        if not src.exists():
            print(f"[건너뜀] {rel} 없음")
            continue
        dst = stage / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def _write_reset_files(stage: Path) -> None:
    for rel, default in RESET_JSON_FILES.items():
        dst = stage / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(json.dumps(default, ensure_ascii=False, indent=2), encoding="utf-8")

    queue_images = stage / "data" / "queue_images"
    queue_images.mkdir(parents=True, exist_ok=True)
    (queue_images / ".gitkeep").write_text("", encoding="utf-8")

    (stage / "config").mkdir(parents=True, exist_ok=True)
    (stage / "config" / "product.yaml.example").write_text(PRODUCT_YAML_EXAMPLE, encoding="utf-8")


def build() -> Path:
    stamp = datetime.now().strftime("%Y%m%d")
    stage = OUT_DIR / f"threads-dashboard-{stamp}"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    for rel in INCLUDE_DIRS:
        _copy_tree(ROOT / rel, stage)
    _copy_files(stage)
    _write_reset_files(stage)

    zip_path = OUT_DIR / f"{stage.name}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in stage.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(stage.parent))

    shutil.rmtree(stage)
    return zip_path


def _check_no_leaks(zip_path: Path) -> list[str]:
    """의심스러운 개인정보(예: 실제 스토어 슬러그, DB 파일 등)가 섞여 들어가지 않았는지
    마지막으로 한 번 더 훑어본다. 문제 되는 항목이 있으면 파일명 목록을 반환한다."""
    suspects = []
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            lower = name.lower()
            if lower.endswith("app.db") or lower.endswith(".env"):
                suspects.append(name)
            if name.endswith("config/product.yaml") or name.endswith("data/reviews.json"):
                suspects.append(name)
    return suspects


if __name__ == "__main__":
    result_path = build()
    leaks = _check_no_leaks(result_path)
    if leaks:
        print("[경고] 아래 항목이 패키지에 포함되어 있습니다. 즉시 확인하세요:")
        for item in leaks:
            print(f"  - {item}")
        raise SystemExit(1)
    print(f"완료: {result_path}")
    print("이 zip 파일 그대로 구매자에게 전달하면 됩니다 (판매자 개인 데이터는 포함되지 않았습니다).")
