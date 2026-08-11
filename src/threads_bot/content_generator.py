from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import anthropic

from .persona import Persona
from .product import Product

MODEL = "claude-sonnet-5"

SUGGEST_SELLING_POINTS_TOOL = {
    "name": "suggest_selling_points",
    "description": "상품의 핵심 셀링포인트 후보 3개를 제출한다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "points": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 3,
                "maxItems": 3,
                "description": "각 15~30자 내외의 짧고 구체적인 셀링포인트 3개",
            },
        },
        "required": ["points"],
    },
}


def suggest_selling_points(
    product: Product,
    reviews: list[dict[str, Any]],
    client: anthropic.Anthropic | None = None,
) -> list[str]:
    """상품명/카테고리/(있다면) 실제 후기를 근거로 핵심 셀링포인트 3개를 추천한다.
    후기가 없는 상품홍보 모드에서는 상품 정보만으로 일반적인 강점을 제안하되,
    없는 효능/수치를 지어내지 않도록 지시한다."""
    client = client or anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    r = product.raw
    reviews_block = (
        "\n".join(f'  - "{rv["text"]}"' for rv in reviews)
        if reviews
        else "(등록된 후기 없음 — 상품명/카테고리만으로 일반적인 강점을 제안하세요. 구체적 수치나 효능을 지어내지 마세요.)"
    )

    message = client.messages.create(
        model=MODEL,
        max_tokens=512,
        system=(
            "당신은 이커머스 상품 마케팅 카피라이터입니다. 주어진 상품 정보만으로 "
            "핵심 셀링포인트 3개를 뽑습니다. 과장하거나 근거 없는 효능/수치를 지어내지 않습니다."
        ),
        tools=[SUGGEST_SELLING_POINTS_TOOL],
        tool_choice={"type": "tool", "name": "suggest_selling_points"},
        messages=[
            {
                "role": "user",
                "content": (
                    f"상품명: {r.get('name') or '(미입력)'}\n"
                    f"카테고리: {r.get('category') or '(미입력)'}\n"
                    f"가격: {r.get('price') or '(미입력)'}\n\n"
                    f"[참고할 실제 후기]\n{reviews_block}\n\n"
                    "suggest_selling_points 도구를 호출해서 결과를 제출하세요."
                ),
            }
        ],
    )

    for block in message.content:
        if block.type == "tool_use" and block.name == "suggest_selling_points":
            return list(block.input["points"])[:3]

    raise RuntimeError("Claude가 suggest_selling_points 도구를 호출하지 않았습니다.")


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
            "topic_tag": {
                "type": "string",
                "description": (
                    "이 글의 Threads 주제 태그(topic_tag) 1개. 본문에 #을 붙여 쓰지 않고 "
                    "별도 필드로만 제출한다. 1~50자, 마침표(.)나 앤퍼샌드(&) 사용 금지. "
                    "여러 단어를 나열하지 말고 자연스러운 한 단어~짧은 구(예: 자취템, 욕실인테리어) "
                    "하나만 쓴다. 글마다 가장 핵심적인 주제로 다양하게 바꾼다."
                ),
            },
        },
        "required": ["hook_category", "topic_summary", "source_review_ids", "text", "topic_tag"],
    },
}


@dataclass
class GeneratedPost:
    hook_category: str
    topic_summary: str
    text: str
    source_review_ids: list[str]
    topic_tag: str = ""


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


def _build_reviews_block(reviews: list[dict[str, Any]], mode: str) -> str:
    if mode == "promo":
        return "(이 상품은 '상품홍보' 모드입니다. 후기 데이터를 제공하지 않으니 후기를 인용하지 마세요.)"
    if not reviews:
        return "(제공된 후기 데이터가 없습니다. 이 경우 상품 정보만으로 일반적인 소개 글을 쓰되, 없는 후기 내용을 지어내지 마세요.)"
    lines = [f'  - id={r["id"]}: "{r["text"]}"' for r in reviews]
    return "[이번에 참고할 실제 구매자 후기]\n" + "\n".join(lines)


def _build_link_note(link_placement: str, smartstore_url: str) -> str:
    if link_placement == "inline":
        return (
            "[링크 표기 방식] 이번 글은 본문 마지막 줄에 실제 상품 링크를 직접 포함하세요: "
            f"{smartstore_url}\n(별도 답글은 달리지 않습니다.)"
        )
    return "[링크 표기 방식] 본문에 URL을 쓰지 마세요. 발행 직후 자동으로 답글에 링크가 달립니다."


def _build_style_examples_block(style_examples: list[dict[str, Any]] | None) -> str:
    if not style_examples:
        return ""
    lines = [f'  ---\n  "{ex["text"]}"' for ex in style_examples]
    return (
        "\n\n[사용자가 직접 즐겨찾기로 지정한, 이 계정의 문체를 가장 잘 보여주는 과거 글 예시]\n"
        "아래 글들의 말투/문장 리듬/톤을 최우선으로 참고해서 쓰세요. 내용을 베끼거나 같은 "
        "주제를 반복하지는 말고, 어떻게 쓰는지(문체)만 배우세요:\n" + "\n".join(lines)
    )


def generate(
    persona: Persona,
    product: Product,
    reviews: list[dict[str, Any]],
    recent_records: list[dict],
    client: anthropic.Anthropic | None = None,
    style_examples: list[dict[str, Any]] | None = None,
) -> GeneratedPost:
    mode = product.raw.get("mode", "review")
    link_placement = product.raw.get("link_placement", "reply")
    client = client or anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    system_prompt = (
        persona.to_system_prompt(mode)
        + "\n\n"
        + product.to_context_block()
        + "\n\n"
        + _build_link_note(link_placement, product.raw.get("smartstore_url", ""))
        + _build_style_examples_block(style_examples)
    )
    history_note = _build_history_note(recent_records)
    reviews_block = _build_reviews_block(reviews, mode)

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
                topic_tag=data.get("topic_tag", "").strip()[:50],
            )

    raise RuntimeError("Claude가 generate_post 도구를 호출하지 않았습니다.")
