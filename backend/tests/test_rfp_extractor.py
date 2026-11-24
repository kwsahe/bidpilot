"""실제 한글 제안요청서용 규칙 기반 추출기 테스트.

네트워크·실제 파일을 쓰지 않는다. 실제 제안요청서에서 관찰한 문장 형태를 손으로
옮겨 만든 한글 픽스처만 사용한다.
"""

from __future__ import annotations

import pytest

from app.services.document_extractor import DocumentPage, ExtractedDocument
from app.services.rfp_extractor import (
    MAX_REQUIREMENTS,
    extract_requirements_from_document,
    extract_with_stats,
)

PROCUREMENT_ID = "g2b-TEST0001-000"


def make_doc(*pages: str, doc_format: str = "hwp") -> ExtractedDocument:
    """페이지 텍스트로 ExtractedDocument를 만든다."""
    return ExtractedDocument(
        file_name="제안요청서.hwp",
        doc_format=doc_format,  # type: ignore[arg-type]
        pages=[DocumentPage(page=i, text=t) for i, t in enumerate(pages, start=1)],
    )


def extract(*pages: str):
    return extract_requirements_from_document(PROCUREMENT_ID, make_doc(*pages))


def contents(requirements) -> list[str]:
    return [r.content for r in requirements]


# --------------------------------------------------------------------------
# 의무 표현 탐지
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "가. 계약상대자는 교육을 총 20회 이상 운영하여야 한다.",
        "나. 사업자는 착수보고서를 계약일로부터 14일 이내에 제출한다.",
        "다. 수행기관은 개인정보 보호 관련 법령을 준수한다.",
        "라. 제안서는 반드시 방문접수로 제출하며 우편접수는 인정하지 않는다.",
        "마. 교육 종료 후 만족도 조사를 실시할 것",
        "바. 계약상대자는 산출물 일체를 발주기관에 납품하여야 함",
        "사. 사전 승인 없이 자료를 외부에 유출하는 것을 금지한다.",
        "아. 강사는 교육 시작 30분 전까지 현장에 도착하도록 한다.",
        "자. 제출한 제안서의 내용은 임의로 변경할 수 없다.",
    ],
)
def test_의무_문장을_요구사항으로_추출한다(line: str) -> None:
    requirements = extract(line)
    assert len(requirements) == 1
    assert requirements[0].requirement_type == "mandatory"
    assert requirements[0].extraction_method == "RULE"


@pytest.mark.parametrize(
    "line",
    [
        "가. 본 사업의 목적은 공공기관 인공지능 역량 강화이다.",
        "나. 사업 예산은 금 140,000,000원(부가가치세 포함)이다.",
        "다. 교육 장소는 발주기관이 별도로 안내할 예정이다.",
    ],
)
def test_의무_표현이_없는_설명문은_추출하지_않는다(line: str) -> None:
    assert extract(line) == []


# --------------------------------------------------------------------------
# 권장(선택) 표현
# --------------------------------------------------------------------------


def test_권장_표현은_optional로_분류한다() -> None:
    requirements = extract(
        "○ 교육 만족도 90점 이상 달성을 권장한다.\n"
        "○ 온라인 복습 콘텐츠 제공은 가급적 포함하는 것이 바람직하다."
    )
    assert len(requirements) == 2
    assert all(r.requirement_type == "optional" for r in requirements)


def test_평가점수_문장을_가점으로_오인하지_않는다() -> None:
    """'평가점수'·'추가점수' 안의 '가점' 때문에 optional로 새지 않아야 한다."""
    requirements = extract("○ 제안사는 기술평가점수 85점 이상을 확보하여야 한다.")
    assert len(requirements) == 1
    assert requirements[0].requirement_type == "mandatory"


def test_가점_항목은_optional로_분류한다() -> None:
    requirements = extract("○ 지역업체에는 가점 2점을 부여할 수 있다.")
    assert len(requirements) == 1
    assert requirements[0].requirement_type == "optional"


# --------------------------------------------------------------------------
# 모호한 자격·실적 조건 -> check
# --------------------------------------------------------------------------


