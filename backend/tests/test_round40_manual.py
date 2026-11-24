"""40차 §3-G — 직접 넣기 · 내보내기(MANUAL-01~06 · RANK-01). 호출 없음."""

from __future__ import annotations

import io
import json
import zlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import get_settings
from app.schemas.manual_notice import ManualNoticeInput
from app.services import company_service, document_extractor, procurement_service
from app.services import manual_notice_service as manual
from app.services import notice_inbox_service as inbox
from app.services import opportunity_brief_service as brief
from app.services import qualification_clause_service as qc

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 15, 3, 0, tzinfo=timezone.utc)
ORG = get_settings().default_organization_id


@pytest.fixture(autouse=True)
def _sandbox(tmp_path, monkeypatch):
    from app.services import eligibility_engine

    monkeypatch.setattr(qc, "PRIVATE_CLAUSE_DIR", tmp_path / "qualification_clauses")
    monkeypatch.setattr(procurement_service, "load_cache", lambda: None)
    monkeypatch.setattr(eligibility_engine, "company_facts_for", lambda *_a, **_k: eligibility_engine.CompanyFacts(location_region="전남광주"))


def _input(**extra) -> ManualNoticeInput:
    data = dict(
        url="https://www.kiat.or.kr/front/board/boardContentsListPage.do?board_id=90", title="AI 교육 운영 수행기관 모집",
        agency="한국산업기술진흥원", deadline=datetime(2026, 10, 28, 16, 0, tzinfo=KST), recruit="bid", methods=["이메일"],
    )
    data.update(extra)
    return ManualNoticeInput(**data)


def _row(**extra):
    manual.create(ORG, _input(**extra), now=NOW)
    return manual.unified_items(organization_id=ORG, profile=company_service.load_profile(ORG), now=NOW)[-1]


# --------------------------------------------------------------------------
# MANUAL-01 — 사람이 적은 지역 제한으로 「불가」를 내지 않는다
# --------------------------------------------------------------------------

ELEVEN = ["서울 외 지역", "수도권 이외", "타지역 불가", "있음", "지역 제한 있음(공고문 참조)", "관내 기업", "본사 소재지 기준",
          "없음(공고문 확인)", "제한 없음 - 공고문 참조", "전국 누구나 가능", "전국 대상"]


@pytest.mark.parametrize("text", ELEVEN)
def test_사람이_적은_지역_글_11꼴은_불가가_아니다(text: str) -> None:
    row = _row(region_limit=text)
    assert row.eligibility_gate == "CHECK", (text, row.gate_reason)
    benefit = _row(region_limit=text, recruit="benefit", url=f"https://www.example.go.kr/notice/b-{abs(hash(text))}", title=f"지원사업 {text}")
    assert benefit.eligibility_gate != "FAIL", (text, benefit.gate_reason)


@pytest.mark.parametrize(("text", "kind"), [
    ("서울 외 지역", "exclude"), ("수도권 이외", "exclude"), ("타지역 불가", "exclude"), ("비수도권", "exclude"), ("서울 제외", "exclude"),
    ("있음", "unknown"), ("지역 제한 있음(공고문 참조)", "unknown"), ("관내 기업", "unknown"), ("본사 소재지 기준", "unknown"),
    ("없음(공고문 확인)", "none"), ("제한 없음 - 공고문 참조", "none"), ("전국 누구나 가능", "none"), ("전국 대상", "none"), ("N/A", "none"),
    ("부산광역시", "list"), ("광주 · 전남", "list"), ("광주광역시 소재 기업", "list"), ("서울, 관내", "unknown"), ("", "blank"),
])
def test_지역_글의_갈래(text: str, kind: str) -> None:
    assert manual.region_kind(text) == kind


def test_다른_지역_목록이어도_사람이_적은_글이면_확인_필요() -> None:
    row = _row(region_limit="부산광역시")
    assert row.eligibility_gate == "CHECK"
    benefit = _row(region_limit="부산광역시", recruit="benefit", url="https://www.example.go.kr/notice/busan", title="부산 지원사업")
    assert benefit.eligibility_gate == "CHECK"


