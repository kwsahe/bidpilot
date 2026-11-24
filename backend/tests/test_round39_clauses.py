"""39차 §3-G — RANK_BRIEF-03(조항 추출: 첫 표시 앞 줄 · 띄어 쓰지 않은 표시 · HWP 글꼴 기호) · 근거 줄 고르기 · RANK_BRIEF-02 · 04 · 05."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.schemas.business_opportunity import NextRoute, UnifiedOpportunity
from app.services import opportunity_brief_service as brief
from app.services import practical_priority as practical
from app.services import qualification_clause_service as qc

NOW = datetime(2026, 10, 16, 3, 0, tzinfo=timezone.utc)


def _body(*lines: str) -> list[tuple[int, str]]:
    return [(3, line) for line in lines]


def test_띄어_쓰지_않은_표시와_첫_표시_앞_줄을_버리지_않는다() -> None:
    """실측(1767741 PDF) — 「○국가종합…」 · 「-[종합여행업(1261)]」 · 「◐ 다음 중…」. 업종 조항이 통째로 사라졌다."""
    clauses = qc.split_clauses(_body(
        "○국가종합전자조달시스템 입찰참가자격등록규정에 따라 반드시 전자입찰서 제출 마감일 전일까지 나라장터(G2B시스템)에",
        "아래의 업종을 입찰참가자격으로 모두 등록한 자",
        "-[ 종합여행업(1261)] 업종 또는[국내외여행업(1262) ] 업종",
        "※ 입찰참가자격 공지사항",
        "◐ 다음 중 어느 하나에 해당하는 자는 입찰참가자격이 없음",
    ))
    texts = [c["text"] for c in clauses]
    assert texts[0].startswith("국가종합전자조달시스템") and texts[0].endswith("등록한 자")
    assert texts[1].startswith("[ 종합여행업(1261)]") and qc.classify(texts[1]) == "industry"
    # 40차 CLAUSE-05 — 「입찰참가자격 공지사항」 · 「다음 중 어느 하나에 해당하는 자는 … 없음」은 결격 목록을 여는 말이라 조항으로 남기지 않는다
    assert not any(t.startswith(("다음 중 어느 하나에", "입찰참가자격 공지사항")) for t in texts) and len(texts) == 2


def test_HWP_글꼴_기호_표시도_조항의_시작이다() -> None:
    """실측(1772697-001 HWP) — 줄마다 U+F0A7(Wingdings) 표시. 1169 · 중소기업 확인서 · 실적 조항이 버려지고 한 줄만 남았다."""
    clauses = qc.split_clauses(_body(
        "  국가종합전자조달시스템 입찰 참가 등록 규정에 학술연구용역[업종코드1169]로 입찰참가자격을 등록한 업체",
        "  「중소기업기본법」 제2조제2항에 따른 중·소기업으로서 발급된 유효기간 내에 있는 확인서를 소지한 업체",
        "  공고일 기준 최근 3년 이내 국가 · 지방자치단체가 발주한 유사 사업 실적이 1건 이상 있는 업체",
        "※ 실적증명서, 계약서 등 증빙서류 제출 시 인정",
    ))
    assert len(clauses) == 4
    assert [qc.classify(c["text"]) for c in clauses[:1]] == ["industry"]
    assert "1169" in clauses[0]["text"]


def test_DOCX_목록은_표시가_없어도_조항_끝에서_나눈다() -> None:
    """실측(1764812 DOCX) — 번호가 글에 없는 목록 셋이 ※ 줄 앞이라 모두 버려졌다."""
    clauses = qc.split_clauses(_body(
        "「국가를 당사자로 하는 계약에 관한 법률 시행령」 제12조에 의한 경쟁입찰 참가자격을 갖춘 자",
        "나라장터(G2B) 입찰참가자격 등록을 완료한 자",
        "부정당업자 제재, 세금 체납 등 결격사유가 없는 자",
        "※ 세부 입찰일정은 나라장터 시스템 공고 화면에 게시된 일정을 따릅니다.",
    ))
    assert [c["text"][:12] for c in clauses] == ["「국가를 당사자로 하는", "나라장터(G2B) 입찰", "부정당업자 제재, 세금", "세부 입찰일정은 나라장"]


def test_여는_말은_조항이_아니다() -> None:
    clauses = qc.split_clauses(_body("아래의 입찰참가자격을 모두 갖춘 자이어야 합니다.", "○ 나라장터에 소프트웨어사업자(1468)로 등록한 자"))
    assert [c["text"][:8] for c in clauses] == ["나라장터에 소프"]


def test_숫자_앞_줄표는_표시가_아니다() -> None:
    assert qc._CLAUSE_START.match("-[종합여행업(1261)]") and not qc._CLAUSE_START.match("-1,000만원 이상")


def _payload(*kinds_texts: tuple[str, str]) -> dict:
    return {"status": "ok", "page_is_approximate": False, "extractor_version": qc.EXTRACTOR_VERSION,
            "clauses": [{"id": f"QC-{n:02d}", "kind": kind, "text": text, "page": 3} for n, (kind, text) in enumerate(kinds_texts, start=1)]}


def test_근거_줄은_판정_조항만_고른다() -> None:
    line, count = qc.evidence_line(_payload(
        ("disqualification", "입찰참가자격 공지사항 ◐ 다음 중 어느 하나에 해당하는 자는 입찰참가자격이 없음"),
        ("other", "세부 입찰일정(공고일, 참가자격 등록마감 …)은 나라장터 시스템 공고 화면에 게시된 일정을 따릅니다"),
        ("track_record", "최근 3년 이내 유사 사업 실적 1건 이상"),
    ))
    assert line == "근거: 공고문 p.3 「최근 3년 이내 유사 사업 실적 1건 이상」(QC-03)" and count == 3


def test_판정_조항이_없으면_결정_조항_없음() -> None:
    line, count = qc.evidence_line(_payload(("disqualification", "부정당업자 제재 등 결격사유가 없는 자"), ("other", "참가자격 및 평가내용")))
    assert line == qc.NO_DECISION_CLAUSE and count == 2
    assert qc.evidence_line(None) == (qc.NOT_READ, 0)


# --------------------------------------------------------------------------
# 브리핑 — RANK_BRIEF-02 · 04 · 05
# --------------------------------------------------------------------------


def test_차수가_바뀐_공고는_새로_탈락이_아니라_공고_변경() -> None:
    old = {"created_at": NOW.isoformat(), "ranking_method": "practical", "days": 30,
           "rows": {"g2b-R26BK01768626-000": {"part": "매출", "rank": 26, "title": "복지행정 안내도우미 AI 시범사업"},
                    "g2b-R26BK01700001-000": {"part": "매출", "rank": 27, "title": "마감된 공고"}}}
    cur = {"ranking_method": "practical", "days": 30, "rows": {"g2b-R26BK01768626-001": {"part": "매출", "rank": 30, "title": "복지행정 안내도우미 AI 시범사업"}}}
    diff = brief.changes(old, cur)
    assert diff["new"] == [] and diff["gone"] == ["g2b-R26BK01700001-000"]
    assert diff["reissued"] == [("g2b-R26BK01768626-000", "g2b-R26BK01768626-001")]


def _item(n: int, *, group: str, tier: str, pinned: bool = False, closed: bool = False, clauses: int = 0) -> UnifiedOpportunity:
    return UnifiedOpportunity(
        id=f"g2b-R26BK0000000{n}-000", source_type="g2b", opportunity_type="procurement", title=f"시험 {n}", agency="기관",
        organization_id="org-sample", priority_rank=n, priority_label="검토", eligibility_gate="CHECK", confidence="medium",
        score_components=[], next_route=NextRoute(kind="procurement_analysis", path="/", label="열기"), source="cached",
        practical_group=group, time_tier=tier, pinned=pinned, closed=closed, clause_count=clauses, recruit_kind=practical.RECRUIT_BID,
        deadline=NOW + timedelta(days=5), practical_block=practical.BLOCK_LARGE if group == practical.GROUP_PARTNER else practical.BLOCK_CORE,
    )


def _listing(items: list[UnifiedOpportunity]):
    from app.schemas.business_opportunity import OpportunitySummary, UnifiedOpportunityListResponse

    return UnifiedOpportunityListResponse(
        organization_id="org-sample", organization_name="주식회사 샘플에듀", total_count=len(items), g2b_count=len(items), bizinfo_count=0,
        returned_count=len(items), closed_count=0, source_status={}, source_errors={}, fetched_at=NOW,
        summary=OpportunitySummary(open_total=len(items), open_g2b=len(items), open_bizinfo=0, priority=0, closed=0, closed_pinned=0, days=30, new_days=3),
        sort="practical", ranking_method="practical", field_mapping_verified=True, note="시험", items=items,
    )


def test_머리_숫자는_시연_고정_공고를_뺀다() -> None:
    items = [_item(1, group="긴급", tier="T6", clauses=7), _item(2, group="제외", tier="T6", pinned=True, closed=True, clauses=6)]
    counts = brief.seen_counts(_listing(items))
    assert counts["g2b"] == 1 and counts["clause_lines"] == 7 and counts["excluded"] == 0


def test_긴급_칸에_13일_이내_파트너형_후보_수를_따로_적는다() -> None:
    items = [_item(1, group="긴급", tier="T6"), _item(2, group=practical.GROUP_PARTNER, tier="T5"), _item(3, group=practical.GROUP_PARTNER, tier="T4")]
    body, _ = brief.build_markdown(_listing(items), now=NOW, previous=None)
    assert "실제 마감까지 13일 이내 — 매출 1건(그 밖에 대형 · 파트너형 후보 중 13일 이내 1건은 아래 「🤝」 칸)" in body
