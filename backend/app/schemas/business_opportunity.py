"""기업마당(bizinfo.go.kr) 지원사업 + 나라장터·기업마당 통합 사업기회 스키마.

**조달공고(나라장터)와 지원사업(기업마당)은 다른 개념이다.** 조달공고는 샘플에듀가 용역을 수주하는
입찰이고, 지원사업은 샘플에듀가 지원금·바우처를 받는 사업이다. 원본 점수는 끝까지 따로 둔다:
- 조달공고 → recommendation(추천등급, 낙찰확률 아님)
- 지원사업 → support_fit(지원 적합도, 선정확률 아님)

그 위에 두 출처를 한 화면에 놓기 위한 **회사 기준 검토 우선순위**(company_priority_score)만 추가한다.
이것도 확률이 아니라 "현재 선택한 회사가 먼저 검토할 순서"다. 원본 점수를 덮어쓰지 않는다.

지원사업 필드는 기업마당 OpenAPI 실응답으로 확인했다 (2026-09-08, scripts/verify_bizinfo_api.py).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.capability import WorkKind, WorkTrack

SupportSource = Literal["bizinfo", "cached", "sample"]
SupportFitLabel = Literal["적합", "검토", "낮음"]

# 신청 기간 원문의 성격. 실응답 15%가 날짜가 아니라 문구다 ('상시 접수', '예산 소진시까지' 등).
# 날짜가 없다고 "마감일 없음"으로 뭉뚱그리지 않는다.
ApplyPeriodKind = Literal["dated", "always_open", "until_budget", "conditional", "unknown"]

APPLY_PERIOD_KIND_LABELS: dict[str, str] = {
    "dated": "기간 지정",
    "always_open": "상시 접수",
    "until_budget": "예산 소진 시까지",
    "conditional": "조건부 마감",
    "unknown": "원문 확인 필요",
}


class SupportAttachment(BaseModel):
    """공고문·신청서식 첨부. kind로 무엇인지 구분한다.

    `url` 은 **내려받기 주소**(`fileDown.do`)다. 기업마당이 목록에 주는 `flpthNm` 은
    `getImageFile.do` 인데 그 주소는 뷰어 HTML 을 준다(0924.md §2 실측) — 담당자가
    링크를 눌러도 내려받기·출력이 안 됐다. 원본은 같은 `atchFileId`·`fileSn` 으로
    `fileDown.do` 를 부를 때 온다.

    `view_url`·`ext` 는 **추가만** 한 선택 필드다. 옛 스냅샷에는 없으므로 기본값을 둔다.
    """

    name: str
    url: str
    #: 30차 §3-A — 이름으로 단 종류: 과제소개서(annex) · 신청 매뉴얼(manual) · 신청 서식(form) · 공고문(notice).
    kind: Literal["form", "notice", "annex", "manual"]
    #: 기업마당이 준 원래 주소(뷰어). 「보기」 보조 링크로만 쓴다.
    view_url: str | None = None
    #: 파일 이름에서 읽은 확장자(hwpx · pdf · hwp). 이름 옆 배지로 쓴다.
    ext: str | None = None
    #: 신청 서식 칸(fileNm/flpthNm) 안의 순번 — 그 첨부 한 개를 받을 때 쓴다(30차 §3-A). 공고문 칸은 None.
    index: int | None = None


class SupportProgram(BaseModel):
    id: str
    title: str
    agency: str
    executing_agency: str | None = None
    summary: str | None = None
    apply_start: date | None = None
    apply_end: date | None = None
    # 날짜로 못 읽은 경우를 위해 원문과 성격을 함께 남긴다.
    apply_period_text: str | None = None
    apply_period_kind: ApplyPeriodKind = "unknown"
    category: str | None = None
    subcategory: str | None = None
    hashtags: list[str] = Field(default_factory=list)
    target: str | None = None
    #: 해시태그·기관명에서 뽑은 **지역 이름**. 통합 이후 이름은 「전남광주」다 (0921 §4-A-4).
    #: 빈 목록은 「지역 한정이 아니다」가 아니라 **「지역 표시를 못 찾았다」**이므로,
    #: 지역 판정은 이것이 비면 「확인 필요」로 간다.
    region_tags: list[str] = Field(default_factory=list)
    #: 요약문의 「☞ …」 문장들. **원문 그대로** 싣는다 — 대상 요건을 지어내지 않는다.
    requirement_sentences: list[str] = Field(default_factory=list)
    url: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # 신청 흐름용 (실응답 확인). 연락처가 섞일 수 있어 공개 스냅샷에서는 마스킹한다.
    apply_method: str | None = None
    contact: str | None = None
    reception_url: str | None = None
    attachments: list[SupportAttachment] = Field(default_factory=list)


class SupportFitComponent(BaseModel):
    key: str
    label: str
    weight: float
    score: float | None
    reason: str


class SupportFit(BaseModel):
    """지원 적합도. 지역·대상·기간은 언제나 규칙이고, 사업영역만 «잴 수 있을 때» 의미 매칭이다.

    무엇으로 쟀는지는 `method` 에 있다. 선정확률이 아니다.
    """

    label: SupportFitLabel
    score: float = Field(ge=0, le=1)
    components: list[SupportFitComponent]
    method: str = "keyword_rule"
    note: str
    #: 회사가 신청 주체가 아닐 수 있다는 안내 (ISSUE-005 · ISSUE-125). 없으면 None.
    #: 문장은 화면에 그대로 나가고, `audience_kind` 는 점수 규칙이 읽는다.
    audience_note: str | None = None
    audience_kind: str | None = None


class SupportProgramView(BaseModel):
    kind: Literal["support"] = "support"
    program: SupportProgram
    support_fit: SupportFit


class SupportProgramListResponse(BaseModel):
    source: SupportSource
    bizinfo_api_configured: bool
    fetched_at: datetime | None
    total_fetched: int
    count: int
    error: str | None
    # 실응답 필드 매핑을 확인했는지. 화면은 이 값을 그대로 보여준다.
    field_mapping_verified: bool
    # 기업마당에 등록된 전체 지원사업 수 (받은 건수가 아니다). 실응답 totCnt.
    total_available: int | None = None
    # 시연 고정 모드인가 (BIZINFO_LIVE_FETCH=0). 화면이 새로고침을 잠그는 근거.
    # 옛 화면·옛 스냅샷과의 호환을 위해 기본값을 둔다 — 없으면 「고정 아님」으로 읽힌다.
    frozen: bool = False
    # 옛 클라이언트가 `?refresh=…` 를 보냈고 **무시했다**는 표시 (N1 · S8).
    # 다시 받아 오는 것은 `POST …/refresh` 다. 조용히 무시하면 보낸 쪽이 「새로 받았다」고
    # 믿고 옛 목록을 새것처럼 보여준다.
    refresh_ignored: bool = False
    items: list[SupportProgramView]


# --------------------------------------------------------------------------
# 지원사업 신청 분석 (입찰 분석과 단계·용어가 다르다)
# --------------------------------------------------------------------------


class SupportRequirementItem(BaseModel):
    """지원사업 신청 조건 한 줄. 목록 API에 없는 것은 지어내지 않고 미확인으로 둔다."""

    key: str
    label: str
    value: str | None
    # confirmed = 원문(API 응답)에 있음 · unknown = 원문 상세 확인 필요
    status: Literal["confirmed", "unknown"]
    source_field: str | None = None
    note: str | None = None


class SupportApplicationPlan(BaseModel):
    """지원사업 신청 분석 결과. 입찰의 요구사항 매트릭스에 대응하지만 용어가 다르다."""

    program_id: str
    organization_id: str
    evidence_scope: str
    generated_at: datetime
    # 신청자격 · 필수/우대조건 · 신청기간 · 제출서류
    eligibility: list[SupportRequirementItem]
    conditions: list[SupportRequirementItem]
    schedule: list[SupportRequirementItem]
    documents: list[SupportRequirementItem]
    # 회사 적합 근거 (승인된 회사자료에서만)
    evidence_matches: list[dict] = Field(default_factory=list)
    evidence_summary: dict | None = None
    unknown_count: int
    note: str


# --------------------------------------------------------------------------
# 통합 사업기회 (나라장터 + 기업마당)
# --------------------------------------------------------------------------

#: 출처 셋 — 나라장터 · 기업마당 · 직접 넣음(사람이 넣은 공고 · 38차 §3-E). 순위는 출처 안에서만 매긴다.
SourceType = Literal["g2b", "bizinfo", "manual"]
SOURCE_TYPES: tuple[str, ...] = ("g2b", "bizinfo", "manual")
#: 출처 이름(표 · 브리핑 · 엑셀이 같은 말을 쓴다).
SOURCE_NAMES: dict[str, str] = {"g2b": "나라장터", "bizinfo": "기업마당", "manual": "직접 넣음"}
SOURCE_LONG_NAMES: dict[str, str] = {"g2b": "나라장터 입찰", "bizinfo": "기업마당 지원사업", "manual": "직접 넣은 공고"}
#: 「pre_spec」 — 나라장터 사전규격(본공고 전 · 38차 §3-D). 나라장터 갈래에 서고 실무순 T3 「선제준비」다.
OpportunityType = Literal["procurement", "support_program", "pre_spec"]
Confidence = Literal["high", "medium", "low"]
# 「미확인」은 «점수를 내지 못했다»이다. 예전에는 그것을 「후순위」로 표기해,
# 판정하지 못한 공고와 실제로 뒤로 보낸 공고가 한 라벨을 썼다 (ISSUE-041).
# CLAUDE.md §12 — 미확인 항목은 score=null 로 두고 0점으로 단정하지 않는다.
PriorityLabel = Literal["우선 검토", "검토", "후순위", "미확인", "마감"]
EligibilityGate = Literal["PASS", "CHECK", "FAIL"]
#: 「pre_spec」 — 본공고가 아직 없는 사전규격. 공고 분석 · 제안서 단추가 없다(규격서 링크는 `detail_url`).
#: 「manual」 — 직접 넣은 공고(사업기회 「직접 넣기 · 후보함」 탭으로).
NextRouteKind = Literal["procurement_analysis", "support_application", "pre_spec", "manual"]


class PriorityComponent(BaseModel):
    """검토 우선순위 구성 항목. score=None 은 '미확인'이며 0점이 아니다."""

    key: str
    label: str
    # 배점 (합 100)
    weight: int
    score: float | None = Field(default=None, ge=0, le=1)
    reason: str


class AnalysisState(BaseModel):
    """공고 하나의 분석 상태 (0920 §4-B-3 · ISSUE-076).

    목록 행·레이더 상세가 이것을 그대로 그린다. **모르는 것은 None 이다** — 0 으로 단정하지
    않는다. 「차단 조건 0」은 «막는 것이 없다»는 뜻이고, 조건을 재 본 적 없는 것과 다르다.
    """

    parsed: bool = False
    requirement_count: int | None = None
    #: 「확인 필요」 — 기계가 정하지 못해 사람이 봐야 하는 항목 수.
    check_count: int | None = None
    #: 담당자가 확인·정정한 항목 수. 위와 **다른 값**이다.
    confirmed_count: int | None = None
    #: 저장된 참여 결정. 파일이 없으면 None (「미정」과 구분).
    decision: str | None = None
    review: str | None = None
    open_findings: int = 0
    #: 참가를 막는 조건 수. 탐지한 적이 없으면 None.
    blocking_conditions: int | None = None
    last_activity_at: datetime | None = None


class NextRoute(BaseModel):
    """선택하면 어디로 가는가. 출처마다 분석 흐름이 다르다."""

    kind: NextRouteKind
    path: str
    label: str


class UnifiedOpportunity(BaseModel):
    id: str
    source_type: SourceType
    opportunity_type: OpportunityType
    title: str
    agency: str
    summary: str | None = None
    # 조달=입찰 마감, 지원=신청 종료일 23:59(KST). 날짜가 없으면 None이고 deadline_text를 본다.
    deadline: datetime | None = None
    deadline_text: str | None = None
    detail_url: str | None = None
    organization_id: str
    # 회사 기준 검토 우선순위 (0~100). 낙찰·선정 확률이 아니다. 계산 가능한 항목이 없으면 None.
    #
    # **두 출처를 가로질러 비교하지 않는다.** 나라장터는 우리가 수주해 매출을 얻는 사업이고
    # 기업마당은 우리가 지원금을 신청하는 사업이라, 같은 1~N 위에 세우면 뜻이 없다.
    # 아래 두 필드가 «자기 출처 안에서의» 점수이고, 화면은 그것을 쓴다.
    company_priority_score: int | None = None
    # 나라장터 항목의 수주 적합도. 기업마당은 None.
    procurement_fit_score: int | None = None
    # 기업마당 항목의 지원 적합도. 나라장터는 None.
    support_fit_score: int | None = None
    # company_priority_score 와 같은 값. 「검토 우선순위」라는 이름을 명시적으로 쓰고 싶을 때.
    review_priority_score: int | None = None
    # 통합 목록 전체에서의 순위. 두 출처가 섞여 있으므로 «표시용»이지 비교 근거가 아니다.
    priority_rank: int
    # 같은 출처 안에서의 순위. 화면이 실제로 보여줄 순위는 이쪽이다.
    source_rank: int = 0
    # 같은 출처 안의 전체 건수 (「3 / 100」처럼 적기 위해).
    source_total: int = 0
    priority_label: PriorityLabel
    # 점수보다 먼저 보는 참여 가능성 게이트. 명확한 지역 제한 등 FAIL은
    # 업무영역 점수가 높아도 추천 상단에 올리지 않는다.
    eligibility_gate: EligibilityGate = "CHECK"
    gate_reason: str | None = None
    confidence: Confidence
    score_components: list[PriorityComponent]
    # 원본 점수를 그대로 유지한다 (조달: grade/score, 지원: label/score).
    source_specific_score: dict = Field(default_factory=dict)
    next_route: NextRoute
    # 데이터 출처: g2b | cached | bizinfo | sample
    source: str
    # 이번 조회에서 받아온 것이 아니라 고정 공고 저장소에서 되살려 붙인 항목인가.
    # 목록 전체의 source 는 "g2b" 라도 이 항목만은 방금 받아온 것이 아니다.
    pinned: bool = False
    closed: bool = False
    reasons: list[str] = Field(default_factory=list)
    checks: list[str] = Field(default_factory=list)
    # 목록 카드용 부가 정보 (조달=예산, 지원=지원분야)
    budget: int | None = None
    category: str | None = None
    # 일의 종류(갈래) — 「AI 교육이냐 개발이냐」. 나라장터 공고에만 있는 축이다.
    # 기업마당 지원사업은 «회사가 신청하는 것»이라 이 축이 없으며, 빈 목록은 「미분류」와 다르다.
    work_kinds: list[WorkKind] = Field(default_factory=list)
    work_tracks: list[WorkTrack] = Field(default_factory=list)
    # 무엇을 보고 판정했는지. 해당 없음(기업마당)이면 None.
    work_basis: str | None = None
    #: 「왜 맞나」 한 줄 (0921 §4-C-3). 근거가 없으면 None — 빈 말을 만들지 않는다.
    fit_line: str | None = None
    #: 「주의」 한 줄. 볼 것이 없으면 None.
    caution_line: str | None = None
    #: 계약방법 · 낙찰방식 · 기술:가격 · 공동수급 한 줄 (0921 §4-B ELIG-AWARD).
    #: 판정이 아니라 **정보**다 — 협상 90:10 과 최저가는 준비할 것이 다르다.
    award_line: str | None = None
    #: **무엇을 갖추면 열리는가** (0921 §4-B). 「소프트웨어사업자(1468) 등록 시 가능」 같은
    #: 문장이 들어간다. 빈 목록은 「지금 판정에 열 수 있는 길이 없다」는 뜻이다.
    unlock_conditions: list[str] = Field(default_factory=list)
    #: 이 공고의 참가자격 **조항 id 집합** (20차 §4-B) — 「QC-04」·「RFP-QC-02」·「REQ-011」.
    #: 두 화면 검사가 목록과 상세를 줄 수가 아니라 이 집합으로 견준다. 기업마당·조항 없는 공고는 빈 목록.
    clause_ids: list[str] = Field(default_factory=list)
    #: 기업마당 지역 태그(대표 이름). 나라장터에는 이 축이 없어 빈 목록이다.
    region_tags: list[str] = Field(default_factory=list)
    #: 기업마당 요약문의 「☞ …」 대상 요건 문장 (앞 3개). **원문 그대로다** — 지어내지 않는다.
    requirement_sentences: list[str] = Field(default_factory=list)
    #: 분석 상태 (0920 §4-B-3). 나라장터 공고만 채워진다 — 지원사업은 이 8단계를 타지 않는다.
    analysis_state: AnalysisState | None = None
    # 접수 기간의 «성격». 기업마당만 의미가 있다(나라장터는 항상 None).
    # 화면이 「상시 접수」를 「신청 종료」로 잘못 읽지 않도록, 마감일(deadline)이 없는 이유를
    # 구분해서 내려보낸다. 값은 SupportProgram.apply_period_kind 를 그대로 옮긴 것이다.
    apply_period_kind: ApplyPeriodKind | None = None
    #: **참가자격 등록 마감** (`bidQlfctRgstDt`, 0922 §4-B-8).
    #:
    #: 실제 데드라인은 입찰마감이 아니라 이쪽인 경우가 많다 — 한남대·KISTI 는 입찰 9-28 인데
    #: 등록은 9-27 18:00 이다. 카드는 두 줄로 적고 D-day 는 **더 이른 쪽**을 쓴다.
    qualification_deadline: datetime | None = None
    #: 갈래 안에서의 순위 (0922 §4-B-7). `{"development": 3, "education": 12}`.
    #:
    #: 나라장터(우리가 수주하는 사업)와 기업마당(우리가 지원금을 신청하는 사업)을 **한 축에
    #: 섞어 1위를 만들지 않는다.** 순위는 같은 출처·같은 갈래 안에서만 뜻이 있다.
    track_ranks: dict[str, int] = Field(default_factory=dict)
    #: **회사가 맡을 자리가 신청 주체가 아닐 때의 표시** (0924 §4-A-4). 예 「간접(공급기업)」.
    #:
    #: 도입기업이 신청하고 공급기업이 수행하는 구조에서는 회사가 신청 주체가 아니다. 그것을
    #: 「불가」로 닫으면 실제로 들어갈 수 있는 길이 화면에서 사라진다. None 이면 직접 신청이다.
    participation: str | None = None
    #: **「회사에 뜻하는 것」 한 줄** (0924 §4-A-6) — 역할 · 받는 것 · 부담 · 마감.
    company_meaning: str | None = None
    #: **「확인 필요」가 어느 쪽 때문인가** (0925 §4-E-4).
    #:
    #: `"company"` 는 회사가 아직 안 적은 값(매출·연구소·상시근로자 수) 때문이고,
    #: `"notice"` 는 공고 원문을 더 봐야 하는 것이다. 앞쪽은 지금 당장 손댈 수 없어
    #: 「이번 주 할 일」의 지원사업 자리에서 뒤로 보낸다. 판정이 「확인 필요」가 아니면 None.
    check_side: Literal["company", "notice"] | None = None
    #: 회사가 신청 주체가 아닐 수 있다는 안내 (ISSUE-125 · prompt_05 §4-E-1).
    #: 「이번 주 할 일」이 이것을 보고 뺀다 — 아침에 읽고 바로 할 수 있는 일이 아니다.
    #: 목록에서는 지우지 않는다(규칙이 틀렸을 때 담당자가 찾을 수 있어야 한다).
    audience_note: str | None = None
    #: 공고문 원문을 읽고 판정했는가. 나라장터 공고는 None(해당 없음)이다.
    document_read: bool | None = None
    #: 못 읽은 이유 (「공고문 이미지」·「아직 안 받음」). 읽었으면 None.
    document_note: str | None = None
    #: 판정 근거로 쓴 **공고문 원문 인용**. 지어낸 문장이 아니라 원문 그대로다 (0924 §3-14).
    clause_quotes: list[str] = Field(default_factory=list)
    #: 「관련 낮음」인 이유 (0922 §4-C-2). None 이면 관련 있는 사업이다.
    #:
    #: 기업마당 1,605건에는 식품·관광·융자처럼 회사와 상관없는 사업이 섞여 있다. 지우지 않고
    #: 기본으로 접는다 — 규칙이 틀렸을 때 담당자가 찾을 수 있어야 한다.
    relevance_note: str | None = None

    # --- 실무 우선순위 (37차 · 기획서 §4-1 1-1 ~ 1-4 · `practical_priority`) -----------------
    #: 공고(등록)일 — 나라장터 `bidNtceDt` · 기업마당 `creatPnttm`. 없으면 None.
    published_at: datetime | None = None
    #: 접수방식 — 나라장터 `bidMethdNm`(전자입찰 · 직찰 · 전자시담) 그대로, 기업마당은 신청방법 글로 가린 것(여럿이면 모두).
    submission_methods: list[str] = Field(default_factory=list)
    #: 기업마당 신청방법 **원문 한 줄**(앞 120자) — 접수방식은 글로 가린 것이라 틀릴 수 있어 원문을 함께 싣는다.
    submission_text: str | None = None
    #: 모집 성격 — 「입찰(매출)」 · 「수행기관 모집(매출)」 · 「수혜(지원금)」.
    recruit_kind: str | None = None
    #: 설명회 일시(나라장터 `dcmtgOprtnDt`). **날짜만 보이고 판정에는 쓰지 않는다** — 필수 참석인지는 공고문을 봐야 안다.
    briefing_at: datetime | None = None
    #: 공동수급협정 마감(나라장터 `cmmnSpldmdAgrmntClseDt`). 없으면 None — 「없음」으로 단정하지 않는다.
    joint_agreement_deadline: datetime | None = None
    #: 공고문 일정표의 가장 이른 마감(참가신청 · 입찰등록 · 제출 마감 · 필수 현장설명 · 43차 결정 1 · `notice_schedule`). 실제 마감은
    #: 입찰 · 등록 · 이것 중 가장 이른 것이다(`practical_priority.effective_deadline`). 공고문을 못 읽었으면 None.
    schedule_deadline: datetime | None = None
    #: 그 마감의 이름 — 「참가신청 마감」 · 「입찰등록 마감」 · 「제출 마감」 · 「현장설명」.
    schedule_deadline_label: str | None = None
    #: 그 마감의 시각을 공고문에서 읽었나(44차 M3). False 면 날짜만 있던 것 — 판정 · 순서는 그날 끝(23:59)으로 세고, 화면 · 브리핑 ·
    #: 엑셀은 「MM/DD(시각 원문 확인)」으로 적는다. 공고문 일정 마감이 없으면 None.
    schedule_deadline_time_known: bool | None = None
    #: 개찰일시(나라장터 `opengDt`) — **마감이 아니다**(43차 H1). 입찰 마감이 비고 공고문도 못 읽었으면 「마감 미상 — 개찰 MM/DD」로만 보인다.
    opening_at: datetime | None = None
    #: 필수 현장설명(공고문 「미신청시 · 미참석시 참가 불가」) — 「필수 — 불참 시 참가 불가」 · 지나면 「사실상 마감」(43차 ELIG-06). 모르면 None.
    briefing_required: bool | None = None
    #: 변경공고(차수 001 이상)의 게시일 — `published_at` 은 원공고 게시일이다(43차 M2 · 신규성 · T1 · T2 는 원공고 기준).
    amended_at: datetime | None = None
    #: SAMPLEEDU 유형 **(근사)** — A1 · A2 · B1 · B2 · C · D · 수혜. 점수에는 쓰지 않는다(운영매뉴얼 v1.2 를 받기 전 근사치).
    fit_type: str | None = None
    #: 유형을 그렇게 본 근거 한 마디.
    fit_type_basis: str | None = None
    #: 시간 등급 T1~T6 (실제 마감 · 공고일 기준) · TU 「마감 미상」(입찰 마감이 비고 공고문 일정표도 없음 · 43차 결정 1).
    time_tier: str | None = None
    #: 분류 칸 — 선제준비 · 신규+여유 · 직접도전 · 조건부 · 일반 접수 중 · 긴급 · 비추천 · 제외.
    practical_group: str | None = None
    #: 실무 우선순위로 세웠을 때의 자리(1부터 · 목록 전체). 화면은 같은 출처 안에서만 견준다.
    practical_order: int = 0
    #: 같은 사업이 여러 운영기관으로 온 묶음의 꼬리표(43차 Q9 · BIZ-03) — 「같은 사업 n건 · 광주 · 전남 운영기관 먼저」. 아니면 None.
    same_program_note: str | None = None
    #: 사전규격 행의 「본공고 예상 · 사업기간 · 할 일」(43차 Q16 · M13). 사전규격이 아니면 None.
    prespec_plan: str | None = None
    #: 「대형 · 파트너형 후보」 덩어리인가 — 개발 · 연구 · 그 밖은 회사 단독 상한 초과, 교육 · 컨설팅은 상한의 2배 초과(광주 · 전남 발주 제외 ·
    #: `practical_priority.is_partner_scale`). 점수는 그대로다.
    partner_scale: bool = False
    #: 등록 업종이 없어 혼자는 못 하지만 공동수급이 허용(「allowed」) · 방식 모름(「unknown」)인 공고(44차 결정 4 ·
    #: `eligibility_engine.industry_partner`). 실무순은 크기 · 지역과 상관없이 대형 · 파트너형 덩어리 · 꼬리표 「업종 없음 · 파트너형(…)」.
    industry_partner: Literal["allowed", "unknown"] | None = None
    #: 저장된 결정 한 줄 — 「참여 · 담당자 · 10/24」 · 「신청 안 함 · …」 · 「결정 전」(44차 M4 · `practical_priority.decision_text`).
    #: 브리핑 · 엑셀 · 이번 주 할 일이 이 값 하나를 쓴다. 결정 파일이 없으면 None.
    decision_text: str | None = None
    #: 근거 줄 — 「근거: 공고문 p.N 「…」(QC-xx)」 · 기업마당은 공고문 인용 · 읽지 않았으면 「공고문 아직 안 읽음」(38차 §3-C-2).
    evidence_line: str | None = None
    #: 읽은 참가자격 조항 수(나라장터 조항 파일 · 쪽 번호 있음). 읽지 않았으면 0.
    clause_count: int = 0
    #: 최근 7일 안에 바뀐 것 — 「마감 · 첨부 · 차수 · 종류」(나라장터 변경 기록 · 지역 뺌 · 38차 §3-C-5). 없으면 빈 목록.
    changed_fields: list[str] = Field(default_factory=list)
    #: 사전규격의 의견등록 마감 — **입찰 마감이 아니다**(D-day · 마감 임박순 · 긴급 칸에 들지 않는다 · 38차 §3-D).
    opinion_deadline: datetime | None = None
    #: 본공고 행 — 「사전규격 n일 전 공개」(사전규격 저장본에 그 번호가 있을 때만).
    pre_spec_note: str | None = None
    #: 사전규격 행 — 본공고가 나왔으면 그 공고 id(「본공고 나옴 →」).
    main_notice_id: str | None = None
    #: 직접 넣은 공고의 출처 층(P1 · P2 · P3 · IRIS · HRD — 사람이 고른 것 · 38차 §3-E).
    source_layer: str | None = None
    #: 기업마당 수행기관 — 소관기관과 함께 「광주 · 전남 기관 자체」 판단에 쓴다(38차 PRACTICAL-05). 나라장터는 None.
    #: 나라장터 수요기관(`dminsttNm` · 43차 M6) — 광주 · 전남 판정은 이 기관 기준. 조달청 대행이면 기관 칸이 「수요기관(조달청 대행)」.
    demand_agency: str | None = None
    executing_agency: str | None = None
    #: 실무순 세 덩어리 — 「본업」 · 「연구 · 감리 · 구매」 · 「대형 · 파트너형 후보」(38차 D12).
    practical_block: str | None = None
    #: 대형 꼬리표 — 「단독으로는 큼 · 파트너형」(공동수급 허용) · 「… · 공동수급 불허」 · 「… · 공동수급 확인 필요」(38차 D14).
    #: 사업기회 행과 브리핑 판단 낱말이 같은 값을 쓴다(`practical_priority.partner_tag` · DOCS-01). 대형이 아니면 None.
    partner_tag: str | None = None
    #: 「규모 큼(단독 상한 n억)」 — 교육 · 컨설팅(A1 · A2 · B1)이 상한보다 크고 2배 이하라 본업에 남는 공고(결정 2 · 39차 · `practical_priority.scale_tag`).
    scale_tag: str | None = None
    #: 「주제 확인 — 공고명에 회사 사업 주제가 없음」(40차 결정 1 · D23 · `practical_priority.topic_of`) — 본업 덩어리 안에서 주제가 맞는 공고 뒤로.
    topic_note: str | None = None
    #: 「AI: 본업 아닐 수 있음 · <이유>」(40차 결정 2 · D24 · `ai_fit_service`) — 「주제 확인」과 같은 자리. 판정 · 점수 · 접기에는 쓰지 않는다.
    ai_fit_note: str | None = None
    #: 실제 마감이 3일 이하 — 「원칙적으로 후순위」(실무 문서 §2.5 · D3).
    deadline_note: str | None = None
    #: 기업마당 — 사업 목적이 회사 갈래(AI 교육 · 컨설팅 · 개발 · 공공 · 학술)인가(`support_kinds.is_ours`). 나라장터는 None.
    #: 브리핑 제외 표의 「유형은 맞는데 지역 때문에 빠진 것」을 가른다(D4).
    kind_fit: bool | None = None
    #: (응답에 싣지 않음) 확인 필요가 회사 쪽 값 때문인가 — 「조건부」 칸을 가른다. 기업마당은 `check_side` 로 읽는다.
    practical_company_gap: bool = Field(default=False, exclude=True)
    #: (응답에 싣지 않음) 나라장터 AI 후보인가 — 아니면 「비추천」(후보 아님 · `include_low` 일 때만 목록에 온다).
    practical_candidate: bool = Field(default=True, exclude=True)


class OpportunitySummary(BaseModel):
    """건수의 **단일 분모** (0920.md §4-B-2 · ISSUE-075).

    같은 화면 안에서도 숫자가 갈려 있었다 — 목록 머리는 「전체 107 · 나라장터 7 · 마감 1 제외」,
    바로 아래 탭은 「전체 (104) · 나라장터 입찰 (4)」. 마감 건을 세는 기준이 달랐기 때문이다
    (`closed_count` 는 시연용 고정을 빼고 세는데, 목록은 고정이든 아니든 마감 행을 숨겼다).

    그래서 **백엔드가 한 벌만 세고** 목록 머리·탭·레이더 계기판·데이터 상태가 전부 이것만 쓴다.
    화면이 다시 세지 않는다.
    """

    #: 마감 전 전체. 화면의 「전체」는 이 값이다.
    open_total: int
    open_g2b: int
    open_bizinfo: int
    #: 직접 넣은 공고(38차 §3-E).
    open_manual: int = 0
    #: 「우선 검토」로 분류된 건수. **전체 기준**이다 — 레이더가 그린 12건 안에서 세지 않는다.
    priority: int
    #: 마감된 건수 (시연용 고정 포함).
    closed: int
    #: 참가·신청할 수 없다고 판정한 건수 (0921 §4-C-2). 기본 목록에서는 숨긴다.
    #: **지운 것이 아니다** — 「불가 포함」을 켜면 돌아온다.
    blocked: int = 0
    #: 그중 시연용으로 고정해 둔 것. 목록이 「시연용 (마감)」 그룹으로 따로 묶는다.
    closed_pinned: int
    #: 이 목록이 본 조회 기간(일). 네 화면이 같은 값을 써야 한다.
    days: int
    #: 「새 공고」로 볼 기간(일). 목록 화면이 이 값으로 「최근 n일 새 공고」를 거른다.
    #:
    #: 예전에는 목록 화면이 `NEW_WINDOW_DAYS = 3` 을 자기가 들고 있었고, 대시보드 띠는
    #: 응답의 `new_days` 를 썼다. 같은 「새 공고」가 두 곳에서 따로 정해지고 있었던 것이다
    #: (0920 §4-B-5 · ISSUE-078).
    new_days: int
    #: 자료를 **마지막으로 받아온** 시각. 응답을 만든 시각이 아니다 (ISSUE-078-a).
    #: 두 출처 중 **오래된 쪽**이다 — 한쪽이 낡았으면 목록 전체가 그만큼 낡은 것이다.
    #: 받아온 적이 없으면 null.
    fetched_at: datetime | None = None


class UnifiedOpportunityListResponse(BaseModel):
    organization_id: str
    organization_name: str
    total_count: int
    g2b_count: int
    bizinfo_count: int
    #: 직접 넣은 공고 수(38차 §3-E).
    manual_count: int = 0
    #: 출처마다 받은 때(38차 BRIEF-04 — 「같은 저장본」은 두 출처가 **모두** 같을 때만). 없으면 None.
    source_fetched_at: dict[str, datetime | None] = Field(default_factory=dict)
    #: 이 응답에 실제로 담긴 건수. total_count 는 자르기 «전» 수집 건수다.
    #: 둘이 다르면 화면이 「수집 N건 중 M건 표시」라고 정직하게 적을 수 있다.
    returned_count: int = 0
    closed_count: int
    #: 자격 판정이 「불가」인 건수. 기본 목록에서는 숨기고 「불가 포함」으로 되돌린다 (0921 §4-C-2).
    blocked_count: int = 0
    # 각 출처의 실제 데이터 상태 (g2b|cached / bizinfo|cached|sample). 화면에서 숨기지 않는다.
    source_status: dict[str, str | None]
    # 한쪽이 실패해도 다른 쪽은 살린다. 실패 사유를 남긴다.
    source_errors: dict[str, str | None]
    # 시연 고정 모드인가 (ISSUE-062). 두 출처 중 하나라도 고정이면 True — 화면은 재수집을 잠근다.
    frozen: bool = False
    # 옛 클라이언트가 `?refresh=…` 를 보냈고 **무시했다**는 표시 (N1 · S8).
    # 다시 받아 오는 것은 `POST …/refresh` 다. 조용히 무시하면 보낸 쪽이 「새로 받았다」고
    # 믿고 옛 목록을 새것처럼 보여준다.
    refresh_ignored: bool = False
    fetched_at: datetime
    #: 건수의 단일 분모 (0920 §4-B-2). 화면은 건수를 **다시 세지 않는다**.
    summary: OpportunitySummary
    #: 나라장터를 「어떻게 받았는가」 — 「공고명 키워드 10개 · 마감 제외 · 최근 30일」.
    #: 옛 캐시로 답할 때는 없을 수 있다(None). 그때 화면은 이 줄을 적지 않는다.
    collected_by: str | None = None
    #: 그 수집에서 나라장터를 부른 횟수.
    collect_calls: int | None = None
    #: 매일 아침 자동 받기(예약 작업)의 마지막 성공 — 48시간 안일 때만(38차 §3-C-4 · `auto_collect`). 화면은 이 값이 있으면
    #: 「새 공고 받기 꺼짐」 대신 「매일 아침 자동으로 받음 · 마지막 MM/DD HH:MM」을 적는다. 로그가 없으면(키트) None.
    auto_collect_at: datetime | None = None
    #: 자동 받기 한 줄(39차 §3-F-2 · `auto_collect.collect_state`) — 화면 다섯 곳이 이 값 하나로 고른다. 키트는 kind=none.
    collect_state: "CollectState | None" = None
    sort: str
    #: 회사가 고른 순서 방식(37차) — 「score」 점수순 · 「practical」 실무 우선순위. 기본 정렬이 이것을 따른다.
    ranking_method: str = "score"
    #: 그 이름(「점수순」 · 「실무 우선순위」). 화면 머리 「정렬: 실무 우선순위(회사 설정)」에 쓴다.
    ranking_method_label: str = "점수순"
    field_mapping_verified: bool
    note: str
    # 갈래별 건수. **자르기(limit) 전** 기준이라 화면의 칩 숫자가 「상위 N건」에 흔들리지 않는다
    # (closed_count 와 같은 시점에 센다).
    track_counts: dict[str, int] = Field(default_factory=dict)
    items: list[UnifiedOpportunity]
    #: 「선제준비」 칸 — 사전규격 · 발주계획(39차 결정 1). **입찰 목록(`items`) · 순번 · 건수에는 들지 않는다.**
    #: `with_prepare` 로 부를 때만 채운다(브리핑 · 「선제준비」 탭). 아니면 None.
    prepare: "PrepareSection | None" = None


class CollectState(BaseModel):
    """자동 받기 상태(39차 §3-F-2 · 40차 D30 「켤 때 받기」 · `auto_collect.collect_state`).

    none = 자동 받기 기록도 예약 작업도 없음(키트) · ok = 오늘 받음 · missed = 오늘 아직(경고) · running = 받는 중(D29 · 경고 아님) ·
    off = 예약 작업 꺼 둠 · 없음(D28 · 경고 · 권유 없음) · waiting = 회사 서버가 오늘 받을 시각 전(43차 M27 · 경고 아님).
    `suffix` = 「 · 일부 실패(…)」 · 「 · 기업마당 못 받음」 — 줄인 글에도 붙인다(COLLECT-01)."""

    kind: Literal["none", "ok", "missed", "running", "off", "waiting"] = "none"
    text: str | None = None
    last_success: datetime | None = None
    suffix: str | None = None
    #: 경고색으로 적을까(44차 OPS-10) — 오늘 아직(missed) · 기업마당 3일 넘게 못 받음. 화면 `collectWarns` 가 이것도 본다.
    warn: bool = False


class OrderPlanRow(BaseModel):
    """발주계획(발주 예정) 한 줄 — 기관이 미리 적은 계획이다. 점수 · 판정이 없다(38차 §3-D)."""

    title: str
    agency: str
    #: 발주 시기(「2026-12」).
    when: str
    amount: int | None = None
    method: str
    #: 공식 상세 주소(g2b.go.kr 만 · 아니면 None).
    url: str | None = None
    #: 본공고가 이미 났다 — `ntceNticeYn=Y` 이거나 `bidNtceNoList` 가 있다(PRESPEC-03). 「공고 전」이라 하지 않는다.
    main_out: bool = False
    #: 그 본공고가 이 저장본 목록에 있으면 그 id(`g2b-R26BK…-000`). 없으면 None.
    main_notice_id: str | None = None
    #: 같은 사업의 사전규격이 이미 나왔다(43차 BRIEF-07 — 발주 예정 49건 중 38건이 사전규격과 겹쳤다) — 「사전규격 나옴 →」.
    prespec_out: bool = False
    #: 발주 시기가 지난 달인데 본공고 · 사전규격이 안 났다 — 「발주 지연」 꼬리표(43차 Q17).
    delayed: bool = False
    #: 유형(근사) — 사전규격 · 입찰과 같은 `practical_priority.type_of_kinds`(제목 낱말 · 45차 M16). 점수 · 판정이 아니다.
    fit_type: str | None = None
    #: 「주제 확인 — …」(교육 · 컨설팅인데 공고명에 회사 사업 주제가 없음) 또는 접은 사유(본업 덩어리 밖). 없으면 None.
    note: str | None = None


class PrepareSection(BaseModel):
    """사업기회 「선제준비」 칸(39차 결정 1 · PRESPEC-02~07).

    한 사전규격은 넷 중 한 곳에만 든다(위에서부터): 본공고가 나옴(`merged` — 칸에서 빼고 본공고 행에 「사전규격 n일 전 공개」) →
    본업이 아님(`others` — 비추천 · 연구 · 감리 · 구매 · 대형, 「다른 사전규격 n건」으로 접음) → 의견 마감 지남(`opinion_passed` — 접음) →
    본업이고 의견 마감 남음(`items` — 기본으로 보임). 칸 안 순서는 의견 마감 남은 것(마감일 있는 것) → 등록일 새것.
    """

    items: list[UnifiedOpportunity] = Field(default_factory=list)
    others: list[UnifiedOpportunity] = Field(default_factory=list)
    opinion_passed: list[UnifiedOpportunity] = Field(default_factory=list)
    merged: list[UnifiedOpportunity] = Field(default_factory=list)
    #: 발주 예정 — 후보 규칙에 맞는 것(본공고 안 나온 것 먼저). 낱말만 걸리고 후보 아닌 것은 수만.
    plans: list[OrderPlanRow] = Field(default_factory=list)
    #: 후보 낱말은 맞지만 유형(근사)이 본업 덩어리 밖(B2 · D)인 발주계획 — 사유와 함께 접는다(45차 M16).
    plans_folded: list[OrderPlanRow] = Field(default_factory=list)
    plans_low: int = 0
    #: 마지막 받기에서 발주계획이 크게 줄었으면 「발주계획 받은 양이 크게 줄었습니다 — 지난 자료 그대로」(39차 §3-F-4). 아니면 None.
    plans_note: str | None = None
    #: 사전규격 · 발주계획 저장본을 받은 때(없으면 None).
    fetched_at: datetime | None = None
    plans_fetched_at: datetime | None = None
    #: 접힌 묶음 건수(45차 M2 · `part=main` 일 때만 — 그때 접힌 묶음 목록은 비워 보내고 펼칠 때 `part=folds` 로 받는다). 아니면 None.
    others_count: int | None = None
    opinion_passed_count: int | None = None
    merged_count: int | None = None
    #: 나라장터 목록을 읽지 못한 사유(2.0.6 — 그때 칸이 비어 「보일 것이 없습니다」로 읽혔다). 읽었으면 None.
    source_error: str | None = None

    @property
    def total(self) -> int:
        return len(self.items) + len(self.others) + len(self.opinion_passed) + len(self.merged)


UnifiedOpportunityListResponse.model_rebuild()


# --------------------------------------------------------------------------
# 기업마당 **공고문 조항** (0924.md §4-A-3 · ISSUE-096)
#
# 요약문에는 없는 것들이다 — 본사 소재·조직 형태·고용 인원·창업 연차·매출·선행사업·역할·
# 정부지원 비율·제외 조항. 공고문 원문에서 뽑아 **원문 그대로** 근거로 남긴다(0924 §3-14).
# --------------------------------------------------------------------------

#: 조항의 갈래. 판정 규칙 BIZ-* 와 1:1 은 아니다 — 한 규칙이 여러 갈래를 볼 수 있다.
SupportClauseKind = Literal[
    "location",          # 소재 요건 (광역·시군 + 본사/사업장/공장)
    "org_type",          # 조직 형태 (사회적기업·마을기업·비영리법인·유치기업 …)
    "headcount",         # 고용 인원 (N인 이상/미만)
    "headcount_waiver",  # 인원 요건의 예외 문장 (「사회적기업 등은 10인 미만도 가능」)
    "founding_years",    # 창업 N년 이내
    "revenue",           # 매출 N억 이상
    "prerequisite",      # 선행사업·기업부설연구소·제품/데이터 보유·공급기업 등록
    "role",              # 회사가 맡을 역할 (신청 주체·공급기업·도입기업·주관 …)
    "money",             # 받는 것·부담 (금액·한도·정부지원 %·자부담 %·「무료」)
    "exclusion",         # 제외 조항
    "deadline_detail",   # 마감 시각·접수 방법
    "strategic_industry",  # 지역 전략산업 (「호남권 광주: ICT, 모빌리티 …」)
    "sme",               # 중소기업 신청 요건 (「중소기업기본법 제2조에 따른 중소기업」 · 10-10)
    "operator_region",   # 「지역정보보호지원센터가 속한 지역기업을 지원」 — 수행기관 지역 기업 대상(10-10 · 123800)
]


class SupportClause(BaseModel):
    """공고문에서 뽑은 조항 한 줄. **원문을 그대로 싣는다** (0924 §3-14).

    `detail` 에는 규칙이 쓰는 값만 담는다(지역 이름·인원 수·비율 …). 값을 못 읽었으면
    비워 둔다 — 지어내지 않는다. 문장을 못 찾았으면 이 조항 자체가 없다.
    """

    kind: SupportClauseKind
    #: 화면에 적을 짧은 이름. 예 「소재: 광주광역시(본사)」.
    label: str
    #: **공고문 원문 그대로.** 요약·의역하지 않는다.
    source_text: str
    #: 원문 쪽 번호. HWP 는 문단 묶음 순번이라 근사값이다.
    page: int | None = None
    #: 어느 절에서 찾았는가 (「신청자격」 등). 못 가렸으면 None.
    section: str | None = None
    #: 규칙이 쓰는 값. 지역 이름·인원 수·연차·비율 등.
    detail: dict = Field(default_factory=dict)


class SupportRequirements(BaseModel):
    """공고문 하나에서 뽑은 조항 전부 (0924 §4-A-3)."""

    program_id: str
    #: 원문을 읽었는가. False 면 아래 목록이 비어 있고 판정은 요약문 기준이다.
    document_read: bool = False
    #: 못 읽은 이유 (이미지 공고문·추출 실패). 읽었으면 None.
    document_note: str | None = None
    pages: int = 0
    #: **지원대상·신청자격 절의 첫 문장** (0925 §4-A-1).
    #:
    #: 규칙이 대상 요건을 확정하지 못했을 때 「확인 필요」 사유에 **원문 그대로** 인용한다.
    #: 「공고문에서 대상 요건을 확정하지 못했습니다 — 지원대상: 「장애인 예비창업자 …」」.
    #: 절을 못 찾았으면 None 이고, 그때는 「지원대상 절을 찾지 못했습니다」라고 적는다.
    target_sentence: str | None = None
    clauses: list[SupportClause] = Field(default_factory=list)
    #: 대상(신청자격 · 지원대상) 절에 있는데 **규칙이 하나도 읽지 못한 줄** — 남으면 「가능」 대신 확인 필요다(36차 R35-DV-01).
    #: 「인지부품 개발 · 제조 기업」 · 「소재부품 으뜸기업 6기」처럼 회사 사실로 가릴 수 없는 대상이다.
    unhandled_targets: list[str] = Field(default_factory=list)

    def of(self, kind: str) -> list[SupportClause]:
        return [c for c in self.clauses if c.kind == kind]