# --------------------------------------------------------------------------
# MANUAL-02 — 공고일 범위 · 줄 건너뛰기
# --------------------------------------------------------------------------


@pytest.mark.parametrize("published", [date(1, 1, 1), date(1999, 12, 31), date(2101, 1, 1)])
def test_공고일_연도가_이상하면_저장_때_막는다(published: date) -> None:
    with pytest.raises(ValidationError):
        _input(published_on=published)


def test_공고일이_오늘보다_늦거나_마감보다_늦으면_막는다() -> None:
    with pytest.raises(ValidationError):
        _input(published_on=datetime.now(KST).date() + timedelta(days=2))
    with pytest.raises(ValidationError):
        _input(published_on=date(2026, 10, 29), deadline=datetime(2026, 10, 28, 16, 0, tzinfo=KST))
    assert _input(published_on=date(2026, 10, 1)).published_on == date(2026, 10, 1)


def test_읽을_때_범위_밖_공고일은_그_줄만_건너뛰고_탭에는_남는다() -> None:
    ok = manual.create(ORG, _input(), now=NOW).notice
    bad = manual.create(ORG, _input(title="공고일을 잘못 적은 공고"), now=NOW).notice
    path = manual.folder(ORG) / f"{bad.id}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["published_on"] = "0001-01-01"
    path.write_text(json.dumps(payload), encoding="utf-8")
    rows = manual.unified_items(organization_id=ORG, profile=company_service.load_profile(ORG), now=NOW)
    assert [r.id for r in rows] == [ok.id]
    assert manual.get(ORG, bad.id).published_on == date(1, 1, 1)  # 직접 넣기 탭에서 고치거나 지울 수 있다


# --------------------------------------------------------------------------
# MANUAL-03 — 압축 폭탄(HWP 칸마다 압축비 · PDF 추출 전 검사)
# --------------------------------------------------------------------------


def _deflate(raw: bytes, wbits: int = -15) -> bytes:
    packer = zlib.compressobj(9, zlib.DEFLATED, wbits)
    return packer.compress(raw) + packer.flush()


class _FakeOle:
    def __init__(self, body: bytes) -> None:
        header = bytearray(64)
        header[document_extractor._HEADER_FLAG_OFFSET] = 0x01
        self.streams = {"FileHeader": bytes(header), "BodyText/Section0": _deflate(body)}

    def openstream(self, name):
        return io.BytesIO(self.streams[name if isinstance(name, str) else "/".join(name)])

    def listdir(self):
        return [key.split("/") for key in self.streams if key.startswith("BodyText/")]

    def close(self) -> None:
        pass