def test_유사실적_조건은_check로_남긴다() -> None:
    requirements = extract(
        "1. 입찰 참가 자격\n"
        "가. 최근 3년간 유사 용역 수행실적이 있는 업체이어야 한다."
    )
    assert len(requirements) == 1
    assert requirements[0].status == "check"
    assert requirements[0].category == "입찰참가자격"


def test_동등_이상_인력조건은_check로_남긴다() -> None:
    requirements = extract(
        "3. 참여 인력\n"
        "가. 총괄책임자는 수석감리원과 동등 이상의 경력을 보유한 자로 배치하여야 한다."
    )
    assert requirements[0].status == "check"


def test_현장설명_필참은_제출서류가_아니라_참가자격으로_분류한다() -> None:
    requirements = extract(
        "1. 입찰 참가 자격\n"
        "다. 현장설명에 참석하고, 입찰에 필요한 구비서류를 제출하여 정해진 기일 내 입찰등록을 필한 업체"
    )
    assert len(requirements) == 1
    assert requirements[0].category == "입찰참가자격"
    assert requirements[0].status == "check"


def test_문장_자체의_분류가_이전_보안_절보다_우선한다() -> None:
    requirements = extract(
        "3. 보안 및 비밀 유지\n"
        "가. 개인정보를 외부에 누설해서는 안 된다.\n"
        "나. 용역완료 후 하자가 발생한 경우 추가 비용 없이 수정·보완하여야 한다."
    )
    assert len(requirements) == 2
    assert requirements[0].category == "보안"
    assert requirements[1].category == "과업내용"


def test_보안_절_뒤의_계약해지_정산_조항은_보안으로_분류하지_않는다() -> None:
    requirements = extract(
        "3. 보안 및 비밀 유지\n"
        "가. 개인정보를 외부에 누설해서는 안 된다.\n"
        "나. 발주처는 계약을 해지할 수 있으며 정하는 바에 따라 정산하여야 한다."
    )
    assert len(requirements) == 2
    assert requirements[0].category == "보안"
    assert requirements[1].category == "기타"


@pytest.mark.parametrize(
    "stamp",
    ["나. 위 사실을 증명함", "나. 위 사실을 증명함.", "나. 위의 사실과 틀림없음을 확인합니다"],
)
def test_서식의_단독_증명_문구는_평가기준으로_추출하지_않는다(stamp: str) -> None:
    requirements = extract(
        "4. 평가 기준\n"
        "가. 최근 2년 표준재무제표를 첨부하여야 한다.\n"
        f"{stamp}"
    )
    assert [item.content for item in requirements] == ["최근 2년 표준재무제표를 첨부하여야 한다."]


def test_증명_낱말이_든_진짜_문장은_상투_문구로_지우지_않는다() -> None:
    requirements = extract(
        "4. 평가 기준\n"
        "가. 입찰보증금을 현금으로 납부할 것을 확약합니다.\n"
        "나. 위 사실을 증명함에 있어 허위가 없어야 한다."
    )
    assert len(requirements) == 2


# --------------------------------------------------------------------------
# 외부 브라우저 점검(2026-11-24) P1-05 — 분류 · 조각 · 제목
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "◦ 해당 교육 과정 및 가천대학교 학점 부여가 가능한 평가 체계 운영",
        "◦ 수강생 단계별(중간/최종) 교육 평가 진행",
    ],
)
def test_과업_절의_교육생_평가_운영은_과업이다(line: str) -> None:
    requirements = extract(f"Ⅱ. 과업 내용\n{line}")
    assert len(requirements) == 1
    assert requirements[0].item_type == "TASK"


def test_과업_절에_끼어든_입찰_평가_조항은_평가기준_그대로다() -> None:
    requirements = extract(
        "Ⅱ. 과업 내용\n"
        "제4조 (제안서 평가) ① 제안서는 기술능력과 입찰가격을 종합하여 평가하며, "
        "평가점수 비율은 기술능력 평가 70/100과 입찰가격 평가 30/100으로 한다."
    )
    assert len(requirements) == 1
    assert requirements[0].item_type == "EVALUATION"


def test_평가_절의_같은_줄은_평가기준_그대로다() -> None:
    requirements = extract(
        "Ⅴ. 평가방법 및 세부평가 배점\n"
        "◦ 해당 교육 과정 및 가천대학교 학점 부여가 가능한 평가 체계 운영"
    )
    assert len(requirements) == 1
    assert requirements[0].item_type == "EVALUATION"


