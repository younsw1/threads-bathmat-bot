#!/usr/bin/env python
"""'시작하기.bat'이 호출하는 최초 설치 + 실행 스크립트.

배치 파일(.bat) 안에 한글 텍스트를 직접 넣으면 cmd.exe가 UTF-8 바이트를 명령어
구분자로 잘못 인식해 줄이 깨지는 문제가 있어(실제로 겪음), 사용자에게 보여줄
안내 문구는 전부 이 파이썬 스크립트의 print()로 옮겼다. .bat 파일 자체는 순수
영문/ASCII만 사용해 인코딩 문제를 원천적으로 피한다.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_DIR = ROOT / ".venv"
VENV_PYTHON = VENV_DIR / "Scripts" / "python.exe"


def run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def ensure_installed() -> None:
    if VENV_PYTHON.exists():
        return
    print()
    print("처음 실행이시네요. 필요한 프로그램을 준비하고 있습니다... (몇 분 정도 걸릴 수 있어요)")
    print()
    import venv

    venv.create(VENV_DIR, with_pip=True)
    run([str(VENV_PYTHON), "-m", "pip", "install", "--upgrade", "pip"])
    run([str(VENV_PYTHON), "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")])
    print()
    print("설치가 끝났습니다!")
    print()


def main() -> None:
    ensure_installed()
    print("대시보드를 시작합니다... 잠시 후 브라우저가 자동으로 열립니다.")
    print('(처음 실행이라면 먼저 "설정" 화면에서 API 키를 등록해주세요 - 자세한 방법은 "사용설명서" 메뉴 참고)')
    print()
    print("이 검은 창을 닫으면 대시보드도 함께 종료됩니다. 창은 그대로 켜두고 브라우저만 쓰시면 됩니다.")
    print()
    run([str(VENV_PYTHON), str(ROOT / "webapp" / "app.py")])


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        print()
        print(f"[오류] 실행 중 문제가 발생했습니다 (종료 코드: {e.code}). 인터넷 연결을 확인한 뒤 다시 실행해주세요.")
        sys.exit(e.code)
    except Exception as e:  # noqa: BLE001
        print()
        print(f"[오류] {e}")
        sys.exit(1)