def test_hwp_칸의_압축비가_비정상이면_거절(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(document_extractor.olefile, "OleFileIO", lambda _p: _FakeOle(b"\0" * (3 * 1024 * 1024)))  # 3MB · 압축비 수천
    with pytest.raises(document_extractor.DocumentExtractionError, match="압축 비율"):
        document_extractor.extract_hwp(tmp_path / "bomb.hwp")
    monkeypatch.setattr(document_extractor.olefile, "OleFileIO", lambda _p: _FakeOle(b"\0" * 600_000))  # 작은 칸은 압축비를 보지 않는다
    document_extractor.extract_hwp(tmp_path / "small.hwp")


def _pdf(content: bytes) -> bytes:
    """FlateDecode 내용 스트림 하나짜리 PDF — 상호 참조표까지 맞춘다."""
    stream = _deflate(content, 15)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" /Filter /FlateDecode >>\nstream\n" + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def test_pdf_는_추출_전에_스트림_압축비_합계를_본다(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bomb = tmp_path / "bomb.pdf"
    bomb.write_bytes(_pdf(b"0 0 m\n" * 600_000))  # 3.6MB 가 수 KB 로 — 압축비 수백
    with pytest.raises(document_extractor.DocumentExtractionError):
        document_extractor.extract_pdf(bomb)
    plain = tmp_path / "plain.pdf"
    plain.write_bytes(_pdf(b"BT /F1 12 Tf 10 10 Td (hello) Tj ET\n" * 20))
    document_extractor._check_pdf_streams(plain)  # 정상 크기는 통과
    monkeypatch.setattr(document_extractor, "MAX_UNCOMPRESSED_BYTES", 300)
    with pytest.raises(document_extractor.DocumentExtractionError):
        document_extractor._check_pdf_streams(plain)  # 합계 상한


def test_업로드는_이벤트_루프_밖에서_읽는다() -> None:
    import inspect

    from app.api import manual as manual_api

    assert "run_in_threadpool" in inspect.getsource(manual_api.upload_manual_document)


# --------------------------------------------------------------------------
# MANUAL-04 · 05 · 06 · RANK-01
# --------------------------------------------------------------------------


@pytest.mark.parametrize(("raw", "kept"), [
    ("https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schStr=인공지능&page=2", "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schStr=인공지능&page=2"),
    ("https://www.example.go.kr/list?q=인공지능", "https://www.example.go.kr/list?q=인공지능"),
    ("https://www.example.go.kr/list?q=인공지능）", "https://www.example.go.kr/list?q=인공지능"),
    ("https://www.nipa.kr/home/2-2/12345에서", "https://www.nipa.kr/home/2-2/12345"),
    ("https://www.bizinfo.go.kr/business.cs?id=7）", "https://www.bizinfo.go.kr/business.cs?id=7"),
    ("https://www.example.go.kr/a/1，마감", "https://www.example.go.kr/a/1"),
    ("https://www.example.go.kr/reg」.", "https://www.example.go.kr/reg"),
])
def test_주소_끝은_붙은_한글_전각_부호만_자른다(raw: str, kept: str) -> None:
    assert inbox.trim_url_tail(raw) == kept


def test_붙여넣기도_쿼리_값의_한글을_남긴다() -> None:
    found, *_ = inbox.parse("후보 https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schStr=인공지능&page=2 확인")
    assert found[0]["url"].endswith("schStr=인공지능&page=2")


def test_브리핑_링크의_세로줄은_퍼센트로() -> None:
    assert brief._safe_url("https://www.example.go.kr/board?ids=1|2") == "https://www.example.go.kr/board?ids=1%7C2"


def test_내보내기_md_는_브리핑과_같은_이스케이프와_출처_안_순위() -> None:
    from app.schemas.business_opportunity import UnifiedOpportunity
    from app.services import opportunity_export_service as export

    assert "출처 안 순위" in export.COLUMNS and "추천순" not in export.COLUMNS
    item = UnifiedOpportunity.model_construct(
        id="manual-1", source_type="manual", opportunity_type="procurement", title="AI 교육 [공식 공고](https://phish.example) <b>확인</b>\r줄",
        agency="기관|본부", priority_rank=204, source_rank=2, eligibility_gate="CHECK", gate_reason=None, detail_url="https://www.example.go.kr/a?x=1|2",
        deadline=None, deadline_text="공고에 마감일 없음", budget=None, work_tracks=[], award_line=None, category=None, fit_line=None,
        caution_line=None, company_priority_score=None, practical_group=None, fit_type=None, submission_methods=[], published_at=None,
    )
    row = export._row(item)
    assert row[2] == "2"  # 섞인 통합 순위 204 가 아니라 출처 안 순위
    listing = type("L", (), {"items": [item], "organization_name": "시험", "summary": type("S", (), {"days": 30, "open_total": 1, "open_g2b": 0, "open_bizinfo": 0})(),
                             "total_count": 1, "blocked_count": 0})()
    md = export.to_markdown(listing)  # type: ignore[arg-type]
    line = next(l for l in md.splitlines() if "manual-1" in l)
    # 대괄호가 이스케이프돼 링크가 되지 않는다 · 꺾쇠(HTML) · CR 도
    assert "\\[공식 공고\\](https://phish" in line and " [공식 공고](" not in line and "\\<b\\>" in line and "\r" not in line
    assert "기관\\|본부" in line and line.rstrip().endswith("https://www.example.go.kr/a?x=1%7C2 |")