def test_산출물_표의_제출_시기_칸은_앞_행과_합친다() -> None:
    requirements = extract(
        "4. 완료보고 및 산출물\n결과보고\n○ 최종산출물(종합보고서 등)\n계약기간\n만료일로부터 14일 이내"
    )
    assert len(requirements) == 1
    assert requirements[0].content == "최종산출물(종합보고서 등) 계약기간 만료일로부터 14일 이내"
    # 원문 줄은 그대로 남긴다.
    assert requirements[0].source_text == "○ 최종산출물(종합보고서 등)\n계약기간\n만료일로부터 14일 이내"


def test_무엇을_내는지_모르는_제출_시기_조각은_버린다() -> None:
    requirements = extract(
        "4. 완료보고 및 산출물\n결과보고\n최종산출물(종합보고서 등)\n계약기간\n만료일로부터 14일 이내"
    )
    assert requirements == []


def test_따로_내려온_절_번호_뒤의_절_이름은_항목이_아니다() -> None:
    requirements = extract(
        "1\n입찰 참가 자격\n"
        "① 최근 3년 내 유사 교육 용역 수행실적을 3건 이상 보유한 자\n"
        "2\n사업자 선정 방법\n"
        "가. 입찰방법 : 제한경쟁입찰"
    )
    assert "사업자 선정 방법" not in contents(requirements)
    assert "최근 3년 내 유사 교육 용역 수행실적을 3건 이상 보유한 자" in contents(requirements)


def test_따로_내려온_번호_뒤의_제출물_칸은_그대로_남는다() -> None:
    requirements = extract(
        "제출 서류\n1\n기술제안서 원본 1부 제출\n2\n가격제안서(전자투찰 / 출력본 미제출)"
    )
    assert "가격제안서(전자투찰 / 출력본 미제출)" in contents(requirements)


def test_모호_표현이_없으면_unmatched가_기본값이다() -> None:
    requirements = extract("가. 계약상대자는 교육을 총 20회 이상 운영하여야 한다.")
    assert requirements[0].status == "unmatched"


def test_자격_맥락이_아니면_유사라는_말만으로_check하지_않는다() -> None:
    requirements = extract("○ 화면 구성은 기존 시스템과 유사한 형태로 개발하여야 한다.")
    assert requirements[0].status == "unmatched"


# --------------------------------------------------------------------------
# 줄바꿈으로 끊긴 문장 이어 붙이기
# --------------------------------------------------------------------------


def test_끊긴_문장을_한_요구사항으로_이어_붙인다() -> None:
    requirements = extract(
        "가. 계약상대자는 연수단의 현지 일정에 필요한 예약사항 등 제반사항에 대하여\n"
        "출발 10일 전까지 발주기관의 사전 확인을 받아야 한다."
    )
    assert len(requirements) == 1
    requirement = requirements[0]
    assert "출발 10일 전까지" in requirement.content
    # source_text는 원문 줄을 그대로 이어 둔다.
    assert requirement.source_text.count("\n") == 1
    assert requirement.source_text.startswith("가. 계약상대자는")


def test_다음_줄이_새_글머리표면_이어_붙이지_않는다() -> None:
    requirements = extract(
        "가. 착수보고서를 제출하여야 한다.\n"
        "나. 완료보고서를 제출하여야 한다."
    )
    assert len(requirements) == 2
    assert all("\n" not in r.source_text for r in requirements)


# --------------------------------------------------------------------------
# 목차 / 제목 / 페이지 번호 배제
# --------------------------------------------------------------------------


def test_제목과_목차와_페이지번호는_요구사항이_아니다() -> None:
    requirements = extract(
        "목   차\n"
        "Ⅰ. 사업 개요 ······················ 3\n"
        "Ⅱ. 과업 내용 ······················ 7\n"
        "Ⅲ. 입찰 참가 및 사업자 선정\n"
        "1. 입찰 참가 자격\n"
        "- 12 -\n"
        "Page 12\n"
        "[서식 1] 입찰 참가 신청서\n"
        "가. 제안서는 50페이지 이내로 작성하여야 한다."
    )
    assert contents(requirements) == ["제안서는 50페이지 이내로 작성하여야 한다."]


