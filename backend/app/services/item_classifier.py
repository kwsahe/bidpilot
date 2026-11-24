"""문서 항목 유형 분류 (TASK / REQUIREMENT / ELIGIBILITY / SUBMISSION / SCHEDULE / EVALUATION / SPECIAL_CONDITION / REFERENCE).

제안요청서에서 뽑은 문장은 성격이 다르다. "무엇을 수행해야 하는가"(TASK)와
"어떤 조건을 충족해야 하는가"(REQUIREMENT·ELIGIBILITY)와 "무엇을 언제 제출하는가"
(SUBMISSION·SCHEDULE)를 한 목록에 섞어 두면 Auditor가 계약조건 누락을 과업 누락처럼
보고하고, 담당자는 설명회 필참 같은 행동 조건을 놓친다.

원칙
- 규칙만 쓴다. 같은 입력이면 같은 결과다 (LLM·네트워크 없음).
- 추출기가 붙인 category를 1차 근거로 쓰고, 본문 표현으로 보정한다.
- 저장된 `requirement_id`(REQ-nnn)는 바꾸지 않는다. 화면용 `display_code`(TSK-nnn 등)만
  같은 번호로 파생한다 — 기존 Auditor·제안서·해결 기록의 참조가 깨지지 않게.
- 마감·설명회 일시는 본문에 날짜가 **명시된 경우에만** due_at으로 옮긴다 (추측 금지).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, get_args

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

#: 이 요구사항에 «어떻게» 대응하는가. 유형(ItemType)이 «무엇인가»라면 이쪽은 «어디서 답하는가»다.
#:
#: 둘을 나눈 이유는 Auditor 때문이다. 예전에는 필수 요구사항이 제안서 본문에 없으면
#: 무조건 HIGH 였다(auditor_service.py:337). 그래서 「소유권은 갑에게 있다」·「용역기간을
#: 조정할 수 있다」 같은 계약 일반조건이 «제안서 누락 HIGH» 로 올라왔다. 제안서에 다시
#: 적을 일이 아니라 계약할 때 지키면 되는 것들이다.
ResponseScope = Literal[
    "PROPOSAL_BODY",        # 제안서 본문에 서술한다 (과업·평가 대응)
    "ELIGIBILITY_DOCUMENT", # 자격 증빙으로 답한다 (업종·면허·실적증명)
    "SUBMISSION_CHECKLIST", # 제출물 체크리스트로 답한다 (부수·형식·매체)
    "PRICE_PROPOSAL",       # 가격제안서로 답한다
    "CONTRACT_COMPLIANCE",  # 계약 준수사항 — 지키면 되고 본문에 다시 적지 않는다
    "INTERNAL_ACTION",      # 우리가 «하는» 일 (설명회 참석·사전등록)
    "REFERENCE_ONLY",       # 배경·목적 — 대응 대상이 아니다
    "CONDITIONAL",          # 협의·조건에 따라 정해진다
    "NOT_APPLICABLE",       # 이 사업에 해당하지 않는다
]

ITEM_TYPES: tuple[ItemType, ...] = get_args(ItemType)
RESPONSE_SCOPES: tuple[ResponseScope, ...] = get_args(ResponseScope)

RESPONSE_SCOPE_LABEL: dict[ResponseScope, str] = {
    "PROPOSAL_BODY": "제안서 본문",
    "ELIGIBILITY_DOCUMENT": "자격 증빙",
    "SUBMISSION_CHECKLIST": "제출 체크리스트",
    "PRICE_PROPOSAL": "가격제안서",
    "CONTRACT_COMPLIANCE": "계약 준수",
    "INTERNAL_ACTION": "사전 행동",
    "REFERENCE_ONLY": "참고",
    "CONDITIONAL": "조건부",
    "NOT_APPLICABLE": "해당 없음",
}

#: 제안서 본문 Coverage 의 분모에 들어가는 범위. 나머지는 «본문 대응 대상 아님»이다.
PROPOSAL_BODY_SCOPES: frozenset[str] = frozenset({"PROPOSAL_BODY"})

# 화면 표시용 접두어. 저장 id(REQ-nnn)는 그대로 두고 번호만 공유한다.
ITEM_TYPE_PREFIX: dict[ItemType, str] = {
    "TASK": "TSK",
    "REQUIREMENT": "REQ",
    "ELIGIBILITY": "ELG",
    "SUBMISSION": "SUB",
    "SCHEDULE": "SCH",
    "EVALUATION": "EVL",
    "SPECIAL_CONDITION": "SPC",
    "REFERENCE": "REF",
}

ITEM_TYPE_LABEL: dict[ItemType, str] = {
    "TASK": "과업",
    "REQUIREMENT": "필수 요구사항",
    "ELIGIBILITY": "참가자격",
    "SUBMISSION": "제출",
    "SCHEDULE": "일정",
    "EVALUATION": "평가기준",
    "SPECIAL_CONDITION": "특이사항",
    "REFERENCE": "참고정보",
}

KST = timezone(timedelta(hours=9))

# --------------------------------------------------------------------------
# 1) 추출기 category → 기본 유형
# --------------------------------------------------------------------------
# rfp_extractor(실제 문서)와 rfp_parser(합성 fixture)의 category를 모두 다룬다.
_CATEGORY_TYPE: dict[str, ItemType] = {
    # rfp_extractor
    "입찰참가자격": "ELIGIBILITY",
    "평가": "EVALUATION",
    "제출서류": "SUBMISSION",
    "일정": "SCHEDULE",
    "과업내용": "TASK",
    "사업개요": "REFERENCE",
    "보안": "REQUIREMENT",
    "인력": "REQUIREMENT",
    # rfp_parser(합성 fixture 태그)
    "자격": "ELIGIBILITY",
    "제출": "SUBMISSION",
    "운영": "TASK",
    "보고": "TASK",
    "교육내용": "TASK",
    "수치": "REQUIREMENT",
    "증빙": "REQUIREMENT",
    "검수": "REQUIREMENT",
    "승인": "REQUIREMENT",
}

# --------------------------------------------------------------------------
# 2) 본문 표현 (강한 신호)
# --------------------------------------------------------------------------
_SPECIAL_RE = re.compile(
    r"보안\s*서약|비밀\s*유지|비밀\s*준수|서약서|각서|청렴\s*계약"
    r"|하도급|공동\s*수급|공동\s*이행|공동\s*계약|컨소시엄"
    r"|입찰\s*보증금|계약\s*보증금|보증금|지체상금|하자\s*보수|하자\s*담보|손해\s*배상"
    r"|저작권|소유권|귀속|지식\s*재산|참석\s*확인서"
)
_ELIGIBILITY_RE = re.compile(
    r"참가\s*자격|입찰\s*참가|자격\s*요건|참가\s*제한|면허|업종|업태|등록증|사업자\s*등록"
    r"|중소기업\s*확인|직접\s*생산|소기업|소상공인|여성\s*기업|장애인\s*기업|지역\s*제한|소재지|본점|지사"
    r"|(?:유사|동종)\s*(?:용역|사업|과업)?\s*실적|수행\s*실적|경력\s*\d|기술자\s*\d|이상\s*보유"
)
_SUBMISSION_RE = re.compile(
    r"제출\s*서류|제출\s*방법|제출\s*처|제출\s*장소|(?<![가-힣])부(?:씩|수)|USB|봉인|봉투"
    r"|방문\s*제출|우편\s*제출|직접\s*제출|전자\s*입찰|입찰서\s*제출|제안서\s*제출|제안서\s*작성\s*(?:방법|요령|지침)"
    r"|파일\s*형식|PDF|HWP|(?<![가-힣])서식|양식|날인|인감|간인|증빙\s*서류|첨부\s*서류"
)
_SUBMISSION_STRONG_RE = re.compile(
    r"제출\s*서류|제출\s*방법|제출\s*처|제출\s*장소|방문\s*제출|우편\s*제출|봉인|USB|(?<![가-힣])\d+\s*부(?![가-힣])"
)
_SCHEDULE_RE = re.compile(
    r"설명회|현장\s*설명|현장\s*방문|사전\s*등록|마감|기한|일시|접수\s*기간|제출\s*기간|공고\s*기간|입찰\s*일시|개찰"
    r"|까지|착수|납품\s*기한|사업\s*기간|용역\s*기간|계약\s*기간|과업\s*기간|교육\s*기간|일정|기간\s*[:：]"
)
_EVALUATION_RE = re.compile(
    r"평가|배점|점수|(?<![가-힣])가점|감점|기술\s*평가|가격\s*평가|협상\s*(?:에\s*의한|순위|대상)|적격\s*심사|심사"
    r"|(?:제안|기술)\s*발표|시연|프레젠테이션|PT|우선\s*협상"
)
# 과업(수행할 일)의 명사형 끝맺음 — rfp_extractor._TASK_TAIL_RE와 같은 취지.
_TASK_TAIL_RE = re.compile(
    r"(?:운영|기획|제공|지원|관리|배정|발급|진행|구성|개발|제작|실시|수행|편성|구축|설계|작성|보고|분석|조사|평가|교육|강의|멘토링|컨설팅)"
    r"(?:\s*및\s*[가-힣]+)?\s*(?:등)?\s*[.)]?$"
)
# 의무 표현 (요구사항 / 조건)
_OBLIGATION_RE = re.compile(
    r"[가-힣]야\s*(?:한다|합니다|하며|하고|하는|함|할|됨|된다)|하여야|해야|할\s*것|반드시|필수|의무|준수|금지|불가|할\s*수\s*없|해서는\s*안|아니\s*된다"
)

# --------------------------------------------------------------------------
# 3) 중대성(criticality) — 참가 자체를 막거나 행동이 필요한 조건
# --------------------------------------------------------------------------
_BLOCKER_BY_TYPE: dict[ItemType, re.Pattern[str]] = {
    "ELIGIBILITY": re.compile(
        r"제한|한정|에\s*한(?:함|한다)|만\s*(?:참가|참여|가능|입찰)|불가|없는\s*자|제외|소재지|본점|지역\s*제한|직접\s*생산|중소기업\s*확인"
    ),
    "SCHEDULE": re.compile(
        r"(?:설명회|현장\s*설명|현장\s*방문).{0,40}(?:필수|반드시|참석|필참|의무)"
        r"|(?:필수|반드시|의무).{0,40}(?:설명회|현장\s*설명|현장\s*방문)"
        r"|사전\s*등록|필참|미참석|참석\s*확인"
    ),
    "SUBMISSION": re.compile(r"방문\s*제출|봉인|직접\s*제출|지참|우편\s*제출|USB|(?<![가-힣])\d+\s*부|파일\s*형식|PDF|HWP"),
    "SPECIAL_CONDITION": re.compile(
        r"보증금|공동\s*수급.{0,20}(?:불가|금지|허용하지)|하도급.{0,20}(?:금지|불가|허용하지)|보안\s*서약|서약서|참석\s*확인서"
    ),
}
_ACTION_TYPES: frozenset[str] = frozenset({"ELIGIBILITY", "SUBMISSION", "SCHEDULE", "SPECIAL_CONDITION"})

# --------------------------------------------------------------------------
# 4) 날짜 (명시된 경우에만)
# --------------------------------------------------------------------------
_DATE_RE = re.compile(
    r"(?P<y>20\d{2})\s*[.\-/년]\s*(?P<m>\d{1,2})\s*[.\-/월]\s*(?P<d>\d{1,2})\s*일?\.?"
    r"(?:\s*[(（][^)）]{1,3}[)）])?"
    r"(?:\s*(?P<h>\d{1,2})\s*[:시]\s*(?P<mi>\d{2})?\s*분?)?"
)
_DUE_KEYWORD_RE = re.compile(r"까지|마감|기한|일시|설명회|접수|제출|개찰|등록")

#: 평가 절에 섞인 «서류를 내라» 줄 — 끝이 「제출 · 첨부」인 증빙 · 재무 서류 줄만 잡는다.
#:
#: 실측(가천대 계열 공고문): 「최근 2년 표준재무제표 첨부」 · 「수행실적 증빙서류(원본 1부 必,
#: 나머지 사본으로 제출)」 · 「사본 : 용역계약서 및 세금계산서(…) 함께 제출」이 평가기준(참고)으로
#: 빠져 필수 셈 · 「제출 · 일정」 탭에 없었다. 끝을 보므로 「증빙서류가 제출된 경우에 한해 인정한다」
#: 같은 평가 규칙 문장은 걸리지 않는다.
_EVALUATION_DOC_SUBMIT_RE = re.compile(
    r"(?:증빙|증명서|재무제표|세금\s*계산서|계약서)[^.]{0,40}(?:제출|첨부)"
    r"(?:하여야\s*(?:한다|함)|해야\s*함|할\s*것)?[)）]?(?:\s*[(（][^()（）]*[)）])?[\s.]*$"
)


def classify_item_type(category: str, content: str, source_text: str = "") -> ItemType:
    """category(추출기 분류) + 본문 표현으로 항목 유형을 정한다."""
    text = f"{content}\n{source_text}".strip()
    base = _CATEGORY_TYPE.get((category or "").strip())

    # 특이사항(하도급·보증금·보안서약 등)은 어느 절에 있어도 특이사항이다.
    if _SPECIAL_RE.search(text) and base not in ("EVALUATION",):
        # 평가 절의 "가점" 문장 등은 그대로 두고, 제출 절의 "서약서 제출"은 특이사항으로 본다.
        return "SPECIAL_CONDITION"

    # 평가 절의 증빙 · 재무 서류 제출 줄은 제출 항목이다 — 빠지면 점수를 잃는 서류다.
    if base == "EVALUATION" and _EVALUATION_DOC_SUBMIT_RE.search(content.strip()):
        return "SUBMISSION"

    if base in ("ELIGIBILITY", "EVALUATION", "SUBMISSION", "SCHEDULE"):
        return base

    if base == "TASK":
        # 과업 절 안에도 설명회·제출 방법·자격 문장이 섞여 들어온다.
        if _BLOCKER_BY_TYPE["SCHEDULE"].search(text):
            return "SCHEDULE"
        if re.search(r"제출\s*서류|방문\s*제출|봉인|(?<![가-힣])\d+\s*부\b", text):
            return "SUBMISSION"
        if re.search(r"참가\s*자격|입찰\s*참가\s*자격", text):
            return "ELIGIBILITY"
        return "TASK"

    # 기타 / 사업개요 / 보안 / 인력 / 미분류 → 본문으로 판단
    # "제출서류: 입찰참가신청서, 사업자등록증 …"처럼 서류 목록은 자격 낱말이 섞여도 제출 항목이다.
    if _SUBMISSION_STRONG_RE.search(text):
        return "SUBMISSION"
    if _ELIGIBILITY_RE.search(text) and re.search(r"자격|참가|실적|면허|업종|등록|확인서|소재지|본점", text):
        return "ELIGIBILITY"
    if _SUBMISSION_RE.search(text) and re.search(r"제출|서류|서식|양식|부|USB|봉인|PDF|HWP|날인|인감", text):
        return "SUBMISSION"
    if _EVALUATION_RE.search(text):
        return "EVALUATION"
    if _SCHEDULE_RE.search(text) and (_DATE_RE.search(text) or re.search(r"설명회|마감|기한|일시|기간|일정|까지|개찰", text)):
        return "SCHEDULE"
    if base == "REQUIREMENT":
        return "REQUIREMENT"
    if base == "REFERENCE":
        return "REFERENCE"
    if _OBLIGATION_RE.search(text):
        return "REQUIREMENT"
    if _TASK_TAIL_RE.search(content.strip()):
        return "TASK"
    return "REFERENCE"


def criticality_of(item_type: ItemType, requirement_type: str, content: str, source_text: str = "", *, category: str = "") -> Criticality:
    text = f"{content}\n{source_text}"
    if item_type == "REFERENCE" or requirement_type == "optional":
        return "low"
    pattern = _BLOCKER_BY_TYPE.get(item_type)
    if pattern is not None and pattern.search(text):
        # 평가 절에서 온 증빙 서류는 빠지면 점수를 잃지만 참가가 막히지는 않는다(「원본 1부」가 제출 차단 규칙에 걸림).
        # 사람 확인으로 다시 셀 때(correction_service)도 같은 함수라 「참가 차단」으로 바뀌지 않는다.
        # 사람이 유형을 「자격」 등으로 바꾼 줄은 그대로 차단 — 평가에서 온 «제출» 줄만 낮춘다.
        return "high" if item_type == "SUBMISSION" and (category or "").strip() == "평가" else "blocker"
    if item_type in _ACTION_TYPES:
        return "high"
    return "normal"


def action_required_of(item_type: ItemType, requirement_type: str) -> bool:
    return item_type in _ACTION_TYPES and requirement_type == "mandatory"


def _to_datetime(match: re.Match[str]) -> datetime | None:
    try:
        year, month, day = int(match["y"]), int(match["m"]), int(match["d"])
        hour = int(match["h"]) if match["h"] else 0
        minute = int(match["mi"]) if match["mi"] else 0
        if hour > 23 or minute > 59:
            return None
        return datetime(year, month, day, hour, minute, tzinfo=KST)
    except ValueError:
        return None


def due_at_of(item_type: ItemType, content: str, source_text: str = "") -> datetime | None:
    """본문에 날짜가 명시된 일정·제출 항목만 due_at을 돌려준다. 없으면 None (추측하지 않는다)."""
    if item_type not in ("SCHEDULE", "SUBMISSION", "ELIGIBILITY"):
        return None
    text = f"{content}\n{source_text}"
    if not _DUE_KEYWORD_RE.search(text):
        return None
    matches = list(_DATE_RE.finditer(text))
    if not matches:
        return None
    # "~까지"가 있으면 그 앞의 마지막 날짜가 마감이다.
    until = text.find("까지")
    if until >= 0:
        before = [m for m in matches if m.end() <= until]
        if before:
            return _to_datetime(before[-1])
    if len(matches) == 1:
        return _to_datetime(matches[0])
    # 기간("2026.9.1 ~ 2026.9.30")은 끝 날짜가 마감이다.
    if re.search(r"[~∼～-]", text):
        return _to_datetime(matches[-1])
    return None


def display_code(item_type: ItemType, requirement_id: str) -> str:
    """REQ-003 → TSK-003 처럼 유형 접두어만 바꾼 화면용 코드 (저장 id는 그대로)."""
    prefix = ITEM_TYPE_PREFIX.get(item_type, "REQ")
    number = requirement_id.split("-", 1)[1] if "-" in requirement_id else requirement_id
    return f"{prefix}-{number}"


# ---------------------------------------------------------------------------
# 대응 범위
# ---------------------------------------------------------------------------

#: 계약 일반조건. 제안서 본문에 다시 적을 것이 아니라 계약하면 지키는 것들이다.
#:
#: 실측(g2b-R26BK01707959-000): 「성과품 납품 후 1년 내 자문 요청에 성실히 응하여야」와
#: 「발주처 사정으로 용역기간이 추가 소요될 경우 조정할 수 있으며」가 제안서 누락 HIGH 로
#: 올라왔다. 둘 다 을이 지킬 조항이지 제안서에 서술할 과업이 아니다.
_CONTRACT_RE = re.compile(
    r"소유권|저작권|지식재산|비밀\s*유지|기밀|보안\s*서약"
    r"|계약\s*(?:해지|해제|파기)|해지할\s*수\s*있|하자|손해\s*배상|지체\s*상금"
    r"|분쟁|관할\s*법원|이의\s*를?\s*제기|청렴|부정\s*당|자문을\s*요청"
    r"|기간을\s*조정|정산|귀속"
)

#: 가격·견적. 제안서 본문이 아니라 가격제안서로 답한다.
_PRICE_RE = re.compile(r"가격\s*제안|입찰\s*가격|견적\s*서|산출\s*내역서|원가\s*계산")

#: 우리가 «하는» 일. 문서로 답하는 것이 아니라 날짜에 맞춰 움직여야 한다.
_INTERNAL_ACTION_RE = re.compile(
    r"설명회|현장\s*설명|사전\s*(?:등록|규격)|참가\s*등록|입찰\s*참가\s*신청"
    r"|질의\s*(?:응답|서)\s*제출|등록\s*마감"
)

#: 협의·조건에 따라 범위가 정해지는 것. 단정하면 안 된다.
_CONDITIONAL_RE = re.compile(r"협의\s*(?:하여|후|를\s*거쳐)|필요\s*시|해당\s*시|요청\s*시|권장")

#: 「서술」이 아니라 「증빙을 붙이는」 것. 평가 절에 실적·재무 증빙 요건이 섞여 들어온다.
#:
#: 실측(g2b-R26BK01707959-000): 「수행실적 증빙서류(원본 1부 必)」·「최근 2년 표준재무제표
#: 첨부」·「나라장터 발행 실적증명서로 대체 가능」이 EVALUATION 으로 분류돼 제안서 본문
#: 대응 대상이 됐다. 본문에 쓸 문장이 아니라 서류를 준비하는 일이다.
_EVIDENCE_DOC_RE = re.compile(
    r"증빙\s*서류|증명서|재무제표|사업자\s*등록증|납세|4대\s*보험|재직\s*증명"
    r"|인증서|등록증|면허증|자격증|원본\s*\d*\s*부|사본으로\s*제출"
)


def response_scope_of(
    item_type: ItemType,
    requirement_type: str,
    content: str,
    source_text: str = "",
) -> ResponseScope:
    """이 요구사항에 어디서 답하는가.

    유형(item_type)을 기본으로 삼되, 본문 표현이 더 구체적으로 말하면 그쪽을 따른다.
    **「해당 없음」은 규칙으로 만들지 않는다** — 원문만 보고 우리 사업에 해당하지
    않는다고 단정할 수 없기 때문이다. 사람이 정정으로만 넣을 수 있다.
    """
    text = f"{content} {source_text}"

    # 가격은 유형과 무관하게 가격제안서로 간다.
    if _PRICE_RE.search(text):
        return "PRICE_PROPOSAL"

    if item_type == "REFERENCE":
        return "REFERENCE_ONLY"
    if item_type == "ELIGIBILITY":
        return "ELIGIBILITY_DOCUMENT"
    if item_type == "SUBMISSION":
        return "SUBMISSION_CHECKLIST"
    if item_type == "SCHEDULE":
        # 일정 중 «참석·등록»은 우리가 움직여야 하는 것이고, 계약 기간 조항은 계약 준수,
        # 나머지는 수행 일정이라 본문이다.
        if _INTERNAL_ACTION_RE.search(text):
            return "INTERNAL_ACTION"
        return "CONTRACT_COMPLIANCE" if _CONTRACT_RE.search(text) else "PROPOSAL_BODY"
    if item_type == "SPECIAL_CONDITION":
        return "CONTRACT_COMPLIANCE" if _CONTRACT_RE.search(text) else "ELIGIBILITY_DOCUMENT"

    # TASK·EVALUATION·REQUIREMENT
    if _INTERNAL_ACTION_RE.search(text):
        return "INTERNAL_ACTION"
    if item_type in ("EVALUATION", "REQUIREMENT") and _EVIDENCE_DOC_RE.search(text):
        # 평가·조건 절에 섞인 증빙 요건. 서술이 아니라 서류 준비다.
        # TASK 에는 걸지 않는다 — 「인증서 발급 과정 운영」 같은 진짜 과업이 있다.
        return "ELIGIBILITY_DOCUMENT"
    if item_type == "REQUIREMENT" and _CONTRACT_RE.search(text):
        # 과업(TASK)·평가(EVALUATION)에는 걸지 않는다. 「하자 없는 교재 제작」 같은
        # 과업 문장이 계약조건으로 내려가면 진짜 누락이 숨는다.
        return "CONTRACT_COMPLIANCE"
    if requirement_type != "mandatory" or _CONDITIONAL_RE.search(text):
        return "CONDITIONAL"
    return "PROPOSAL_BODY"


def classify_fields(
    *,
    category: str,
    requirement_type: str,
    content: str,
    source_text: str = "",
    requirement_id: str = "",
) -> dict[str, Any]:
    """Requirement에 덧붙일 항목 유형 필드 묶음."""
    item_type = classify_item_type(category, content, source_text)
    return {
        "item_type": item_type,
        "response_scope": response_scope_of(item_type, requirement_type, content, source_text),
        "criticality": criticality_of(item_type, requirement_type, content, source_text, category=category),
        "action_required": action_required_of(item_type, requirement_type),
        "due_at": due_at_of(item_type, content, source_text),
        "display_code": display_code(item_type, requirement_id) if requirement_id else None,
    }


def enrich_payload(requirement: dict[str, Any], *, page_is_approximate: bool = False, force: bool = False) -> bool:
    """저장된 requirement dict에 항목 유형 필드를 채운다. 바뀐 것이 있으면 True.

    이미 item_type이 있는 항목(사람이 고친 것 포함)은 force가 아니면 건드리지 않는다.
    """
    changed = False
    if force or not requirement.get("item_type"):
        fields = classify_fields(
            category=str(requirement.get("category") or ""),
            requirement_type=str(requirement.get("requirement_type") or "mandatory"),
            content=str(requirement.get("content") or ""),
            source_text=str(requirement.get("source_text") or ""),
            requirement_id=str(requirement.get("requirement_id") or ""),
        )
        if fields["due_at"] is not None:
            fields["due_at"] = fields["due_at"].isoformat()
        requirement.update(fields)
        changed = True
    if "page_is_approximate" not in requirement:
        requirement["page_is_approximate"] = page_is_approximate
        changed = True
    if not requirement.get("review_status"):
        requirement["review_status"] = "unreviewed"
        changed = True
    if not requirement.get("response_scope"):
        # item_type 은 사람이 고쳤을 수 있으므로 «지금 값»을 기준으로 파생한다.
        requirement["response_scope"] = response_scope_of(
            requirement.get("item_type", "REQUIREMENT"),
            str(requirement.get("requirement_type") or "mandatory"),
            str(requirement.get("content") or ""),
            str(requirement.get("source_text") or ""),
        )
        changed = True
    if not requirement.get("display_code"):
        requirement["display_code"] = display_code(
            requirement.get("item_type", "REQUIREMENT"), str(requirement.get("requirement_id") or "")
        )
        changed = True
    return changed


def item_counts(requirements: list[dict[str, Any]] | list[Any]) -> dict[str, int]:
    """유형별 건수 (탭 배지용). 모든 유형 키를 0으로라도 넣는다."""
    counts: dict[str, int] = {t: 0 for t in ITEM_TYPES}
    for req in requirements:
        item_type = req.get("item_type") if isinstance(req, dict) else getattr(req, "item_type", None)
        key = item_type if item_type in counts else "REQUIREMENT"
        counts[key] += 1
    return counts
