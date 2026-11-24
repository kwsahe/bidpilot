"""입찰공고문 참가자격 절 뽑기 (19차 §4-A).

실제 공고문 7건(`data/public/real_rfp/`, gitignore — 이미 내려받아 둔 것)으로 절 찾기·조항
나누기·종류 가르기를 잰다. 파일이 없는 환경에서는 그 부분만 건너뛴다.

여기서 잰 것이 앱이 「지역/업종 공고서」(기준 답안)를 스스로 확인하는 근거다 — 검수자가
나라장터 화면에 값이 없어 공고문을 열어야 했던 바로 그 자리다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services import attachment_service, qualification_clause_service as qc

REAL_RFP = Path(__file__).resolve().parents[2] / "data" / "public" / "real_rfp"


def _notice_file(notice_id: str) -> tuple[Path, str]:
    folder = REAL_RFP / notice_id
    if not folder.is_dir():
        pytest.skip("실제 공고 첨부가 없는 환경")
    by_index = {int(p.name.split("_", 1)[0]): p for p in folder.iterdir() if "_" in p.name}
    names = {i: p.name.split("_", 1)[1] for i, p in by_index.items()}
    atts = [{"name": names.get(i, ""), "url": "https://www.g2b.go.kr/x" if i in names else ""}
            for i in range(max(names) + 1)]
    index = attachment_service.pick_notice_document(atts)
    assert index is not None, f"{notice_id}: 공고문 첨부를 고르지 못했다"
    return by_index[index], names[index]


def _extract(notice_id: str) -> dict:
    path, name = _notice_file(notice_id)
    return qc.extract_clauses(path, file_name=name)


def _kinds(result: dict) -> dict[str, int]:
    out: dict[str, int] = {}
    for clause in result["clauses"]:
        out[clause["kind"]] = out.get(clause["kind"], 0) + 1
    return out


# ---------------------------------------------------------------------------
# 1) 실제 공고문 7건 — 머리글 표기가 다 다르다
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("notice_id", "heading_starts", "page_from"),
    [
        ("g2b-R26BK01687776-000", "3. 입찰참가자격", 3),  # PDF · 「(아래 모든 자격을 충족하여야 함)」
        ("g2b-R26BK01688513-000", "2. 입찰참가자격", 2),  # HWPX · 조달청 서식
        ("g2b-R26BK01691972-000", "3. 입찰참가자격", 2),  # HWP · 물품
        ("g2b-R26BK01697240-000", "2. 입찰참가자격", 1),  # ZIP 안의 입찰공고서 PDF
        ("g2b-R26BK01699556-000", "4. 입찰참가자격", 1),  # PDF · 가천대 생성형
        ("g2b-R26BK01704406-000", "2. 입찰 참가자격", 2),  # HWP · 「: 아래의 조건을 모두 갖춘 업체」
        ("g2b-R26BK01707959-000", "4. 입찰참가자격", 1),  # PDF · 가천대 피지컬 (시연 동선)
    ],
)
def test_실제_공고문_일곱에서_절을_찾는다(notice_id: str, heading_starts: str, page_from: int) -> None:
    result = _extract(notice_id)
    assert result["status"] == "ok", result["note"]
    assert result["section"]["heading"].startswith(heading_starts)
    assert result["section"]["page_from"] == page_from
    assert result["clauses"], "조항을 하나도 나누지 못했다"
    for number, clause in enumerate(result["clauses"], start=1):
        assert clause["id"] == f"QC-{number:02d}"
        assert clause["page"] >= page_from


def test_감리_공고는_업종코드_6146_과_중소기업_조항이_나온다() -> None:
    result = _extract("g2b-R26BK01688513-000")
    industry = [c for c in result["clauses"] if c["kind"] == "industry"]
    assert industry and qc.industry_codes(industry[0]["text"]) == ["6146"]
    assert _kinds(result).get("company_type", 0) >= 1
    # 「2-4. 조달청 입찰참가자격 등록관련 안내」 부터는 참가자격이 아니다 — 거기서 절이 끝난다.
    assert not any("등록장소" in c["text"] or "중대재해" in c["text"] for c in result["clauses"])


def test_물품_공고는_제출서류_앞에서_멈춘다() -> None:
    result = _extract("g2b-R26BK01691972-000")
    assert len(result["clauses"]) == 4
    assert not any("제출서류" in c["text"] or "☎" in c["text"] for c in result["clauses"])


def test_압축_첨부에서는_제안요청서가_아니라_입찰공고서를_연다() -> None:
    result = _extract("g2b-R26BK01697240-000")
    assert "입찰공고서" in result["file"]
    assert _kinds(result).get("consortium") == 1  # 「공동수급 및 하도급은 불허함」


def test_서울시립대_공고는_본점_소재지_조항이_지역으로_나온다() -> None:
    result = _extract("g2b-R26BK01704406-000")
    region = [c for c in result["clauses"] if c["kind"] == "region"]
    assert region and "서울특별시" in region[0]["text"]
    assert any(qc.industry_codes(c["text"]) == ["1468"] for c in result["clauses"] if c["kind"] == "industry")


def test_가천대_생성형은_실적_조항이_둘이고_피지컬은_인력_조항이_있다() -> None:
    assert _kinds(_extract("g2b-R26BK01699556-000")).get("track_record") == 2
    assert _kinds(_extract("g2b-R26BK01707959-000")).get("staff") == 1


def test_표가_깨진_자리는_조항으로_만들지_않는다() -> None:
    """인천TP 공고문(1687776)은 자격 표가 「⋅ ⋅ ⋅ ⋅」로만 뽑힌다. 그것을 조항으로 지어내지 않는다."""
    result = _extract("g2b-R26BK01687776-000")
    assert not any("⋅" in c["text"] for c in result["clauses"])


# ---------------------------------------------------------------------------
# 2) 머리글·조항 규칙 (합성 줄)
# ---------------------------------------------------------------------------


def _lines(*texts: str) -> list[tuple[int, str]]:
    return [(1, t) for t in texts]


def test_절_밖의_입찰참가자격_낱말은_머리글이_아니다() -> None:
    lines = _lines(
        "부정당업자의 입찰참가자격 제한 처분을 받겠습니다.",
        "입찰참가자격등록증상의 상호 및 대표자가 다른 경우",
        "* 입찰참가자격의 판단기준일은 입찰참가자격등록 마감일",
    )
    assert qc.find_sections(lines) == []


def test_다음_번호_절에서_끝난다() -> None:
    lines = _lines(
        "2. 입찰참가자격",
        "가. 부정당업자에 해당하지 아니한 자",
        "나. 본점 소재지가 광주광역시인 업체",
        "3. 입찰방법",
        "가. 전자입찰",
    )
    ((start, end, heading),) = qc.find_sections(lines)
    assert (start, end, heading) == (0, 3, "2. 입찰참가자격")
    clauses = qc.split_clauses(lines[start + 1:end])
    assert [c["text"] for c in clauses] == ["부정당업자에 해당하지 아니한 자", "본점 소재지가 광주광역시인 업체"]


@pytest.mark.parametrize(
    "heading",
    [
        "2. 입찰 참가자의 자격",  # 1718661
        "다. 견적참가자격",  # 1722698 소액 수의견적
        "◐ 입찰참가자격(모두를 만족하여야 함)",  # NIA 셋
        "3-1. 입찰참가 자격",  # 1730997
        "6.\x00입찰참가자격",  # 연암대 둘 — PDF 빈칸이 NUL
    ],
)
def test_72건_실측에서_나온_머리글_표기(heading: str) -> None:
    pages = [qc.document_extractor.DocumentPage(page=1, text=f"{heading}\n가. 부정당업자에 해당하지 아니한 자\n")]
    lines = qc._lines(pages)
    sections = qc.find_sections(lines)
    assert sections, heading
    start, end, _ = sections[0]
    assert qc.split_clauses(lines[start + 1:end])[0]["text"] == "부정당업자에 해당하지 아니한 자"


def test_증명서류_문장은_머리글이_아니다() -> None:
    """1730997 — 「라. 입찰참가자격 증명서류 및 제안서는 사실대로 작성하여야 하며」를 절로 잡았었다."""
    assert qc.find_sections(_lines("라. 입찰참가자격 증명서류 및 제안서는 사실대로 작성하여야 하며")) == []


def test_작은_절_번호로_시작한_절은_다음_작은_절에서_끝난다() -> None:
    lines = _lines("3-1. 입찰참가 자격", "가. 부정당업자에 해당하지 아니한 자", "3-2. 입찰방법", "가. 전자입찰")
    ((start, end, _),) = qc.find_sections(lines)
    assert (start, end) == (0, 2)


def test_번호와_제목이_두_줄이면_번호_줄에서_절이_끝난다() -> None:
    """실측(1727923 한글 공고서) — 「2」/「입찰참가자격」/「❍ …」…/「3」/「추진일정」."""
    lines = _lines("2", "입찰참가자격", "❍ 관련 규정에 따라 입찰참가자격을 갖춘 자", "❍ 로봇 실습형 교재 개발이 가능한 자",
                   "3", "추진일정", "❍ 입찰참가자격 등록마감일시 : 2026. 9. 23.")
    ((start, end, _),) = qc.find_sections(lines)
    assert (start, end) == (1, 4)
    assert [c["text"] for c in qc.split_clauses(lines[start + 1:end])] == [
        "관련 규정에 따라 입찰참가자격을 갖춘 자", "로봇 실습형 교재 개발이 가능한 자"]
    # 쪽 번호 뒤에 조항이 이어지면 끝이 아니다.
    assert qc.find_sections(_lines("3. 입찰참가자격", "- 부정당업자가 아닌 자", "2", "- 중소기업자로서 확인서를 소지한 자"))[0][1] == 4
    # 절 안 표의 행 번호(절 번호보다 작다)도 끝이 아니다 — 실측 1712423.
    table = _lines("3. 입찰 참가 자격", "- 직접생산확인증명서를 소지한 업체", "연번 제품명", "1", "전시회,회의및 행사대행서비스",
                   "- 부정당업자에 해당하지 않는 자", "4. 입찰일정")
    assert qc.find_sections(table)[0][1] == 6


def test_표시만_한_줄에_있어도_조항으로_나누고_기타자유업종에서_끊지_않는다() -> None:
    """실측(1719524 HWPX) — 「○」 다음 줄이 조항이고, 「[기타자유업종(9999)] …」는 「기타」 절이 아니다."""
    lines = _lines(
        "3. 입찰참가자격",
        "아래의 입찰참가자격을 모두 갖춘 자이어야 합니다.",
        "○",
        "나라장터에 아래의 사항을 입찰참가자격으로 등록한 자",
        "[기타자유업종(9999)] 업종을 등록한 업체",
        "○",
        "「중소기업기본법」 제2조에 따른 중소기업자로서 확인서를 소지한 자",
        "4. 입찰일정",
    )
    ((start, end, _),) = qc.find_sections(lines)
    assert end == 7
    clauses = qc.split_clauses(lines[start + 1:end])
    assert len(clauses) == 2
    assert "9999" in clauses[0]["text"] and qc.classify(clauses[0]["text"]) == "industry"


def test_띄어쓰기만_다른_업종_이름은_한_번만_나온다() -> None:
    assert qc.industry_names("소프트웨어 사업자(컴퓨터관련서비스사업)로 신고를 필한 업체") == ["소프트웨어사업자", "컴퓨터관련서비스"]


def test_번호_없는_절은_다음_절_낱말에서_끝난다() -> None:
    """실측(가천대 피지컬 제안요청서) — 「입찰 참가 자격」 뒤에 「- 입찰방법 : …」「3 낙찰 및 계약」이 온다."""
    lines = _lines(
        "입찰 참가 자격",
        "- 부정당업자에 해당하지 아니한 자",
        "- 입찰방법 : 제한경쟁입찰, 2단계",
        "- 평가기준 및 방법 : 아래 표 참조",
    )
    ((start, end, _),) = qc.find_sections(lines)
    assert (start, end) == (0, 2)
    assert qc.find_sections(_lines("입찰 참가 자격", "- 공동수급은 허용하지 않음", "3 낙찰 및 계약", "- 대금은 완료 후 지급"))[0][1] == 2


def test_여는_말과_작은_머리글은_조항이_아니다() -> None:
    body = _lines("2-1. 아래 자격을 모두 갖춘 자", "다. 자격사항", "- 공급 가능 확인서를 제출할 수 있는 업체")
    assert [c["text"] for c in qc.split_clauses(body)] == ["공급 가능 확인서를 제출할 수 있는 업체"]


def test_꺾인_줄은_앞_조항에_이어_붙인다() -> None:
    body = _lines("가. 입찰등록마감일 현재 부정당업자로 지정되지", "아니한 업체")
    assert qc.split_clauses(body)[0]["text"] == "입찰등록마감일 현재 부정당업자로 지정되지 아니한 업체"


# ---------------------------------------------------------------------------
# 3) 종류 가르기 — 종류마다 한 건 이상
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("나라장터에 소프트웨어사업자(컴퓨터관련서비스사업)(1468)로 등록한 자", "industry"),
        ("정보시스템 감리법인(업종코드 : 6146)으로 입찰참가자격을 등록한 자", "industry"),
        ("법인등기부상 본점 소재지가 광주광역시인 업체", "region"),
        ("「중소기업기본법」에 따른 중소기업자로서 확인서를 소지한 자", "company_type"),
        ("최근 3년 이내 유사 용역 수행 실적 3건 이상", "track_record"),
        ("총괄책임자는 관련 분야 경력 5년 이상인 자", "staff"),
        ("공인 트레이너(NCT)를 2인 이상 보유한 업체", "staff"),
        ("공동수급(공동이행)은 허용하지 않음", "consortium"),
        ("부정당업자에 해당하지 아니한 자", "disqualification"),
        ("「중소기업제품 구매촉진법」제8조의2에 해당하는 자는 입찰에 참여할 수 없습니다", "disqualification"),
        ("대기업 및 중견기업 소프트웨어 사업자는 본 입찰에 참여할 수 없으며", "disqualification"),
        ("AI 관련 수행실적, 벤처기업 확인 등은 별도의 입찰참가 제한요건으로 하지 않으며", "other"),
        ("연구수행 경험이 요구되는 연구용역으로서 우선조달계약 예외를 적용하여 법인·단체 등의 입찰참가를 허용", "other"),
        ("관련 수행실적은 제안서 평가 시 [붙임 2]의 기준에 따라 평가합니다.", "other"),
        ("최근 3년 이내 지자체 관내 지역 주민을 대상으로 캠프를 성공적으로 운영한 실적이 있는 업체", "track_record"),
        ("공고일 현재 시 관내 업체로서 등록을 마친 자", "region"),
        ("실적은 실적증명서, 계약서 등 객관적 증빙 자료로 확인합니다.", "other"),
        ("현장설명에 참가한 업체로서 등록을 필한 업체", "other"),
        ("세부품명번호 10자리<교육훈련장비(6010999901)>로 등록된 자", "other"),
    ],
)
def test_조항_종류(text: str, kind: str) -> None:
    assert qc.classify(text) == kind


def test_국가기술자격은_사람_조항이_아니다() -> None:
    """「국가기술자격」 안의 「기술자」를 사람으로 읽으면 과정 보유 조항이 인력 조항이 된다."""
    assert qc.classify("국가기술자격 취득 과정을 자사 교육과정으로 보유·운영 중인 자") != "staff"


@pytest.mark.parametrize(
    ("text", "codes"),
    [
        ("SW사업자(1426/1468/1469/1470) 중 하나", ["1426", "1468", "1469", "1470"]),
        ("업종코드 1468 에 등록", ["1468"]),
        ("규격입찰접수처 : 총무팀(☎ 053-589-7732)", []),  # 전화번호
        ("정부조달콜센터(☎ 지역번호없이 1588-0800)", []),
        ("사업기간(2026년) 내", []),
    ],
)
def test_업종_코드는_괄호_안_코드_모양일_때만(text: str, codes: list[str]) -> None:
    assert qc.industry_codes(text) == codes


# ---------------------------------------------------------------------------
# 4) 공고 하나 — 내려받지 않고, 없으면 없다고 적는다
# ---------------------------------------------------------------------------


def test_내려받지_않은_공고문은_not_fetched(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(attachment_service, "CACHE_DIR", tmp_path / "real_rfp")
    atts = [{"name": "입찰공고문.pdf", "url": "https://www.g2b.go.kr/x"}]
    payload = qc.build_payload("g2b-TEST-000", atts)
    assert payload["status"] == "not_fetched"
    assert payload["clauses"] == []
    assert "내려받지 않았습니다" in payload["note"]


def test_공고문_첨부가_없으면_그렇게_적는다(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(attachment_service, "CACHE_DIR", tmp_path / "real_rfp")
    payload = qc.build_payload("g2b-TEST-000", [{"name": "제안요청서.hwp", "url": "https://www.g2b.go.kr/x"}])
    assert payload["status"] == "not_fetched"
    assert "입찰공고문이 없습니다" in payload["note"]


def test_저장하고_다시_읽는다(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(qc, "CLAUSE_DIR", tmp_path / "qualification_clauses")
    qc._MEMO.clear()
    payload = {"notice_id": "g2b-TEST-000", "status": "ok", "clauses": [{"id": "QC-01", "text": "t", "page": 1, "kind": "other"}]}
    qc.save(payload)
    assert qc.load("g2b-TEST-000")["clauses"][0]["id"] == "QC-01"
    assert qc.load("g2b-NONE-000") is None
    assert qc.load(None) is None