def test_표_셀_조각과_짧은_줄은_버린다() -> None:
    requirements = extract(
        "연번\n품명\n수량\n6\nSET\n"
        "가. 납품업체는 계약기간 내에 설치를 완료하여야 한다."
    )
    assert len(requirements) == 1


def test_한_줄로_붙은_표_덤프는_문장으로_보지_않는다() -> None:
    dump = "작 성 항 목작 성 방 법" + "제안 업체의 일반 현황을 명료하게 작성하여야 한다" * 20
    requirements = extract(dump)
    assert requirements == []


# --------------------------------------------------------------------------
# 절 번호 -> 카테고리
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("heading", "expected"),
    [
        ("Ⅲ. 입찰 참가 자격", "입찰참가자격"),
        ("Ⅳ. 제안서 작성 및 제출 안내", "제출서류"),
        ("Ⅴ. 평가방법 및 세부평가 배점", "평가"),
        ("Ⅱ. 과업 내용", "과업내용"),
        ("3. 보안 및 비밀 유지", "보안"),
        ("4. 참여 인력 구성", "인력"),
        ("5. 추진 일정", "일정"),
    ],
)
def test_절_제목에서_카테고리를_끌어온다(heading: str, expected: str) -> None:
    requirements = extract(f"{heading}\n가. 관련 서류를 기한 내에 제출하여야 한다.")
    assert requirements[0].category == expected


def test_대분류가_바뀌면_이전_카테고리를_물려주지_않는다() -> None:
    requirements = extract(
        "Ⅴ. 평가방법 및 세부평가 배점\n"
        "가. 제안발표는 제안서에 명시된 총괄책임자가 직접 발표해야 함\n"
        "Ⅶ. 기자재 상세 규격\n"
        "나. 본 실습장치는 4축 로봇을 사용하여야 한다."
    )
    assert requirements[0].category == "평가"
    assert requirements[1].category != "평가"


# --------------------------------------------------------------------------
# 계약 일반조건 걸러내기
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        # 권리포기 조항 — 제안서가 대응할 내용이 아니다
        "○ 제안업체는 심사위원회 구성, 평가기준, 평가결과에 대하여 일체 이의를 제기할 수 없음",
        "○ 평가 결과에 대하여 이의를 제기할 수 없다.",
        "※ 천재지변으로 본 사업이 취소될 경우 본 계약은 자동 해지되며 이로 인한 일체의 손해배상을 청구할 수 없음",
        "○ 해석에 있어 의견을 달리할 경우 발주처의 해석에 따르고 이의를 제기할 수 없음",
        "○ 규정에 명시된 이외의 사항에 대해 분쟁이 있을 경우 통상적 관례에 따라야 함",
        # 과업 범위에서 제외한다고 못박은 문구
        "- 다음 사항은 별도 예산으로 추진하는 사항으로, 본 용역의 직접적인 과업 범위에는 포함되지 않음",
    ],
)
def test_계약_일반조건은_요구사항으로_추출하지_않는다(line: str) -> None:
    assert extract(line) == []


def test_계약조건을_걸러도_진짜_요구사항은_남는다() -> None:
    requirements = extract(
        "○ 제안업체는 평가결과에 대하여 일체 이의를 제기할 수 없음\n"
        "○ 계약상대자는 착수보고서를 계약일로부터 14일 이내에 제출하여야 한다."
    )
    assert len(requirements) == 1
    assert requirements[0].content.startswith("계약상대자는 착수보고서를")


def test_요구사항_정의서_표는_계약조건_필터를_적용하지_않는다() -> None:
    """문서가 요구사항이라고 선언한 표 항목은 문구와 무관하게 남긴다."""
    requirements = extract(
        "요구사항 고유번호\n"
        "SFR-001\n"
        "요구사항 명칭\n"
        "이의신청 처리\n"
        "요구사항 상세설명\n"
        "ㅇ 민원인이 이의를 제기할 수 없는 처분 유형을 화면에 안내하여야 한다."
    )
    assert len(requirements) == 1
    assert requirements[0].title.startswith("SFR-001")


# --------------------------------------------------------------------------
# 포함관계 중복
# --------------------------------------------------------------------------


