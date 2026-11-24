"""입찰참가신청서 서식 초안 테스트.

핵심은 두 가지다.
- 근거가 있는 칸만 채우고, 값마다 어느 쪽에서 왔는지 남긴다.
- 회사 식별정보와 개인정보(특히 주민등록번호)는 절대 채우지 않는다.
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone

import docx
import pytest

from app.schemas.procurement import ProcurementNotice
from app.services import bid_application_export as bae

KST = timezone(timedelta(hours=9))

# 실제 입찰공고문 4쪽(가천대 공고)의 서식 문구를 그대로 옮긴 것.
PAGE_4 = """[붙임1]
입찰참가신청서 처 리 기 간
상 호 법인등록번호
입 찰 공 고
제 산학202610082호 입 찰 일 자 2026년 09월 15일 10:00
찰 (지명)번호
* 보증금율 : 입찰금액의 10 %
* 보증금납부방법 : 보증보험증권
붙임서류 : 1. 입찰참가 신청서 1부.
2. 사업자등록증사본 및 법인등기부등본(법인에 한함) 각 1통.
3. 인감증명서 1통(사용인감계 1부).
20 . . .
신 청 인 (대표자) : (인)
"""
# 앞쪽에도 '10'과 '보증보험증권'이 나온다 — 값만으로 쪽을 찾으면 여기가 잡힌다.
PAGE_1 = "입찰공고 제 산학202610082호\n납부방법은 보증보험증권 10 건 참고"


def notice() -> ProcurementNotice:
    return ProcurementNotice(
        id="g2b-TEST0001-000",
        notice_no="TEST0001-000",
        title="가천대학교 AI부트캠프 사업 생성형 AI 활용 교육 기획·운영 위탁 용역(2026-2학기)",
        agency="가천대학교 산학협력단",
        published_at=datetime(2026, 8, 26, tzinfo=KST),
        deadline_at=datetime(2026, 9, 15, 10, 0, tzinfo=KST),
        budget=27_934_500,
    )


def pages() -> list[tuple[int, str]]:
    return [(1, PAGE_1), (2, ""), (3, ""), (4, PAGE_4)]


def text_of(payload: bytes) -> str:
    document = docx.Document(io.BytesIO(payload))
    parts = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            parts.extend(cell.text for cell in row.cells)
    return "\n".join(parts)


# --------------------------------------------------------------------------
# 채우는 것
# --------------------------------------------------------------------------


def test_공고와_입찰공고문에서_채울_수_있는_칸을_채운다() -> None:
    draft = bae.build_draft(notice(), pages(), identity={})
    values = {f.label: f.value for f in draft.all_fields}
    assert values["입찰공고(지명)번호"] == "제 산학202610082호"
    assert values["입 찰 일 자"] == "2026년 09월 15일 10:00"
    assert values["입 찰 건 명"] == notice().title
    assert values["보 증 금 율"] == "입찰금액의 10 %"
    assert values["보증금납부방법"] == "보증보험증권"
    assert draft.filled_count == 5


def test_값이_실제로_나온_쪽을_근거로_적는다() -> None:
    """'10'이나 '보증보험증권'은 1쪽에도 나온다. 서식이 있는 4쪽을 집어야 한다."""
    draft = bae.build_draft(notice(), pages(), identity={})
    sources = {f.label: f.source for f in draft.all_fields}
    assert sources["보 증 금 율"] == "입찰공고문 p.4"
    assert sources["보증금납부방법"] == "입찰공고문 p.4"
    assert sources["입 찰 일 자"] == "입찰공고문 p.4"


def test_붙임서류를_번호와_함께_옮긴다() -> None:
    draft = bae.build_draft(notice(), pages(), identity={})
    assert len(draft.documents) == 3
    assert draft.documents[0].startswith("1. 입찰참가 신청서")
    assert draft.documents_source == "입찰공고문 p.4"


def test_입찰공고문이_없으면_공고_마감일로_입찰일자를_채운다() -> None:
    draft = bae.build_draft(notice(), [], identity={})
    values = {f.label: f.value for f in draft.all_fields}
    assert values["입 찰 일 자"] == "2026년 09월 15일 10:00"
    sources = {f.label: f.source for f in draft.all_fields}
    assert sources["입 찰 일 자"] == "공고 마감일시"
    # 입찰공고문에서만 알 수 있는 값은 비어 있어야 한다 (추측 금지)
    assert values["입찰공고(지명)번호"] == ""
    assert values["보 증 금 율"] == ""


# --------------------------------------------------------------------------
# 채우지 않는 것 — 이 규칙이 깨지면 안 된다
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label",
    ["상 호", "법인등록번호", "주 소", "전 화 번 호", "대 표 자", "주민등록번호",
     "대리인 성명", "대리인 주민등록번호", "사 용 인 감", "보 증 액"],
)
def test_회사_식별정보와_개인정보는_비워_둔다(label: str) -> None:
    draft = bae.build_draft(notice(), pages(), identity={})
    field = next(f for f in draft.all_fields if f.label == label)
    assert field.value == "", f"{label} 을 자동으로 채우면 안 된다"
    assert field.source, "빈칸에도 왜 비었는지는 적어야 한다"


def test_주민등록번호_칸은_개인정보라고_밝힌다() -> None:
    draft = bae.build_draft(notice(), pages(), identity={})
    for label in ("주민등록번호", "대리인 주민등록번호"):
        field = next(f for f in draft.all_fields if f.label == label)
        assert "개인정보" in field.source


def test_문서에_주민등록번호_형태의_숫자가_없다() -> None:
    """서식 문서에 6-7자리 주민등록번호 꼴이 들어가면 안 된다."""
    import re

    text = text_of(bae.build_document(bae.build_draft(notice(), pages(), identity={})))
    assert not re.search(r"\d{6}\s*-\s*\d{7}", text)


# --------------------------------------------------------------------------
# 문서
# --------------------------------------------------------------------------


def test_문서는_서식_표와_안내를_담는다() -> None:
    text = text_of(bae.build_document(bae.build_draft(notice(), pages(), identity={})))
    assert "입 찰 참 가 신 청 서" in text
    assert "AI가 채운 초안입니다" in text
    assert "가천대학교 산학협력단 귀중" in text
    assert "제 산학202610082호" in text
    assert "입찰공고문 p.4" in text
    assert "담당자 입력" in text


def test_표에_빈칸이_그대로_보인다() -> None:
    text = text_of(bae.build_document(bae.build_draft(notice(), pages(), identity={})))
    assert "(빈칸)" in text


def test_docx_pdf_외_형식은_거부한다() -> None:
    import asyncio

    with pytest.raises(bae.BidApplicationError):
        asyncio.run(bae.export_application("g2b-TEST0001-000", fmt="txt"))


# --------------------------------------------------------------------------
# 회사 공개 등록정보 (상호·주소·전화번호)
# --------------------------------------------------------------------------

IDENTITY = {
    "name": "주식회사 샘플에듀",
    "address": "전남광주통합특별시 북구 가상로 77, 303호",
    "phone": "062-000-0000",
}


def test_등록된_회사정보로_신청인_칸을_채운다() -> None:
    draft = bae.build_draft(notice(), pages(), identity=IDENTITY)
    values = {f.label: f.value for f in draft.all_fields}
    assert values["상 호"] == "주식회사 샘플에듀"
    assert values["주 소"].startswith("전남광주통합특별시")
    assert values["전 화 번 호"] == "062-000-0000"
    sources = {f.label: f.source for f in draft.all_fields}
    assert sources["상 호"] == bae.IDENTITY_SOURCE


def test_회사정보를_채워도_개인정보_칸은_비운다() -> None:
    """상호를 채우는 것과 대표자 개인정보를 채우는 것은 다른 문제다."""
    draft = bae.build_draft(notice(), pages(), identity=IDENTITY)
    values = {f.label: f.value for f in draft.all_fields}
    for label in ("대 표 자", "주민등록번호", "대리인 성명", "대리인 주민등록번호", "사 용 인 감"):
        assert values[label] == "", f"{label} 은 개인정보라 채우면 안 된다"


def test_등록정보에_없는_법인등록번호는_비운다() -> None:
    draft = bae.build_draft(notice(), pages(), identity=IDENTITY)
    field = next(f for f in draft.all_fields if f.label == "법인등록번호")
    assert field.value == "" and field.source == bae.TODO


def test_등록정보_파일이_없으면_신청인_칸을_비운다() -> None:
    draft = bae.build_draft(notice(), pages(), identity={})
    values = {f.label: f.value for f in draft.all_fields}
    assert values["상 호"] == "" and values["주 소"] == "" and values["전 화 번 호"] == ""


def test_등록정보_파일의_허용되지_않은_키는_서식에_새지_않는다(tmp_path, monkeypatch) -> None:
    """파일에 주민등록번호 같은 값이 들어와도 화이트리스트가 막는다."""
    target = tmp_path / "company_identity.json"
    target.write_text(
        json.dumps(
            {"name": "주식회사 샘플에듀", "resident_number": "800101-1234567", "ceo": "홍길동"},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(bae, "IDENTITY_FILE", target)
    loaded = bae.load_identity()
    assert loaded == {"name": "주식회사 샘플에듀"}
    assert "resident_number" not in loaded and "ceo" not in loaded


def test_등록정보_파일이_깨져도_서식은_나온다(tmp_path, monkeypatch) -> None:
    target = tmp_path / "company_identity.json"
    target.write_text("{ 깨진 json", encoding="utf-8")
    monkeypatch.setattr(bae, "IDENTITY_FILE", target)
    assert bae.load_identity() == {}


def test_실제_등록정보_파일이_읽힌다() -> None:
    """저장소에 넣어 둔 회사 정보가 실제로 로드되는지 (경로 오타 방지)."""
    loaded = bae.load_identity()
    if not loaded:
        pytest.skip("data/company/company_identity.json 이 없는 환경")
    assert loaded.get("name") == "주식회사 샘플에듀"
    assert "resident" not in json.dumps(loaded, ensure_ascii=False)


def test_회사정보를_채운_문서에도_주민등록번호_꼴_숫자가_없다() -> None:
    import re

    text = text_of(bae.build_document(bae.build_draft(notice(), pages(), identity=IDENTITY)))
    assert not re.search(r"\d{6}\s*-\s*\d{7}", text)
    assert "주식회사 샘플에듀" in text
