from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

RequirementType = Literal["mandatory", "optional"]
RequirementStatus = Literal["matched", "partial", "unmatched", "check"]
ExtractionMethod = Literal["RULE", "AI_EXTRACTION", "HUMAN"]

# 문서 항목 유형 — "무엇을 수행"(TASK) / "어떤 조건"(REQUIREMENT·ELIGIBILITY) /
# "무엇을 언제 제출"(SUBMISSION·SCHEDULE) / 평가·특이사항·참고를 구분한다 (services/item_classifier.py).
ItemType = Literal[
    "TASK",
    "REQUIREMENT",
    "ELIGIBILITY",
    "SUBMISSION",
    "SCHEDULE",
    "EVALUATION",
    "SPECIAL_CONDITION",
    "REFERENCE",
]
Criticality = Literal["blocker", "high", "normal", "low"]
# 이 요구사항에 «어디서» 답하는가. 항목 유형이 "무엇인가"라면 이쪽은 "어떻게 대응하는가"다.
# Auditor가 계약 일반조건을 제안서 본문 누락으로 단정하지 않도록 하는 축이다
# (services/item_classifier.py 의 ResponseScope 와 같은 어휘).
ResponseScope = Literal[
    "PROPOSAL_BODY",
    "ELIGIBILITY_DOCUMENT",
    "SUBMISSION_CHECKLIST",
    "PRICE_PROPOSAL",
    "CONTRACT_COMPLIANCE",
    "INTERNAL_ACTION",
    "REFERENCE_ONLY",
    "CONDITIONAL",
    "NOT_APPLICABLE",
]
# 담당자 검토 상태. 시스템은 unreviewed로만 만들고 confirmed/corrected/rejected는 사람이 정한다.
ReviewStatus = Literal["unreviewed", "confirmed", "corrected", "rejected"]

# 저장 문서 스키마 버전.
#   1 = 항목 유형 이전
#   2 = item_type·criticality·display_code 포함
#   3 = 안정 ID(stable_id)·대응 범위(response_scope)·요구사항 집합 신원 포함
REQUIREMENT_SCHEMA_VERSION = 3


class Requirement(BaseModel):
    """RFP에서 구조화한 항목 1건. page와 source_text는 원문 근거로 반드시 보존한다.

    `requirement_id`(REQ-nnn)는 저장·참조 키라 유형이 바뀌어도 그대로다.
    화면에는 유형 접두어를 붙인 `display_code`(TSK-nnn 등)를 보여준다.
    """

    id: str
    procurement_id: str
    requirement_id: str = Field(pattern=r"^REQ-\d{3}$")
    category: str
    requirement_type: RequirementType
    title: str
    content: str = Field(min_length=1)
    page: int | None = Field(default=None, ge=1)
    source_text: str = Field(min_length=1)
    status: RequirementStatus = "unmatched"
    extraction_method: ExtractionMethod = "RULE"

    # --- 항목 유형 (schema_version 2). 예전 파일은 읽을 때 분류기가 채운다. ---
    item_type: ItemType = "REQUIREMENT"
    criticality: Criticality = "normal"
    # 자격·제출·일정·특이사항처럼 담당자의 행동(등록·참석·서류 준비)이 필요한 항목.
    action_required: bool = False
    # 본문에 날짜가 명시된 경우에만 채운다 (KST). 추측하지 않는다.
    due_at: datetime | None = None
    # HWP/HWPX 문단 근사 페이지면 True (RfpParseResult.page_is_approximate를 항목에도 복사).
    page_is_approximate: bool = False
    review_status: ReviewStatus = "unreviewed"
    # --- schema_version 3: 번호가 밀려도 끊기지 않는 신원 ------------------
    #
    # requirement_id(REQ-nnn)는 문서 등장 순서 일련번호라, 문서 중간에 항목이 하나
    # 끼면 뒤 번호가 전부 밀린다. 그 상태로 옛 제안서를 읽으면 다른 요구사항을
    # 가리킨다 (실측: 19문장 중 5문장). 그래서 내용에서 결정론적으로 나오는
    # 영구 식별자를 따로 둔다. requirement_id 는 형식이 스키마에 고정돼 있고
    # 하류 전체가 외래키로 쓰므로 **바꾸지 않는다**.
    #
    # 옛 파일에는 없으므로 None 을 허용하고, 읽을 때 채운다 (services/requirement_set.py).
    stable_id: str | None = None
    #: 정규화한 원문의 해시. stable_id 를 못 믿을 때의 2차 대조 키.
    source_text_hash: str | None = None
    #: 사람이 원문에서 찾아갈 위치 표기(p3#0). HWP 페이지는 근사값이라 앵커로는 쓰지 않는다.
    source_locator: str | None = None
    #: 어디서 대응하는가. 비어 있으면 읽을 때 item_type 에서 파생한다.
    response_scope: ResponseScope | None = None
    # 화면용 코드 (TSK-003 등). 없으면 프론트가 item_type + requirement_id로 만든다.
    display_code: str | None = None