def test_다른_요구사항에_통째로_포함되면_긴_쪽만_남긴다() -> None:
    requirements = extract(
        "○ 계약상대자는 교육 종료 후 만족도 조사를 실시하여야 하며 결과를 최종보고서에 포함한다.\n"
        "○ 계약상대자는 교육 종료 후 만족도 조사를 실시하여야 하며"
    )
    assert len(requirements) == 1
    assert "최종보고서에 포함한다" in requirements[0].content


def test_짧은_문장은_포함관계로_지우지_않는다() -> None:
    """짧은 문장은 우연히 다른 문장에 포함될 수 있어 둘 다 남긴다."""
    requirements = extract(
        "○ 산출물은 PDF로 제출한다.\n"
        "○ 계약상대자는 사업 종료 시 산출물은 PDF로 제출한다는 원칙을 지켜야 한다."
    )
    assert len(requirements) == 2


# --------------------------------------------------------------------------
# 요구사항 정의서 표
# --------------------------------------------------------------------------


REQUIREMENT_TABLE = """□ 상세 요구사항
가. 기능 요구사항(SFR)
요구사항 고유번호
SFR-001
요구사항 명칭
AI 기반 자동 취약점 탐색
요구사항 분류
기능 요구사항
요구사항상세설명
정의
AI 엔진으로 진단 대상을 식별하고 취약점 탐색을 자동 수행
세부 내용
○ 진단 대상 자산 자동 식별
○ 공격 표면 분석 및 취약점 탐지
요구사항 고유번호
SER-001
요구사항 명칭
보안요구사항 일반
요구사항 분류
보안 요구사항
요구사항상세설명
정의
공통 보안요구사항
세부 내용
○ 보안관리 체계 준수
"""


def test_요구사항_정의서_표를_요구사항으로_읽는다() -> None:
    requirements = extract(REQUIREMENT_TABLE)
    codes = [r.title.split()[0] for r in requirements]
    assert "SFR-001" in codes
    assert "SER-001" in codes

    functional = next(r for r in requirements if r.title.startswith("SFR-001"))
    assert "AI 엔진으로 진단 대상을" in functional.content
    # 정의만으로는 얇은 항목이 있어 세부 내용을 이어 담는다.
    assert "진단 대상 자산 자동 식별" in functional.content
    assert functional.category == "과업내용"
    assert functional.requirement_type == "mandatory"
    assert "요구사항 고유번호" in functional.source_text

    security = next(r for r in requirements if r.title.startswith("SER-001"))
    assert security.category == "보안"


def test_요구사항_고유번호_형식이_아니면_표로_읽지_않는다() -> None:
    requirements = extract(
        "요구사항 고유번호\n"
        "해당사항 없음\n"
        "가. 산출물은 계약 종료 전까지 제출하여야 한다."
    )
    assert len(requirements) == 1
    assert requirements[0].content.startswith("산출물은")


# --------------------------------------------------------------------------
# 중복 제거 / ID 부여 / 원문 근거
# --------------------------------------------------------------------------


def test_거의_같은_문장은_중복_제거한다() -> None:
    requirements = extract(
        "가. 계약상대자는 착수보고서를 제출하여야 한다.\n"
        "○ 계약상대자는 착수보고서를 제출하여야 한다\n"
        "나. 계약상대자는 완료보고서를 제출하여야 한다."
    )
    assert len(requirements) == 2


def test_REQ_아이디는_001부터_순차로_붙는다() -> None:
    requirements = extract(
        "가. 착수보고서를 제출하여야 한다.\n"
        "나. 중간보고서를 제출하여야 한다.\n"
        "다. 완료보고서를 제출하여야 한다."
    )
    assert [r.requirement_id for r in requirements] == ["REQ-001", "REQ-002", "REQ-003"]
    assert [r.id for r in requirements] == [
        f"{PROCUREMENT_ID}:REQ-001",
        f"{PROCUREMENT_ID}:REQ-002",
        f"{PROCUREMENT_ID}:REQ-003",
    ]
    assert all(r.procurement_id == PROCUREMENT_ID for r in requirements)


