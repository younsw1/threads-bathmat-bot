from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PERSONA_PATH = Path(__file__).resolve().parents[2] / "config" / "persona.yaml"


@dataclass
class Persona:
    raw: dict[str, Any]

    @classmethod
    def load(cls, path: Path = DEFAULT_PERSONA_PATH) -> "Persona":
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls(raw=data)

    def to_system_prompt(self, mode: str = "review") -> str:
        r = self.raw
        hooks = "\n".join(
            f"  - [{h['id']}] {h['name']}: {h['description']}\n"
            + "\n".join(f"      예: \"{ex}\"" for ex in h["example_openers"])
            for h in r["fomo_hook_categories"]
        )
        banned = "\n".join(f"  - {b}" for b in r["banned_patterns"])
        style = "\n".join(f"  - {s}" for s in r["style_rules"])
        content_source_rule = (
            r["content_source_rule_promo"] if mode == "promo" else r["content_source_rule"]
        )

        return f"""당신은 쓰레드(Threads) 계정 "{r['name']}"을 운영하는 사람입니다.
니치: {r['niche']}
타깃 독자: {r['audience']}

[계정 정체성]
{r['identity_note']}

[콘텐츠 소재 원칙]
{content_source_rule}

[말투]
{r['tone']}

[FOMO 후크 카테고리 - 매 글마다 이 중 하나를 골라 첫 줄에 반영]
{hooks}

[절대 하지 말 것]
{banned}

[문체 규칙]
{style}

당신은 실제 사람입니다. AI라는 티가 나면 안 됩니다. 제공되지 않은 정보는 지어내지 말고,
반드시 주어진 실제 후기 내용에 근거해서만 씁니다."""
