"""38차 §3-E — 공고 직접 넣기 · GPT 결과 붙여넣기(확인 전 후보함) · 오늘 열어 본 곳.

- 입력 검증: https 만 · 필수 다섯 · **모집 대상 기본값 없음** · 길이 상한 · 제어 문자
- 중복: 나라장터 공고번호 · 기업마당 pblancId 가 저장본에 있으면 새로 만들지 않는다 · 같은 주소 두 번
- D16: 직접 넣은 공고는 자동으로 「가능」이 되지 않는다 · 공고문이 없으면 「공고문 아직 안 읽음」 · 불가는 그대로
- 붙여넣기 파서: LLM 없이 · 깨진 표 · 링크 없는 줄 · 위험한 링크 · 상한 · 저장본 대조
- 오늘 열어 본 곳: 처음 목록 주소는 두 문서에 그대로 있는 것만(지어내지 않음) · 연 시각만 적는다
- 브리핑: 기관 자체접수 칸이 찬다 · 확인 전 후보 칸 · 열어 본 곳 n/m · 모든 제목 칸 이스케이프(BRIEF-07)
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import get_settings
from app.schemas.business_opportunity import NextRoute, OpportunitySummary, UnifiedOpportunity, UnifiedOpportunityListResponse
from app.schemas.manual_notice import ManualNoticeInput
from app.schemas.procurement import ProcurementNotice
from app.services import (
    company_service,
    manual_notice_service as manual,
    notice_inbox_service as inbox,
    opportunity_brief_service as brief,
    practical_priority as practical,
    procurement_service,
    watchlist_service as watch,
)
from app.services import qualification_clause_service as qc

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 15, 3, 0, tzinfo=timezone.utc)
ORG = get_settings().default_organization_id
REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _private_clauses(tmp_path, monkeypatch):
    """조항 파일(Git 밖 공용 폴더)도 tmp 로 — 시험이 살아 있는 저장본을 쓰지 않게."""
    monkeypatch.setattr(qc, "PRIVATE_CLAUSE_DIR", tmp_path / "qualification_clauses")
    monkeypatch.setattr(procurement_service, "load_cache", lambda: None)


def _input(**extra) -> ManualNoticeInput:
    data = dict(
        url="https://www.kosac.re.kr/menus/274/bns/PBANC_00000000000514",
        title="「교원양성기관 AI 교육과정 개발·확산 컨설팅」 수행기관 모집 공고",
        agency="한국과학창의재단",
        deadline=datetime(2026, 10, 28, 16, 0, tzinfo=KST),
        recruit="operator",
        methods=["PMS/기관시스템"],
    )
    data.update(extra)
    return ManualNoticeInput(**data)


# --------------------------------------------------------------------------
# 입력 검증
# --------------------------------------------------------------------------


@pytest.mark.parametrize("url", ["http://example.go.kr/a", "javascript:alert(1)", "data:text/html,x", "https://exa mple.kr/a", "ftp://a.kr/x", ""])
def test_https_공식_주소만_받는다(url: str) -> None:
    with pytest.raises(ValidationError):
        _input(url=url)


def test_모집_대상은_기본값이_없다() -> None:
    data = _input().model_dump()
    data.pop("recruit")
    with pytest.raises(ValidationError):
        ManualNoticeInput(**data)
    with pytest.raises(ValidationError):
        _input(recruit="benefit_or_operator")


def test_필수_칸과_길이_상한() -> None:
    for field in ("title", "agency"):
        with pytest.raises(ValidationError):
            _input(**{field: "   "})
    with pytest.raises(ValidationError):
        _input(title="가" * 201)
    with pytest.raises(ValidationError):
        _input(body_text="나" * 50_001)
    assert _input(title="AI\x00 교육\x07").title == "AI 교육"  # 제어 문자는 지운다


# --------------------------------------------------------------------------
# 저장 · 중복
# --------------------------------------------------------------------------


def test_넣으면_회사_폴더에_저장하고_연락처를_가린다() -> None:
    result = manual.create(ORG, _input(body_text="문의: 홍길동 062-123-4567 hong@example.com"), created_by="담당자", now=NOW)
    notice = result.notice
    assert notice is not None and result.duplicate_of is None
    assert manual.is_manual_id(notice.id) and notice.created_by == "담당자"
    stored = manual.folder(ORG) / f"{notice.id}.json"
    text = stored.read_text(encoding="utf-8")
    assert "062-123-4567" not in text and "hong@example.com" not in text
    assert manual.list_notices(ORG)[0].id == notice.id


def test_같은_주소는_두_번_만들지_않고_회사마다_id_가_다르다() -> None:
    first = manual.create(ORG, _input(), now=NOW).notice
    again = manual.create(ORG, _input(url=_input().url + "#frag"), now=NOW)  # 조각 · 끝 슬래시는 같은 주소
    assert again.notice is None and again.duplicate_of == first.id
    assert manual.notice_id_of(ORG, _input().url) != manual.notice_id_of("org-other-company", _input().url)


def test_저장본에_있는_나라장터_공고면_그_공고로_잇는다(monkeypatch) -> None:
    notice = ProcurementNotice(id="g2b-R26BK01770001-000", notice_no="R26BK01770001-000", title="AI 교육", agency="기관", published_at=NOW)
    cached = procurement_service.ProcurementResult(source="cached", fetched_at=NOW, total_fetched=1,
                                                   notices=[procurement_service.NoticeView(notice=notice, match=None)])  # type: ignore[arg-type]
    monkeypatch.setattr(procurement_service, "load_cache", lambda: cached)
    url = "https://www.g2b.go.kr/link/PNPE027_01/single/?bidPbancNo=R26BK01770001&bidPbancOrd=000"
    result = manual.create(ORG, _input(url=url), now=NOW)
    assert result.notice is None and result.duplicate_of == "g2b-R26BK01770001-000"
    assert not list(manual.folder(ORG).glob("manual-*.json")) if manual.folder(ORG).exists() else True


def test_저장본에_있는_기업마당_공고면_그_공고로_잇는다(tmp_path, monkeypatch) -> None:
    from app.services import bizinfo_service

    cache = tmp_path / "bizinfo_cache.json"
    cache.write_text(json.dumps({"items": [{"pblancId": "PBLN_000000000123852"}]}), encoding="utf-8")
    monkeypatch.setattr(bizinfo_service, "CACHE_FILE", cache)
    result = manual.create(ORG, _input(url="https://www.jcia.or.kr/cf/Board/9562/detailView.do", body_text="원문 pblancId=PBLN_000000000123852"), now=NOW)
    assert result.duplicate_of == "bizinfo-PBLN_000000000123852"


def test_고치기_지우기는_그_회사_폴더_안에서만() -> None:
    notice = manual.create(ORG, _input(), now=NOW).notice
    updated = manual.update(ORG, notice.id, _input(title="고친 공고명"), now=NOW + timedelta(hours=1))
    assert updated.title == "고친 공고명" and updated.id == notice.id and updated.created_at == notice.created_at
    with pytest.raises(manual.ManualNoticeNotFoundError):
        manual.delete(ORG, "../../evil")
    manual.delete(ORG, notice.id)
    assert manual.list_notices(ORG) == []


# --------------------------------------------------------------------------
# 판정 — D16
# --------------------------------------------------------------------------


def _items():
    return manual.unified_items(organization_id=ORG, profile=company_service.load_profile(ORG), now=NOW)


def test_공고문이_없으면_확인_필요_공고문_아직_안_읽음() -> None:
    manual.create(ORG, _input(), now=NOW)
    manual.create(ORG, _input(url="https://www.socialenterprise.or.kr/x?id=1", title="2026 사회적가치지표 측정기업 모집", recruit="benefit"), now=NOW)
    rows = _items()
    assert {r.opportunity_type for r in rows} == {"procurement", "support_program"}
    for row in rows:
        assert row.source_type == "manual" and row.eligibility_gate == "CHECK"
        assert row.gate_reason == manual.NOT_READ_REASON and row.evidence_line == qc.NOT_READ
        assert row.next_route.kind == "manual"
    operator = next(r for r in rows if r.opportunity_type == "procurement")
    assert operator.recruit_kind == practical.RECRUIT_OPERATOR and brief.is_revenue(operator)
    benefit = next(r for r in rows if r.opportunity_type == "support_program")
    assert benefit.recruit_kind == practical.RECRUIT_BENEFIT and not brief.is_revenue(benefit)


def test_마감이_지났으면_불가는_그대로() -> None:
    manual.create(ORG, _input(deadline=datetime(2026, 10, 1, 18, 0, tzinfo=KST)), now=NOW)
    [row] = _items()
    assert row.eligibility_gate == "FAIL" and row.closed


def test_규칙이_가능이어도_사람_확인_전에는_가능이_아니다() -> None:
    gate, reason = manual._cap("PASS", "다 맞음", document_ok=True)
    assert (gate, reason) == ("CHECK", manual.HUMAN_CHECK_REASON)
    assert manual._cap("PASS", "다 맞음", document_ok=False) == ("CHECK", manual.NOT_READ_REASON)
    assert manual._cap("FAIL", "지역", document_ok=False) == ("FAIL", "지역")


def _docx(path: Path) -> bytes:
    import docx

    doc = docx.Document()
    for line in (
        "2026년 교원양성기관 AI 교육과정 개발 확산 컨설팅 수행기관 모집 공고입니다. 아래와 같이 수행기관을 모집하오니 많은 참여 바랍니다.",
        "1. 사업 개요",
        "가. 사업명: 교원양성기관 AI 교육과정 개발 확산 컨설팅",
        "3. 입찰참가자격",
        "가. 「소프트웨어 진흥법」 제58조에 따른 소프트웨어사업자(업종코드 1468)로 등록한 자",
        "나. 「중소기업기본법」 제2조에 따른 중소기업으로서 담당자 연락처 062-111-2222 로 문의",
        "4. 제출서류",
        "가. 제안서 1부",
    ):
        doc.add_paragraph(line)
    doc.save(path)
    return path.read_bytes()


def test_공고문을_올리면_조항으로_근거_줄을_달고_여전히_가능은_아니다(tmp_path) -> None:
    notice = manual.create(ORG, _input(), now=NOW).notice
    payload = _docx(tmp_path / "공고문.docx")
    saved = manual.attach_document(ORG, notice.id, file_name="공고문.docx", payload=payload, now=NOW)
    assert saved.document is not None and saved.document.status == "ok"
    clauses = qc.load(notice.id)
    assert clauses and clauses["clauses"] and "062-111-2222" not in json.dumps(clauses, ensure_ascii=False)
    [row] = _items()
    assert row.evidence_line.startswith("근거: 공고문") and row.clause_count >= 2
    assert row.eligibility_gate != "PASS"
    manual.delete(ORG, notice.id)
    assert qc.load(notice.id) is None  # 지우면 조항 파일도


@pytest.mark.parametrize(("name", "size", "message"), [("공고문.exe", 10, "파일만"), ("공고문.pdf", 0, "빈 파일"), ("공고문.pdf", 20 * 1024 * 1024 + 1, "MB")])
def test_공고문_파일_형식과_크기(name: str, size: int, message: str) -> None:
    notice = manual.create(ORG, _input(), now=NOW).notice
    with pytest.raises(manual.ManualNoticeError, match=message):
        manual.attach_document(ORG, notice.id, file_name=name, payload=b"x" * size)


def test_실무순_접수방식_이메일_PMS_0_광주전남_1() -> None:
    def item(methods: list[str], agency: str = "서울 기관") -> UnifiedOpportunity:
        return UnifiedOpportunity(
            id="manual-000000000001", source_type="manual", opportunity_type="procurement", title="t", agency=agency,
            organization_id=ORG, priority_rank=1, priority_label="검토", eligibility_gate="CHECK", confidence="low",
            score_components=[], next_route=NextRoute(kind="manual", path="/", label="열기"), source="manual",
            submission_methods=methods,
        )

    assert practical.method_rank(item(["이메일"]), home=False) == 0
    assert practical.method_rank(item(["PMS/기관시스템"]), home=False) == 0
    assert practical.method_rank(item(["나라장터"]), home=True) == 1
    assert practical.method_rank(item(["방문/우편"]), home=False) == 2
    assert practical.method_rank(item(["나라장터"]), home=False) == 3


def test_통합_목록에서_직접_넣음은_자기_갈래_안에서만_순위() -> None:
    from app.schemas.organization import AnalysisContext
    from app.services import opportunity_service

    manual.create(ORG, _input(), now=NOW)
    manual.create(ORG, _input(url="https://www.nipa.kr/home/2-2/1", title="AI 바우처 공급기업 모집"), now=NOW)
    listing = asyncio.run(opportunity_service.list_opportunities(
        context=AnalysisContext(organization_id=ORG, evidence_scope="internal"), source="manual", now=NOW, include_blocked=True,
    ))
    assert listing.manual_count == 2 and listing.g2b_count == 0 and listing.bizinfo_count == 0
    assert sorted(i.source_rank for i in listing.items) == [1, 2] and all(i.source_total == 2 for i in listing.items)
    assert listing.summary.open_manual == 2 and listing.source_status["manual"] == "manual"


# --------------------------------------------------------------------------
# 붙여넣기 파서
# --------------------------------------------------------------------------

SAMPLE = REPO / "docs" / "reports" / "2026-11-01_gpt_workflow" / "brief_2026-10-14.md"
NO_DOCS = pytest.mark.skipif(not SAMPLE.exists(), reason="사내 문서(docs/) 없음")


@NO_DOCS
def test_사업담당자_브리핑을_붙여_넣으면_링크마다_후보가_된다() -> None:
    text = SAMPLE.read_text(encoding="utf-8")
    found, rejected, without_link, truncated = inbox.parse(text)
    urls = {row["url"] for row in found}
    assert len(urls) >= 40 and rejected == []  # 「[52844](앵커)」 같은 문서 안 표시는 링크로 보지 않는다
    assert truncated == max(0, len(text.splitlines()) - 300)
    top = next(row for row in found if "bidPbancNo=R26BK01760442" in row["url"] and row["title"])
    assert top["title"] == "대학 AI 인프라 기반 구축" and top["agency"] == "인덕대학"
    prose = [row for row in found if row["line_no"] == 11]
    assert len(prose) == 4 and prose[0]["title"].startswith("AI 기반의 X-ray")


def test_깨진_표_링크_없는_줄_위험한_링크() -> None:
    text = "\n".join([
        "| 공고 | 기관 | 마감 | 링크 |",
        "|---|---|---|---|",
        "| **AI 교육 운영** | 광주광역시 | 10/30 | [바로가기](https://www.gicon.or.kr/board.es?mid=a10204000000&bid=0003&act=view&list_no=1) |",
        "| 깨진 줄 | 기관만 있음",
        "링크 없는 설명 줄입니다",
        "| 위험 | 기관 | 10/30 | [눌러](javascript:alert(1)) |",
        "옛 주소 http://www.example.go.kr/x 와 data:text/html,hi",
        "맨 주소 https://www.iris.go.kr/contents/retrieveBsnsAncmView.do?ancmId=024160&ancmPrg=ancmIng 끝",
    ])
    found, rejected, without_link, _ = inbox.parse(text)
    assert [r["title"] for r in found] == ["AI 교육 운영", "맨 주소"]
    assert found[0]["agency"] == "광주광역시" and found[0]["date_text"] == "10/30"
    reasons = sorted(r.reason for r in rejected)
    assert reasons == sorted(["위험한 링크 — 받지 않습니다", "https 가 아닌 주소 — 받지 않습니다", "위험한 링크 — 받지 않습니다"])
    assert without_link == 2


def test_상한을_넘는_줄은_보지_않는다() -> None:
    lines = [f"[공고 {n}](https://www.nipa.kr/home/2-2/{n})" for n in range(320)]
    found, _r, _w, truncated = inbox.parse("\n".join(lines))
    assert len(found) == 300 and truncated == 20


def test_붙여넣기_저장_중복_버리기_정식으로_넣기(monkeypatch) -> None:
    text = "| 공고 | 기관 | 링크 |\n|---|---|---|\n| AI 교육 | 기관 | [원문](https://www.nipa.kr/home/2-2/9) |"
    first = inbox.paste(ORG, text, now=NOW)
    again = inbox.paste(ORG, text, now=NOW)
    assert first.added == 1 and again.added == 0 and again.already_in_inbox == 1
    [entry] = inbox.pending(ORG)
    assert entry.title == "AI 교육" and entry.existing_id is None
    saved = manual.create(ORG, _input(url=entry.url, inbox_id=entry.id), now=NOW).notice
    assert inbox.pending(ORG) == [] and inbox.load(ORG)[0].manual_id == saved.id
    second = inbox.paste(ORG, text.replace("/9)", "/10)"), now=NOW).entries[0]
    gone = inbox.discard(ORG, second.id, "  교육 아님  ")
    assert gone.status == "discarded" and gone.discard_reason == "교육 아님"


# --------------------------------------------------------------------------
# 오늘 열어 본 곳
# --------------------------------------------------------------------------


@NO_DOCS
def test_처음_목록_주소는_두_문서에_그대로_있는_것만() -> None:
    docs = (REPO / "docs/reports/2026-11-01_gpt_workflow/analysis_sources.md").read_text(encoding="utf-8") + (
        REPO / "docs/reports/2026-11-03_coverage/sweep_candidates.csv").read_text(encoding="utf-8-sig") + (
        # 39차 — 대학 공동 전자조달(ebiz4u) 주소는 recheck31 10-17 탐색 자료에 그대로 있다
        REPO / "docs/reports/2026-11-05_recheck31/sweep_1017_rows.json").read_text(encoding="utf-8")
    sites = watch.defaults()
    assert len(sites) >= 25
    for site in sites:
        if site.url is None:
            assert site.memo == watch.BLANK_NOTE
            continue
        assert site.url.startswith("https://")
        host_root = "/".join(site.url.split("/")[:3]) + "/"
        assert site.url in docs or (site.memo == watch.HOME_NOTE and site.url == host_root and host_root[:-1] in docs), site.name


def test_열기는_시각만_적고_고치기는_연_때를_이어_둔다() -> None:
    site = next(s for s in watch.load(ORG) if s.url)
    assert watch.opened_today(ORG, now=NOW)[0] == 0
    watch.mark_opened(ORG, site.id, now=NOW)
    opened, total = watch.opened_today(ORG, now=NOW)
    assert opened == 1 and total == sum(1 for s in watch.defaults() if s.url)
    from app.schemas.manual_notice import WatchSiteInput

    kept = watch.replace(ORG, [WatchSiteInput(id=site.id, name=site.name + " (고침)", url=site.url), WatchSiteInput(name="새 게시판", url="https://www.nipa.kr/home/2-2")])
    assert kept[0].last_opened_at is not None and len(kept) == 2
    with pytest.raises(ValidationError):
        WatchSiteInput(name="나쁨", url="javascript:alert(1)")


# --------------------------------------------------------------------------
# 브리핑
# --------------------------------------------------------------------------


def _listing(items):
    return UnifiedOpportunityListResponse(
        organization_id=ORG, organization_name="주식회사 샘플에듀", total_count=len(items), g2b_count=0, bizinfo_count=0,
        manual_count=len(items), returned_count=len(items), closed_count=0, source_status={}, source_errors={}, fetched_at=NOW,
        summary=OpportunitySummary(open_total=len(items), open_g2b=0, open_bizinfo=0, priority=0, closed=0, closed_pinned=0, days=30, new_days=3),
        sort="practical", ranking_method="practical", field_mapping_verified=True, note="시험", items=items,
    )


def test_브리핑_기관_자체접수_칸이_차고_확인_전_후보와_열어_본_곳을_적는다() -> None:
    manual.create(ORG, _input(title="AI 교육 운영 | 제목 [눌러](javascript:alert(1)) **굵게**"), now=NOW)
    inbox.paste(ORG, "| 공고 | 기관 | 링크 |\n|---|---|---|\n| 후보 <b>굵게</b> | 기관 | [원문](https://www.nipa.kr/home/2-2/7) |", now=NOW)
    rows = _items()
    practical.annotate(rows, now=NOW, ceiling_krw=200_000_000)
    practical.order(rows, now=NOW, home_of=lambda i: False)
    body, _ = brief.build_markdown(_listing(rows), now=NOW, previous=None)
    section = body.split("# 기관 자체접수")[1].split("# 나라장터 후보")[0]
    assert "직접 넣은 공고 1건" in section and "직접 넣음" in section
    assert "[눌러](javascript" not in body and "AI 교육 운영 \\| 제목 \\[눌러\\]" in body  # 제목 칸 이스케이프(BRIEF-07)
    assert "\\<b\\>" in body and "[원문](https://www.nipa.kr/home/2-2/7)" in body
    assert "# 📥 GPT · 사람이 찾은 확인 전 후보 1건" in body
    assert "오늘 사람이 열어 본 곳 0/" in body and "직접 넣음 1건 · 확인 전 후보 1건" in body


def test_링크_주소의_괄호는_퍼센트로() -> None:
    assert brief._safe_url("https://a.kr/x(1)") == "https://a.kr/x%281%29"
    assert brief._safe_url("javascript:alert(1)") is None


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------


def test_API_넣기_목록_고치기_지우기_붙여넣기_열어본곳(client) -> None:
    bad = client.post(f"/api/manual-notices?organization_id={ORG}", json={**json.loads(_input().model_dump_json()), "url": "http://x.kr/a"})
    assert bad.status_code == 422
    body = json.loads(_input().model_dump_json())
    body.pop("recruit")
    assert client.post(f"/api/manual-notices?organization_id={ORG}", json=body).status_code == 422
    created = client.post(f"/api/manual-notices?organization_id={ORG}", json=json.loads(_input().model_dump_json()))
    assert created.status_code == 201
    notice_id = created.json()["notice"]["id"]
    assert [n["id"] for n in client.get(f"/api/manual-notices?organization_id={ORG}").json()] == [notice_id]
    upload = client.post(f"/api/manual-notices/{notice_id}/document?organization_id={ORG}", files={"file": ("x.exe", b"zz")})
    assert upload.status_code == 400
    changed = client.put(f"/api/manual-notices/{notice_id}?organization_id={ORG}", json=json.loads(_input(title="고침").model_dump_json()))
    assert changed.status_code == 200 and changed.json()["title"] == "고침"
    assert client.delete(f"/api/manual-notices/{notice_id}?organization_id={ORG}").status_code == 204
    assert client.delete(f"/api/manual-notices/{notice_id}?organization_id={ORG}").status_code == 404
    pasted = client.post(f"/api/notice-inbox/paste?organization_id={ORG}", json={"text": "[AI 교육](https://www.nipa.kr/home/2-2/3)"})
    assert pasted.status_code == 200 and pasted.json()["added"] == 1
    too_big = client.post(f"/api/notice-inbox/paste?organization_id={ORG}", json={"text": "가" * (200 * 1024 + 1)})
    assert too_big.status_code == 422
    sites = client.get(f"/api/watchlist?organization_id={ORG}").json()
    opened = client.post(f"/api/watchlist/{sites[3]['id']}/opened?organization_id={ORG}")
    assert opened.status_code == 200 and opened.json()["last_opened_at"]
    listing = client.get(f"/api/business-opportunities?organization_id={ORG}&source=manual")
    assert listing.status_code == 200