def test_페이지와_원문을_그대로_보존한다() -> None:
    line = "가. 교육은 총 20회 이상 운영하여야 한다."
    requirements = extract("표지", "Ⅱ. 과업 내용", line)
    assert len(requirements) == 1
    assert requirements[0].page == 3
    assert requirements[0].source_text == line


def test_제목은_비지_않는다() -> None:
    requirements = extract(
        "가. 계약상대자는 교육 운영에 필요한 강사, 교재, 실습 장비, 보조 인력 등 "
        "제반 사항을 자체 부담으로 준비하여야 한다."
    )
    title = requirements[0].title
    assert title
    assert len(title) <= 41  # TITLE_MAX_CHARS + 말줄임표


def test_같은_입력이면_같은_결과를_낸다() -> None:
    doc = make_doc(REQUIREMENT_TABLE, "가. 산출물을 제출하여야 한다.")
    first = extract_requirements_from_document(PROCUREMENT_ID, doc)
    second = extract_requirements_from_document(PROCUREMENT_ID, doc)
    assert [r.model_dump() for r in first] == [r.model_dump() for r in second]


def test_요구사항_수에_상한이_있다() -> None:
    page = "\n".join(
        f"가. 제{i}호 산출물을 계약 종료 전까지 제출하여야 한다." for i in range(MAX_REQUIREMENTS + 30)
    )
    requirements = extract(page)
    assert len(requirements) == MAX_REQUIREMENTS


def test_빈_문서는_빈_목록을_돌려준다() -> None:
    assert extract_requirements_from_document(PROCUREMENT_ID, make_doc()) == []


def test_서식_본문이_짧은_요구사항을_삼키지_않는다() -> None:
    """포함하는 쪽이 훨씬 길면 같은 문장의 변형이 아니라 다른 덩어리다."""
    form_dump = (
        "위 임 장 대표자성명 생년월일 주소 업체명 연락처 대리인 성명 생년월일 주소 업체명 "
        "연락처 상기인을 업체의 대표자 또는 대리인으로 위임하였음을 증명합니다. "
        "위임장에 사용하는 도장은 대표자 인장과 같아야 함 지참서류는 신분증으로 하여야 한다."
    )
    requirements = extract(
        form_dump + "\n"
        "○ 위임장에 사용하는 도장은 대표자 인장과 같아야 함"
    )
    assert any("위임장에 사용하는 도장" == r.content[:12] for r in requirements) or any(
        r.content.startswith("위임장에 사용하는 도장") for r in requirements
    )


# --------------------------------------------------------------------------
# 추출 상한 표시
# --------------------------------------------------------------------------


def _many_requirements(n: int) -> str:
    return "\n".join(
        f"○ 계약상대자는 {i}번 산출물을 기한 내에 제출하여야 한다." for i in range(n)
    )


def test_상한을_넘으면_truncated로_표시한다() -> None:
    doc = make_doc(_many_requirements(MAX_REQUIREMENTS + 30))
    result = extract_with_stats(PROCUREMENT_ID, doc)

    assert len(result.requirements) == MAX_REQUIREMENTS
    assert result.candidate_count == MAX_REQUIREMENTS + 30
    assert result.truncated is True


def test_상한_안이면_truncated가_아니다() -> None:
    doc = make_doc(_many_requirements(5))
    result = extract_with_stats(PROCUREMENT_ID, doc)

    assert len(result.requirements) == 5
    assert result.candidate_count == 5
    assert result.truncated is False


def test_candidate_count는_중복을_제거한_뒤_센다() -> None:
    """상한 전 후보 수이지 원문 줄 수가 아니다."""
    doc = make_doc(
        "○ 계약상대자는 착수보고서를 제출하여야 한다.\n"
        "○ 계약상대자는 착수보고서를 제출하여야 한다\n"
        "○ 계약상대자는 완료보고서를 제출하여야 한다."
    )
    result = extract_with_stats(PROCUREMENT_ID, doc)
    assert result.candidate_count == 2
    assert result.truncated is False


def test_extract_requirements_from_document는_기존_반환형을_지킨다() -> None:
    doc = make_doc(_many_requirements(3))
    assert extract_requirements_from_document(PROCUREMENT_ID, doc) == (
        extract_with_stats(PROCUREMENT_ID, doc).requirements
    )
