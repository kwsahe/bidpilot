"""사업계획서 초안 완성도 점검표 (25차 · prompt_15 §4-D) — **한 함수**가 계산하고 화면 두 곳이 읽는다.

점검표는 「이 초안이 공고 양식을 얼마나 채웠는가」를 센 값이다. **선정 가능성이나 초안의 질을 말하지 않는다** —
완성도가 높은지는 사람이 읽고 정한다(CLAUDE.md §17 · 보고의 사람 평가 표). 여기 수치는 제출 전에 무엇이 비었는지 보여 준다.

| 항목 | 기준 |
| 양식 항목 채움 | 소항목 n/m(빈 절 목록) · 표가 양식 그대로 있는가 · 채운 표 |
| 평가 항목 대응 | 항목마다 겨냥한 절 · 가점(비수도권 본점 — 회사 소재지 사실로 판정) |
| 근거 있는 문장 | 회사 근거 · 공고 근거 · AI 제안 수 |
| 공고 문장 복사 | AI 문장 중 복사 표시 비율 — 10% 이하 초록 · 그 위 호박 |
| 숫자 검증 | 근거 불일치 · 사업비 합계·상한·비목 · 일정 범위 · 남은 양식 예시 값 |
| 분량 | 본문 글자 수 / 양식 권장(쪽 × 1,500자) — 60~130% 초록 |
| 사람이 채울 칸 | 제출 전 채울 것 n개 |
| 초안 종류 | AI 초안(공급자 · 모델) / 규칙 초안(공고 양식 뼈대) · 실패한 절 수 |
"""

from __future__ import annotations

from typing import Any

from app.services import plan_validation
from app.services.plan_draft_service import CHARS_PER_PAGE, COMPANY, FLAG_COPY, GROUNDING_FLAGS, NOTICE, SUGGESTION
from app.services.plan_form_service import HUMAN_INPUT, TASK_PENDING

#: 저장된 옛 초안의 경고(「공고 문장 복사 — …」 · 「공고 근거 확인 필요 — …」)도 센다(32차 — 경고 글을 바꿨다).
_COPY_FLAGS = (FLAG_COPY, "공고 문장 복사")
_GROUNDING_FLAGS = (*GROUNDING_FLAGS, "근거 확인 필요", "공고 근거 확인 필요")

#: 수도권 — 「비수도권 본점」 가점 판정.
CAPITAL_REGION_WORDS = ("서울", "경기", "인천")


def _content(sentence: dict[str, Any]) -> bool:
    """본문으로 셀 문장 — 안내 · 공고 인용 · 빈칸 표시 · 후보 목록이 아닌 것."""
    text = str(sentence.get("text") or "")
    # 모델이 「(담당자 입력 — 예: …)」처럼 빈칸 표시를 바꿔 써도 빈칸이다.
    # 규칙 사실 줄(창업 연차 등 · rule_unit 이 역량 절에 넣는다)은 본문이 아니다 — 「양식 2/8」로 세었다(26차 ISSUE-152).
    if sentence.get("note") or sentence.get("notice_quote") or sentence.get("fact") or HUMAN_INPUT.rstrip(")") in text:
        return False
    return not text.startswith(("수행 실적 후보:", "회사자료:"))