class PageInfo(BaseModel):
    page: int = Field(ge=1)
    char_count: int = Field(ge=0)


class RfpParseResult(BaseModel):
    procurement_id: str
    source: str
    document: str
    # 실제 공고 첨부에서 파싱한 경우의 문서 형식(pdf/hwp/hwpx). 합성 fixture는 None.
    doc_format: str | None = None
    # HWP/HWPX는 페이지 정보가 없어 문단 묶음으로 page를 근사한다 (UI에 근사값임을 표기).
    page_is_approximate: bool = False
    #: 요구사항을 뽑은 문서가 제안요청서류(`rfp`)인가 입찰공고문(`notice`)인가 (27차 §3-A-4).
    #: 제안요청서가 첨부에 없어 공고문에서 뽑았으면 화면이 「과업 세부 요구사항이 빠져 있을 수 있다」고 알린다.
    #: 옛 저장 파일(필드 없음)은 `rfp_parser.migrate_payload` 가 문서 이름으로 채운다.
    document_role: Literal["rfp", "notice"] = "rfp"
    page_count: int = Field(ge=0)
    pages: list[PageInfo]
    empty_pages: list[int]
    count: int = Field(ge=0)
    # 추출 상한(rfp_extractor.MAX_REQUIREMENTS)을 적용하기 전 후보 수.
    # candidate_count > count 이면 문서 뒤쪽 요구사항이 응답에서 빠진 것이므로
    # truncated=True로 표시하고 화면과 Auditor Coverage에 그대로 드러낸다.
    candidate_count: int | None = Field(default=None, ge=0)
    truncated: bool = False
    requirements: list[Requirement]
    generated_at: datetime
    # 저장 형식 버전. 예전 파일(없음=1)은 load_generated가 읽을 때 2로 올린다.
    schema_version: int = Field(default=REQUIREMENT_SCHEMA_VERSION, ge=1)
    # 유형별 건수 (탭 배지). 요구사항 목록에서 계산한 값이며 응답에만 실린다.
    item_counts: dict[str, int] = Field(default_factory=dict)
    # --- schema_version 3: 이 «집합»의 신원 --------------------------------
    #
    # 제안서·감사가 «어느 요구사항 집합을 보고 만들어졌는지» 기록하려면 집합에도
    # 이름이 있어야 한다. hash 는 정렬·번호가 아니라 내용(stable_id·필수여부·유형·
    # 대응범위)에서 나오므로, 순서만 바뀐 재추출은 같은 값이다.
    requirement_set_id: str | None = None
    requirement_set_hash: str | None = None
    #: 내용이 바뀔 때만 오르는 판 번호. 같은 내용으로 다시 뽑으면 그대로다.
    requirement_set_version: int = Field(default=1, ge=1)
    #: 원문 문서가 바뀌었는지 보기 위한 값 (제안서 생성 이후 첨부 교체 감지).
    source_document_hash: str | None = None
    #: 분모를 화면 전체가 같이 쓰게 하려고 여기서 한 번만 센다.
    mandatory_count: int = Field(default=0, ge=0)
    optional_or_conditional_count: int = Field(default=0, ge=0)
    #: 대응 범위별 건수 (제안서 본문 대상이 몇 건인지 화면이 알아야 한다).
    response_scope_counts: dict[str, int] = Field(default_factory=dict)


class RfpParseRequest(BaseModel):
    procurement_id: str = Field(min_length=1, max_length=64)
    # 실제 공고 파싱 시 사용할 첨부 인덱스. 생략하면 서버가 제안요청서를 자동 선택한다.
    attachment_index: int | None = Field(default=None, ge=0, le=9)
    #: 사람이 확인 창에서 파일 이름을 보고 「받고 분석」을 눌렀다 — 로컬에 없는 첨부 한 건을 받아도 된다
    #: (27차 §3-A-2). 기본은 거짓이라 고정 모드에서 조용히 받는 길은 그대로 막혀 있다.
    fetch_attachment: bool = False
