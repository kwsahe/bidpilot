"""분석 상태의 단일 출처 (0920.md §4-B-3 · ISSUE-076).

결정·검토·조건·발견 항목을 대시보드 훅만 읽고 있었다. 그래서 같은 공고가 화면마다 다른
상태로 보였다 — 대시보드 띠는 「내 결정 대기 **5**」, 사업기회의 「검토 중」 탭은 **0건**.
정의가 아예 달랐기 때문이다.

여기서 지키는 약속은 셋이다.

1. **띠와 탭이 같은 공고 집합을 낸다.** 세 경우(결정 파일만 · 파싱만 · 공개 레거시 발견
   기록만)에서 두 화면의 답이 같아야 한다.
2. **모르는 것은 0 이 아니다.** 조건을 탐지한 적이 없으면 「차단 조건 0」이 아니라 「모름」이다.
3. **공개 레거시 파일도 읽는다.** 조직 구조로 옮기기 전에 저장된 기록이 빠지면 안 된다.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.schemas.decision import DecisionRequest
from app.schemas.organization import AnalysisContext
from app.services import (
    daily_digest_service,
    decision_service,
    finding_resolution_service,
    g2b_client,
    notice_state_service,
    procurement_service,
    review_queue_service,
    rfp_parser,
)

NOW = datetime(2026, 9, 17, 3, 0, tzinfo=timezone.utc)
ORG = "org-sample"
#: 가천대 피지컬 AI 교육 — 공개 레거시 발견 처리 기록이 실제로 있는 유일한 공고.
LEGACY_NOTICE = "g2b-R26BK01707959-000"


@pytest.fixture(autouse=True)
def no_live_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _explode(**_kwargs: object) -> object:
        raise AssertionError("분석 상태를 만들다가 나라장터를 불렀습니다")

    monkeypatch.setattr(g2b_client, "fetch_bid_notices", _explode)
    monkeypatch.setattr(g2b_client, "collect_notices", _explode)
    procurement_service.clear_memo()


@pytest.fixture(autouse=True)
def own_generated_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """이 파일만의 파싱 결과 폴더.

    공용 사본(conftest 의 session 픽스처)은 **테스트 사이에 남는다.** 여기서 요구사항 파일을
    심고 저 곳에서 「파싱된 공고」를 세면, 앞 테스트가 남긴 파일 때문에 뒤 테스트가 깨진다
    (실제로 전체 실행에서만 두 건이 실패했다).
    """
    own = tmp_path / "generated"
    own.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(rfp_parser, "GENERATED_DIR", own)
    return own


@pytest.fixture()
def context() -> AnalysisContext:
    return AnalysisContext(organization_id=ORG, evidence_scope="internal")


def seed_cache(cache_file: Path, ids: list[str]) -> None:
    notices = [
        {
            "notice": {
                "id": nid,
                "notice_no": nid.replace("g2b-", ""),
                "title": f"{nid} 생성형 AI 교육 운영",
                "agency": "시험기관",
                "published_at": NOW.isoformat(),
                "deadline_at": None,
                "budget": None,
                "region": None,
                "description": None,
                "source_url": None,
                "raw_data": {},
            },
            "candidate": {},
            "pinned": False,
        }
        for nid in ids
    ]
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps({"fetched_at": NOW.isoformat(), "days": 30, "total_fetched": len(notices), "notices": notices}, ensure_ascii=False),
        encoding="utf-8",
    )


def write_requirements(procurement_id: str, statuses: list[str]) -> None:
    """파싱 결과를 심는다. `generated_dir` 픽스처가 임시 폴더로 돌려 둔다."""
    path = rfp_parser.generated_path(procurement_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "procurement_id": procurement_id,
                "requirements": [
                    {"requirement_id": f"REQ-{i:03d}", "status": status, "review_status": "unreviewed", "content": "x"}
                    for i, status in enumerate(statuses, start=1)
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# 세는 규칙
# ---------------------------------------------------------------------------


def test_요구사항_수와_확인_필요_수는_다른_값이다(context: AnalysisContext) -> None:
    """화면 배지 「요구사항 55 · 확인 필요 30」의 두 숫자다.

    「확인 필요」는 기계가 못 정한 것(status=check)이고, 「담당자 확인」은 사람이 손본
    것(review_status)이다. 둘을 한 필드로 합치면 화면이 어느 쪽인지 알 수 없다.
    """
    write_requirements("g2b-A-000", ["check", "check", "unmatched", "matched"])
    state = notice_state_service.state_of("g2b-A-000", context)
    assert state.parsed is True
    assert state.requirement_count == 4
    assert state.check_count == 2
    assert state.confirmed_count == 0


def test_손대지_않은_공고는_싼_값으로_끝낸다(context: AnalysisContext) -> None:
    """목록 100건에 파일을 다 열면 화면이 몇 초씩 걸린다."""
    state = notice_state_service.state_of("g2b-NOTHING-000", context)
    assert state.parsed is False
    assert state.requirement_count is None
    assert state.touched is False
    assert state.awaiting_decision is False


def test_조건을_탐지한_적이_없으면_0이_아니라_모름이다(context: AnalysisContext) -> None:
    """「차단 조건 0」은 «막는 것이 없다»는 뜻이다. 재 본 적 없는 것과 다르다."""
    write_requirements("g2b-B-000", ["check"])
    assert notice_state_service.state_of("g2b-B-000", context).blocking_conditions is None


def test_결정_파일이_없으면_미정이_아니라_None이다(context: AnalysisContext) -> None:
    """`load_decision` 은 파일이 없어도 「미정」을 지어서 돌려준다 — 그 둘을 구분한다."""
    write_requirements("g2b-C-000", ["check"])
    state = notice_state_service.state_of("g2b-C-000", context)
    assert state.decision is None
    assert state.awaiting_decision is True, "분석을 시작했고 결정이 안 났다"


def test_결정을_내리면_검토_중에서_빠진다(context: AnalysisContext) -> None:
    write_requirements("g2b-D-000", ["check"])
    decision_service.save_decision(
        "g2b-D-000",
        DecisionRequest(status="HOLD", reasons=["시험"], decided_by="시험담당"),
        gate=None,
        context=context,
    )
    state = notice_state_service.state_of("g2b-D-000", context)
    assert state.decision == "HOLD"
    assert state.awaiting_decision is False


# ---------------------------------------------------------------------------
# 띠 = 탭 (ISSUE-076-a)
# ---------------------------------------------------------------------------


def digest_pending(context: AnalysisContext) -> set[str]:
    payload = asyncio.run(daily_digest_service.build(context=context, now=NOW))
    return set(payload["pending_ids"])


def queue_ids(context: AnalysisContext) -> set[str]:
    return {row["procurement_id"] for row in review_queue_service.build(context=context, now=NOW)["items"]}


def test_띠의_결정_대기와_검토_중_탭이_같은_공고를_가리킨다(
    notice_cache_file: Path, context: AnalysisContext
) -> None:
    """같은 순간 띠는 5건, 탭은 0건이었다 (ISSUE-076-a).

    띠는 목록에 있는 공고만 세므로(캐시를 돈다) 탭이 더 넓을 수는 있다. 하지만 **띠에 있는
    것이 탭에 없으면 안 된다** — 담당자가 띠를 눌러 들어갔는데 빈 목록을 보게 된다.
    """
    seed_cache(notice_cache_file, ["g2b-P-000", "g2b-Q-000"])
    write_requirements("g2b-P-000", ["check", "unmatched"])

    pending = digest_pending(context)
    assert "g2b-P-000" in pending, "분석을 시작했고 결정이 안 났다"
    assert "g2b-Q-000" not in pending, "목록에 있기만 한 공고는 세지 않는다"
    # **같은 집합이어야 한다.** 띠를 누르면 「검토 중」 탭이 열리므로, 숫자가 다르면
    # 담당자가 5건을 눌러 들어가 0건을 보게 된다 (0920 §4-B-3).
    assert pending == queue_ids(context)


def test_결정_파일만_있는_공고도_두_화면이_함께_안다(
    notice_cache_file: Path, context: AnalysisContext
) -> None:
    seed_cache(notice_cache_file, ["g2b-R-000"])
    decision_service.save_decision(
        "g2b-R-000",
        DecisionRequest(status="UNREVIEWED", reasons=[], decided_by="시험담당"),
        gate=None,
        context=context,
    )
    assert "g2b-R-000" in digest_pending(context)
    assert "g2b-R-000" in queue_ids(context)


# ---------------------------------------------------------------------------
# 공개 레거시 파일 (ISSUE-076-b)
# ---------------------------------------------------------------------------


def test_공개_레거시_발견_기록을_읽는다(context: AnalysisContext) -> None:
    """가천대 피지컬의 처리 기록은 `data/public/reviews/` 에 있다.

    읽기 경로가 조직 폴더만 보고 있어서 이 기록이 「검토 중」 탭에서 통째로 빠졌다.
    결정·검토는 이미 공개 레거시를 읽고 있었고 발견 항목만 달랐다.
    """
    legacy_file = finding_resolution_service.RESOLUTION_DIR / f"{LEGACY_NOTICE}.findings.json"
    if not legacy_file.exists():
        pytest.skip("공개 레거시 발견 기록이 없다")

    listing = finding_resolution_service.load_resolutions(LEGACY_NOTICE, context)
    assert listing.resolutions, "공개 레거시 기록을 읽지 못했다"
    assert listing.legacy_result is True, "레거시로 읽었다는 사실을 말해야 한다"
    assert listing.evidence_scope == "public_demo"


def test_레거시_기록이_있는_공고는_검토_중_후보에_든다(context: AnalysisContext) -> None:
    legacy_file = finding_resolution_service.RESOLUTION_DIR / f"{LEGACY_NOTICE}.findings.json"
    if not legacy_file.exists():
        pytest.skip("공개 레거시 발견 기록이 없다")
    assert LEGACY_NOTICE in notice_state_service.touched_ids(context)


def test_다른_회사의_결과는_읽지_않는다() -> None:
    """회사 격리가 먼저다. 레거시 대체는 **기본 회사**일 때만 일어난다."""
    other = AnalysisContext(organization_id="org-test-alpha", evidence_scope="internal")
    listing = finding_resolution_service.load_resolutions(LEGACY_NOTICE, other)
    assert listing.resolutions == []
    assert listing.legacy_result is False