def _bonus(evaluation: dict[str, Any], company_region: str | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for bonus in evaluation.get("bonus") or []:
        applies: bool | None = None
        basis = "회사 소재지가 적혀 있지 않다 — 담당자 확인"
        if bonus.get("non_capital_region") and company_region:
            applies = not any(word in company_region for word in CAPITAL_REGION_WORDS)
            basis = f"회사 소재지 {company_region} → {'비수도권(대상)' if applies else '수도권(대상 아님)'}"
        out.append({"name": bonus.get("name"), "points": bonus.get("points"), "applies": applies, "basis": basis})
    return out


LEGACY_SUMMARY = "예전 초안(양식 이전 6절) — 다시 만들면 공고 양식 순서로 씁니다"


def plan_completeness(draft: dict[str, Any], form: dict[str, Any], *, company_region: str | None = None) -> dict[str, Any]:
    sections = draft.get("sections") or []
    if sections and not any("kind" in s for s in sections):
        # 25차 전에 만든 초안(사업 개요 · 신청 자격 · … 6절) — 양식 기준으로 셀 수 없다.
        return {"legacy": True, "summary": LEGACY_SUMMARY}
    items = [s for s in sections if s.get("kind") == "item" and not s.get("optional")]
    filled = [s for s in items if any(_content(x) for x in s.get("sentences") or [])]
    form_tables = [t["key"] for t in form.get("tables") or []]
    tables = {t.get("key"): t for t in draft.get("tables") or []}
    present = [k for k in form_tables if k in tables]
    tables_filled = [
        k for k in present
        if any(cell not in (HUMAN_INPUT, "") for row in tables[k].get("rows") or [] for cell in row[1 if tables[k].get("key") == "performance" else 0:])
    ]

    evaluation = form.get("evaluation") or {}
    eval_rows = []
    for item in evaluation.get("items") or []:
        names = [s["section"] for s in items if item["name"] in (s.get("eval_targets") or [])]
        eval_rows.append({"name": item["name"], "sections": names})

    typed = [x for s in sections for x in s.get("sentences") or [] if x.get("type")]
    grounding = {
        "company": sum(1 for x in typed if x["type"] == COMPANY),
        "notice": sum(1 for x in typed if x["type"] == NOTICE),
        "suggestion": sum(1 for x in typed if x["type"] == SUGGESTION),
        "total": len(typed),
        # 서로 다른 회사 근거 수 — 같은 한 줄을 절마다 되풀이해도 하나다(27차 검수 D4).
        "company_sources": len({i for x in typed if x["type"] == COMPANY for i in x.get("source_ids") or []}),
    }

    ai = [x for s in sections for x in s.get("sentences") or [] if x.get("ai")]
    # 경고 글은 plan_draft_service 상수에서 — 저장된 옛 초안은 옛 글로 센다(읽는 곳에서 바꾸기 전 원본이라)
    copied = [x["text"] for x in ai if any(f.startswith(_COPY_FLAGS) for f in x.get("flags") or [])]
    copy_percent = round(100 * len(copied) / len(ai)) if ai else 0

    mismatches = sum(1 for x in ai if any(f.startswith(_GROUNDING_FLAGS) for f in x.get("flags") or []))
    schedule_out = sum(1 for row in (tables.get("schedule") or {}).get("rows") or [] if any("협약 기간 밖" in str(c) for c in row))
    examples = form.get("form_examples") or {}
    example_won = {float(n) for n in examples.get("numbers") or []}
    texts = [str(x.get("text") or "") for x in ai] + [str(c) for t in tables.values() if t.get("by") == "llm" for row in t.get("rows") or [] for c in row]
    examples_left = sum(1 for text in texts for key in plan_validation.number_keys(text) if key[0] == "won" and key[1] in example_won)

    body_texts = [str(x.get("text") or "") for s in items for x in s.get("sentences") or [] if _content(x)]
    body_chars = sum(len(t) for t in body_texts)
    pages = (form.get("rules") or {}).get("pages")
    recommended = pages * CHARS_PER_PAGE if pages else None
    length_percent = round(100 * body_chars / recommended) if recommended else None

    blanks = draft.get("blanks") or []
    fields = list(dict.fromkeys(str(b.get("field")) for b in blanks))

    generated_by = draft.get("generated_by") or "rules"
    failed = sum(1 for s in sections if s.get("llm_error"))
    kind_label = (
        f"AI 초안({draft.get('provider') or '?'} · {draft.get('model') or '?'})" if generated_by == "llm" else "기본 초안(AI 미사용 · 공고 양식 목차)"
    )
    covered = sum(1 for row in eval_rows if row["sections"])
    task_pending = bool(form.get("tasks")) and not form.get("selected_task")
    fill = draft.get("company_fill")  # 일반현황 자동 채움 셈(화면 응답 · 내려받기에서만 붙는다 · 29차 §3-B)
    counted = f"회사자료로 채움 {fill['filled']}칸 · 담당자가 채울 칸 {len(fields)}개" if fill else f"담당자가 채울 칸 {len(fields)}개"
    summary = (f"양식 {len(items)}칸 중 {len(filled)}칸 채움 · 심사 항목 {len(eval_rows)}개 중 {covered}개 다룸 · {counted} · "
               + ("AI 초안" if generated_by == "llm" else "기본 초안"))
    return {
        "form": {
            "items_filled": len(filled), "items_total": len(items),
            "empty_items": [s["section"] for s in items if s not in filled],
            "tables_present": len(present), "tables_total": len(form_tables), "tables_filled": len(tables_filled),
            "source": form.get("source"), "notice": form.get("notice"),
        },
        "evaluation": {"covered": covered, "total": len(eval_rows), "items": eval_rows, "bonus": _bonus(evaluation, company_region)},
        "grounding": grounding,
        "copy": {"count": len(copied), "ai_total": len(ai), "percent": copy_percent, "tone": "pass" if copy_percent <= 10 else "warn", "sentences": copied[:10]},
        "numbers": {
            "mismatches": mismatches,
            "budget": (draft.get("validation") or {}).get("budget"),
            "schedule_out": schedule_out,
            "examples_left": examples_left,
        },
        "length": {
            "chars": body_chars, "recommended": recommended, "percent": length_percent,
            "tone": None if length_percent is None else ("pass" if 60 <= length_percent <= 130 else "warn"),
            # 쉬운 문장(30차 §3-B) — 문장 평균 · 최장 글자 수 · 「·」 수 · 120자 넘는 문장 수
            "sentence_avg": round(body_chars / len(body_texts)) if body_texts else None,
            "sentence_max": max((len(t) for t in body_texts), default=None),
            "dots": sum(t.count("·") for t in body_texts),
            "over_120": sum(1 for t in body_texts if len(t) > 120),
        },
        "blanks": {"count": len(fields), "fields": fields, "task_pending": task_pending},
        "company_fill": fill,
        "kind": {"label": kind_label, "generated_by": generated_by, "provider": draft.get("provider"), "model": draft.get("model"), "failed_sections": failed},
        "summary": summary,
        "legacy": False,
        "task_pending_label": TASK_PENDING if task_pending else None,
    }
