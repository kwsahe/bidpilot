"""기준 답안 시험 (39차 §3-A-2 · D18 → 40차 §3-A-3 · D25) — 검수자 판정(공고명 · 조달분류 · 기관 · 예산만 봄).

- 10-16: recheck31 157건(`precision_gold_1017.json` · 갈래 a · b · c · d_fn)
- 10-19: recheck32 536건(`precision_gold_1019.json` · 10-17 답안이 있으면 그 판정 · `lists` = recheck32 가 그 공고를 본 목록)
- 10-20: recheck33 494건(`precision_gold_1020.json` · 41차 D34 · 10-17 · 10-19 답안이 있으면 그 판정 · 홀드아웃 109건 포함 · 규칙만)

픽스처의 원자료로 작은 저장본을 만들고 **제품과 같은 길**(`opportunity_service.list_opportunities`)로 목록을 세운다.

- 「본업(core)」은 후보이고(비추천으로 접히지 않음) 본업 덩어리다. 크기 문턱(상한 × 2 넘는 교육 · 컨설팅 · 상한 넘는 개발 →
  대형 · 파트너형 후보)은 덩어리를 따지지 않는다. 사전규격(결정 1 — 입찰 순위 밖)은 「다른 사전규격」에 접히지 않는다(D25 ③).
- (a) 본업 상위 40 · (c) 대형의 「아님(not_ours)」은 본업 덩어리 **「주제 맞음」 구간**(살아 있는 것 · 「주제 확인」 · AI 꼬리표 없음)에
  남지 않는다. 10-16 은 39차처럼 본업 덩어리 전체에 남지 않는다.
- 판정은 고치지 않는다(D21). 끝까지 못 고친 줄은 아래 `KNOWN` 에 이유와 함께 적는다.
- 「규칙 + AI」(40차 D25 · `+ai`) — §3-D L2 에서 받은 AI 답(`ai_fit_1016.json` · `ai_fit_1019.json`)을 시험 저장소의 회사 폴더에 넣고
  `ai_fit_assist` 를 켠 채 같은 단언을 한다(AI 를 다시 부르지 않는다).
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.schemas.organization import AnalysisContext
from app.services import opportunity_service, prespec_service
from app.services import practical_priority as practical
from app.services import procurement_service

FIXTURES = Path(__file__).parent / "fixtures"
#: 기준 답안 픽스처 · 그 저장본의 「지금」(12:00 KST) · 저장본 받은 때
GOLDS: dict[str, tuple[Path, datetime, str]] = {
    "1017": (FIXTURES / "precision_gold_1017.json", datetime(2026, 10, 16, 3, 0, tzinfo=timezone.utc), "2026-10-16T00:00:40+00:00"),
    "1019": (FIXTURES / "precision_gold_1019.json", datetime(2026, 10, 19, 3, 0, tzinfo=timezone.utc), "2026-10-19T00:53:11+00:00"),
    "1020": (FIXTURES / "precision_gold_1020.json", datetime(2026, 10, 20, 3, 0, tzinfo=timezone.utc), "2026-10-20T00:41:30+00:00"),
}
ORG = get_settings().default_organization_id

#: 끝까지 못 고친 줄 — 픽스처마다 `id: 이유`. D25 안이어야 한다(아래 마지막 시험).
_LARGE_PRESPEC = "대형 사전규격 — 결정 1(「다른 사전규격」에 대형을 접음) · 결정 2 크기 문턱(개발 C 는 상한 · 교육 A1 은 상한 × 2 초과) 그대로"
KNOWN: dict[str, dict[str, str]] = {
    "1017": {
        "g2bpre-R26BD00283331": _LARGE_PRESPEC,  # 재정데이터 분석교육 7.16억 · A1
        "g2bpre-R26BD00284529": _LARGE_PRESPEC,  # 관광산업 통합교육플랫폼 서비스 운영 4.8억 · C
    },
    "1019": {
        "g2bpre-R26BD00283331": _LARGE_PRESPEC,
        "g2bpre-R26BD00284529": _LARGE_PRESPEC,
        "g2bpre-R26BD00284173": _LARGE_PRESPEC,  # AI-LXP 플랫폼 구축 및 일학습병행과정 컨텐츠 개발 4.0억 · C
    },
    "1020": {
        "g2bpre-R26BD00283331": _LARGE_PRESPEC,
        "g2bpre-R26BD00284529": _LARGE_PRESPEC,
        "g2bpre-R26BD00284173": _LARGE_PRESPEC,
        "g2bpre-R26BD00287014": _LARGE_PRESPEC,  # AI기반 조사 데이터 구조화 및 분석 기술 개발 · C
    },
}


def _is_ac(name: str, row: dict) -> bool:
    """(a) 본업 상위 40 · (c) 대형 — 10-16 은 갈래 글자, 10-19 는 recheck32 가 본 목록."""
    if name == "1017":
        return row.get("section") in ("a", "c")
    lists = row.get("lists") or []
    return "core_block_top40" in lists or "partner_top15" in lists


#: 규칙 + AI 갈래의 AI 답 픽스처(40차 §3-D L2).
AI_FIXTURES = {"1017": FIXTURES / "ai_fit_1016.json", "1019": FIXTURES / "ai_fit_1019.json"}


def _install_ai(name: str) -> None:
    from app.core import org_storage, storage

    root = org_storage.storage_for(ORG)
    root.root.mkdir(parents=True, exist_ok=True)
    entries = json.loads(AI_FIXTURES[name].read_text(encoding="utf-8"))["entries"]
    storage.write_json_atomic(root.root / "ai_fit.json", {"entries": entries, "runs": []})
    payload = storage.read_json(root.delivery_capacity_file, default=None) or {}
    storage.write_json_atomic(root.delivery_capacity_file, {**payload, "ai_fit_assist": True})


@pytest.fixture(params=[*sorted(GOLDS), *(f"{n}+ai" for n in sorted(AI_FIXTURES))])
def gold_listing(request, notice_cache_file: Path, tmp_path: Path):
    name, _, with_ai = request.param.partition("+")
    path, now, fetched_at = GOLDS[name]
    if with_ai:
        _install_ai(name)
    gold = json.loads(path.read_text(encoding="utf-8"))
    records = [row["cache_record"] for row in gold["items"] if row.get("cache_record")]
    notice_cache_file.parent.mkdir(parents=True, exist_ok=True)
    notice_cache_file.write_text(
        json.dumps({"fetched_at": fetched_at, "days": 30, "collected_by": "시험 — 기준 답안 원자료",
                    "total_fetched": len(records), "notices": records}, ensure_ascii=False),
        encoding="utf-8",
    )
    prespec_service.PRESPEC_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    prespec_service.PRESPEC_CACHE_FILE.write_text(
        json.dumps({"fetched_at": fetched_at, "days": 7, "keep_days": 30,
                    "items": [row["prespec_item"] for row in gold["items"] if row.get("prespec_item")]}, ensure_ascii=False),
        encoding="utf-8",
    )
    procurement_service.clear_memo()
    context = AnalysisContext(organization_id=ORG, evidence_scope="internal")
    listing = asyncio.run(opportunity_service.list_opportunities(
        context=context, source="g2b", days=30, include_closed=True, include_blocked=True, now=now, with_prepare=True,
    ))
    # 사전규격은 39차 결정 1 로 입찰 목록 밖 — 「선제준비」 칸 넷(보임 · 다른 것 · 의견 마감 지남 · 본공고 나옴)에서 찾는다.
    section = listing.prepare
    pre = [*section.items, *section.others, *section.opinion_passed, *section.merged] if section else []
    others = {item.id for item in (section.others if section else [])}
    return name, gold, {item.id: item for item in [*listing.items, *pre]}, others


def _folded(item) -> bool:
    return item.practical_group == "비추천" or bool(item.relevance_note)


def _core_block(item) -> bool:
    return (item.practical_block or practical.BLOCK_CORE) == practical.BLOCK_CORE


def _live(item) -> bool:
    return item.practical_group not in ("제외", "비추천")


def _topic_ok(item) -> bool:
    return not getattr(item, "topic_note", None) and not getattr(item, "ai_fit_note", None)


def test_기준_답안_본업은_접히지_않고_본업_덩어리다(gold_listing) -> None:
    name, gold, by_id, others = gold_listing
    bad: list[str] = []
    for row in gold["items"]:
        if row["label"] != "core":
            continue
        item = by_id.get(row["id"])
        assert item is not None, f"[{name}] 목록에 없음: {row['id']} {row['title']}"
        problem = None
        if _folded(item):
            problem = f"접힘 — {item.relevance_note}"
        elif item.opportunity_type == "pre_spec":
            if row["id"] in others:
                problem = f"다른 사전규격({item.practical_block} · {item.fit_type})"
        elif not _core_block(item) and item.practical_block != practical.BLOCK_LARGE:
            problem = f"{item.practical_block} 덩어리({item.fit_type})"
        if problem and row["id"] not in KNOWN[name]:
            bad.append(f"[{name}] {row['id']} {row['title'][:44]} — {problem}")
    assert not bad, "기준 답안 「본업」인데:\n" + "\n".join(bad)


def test_기준_답안_ac_아님은_본업_덩어리_주제_맞음에_남지_않는다(gold_listing) -> None:
    name, gold, by_id, _others = gold_listing
    rows = [r for r in gold["items"] if _is_ac(name, r) and r["label"] == "not_ours"]
    stuck = []
    for row in rows:
        item = by_id[row["id"]]
        # 10-16 은 39차 그대로 본업 덩어리 전체에 남지 않는다 · 10-19 는 「주제 맞음」 구간에 남지 않는다(D25 ④)
        inside = _live(item) and _core_block(item) and (name == "1017" or _topic_ok(item))
        if inside and row["id"] not in KNOWN[name]:
            stuck.append(f"[{name}] {row['id']} {row['title'][:44]} — {item.practical_group} · {item.fit_type}")
    assert not stuck, f"(a) · (c) 「아님」 {len(rows)}건 중 남은 것:\n" + "\n".join(stuck)


def test_못_고친_줄은_D25_합격선_안이다() -> None:
    for name, (path, _now, _fetched) in GOLDS.items():
        gold = json.loads(path.read_text(encoding="utf-8"))
        labels = {r["id"]: r for r in gold["items"]}
        known = KNOWN[name]
        assert all(i in labels for i in known), f"[{name}] 픽스처에 없는 KNOWN id"
        core_known = [i for i in known if labels[i]["label"] == "core"]
        ac_known = [i for i in known if labels[i]["label"] == "not_ours" and _is_ac(name, labels[i])]
        ac_total = sum(1 for r in gold["items"] if _is_ac(name, r) and r["label"] == "not_ours")
        # ③ 비추천 접힘 ≤ 2 · 숨은 본업 0 · 다른 사전규격 ≤ 3 → 못 고친 「본업」은 다섯을 넘지 않고 d_fn 은 없다
        assert len(core_known) <= 5 and not [i for i in core_known if labels[i].get("section") == "d_fn"], name
        assert len(ac_known) <= ac_total * 0.15, f"[{name}] (a) · (c) 못 고친 「아님」 {len(ac_known)}/{ac_total}"
