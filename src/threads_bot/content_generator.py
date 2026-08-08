from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import anthropic

from .persona import Persona
from .product import Product

MODEL = "claude-sonnet-5"

GENERATE_POST_TOOL = {
    "name": "generate_post",
    "description": "쓰레드에 올릴 글 하나를 확정해서 제출한다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "hook_category": {
                "type": "string",
                "description": "이번 글에 사용한 FOMO 후크 카테고리 id (예: scarcity, urgency, curiosity_gap, loss_aversion, social_proof, exclusivity)",
            },
            "topic_summary": {
                "type": "string",
                "description": "이번 글의 주제를 5~15자로 요약 (다음 글의 중복 회피 판단용)",
            },
            "source_review_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "이번 글이 실제로 인용/참고한 후기의 id 목록",
            },
            "text": {
                "type": "string",
                "description": "쓰레드에 실제로 게시할 최종 글 본문. 500자(공백 포함) 이내.",
            },
        },
        "required": ["hook_category", "topic_summary", "source_review_ids", "text"],
    },
}


@dataclass
class GeneratedPost:
    hook_category: str
    topic_summary: str
    text: str
    source_review_ids: list[str]


def _build_history_note(recent_records: list[dict]) -> str:
    if not recent_records:
        return "최근 발행 이력이 없습니다."
    lines = [
        f"  - ({r['hook_category']}) {r['topic_summary']}" for r in recent_records
    ]
    return (
        "최근에 이미 다룬 주제/후크 카테고리입니다. 같은 주제나 같은 후크 카테고리를 "
        "연속으로 반복하지 마세요:\n" + "\n".join(lines)
    )


def _build_reviews_block(reviews: list[dict[str, Any]]) -> str:
    if not reviews:
        return "(제공된 후기 데이터가 없습니다. 이 경우 상품 정보만으로 일반적인 소개 글을 쓰되, 없는 후기 내용을 지어내지 마세요.)"
    lines = [f'  - id={r["id"]}: "{r["text"]}"' for r in reviews]
    return "[이번에 참고할 실제 구매자 후기]\n" + "\n".join(lines)


def generate(
    persona: Persona,
    product: Product,
    reviews: list[dict[str, Any]],
    recent_records: list[dict],
    client: anthropic.Anthropic | None = None,
) -> GeneratedPost:
    client = client or anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    system_prompt = persona.to_system_prompt() + "\n\n" + product.to_context_block()
    history_note = _build_history_note(recent_records)
    reviews_block = _build_reviews_block(reviews)

    message = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=system_prompt,
        tools=[GENERATE_POST_TOOL],
        tool_choice={"type": "tool", "name": "generate_post"},
        messages=[
            {
                "role": "user",
                "content": (
                    "오늘 쓰레드에 올릴 글 하나를 작성해주세요.\n\n"
                    f"{reviews_block}\n\n"
                    f"{history_note}\n\n"
                    "제공된 후기 중 실제로 이번 글에 반영한 것만 source_review_ids에 넣으세요. "
                    "generate_post 도구를 호출해서 결과를 제출하세요."
                ),
            }
        ],
    )

    for block in message.content:
        if block.type == "tool_use" and block.name == "generate_post":
            data = block.input
            return GeneratedPost(
                hook_category=data["hook_category"],
                topic_summary=data["topic_summary"],
                text=data["text"].strip(),
                source_review_ids=data.get("source_review_ids", []),
            )

    raise RuntimeError("Claude가 generate_post 도구를 호출하지 않았습니다.")
