"""39차 §3-G MANUAL-01~09 · FRONTEND-06 — 직접 넣기 · 후보함."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import get_settings
from app.schemas.manual_notice import ManualNoticeInput
from app.services import company_service, procurement_service
from app.services import manual_notice_service as manual
from app.services import notice_inbox_service as inbox
from app.services import qualification_clause_service as qc

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 15, 3, 0, tzinfo=timezone.utc)
ORG = get_settings().default_organization_id


@pytest.fixture(autouse=True)
def _sandbox(tmp_path, monkeypatch):
    from app.services import eligibility_engine

    monkeypatch.setattr(qc, "PRIVATE_CLAUSE_DIR", tmp_path / "qualification_clauses")
    monkeypatch.setattr(procurement_service, "load_cache", lambda: None)
    # 회사 소재지가 있어야 지역 규칙이 「불가」를 낼 수 있다(시험 회사 폴더는 비어 있다) — 샘플에듀 과 같은 전남광주
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
    rows = manual.unified_items(organization_id=ORG, profile=company_service.load_profile(ORG), now=NOW)
    return rows[-1]


# --------------------------------------------------------------------------
# MANUAL-01 — 지역 제한
# --------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["지역 제한 없음", "-", "해당없음", "N/A", "제한 없음(전국)", "없음(전국 가능)", "전국"])
def test_제한_없음_꼴은_불가가_아니다(text: str) -> None:
    row = _row(region_limit=text)
    assert row.eligibility_gate == "CHECK"
    assert manual.region_kind(text) == "none"


@pytest.mark.parametrize("text", ["서울 제외", "수도권 제외"])
def test_제외는_확인_필요(text: str) -> None:
    row = _row(region_limit=text)
    assert row.eligibility_gate == "CHECK"
    benefit = _row(region_limit=text, recruit="benefit", url="https://www.example.go.kr/notice/benefit-1", title=f"지원사업 {text}")
    assert benefit.eligibility_gate == "CHECK"  # 「서울 제외」가 대상 지역 서울로 읽혀 불가였다


def test_다른_지역_목록도_사람이_적은_글이면_확인_필요() -> None:
    # 40차 MANUAL-01 — 사람이 적은 글로 「불가」를 내지 않는다(39차까지는 불가 · 숨김)
    row = _row(region_limit="부산광역시")
    assert row.eligibility_gate == "CHECK"


# --------------------------------------------------------------------------
# MANUAL-03 — 같은 주소라도 공고명이 다르면 다른 공고
# --------------------------------------------------------------------------


def test_같은_게시판_주소의_다른_공고는_둘_다_넣는다() -> None:
    first = manual.create(ORG, _input(), now=NOW)
    second = manual.create(ORG, _input(title="생성형 AI 컨설팅 수행기관 모집"), now=NOW)
    assert first.notice and second.notice and first.notice.id != second.notice.id
    again = manual.create(ORG, _input(url=_input().url + "#2"), now=NOW)
    assert again.notice is None and again.duplicate_of == first.notice.id


def test_옛_id_로_저장된_공고도_같은_주소_공고명이면_중복() -> None:
    old = manual.create(ORG, _input(), now=NOW).notice
    legacy_id = manual.notice_id_of(ORG, _input().url)  # 38차 꼴(주소만)
    path = manual.folder(ORG) / f"{old.id}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["id"] = legacy_id
    path.unlink()
    (manual.folder(ORG) / f"{legacy_id}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    assert manual.create(ORG, _input(), now=NOW).duplicate_of == legacy_id


def test_붙여넣기_한_주소_두_공고는_두_줄() -> None:
    url = "https://www.kiat.or.kr/front/board/boardContentsListPage.do?board_id=90"
    text = f"| 공고 | 기관 | 링크 |\n|---|---|---|\n| AI 교육 운영 수행기관 모집 | KIAT | [바로가기]({url}) |\n| AI 컨설팅 수행기관 모집 | KIAT | [바로가기]({url}) |"
    result = inbox.paste(ORG, text, now=NOW)
    assert result.added == 2 and result.already_in_inbox == 0


def test_공고명_없이_다시_붙인_주소는_38차_줄과_id_가_겹치지_않는다() -> None:
    """39차 마지막 검토 — 38차 줄의 id 는 sha1(주소)였다. 공고명 없는 새 줄도 같은 값이면 버리기 · 넣음 표시가 옛 줄에만 걸렸다."""
    import hashlib

    url = "https://www.kiat.or.kr/front/board/boardContentsListPage.do?board_id=91"
    inbox.paste(ORG, f"| 공고 | 기관 | 링크 |\n|---|---|---|\n| AI 교육 운영 수행기관 모집 | KIAT | [바로가기]({url}) |", now=NOW)
    path = inbox.path_of(ORG)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["entries"][0]["id"] = "inbox-" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]  # 38차 꼴 id
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    inbox.paste(ORG, url, now=NOW)
    ids = [e.id for e in inbox.load(ORG)]
    assert len(ids) == 2 and len(set(ids)) == 2


# --------------------------------------------------------------------------
# MANUAL-04 · 05 · 06 — 저장본 한 번 · 상한에서 거절 · 주소 끝 글자
# --------------------------------------------------------------------------


def test_붙여넣기는_저장본을_한_번만_읽는다(monkeypatch) -> None:
    calls = []

    def counted():
        calls.append(1)
        return None

    monkeypatch.setattr(procurement_service, "load_cache", counted)
    rows = "\n".join(f"- AI 교육 {n} https://www.g2b.go.kr/link/PNPE027_01/single/?bidPbancNo=R26BK0{n:07d}&bidPbancOrd=000" for n in range(60))
    result = inbox.paste(ORG, rows, now=NOW)
    assert result.added == 60 and len(calls) == 1


def test_후보함_상한이면_지우지_않고_거절한다(monkeypatch) -> None:
    monkeypatch.setattr(inbox, "MAX_ENTRIES", 5)
    first = inbox.paste(ORG, "\n".join(f"- 옛 후보 {n} https://a.or.kr/n/{n}" for n in range(4)), now=NOW)
    second = inbox.paste(ORG, "\n".join(f"- 새 후보 {n} https://a.or.kr/m/{n}" for n in range(3)), now=NOW)
    assert first.added == 4 and second.added == 1 and second.refused_full == 2
    assert [e.title for e in inbox.pending(ORG)][:4] == [f"옛 후보 {n}" for n in range(4)]  # 오래된 후보가 그대로


def test_맨_주소_끝의_한글_전각_문장부호는_자른다() -> None:
    found, *_ = inbox.parse("자세한 것은 https://www.nipa.kr/home/2-2/12345에서 확인\nhttps://www.bizinfo.go.kr/business.cs?id=7） 마감")
    assert [r["url"] for r in found] == ["https://www.nipa.kr/home/2-2/12345", "https://www.bizinfo.go.kr/business.cs?id=7"]


# --------------------------------------------------------------------------
# MANUAL-02 · 08 — 연락처 꼴 · 선형 · 압축 상한
# --------------------------------------------------------------------------


def test_전화_꼴을_더_가린다() -> None:
    masked = procurement_service.mask_contact_text("담당 062)123-4567 · 010.1234.5678 · 010 1234 5678 · (062) 123-4567 · 2026.10.18 · 0.5")
    assert "4567" not in masked and "5678" not in masked and "2026.10.18" in masked and "0.5" in masked


def test_연락처_가림은_긴_글에서도_선형() -> None:
    started = time.perf_counter()
    procurement_service.mask_contact_text("A" * 300_000)
    assert time.perf_counter() - started < 1.0


def test_hwpx_압축_폭탄은_풀기_전에_막는다(tmp_path: Path) -> None:
    import zipfile

    from app.services import document_extractor

    bomb = tmp_path / "bomb.hwpx"
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("Contents/section0.xml", "<p>" + "가" * 2_000_000 + "</p>")  # 압축비 수천 배
    with pytest.raises(document_extractor.DocumentExtractionError):
        document_extractor.extract_hwpx(bomb)


def test_hwp_풀_크기_상한은_본문_칸을_합친_양이다(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """39차 마지막 검토 — 칸마다만 막으면 상한 안쪽 칸 여럿으로 상한의 몇십 배까지 풀렸다."""
    import io
    import zlib

    from app.services import document_extractor

    def deflate(raw: bytes) -> bytes:
        packer = zlib.compressobj(9, zlib.DEFLATED, -15)
        return packer.compress(raw) + packer.flush()

    class FakeOle:
        def __init__(self, count: int) -> None:
            header = bytearray(64)
            header[document_extractor._HEADER_FLAG_OFFSET] = 0x01  # 압축됨
            self.streams = {"FileHeader": bytes(header)}
            self.streams.update({f"BodyText/Section{i}": deflate(b"\0" * 600) for i in range(count)})

        def openstream(self, name: str | list[str]) -> io.BytesIO:
            return io.BytesIO(self.streams[name if isinstance(name, str) else "/".join(name)])

        def listdir(self) -> list[list[str]]:
            return [key.split("/") for key in self.streams if key.startswith("BodyText/")]

        def close(self) -> None:
            pass

    monkeypatch.setattr(document_extractor, "MAX_UNCOMPRESSED_BYTES", 1000)
    monkeypatch.setattr(document_extractor.olefile, "OleFileIO", lambda _path: FakeOle(1))
    document_extractor.extract_hwp(tmp_path / "one.hwp")  # 칸 하나(600)는 상한 안
    monkeypatch.setattr(document_extractor.olefile, "OleFileIO", lambda _path: FakeOle(2))
    with pytest.raises(document_extractor.DocumentExtractionError):
        document_extractor.extract_hwp(tmp_path / "two.hwp")  # 두 칸 합 1,200 > 1,000


def test_붙여넣기_한_줄은_길이_상한까지만_본다() -> None:
    started = time.perf_counter()
    found, *_ = inbox.parse("x" * 200_000 + " https://a.or.kr/n/1")
    assert time.perf_counter() - started < 2.0 and found == []  # 상한 뒤의 주소는 보지 않는다


# --------------------------------------------------------------------------
# MANUAL-09 — 범위 밖 마감
# --------------------------------------------------------------------------


def test_범위_밖_마감은_저장_때_막는다() -> None:
    with pytest.raises(ValidationError):
        _input(deadline=datetime(1, 1, 1, tzinfo=KST))


def test_읽을_때_범위_밖_마감은_그_줄만_건너뛴다() -> None:
    ok = manual.create(ORG, _input(), now=NOW).notice
    bad = manual.create(ORG, _input(title="연도를 잘못 적은 공고"), now=NOW).notice
    path = manual.folder(ORG) / f"{bad.id}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["deadline"] = "0001-01-01T00:00:00+09:00"
    path.write_text(json.dumps(payload), encoding="utf-8")
    rows = manual.unified_items(organization_id=ORG, profile=company_service.load_profile(ORG), now=NOW)
    assert [r.id for r in rows] == [ok.id]
    # 39차 마지막 검토 — 직접 넣기 탭에는 남아 고치거나 지울 수 있다(읽는 모델은 연도를 막지 않는다 · 입력만 막는다)
    assert bad.id in {n.id for n in manual.list_notices(ORG)}
    assert manual.get(ORG, bad.id).deadline.year == 1
    fixed = manual.update(ORG, bad.id, _input(title="연도를 잘못 적은 공고"), now=NOW)
    assert fixed.deadline.year >= 2000
    rows = manual.unified_items(organization_id=ORG, profile=company_service.load_profile(ORG), now=NOW)
    assert {r.id for r in rows} == {ok.id, bad.id}


# --------------------------------------------------------------------------
# 「오늘 열어 본 곳」 — 대학 공동 전자조달(ebiz4u) · 이미 저장한 회사에도 한 번
# --------------------------------------------------------------------------


def test_새_기본_곳은_저장한_회사에도_한_번_보이고_빼면_다시_붙지_않는다() -> None:
    from app.schemas.manual_notice import WatchSiteInput
    from app.services import watchlist_service as watch

    ebiz = "대학 공동 전자조달(ebiz4u) 공개 입찰"
    assert ebiz in [s.name for s in watch.defaults()]
    # 38차 꼴로 저장된 목록(offered 없음) — 새 기본 곳이 덧붙는다
    path = watch.path_of(ORG)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"sites": [{"id": "site-0000000001", "name": "광주TP", "url": "https://www.gjtp.or.kr/home/business.cs"}]}, ensure_ascii=False), encoding="utf-8")
    assert [s.name for s in watch.load(ORG)] == ["광주TP", ebiz]
    # 사람이 빼고 저장하면 다시 붙지 않는다
    watch.replace(ORG, [WatchSiteInput(name="광주TP", url="https://www.gjtp.or.kr/home/business.cs")])
    assert [s.name for s in watch.load(ORG)] == ["광주TP"]
