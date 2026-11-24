"""사업계획서 초안 — 공고 양식 뼈대 위에 절마다 근거 묶음 → 작성 → 규칙 검증 → 검토 한 번 (25차 · prompt_15 §4-C).

## 흐름

1. **양식**(`plan_form_service`)의 대항목 · 소항목 · 표 순서가 초안의 순서다. 소항목 하나가 「절」 하나다.
2. **근거 묶음**(규칙) — 절마다: 겨냥하는 평가 항목 · 걸리는 공고 조항 · 고른 과제(과제소개서 발췌) · 회사 사실 ·
   실적 원장 후보 행 · 역량 · 채택된 회사자료. 조각마다 `source_id`. 묶음은 **안에서** 검증 · 화면에 쓴다.
3. **작성**(LLM · 절 하나에 한 번 · 구조화 출력) — 밖으로는 `llm_payload()` 하나를 거친 것만 보낸다(§2 허용 목록).
4. **검증**(규칙 · `plan_validation`) — 근거 없는 회사 주장은 `AI_SUGGESTION` 으로 내린다 · 예시 값 · 사람 칸 지움 ·
   금칙어 · 공고 문장 복사 · 사업비 합계·상한·비목 · 일정 범위.
5. **검토 한 번 → 고침 한 번**(LLM · 선택) — 평가위원 입장의 약점을 받고 걸린 절만 다시 쓴다(반복 없음).
   논리 호출 상한 = 절 수 + 2. 한 벌 전체 시간 상한 5분 — 호출마다 **남은 시간**을 제한 시간으로 넘기고, 남은 시간이
   30초 미만이면 새 호출을 하지 않는다(그 절은 규칙 내용 · 「시간 상한」 사유).

AI 가 꺼져 있거나(시연 기본) 크레딧이 확인되지 않으면 **규칙 초안(공고 양식 뼈대)** — 같은 순서 · 같은 표 ·
겨냥 평가 항목 · 공고 요구 인용 · 규칙이 맞춘 회사 사실 · 실적 후보, 나머지는 「(담당자 입력)」.
실패는 **절 단위** — 실패한 절만 규칙 내용 + 사유, 성공한 절은 남긴다.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core import storage
from app.services import llm_client, plan_validation
from app.services.plan_form_service import HUMAN_INPUT, TASK_PENDING

logger = logging.getLogger(__name__)

NOTICE = "RFP_GROUNDED"
COMPANY = "COMPANY_EVIDENCE_GROUNDED"
SUGGESTION = "AI_SUGGESTION"

#: 한 벌 시간 상한 — 중계 대기(nginx `proxy_read_timeout 300s` · 화면 중계 fetch 300초)보다 짧게 둔다(44차 M2). 같으면 끝무렵
#: 연결이 먼저 끊겨 화면은 실패인데 서버는 다 써서 저장했다. 남는 30초는 앞뒤 처리(검증 · 저장 · 응답) 몫이다.
TIME_LIMIT_SECONDS = 270.0
#: 남은 시간이 이보다 적으면 새 호출을 하지 않는다 — 한 절을 쓰는 데 20초 넘게 걸린다.
MIN_CALL_SECONDS = 30.0
#: 동시에 쓰는 절 수. ponytail: 고정 4 — 공급자 한도(429·사용 한도)에 걸리면 줄인다.
PARALLEL_WRITES = 4
#: 문단 분량 기준(§4-D) — 양식 권장 쪽수 × 쪽당 글자.
CHARS_PER_PAGE = 1500

AI_OFF_NOTE = "AI 사용 꺼짐 — 기본 초안(공고 양식 목차)"
#: 담당자가 「AI 없이」를 고른 경우 (29차 R28-01) — 서버 AI 가 켜져 있어도 부르지 않는다.
NO_AI_REASON = "담당자가 AI 없이 기본 초안을 골랐습니다"
#: 밖으로 보내지 않는 규칙 사실의 머리 — `support_application_service.COMPANY_FACT_WORDS` 의 고용 인원 · 소상공인 범위 · 매출.
PRIVATE_FACT_PREFIXES = ("고용 인원:", "소상공인 범위:", "매출:")
#: 회사 근거가 될 수 없는 source_id — 공고 · 과제 · 평가 기준(회사 주장은 회사 조각으로만 뒷받침한다).
NOTICE_ID_PREFIXES = ("clause:", "task:", "eval:")
#: 공고 근거 문장인데 인용이 문장의 이만큼도 안 되면 나머지는 우리 계획이다 — AI 제안으로 내린다.
#: ponytail: 글자 비율 휴리스틱 — 오탐이 보이면 문장을 인용 · 계획으로 나누는 쪽으로.
NOTICE_QUOTE_SHARE = 0.5
#: 회사 근거 문장에서 가리킨 조각 밖의 글자가 이보다 많으면 계획·추론이다(AI 제안).
COMPANY_UNCOVERED_CHARS = 40
#: 본문이 아니라 담당자 메모인 문장(좁게) — 빈칸 목록으로 옮긴다.
_MEMO_RE = re.compile(r"근거\s*자료로\s*확인되지\s*않|정리하기를\s*제안|평가\s*항목(?:인|에서|에\s*맞춰)"
                      # 평가위원에게 약점을 털어놓는 말 — 본문이 아니라 담당자 확인(29차 품질 확인 Q7)
                      r"|입증할\s*수\s*(?:없|는\s*없)|(?:구체성|적정성|설득력)이\s*(?:낮|떨어|부족)")
#: 본문에 새면 안 되는 작성 사정(내부 말) — 그 문장은 본문에서 내리고 담당자 확인으로 옮긴다(30차 §3-B · Codex 실측 C-03).
#: 작성 사정 **꼴**로만 좁힌다 — AI · RAG 과제의 기술 문장(「주어진 자료에서 근거 조각을 찾아 답한다」 · 「답을 지어내지 않도록」)은
#: 본문에 남는다(31차 R30-23). 「해당없음입니다」는 여기서 보지 않는다 — 양식이 「없을 시 해당없음」을 요구하면 본문이다(R30-22).
_INTERNAL_RE = re.compile(
    r"과제\s*소개서\s*발췌|source[_\s]?id|확인할\s*수\s*없으므로"
    r"|근거\s*조각(?:에는|에서는|에\s*따르면|이\s*없|만으로는)"
    r"|(?:근거|자료|확인)[^.]{0,15}단정하지\s*않"
    r"|지어내지\s*않았"
    r"|제공된\s*(?:자료|근거|정보)(?:만으로는|로는)\s*(?:확인|알\s*수|판단)"
    r"|주어진\s*(?:자료|근거|정보)(?:에는|에서는|만으로는|로는)\s*(?:확인|알\s*수|없)"
    r"|입력\s*자료에(?:는)?\s*(?:없|나와\s*있지)"
    # 32차 R31-31 — 「수치는 지어내지 않고 (담당자 입력)으로 비워 둡니다」 · 「단정하지 않고 확인 후 기재」 · 「제공된 자료만으로 작성」 ·
    # 「주어진 자료에 … 없어」 · 「입력 자료에서는 확인되지」. 문서를 **쓰는** 사정(빈칸 · 비워 · (담당자 입력) · 기재 · 작성)만 —
    # 「근거가 없으면 답을 지어내지 않고 담당자에게 넘깁니다」 같은 AI · RAG 기술 문장은 본문에 남는다.
    r"|(?:지어내지|단정하지)\s*않(?:았|고)[^.]{0,20}(?:\(\s*담당자\s*입력\s*\)|담당자가\s*(?:채[우워울웁]|적[어을는])|빈칸|비워|확인\s*후\s*(?:기재|작성|채))"
    r"|제공된\s*(?:자료|근거|정보)만으로\s*작성"
    r"|주어진\s*(?:자료|근거|정보)에[^.]{0,20}없어"
    r"|입력\s*(?:자료|정보)에서는\s*확인되지"
)
#: 「해당 없음이다 · 해당없음입니다」 — 양식 안내에 「없을 시 · 없으면」이 없을 때만 작성 사정으로 본다(31차 R30-22).
_NONE_RE = re.compile(r"해당\s*없음\s*(?:이다|입니다)")
_GUIDE_NONE_RE = re.compile(r"없을\s*시|없으면|없는\s*경우|해당\s*없음")
#: 「기관 현황 · 문제: (담당자 입력)」 줄 — 과제소개서가 없을 때 첫 소항목 한 곳에만(30차 §3-B · C-02 8절 반복).
_AGENCY_STATUS_RE = re.compile(r"기관\s*(?:의\s*)?현황\s*[·ㆍ,및]?\s*문제")
TASK_FIRST = "과제를 먼저 고르세요"
ANNEX_MISSING = "과제소개서(공고 첨부 [별첨 1])를 받으면 과제 해결방안을 더 구체적으로 씁니다"


# ---------------------------------------------------------------------------
# 구조화 출력 스키마 — 표는 양식 표마다 열이 정해진 모델(dict[str, Any] 가 아니다 · xAI 규칙)
# ---------------------------------------------------------------------------


class PlanSentenceOut(BaseModel):
    text: str
    type: Literal["RFP_GROUNDED", "COMPANY_EVIDENCE_GROUNDED", "AI_SUGGESTION"]
    source: str | None = None
    source_ids: list[str] = Field(default_factory=list)


class ScheduleRowOut(BaseModel):
    """「사업 추진일정」 — 추진 내용 · 추진 기간 · 세부 내용(+ 입찰 세부 추진 일정표의 담당(역할) · 산출물 · 2.9.0 · 사업계획서는 비워 둔다)"""

    task: str
    period: str
    detail: str
    owner: str = ""
    output: str = ""


class BudgetRowOut(BaseModel):
    """「사업비 집행계획」 — 비목 · 산출근거 · 금액(원)"""

    item: str
    basis: str
    amount_krw: int | None = None


class PlanTablesOut(BaseModel):
    schedule: list[ScheduleRowOut] = Field(default_factory=list)
    budget: list[BudgetRowOut] = Field(default_factory=list)


class PlanBlankOut(BaseModel):
    field: str
    why: str
    #: 채울 때 필요한 자료(증빙 서류 · 회사자료 칸 이름 · 2.10.0 m4) — 입찰 지시문만 묻는다. 빈 글이면 빈칸 목록에 싣지 않는다.
    proof: str = ""


class PlanSectionOut(BaseModel):
    sentences: list[PlanSentenceOut] = Field(default_factory=list)
    tables: PlanTablesOut = Field(default_factory=PlanTablesOut)
    blanks: list[PlanBlankOut] = Field(default_factory=list)


class ReviewWeakness(BaseModel):
    unit_key: str
    eval_item: str
    weakness: str


class ReviewFix(BaseModel):
    """고칠 문장 하나 — 초안 문장을 그대로 옮기고 어떻게 고칠지 한 줄."""

    unit_key: str
    sentence: str
    fix: str


class ReviewScore(BaseModel):
    """평가 항목 하나의 채점 (29차 §3-C) — 상 · 중 · 하 · 이유 · 맡은 소항목 · 고칠 문장."""

    eval_item: str
    grade: Literal["상", "중", "하"]
    reason: str
    unit_keys: list[str] = Field(default_factory=list)
    fixes: list[ReviewFix] = Field(default_factory=list)


class PlanReviewOut(BaseModel):
    """검토 호출 한 번의 답 — 평가위원 채점(`scores`). `weaknesses` 는 옛 모양(채점이 없을 때만 본다)."""

    scores: list[ReviewScore] = Field(default_factory=list)
    weaknesses: list[ReviewWeakness] = Field(default_factory=list)


#: 새 스키마 셋 — xAI 규칙 검사 대상(§4-A-5).
SCHEMAS: tuple[type[BaseModel], ...] = (PlanSectionOut, PlanReviewOut)


SYSTEM_PROMPT = f"""당신은 정부지원사업 사업계획서를 쓰는 담당자를 돕습니다. 결과는 담당자가 고쳐 쓸 **초안**입니다.
지킬 것:
- {llm_client.SOURCE_GUARD}
- 양식의 목차와 표를 바꾸지 않습니다. 주어진 소항목 하나만 씁니다.
- 공고 문장을 베끼지 말고, **우리 회사가 이 과제를 어떻게 하는지**를 씁니다.
- 회사에 대한 주장은 반드시 source_ids 로 근거 조각을 가리킵니다(COMPANY_EVIDENCE_GROUNDED). 근거가 없는 제안은 AI_SUGGESTION 입니다.
- 공고를 근거로 한 문장(RFP_GROUNDED)은 source 에 인용한 공고 문장을 그대로 두고 source_ids 를 답니다.
- 숫자는 근거 조각에 있는 것만 씁니다. 없으면 「(담당자 입력)」이라고 쓰고 blanks 에 올립니다.
- 양식의 예시 값(000, 0000.00.00, 예시 금액·날짜)을 쓰지 않습니다.
- 대표자·연락처·이메일·사업자등록번호·주소·인력 성명·매출액·고용인원·수상 이력은 쓰지 않습니다(목록은 따로 만듭니다).
- 「보장·최고·유일·100%·선정 확률」 같은 표현을 쓰지 않습니다.
- 평가위원이 찾는 것(이해도 · 구체성 · 차별성 · 지속 가능성)을 **계획으로** 보여 줍니다. 평가하는 말 · 약점을 털어놓는 말(「입증할 수 없다」 · 「구체성이 낮다」)은 본문에 쓰지 않습니다.
- RFP_GROUNDED 는 공고의 요구를 옮겨 말하는 문장에만 씁니다. 우리 회사의 계획·제안은 AI_SUGGESTION 입니다.
- 실적의 발주기관(client_agency)을 협력·공동 운영 기관처럼 쓰지 않습니다 — 「OO이 발주한 …」.
- 외부 기관의 신청 절차·제공처·데이터셋 이름을 근거 없이 단정하지 않습니다. 모르면 blanks 에 올립니다.
- 사업비 비목은 공고의 비목 정의(budget_item_reference)에 맞춰 고릅니다(예: 반영구 비품은 기계장치).
- 회사 사실(COMPANY_EVIDENCE_GROUNDED)과 그 사실로 하는 계획·추론(AI_SUGGESTION)은 다른 문장으로 나눕니다.
- 사업영역·인증·품목 이름만으로 수행 경험이나 보유 제품이 있다고 쓰지 않습니다.
- 소항목을 회사 소개(설립·사업영역) 문장으로 시작하지 않습니다 — 회사 소개는 역량 절이 맡습니다.
- 첫 문장에서 과제명·평가 기준을 되풀이하지 않습니다(과제·공고 요구 인용 줄은 따로 붙습니다). 「~을 보여 주어야 합니다」처럼 평가 기준을 옮기는 문장은 쓰지 않습니다.
- 담당자에게 하는 말, 근거가 없다는 설명, 평가 항목 이름을 직접 부르는 말은 본문이 아니라 blanks 에 씁니다.
- 빈칸은 정확히 「(담당자 입력)」만 씁니다. 선택지·예시는 blanks 의 why 에 씁니다.
- blanks 에는 이 소항목 본문·표에 「(담당자 입력)」으로 남긴 칸과 확인이 필요한 AI 제안만 올립니다. 「있으면 추가」 같은 권유나 다른 곳에서 채우는 칸(인력 구성·수상 이력 표, 대표자·연락처 등)은 올리지 않습니다.
- blanks 의 why 는 담당자가 읽을 말로 씁니다(source_id · 근거 조각 같은 내부 용어를 쓰지 않습니다).
쓰는 틀(29차 — 평가위원이 읽는 순서):
- 소항목 본문은 ① 현황 → ② 문제 → ③ 해결 방안 → ④ 차별성 → ⑤ 기대 성과 순서로 씁니다. 머리표(①~⑤)는 쓰지 않고 문장 흐름으로 잇습니다.
  소항목 성격에 맞지 않는 단계(예: 집행 계획의 「차별성」)는 건너뜁니다.
- 기대 성과의 정량 목표는 공고 · 과제 · 회사 근거 조각에 있는 숫자만 씁니다. 없으면 「(담당자 입력)」로 두고 blanks 에 올립니다.
- 공고 · 과제에서 쓰는 이름(과제명 · 기관명 · 데이터 이름 · 평가 항목의 말)을 바꾸지 않고 그대로 씁니다. 같은 것을 두 이름으로 부르지 않습니다.
- 다른 소항목이 맡은 내용(회사 소개 · 추진 일정 · 사업비)을 되풀이하지 않습니다. 같은 문장을 두 번 쓰지 않습니다.
- 주어진 목표 분량에 맞춥니다(±20%). 짧다고 지어내지 말고, 근거가 없으면 빈칸으로 둡니다.
- ④ 차별성은 기술 · 경쟁력 소항목에서만 씁니다. 다른 소항목은 건너뜁니다.
- AI 의 역할 · 한계(예: 「AI 는 판정을 돕는다」) 같은 설명은 한 소항목에서 한 번만 씁니다. 그 소항목에 새로운 내용만 씁니다.
- 정량 성과 지표는 추진 계획 소항목에서만 정합니다. 다른 소항목은 새 지표 이름을 만들지 않습니다.
- 회사를 부를 때는 「당사」 하나로 씁니다. 과제명의 핵심어(예: DX/AX 전환)는 본문에서도 그대로 씁니다.
- 과제소개서 발췌(task.annex_excerpt)가 있으면 기관의 현황 · 문제 · 쓸 공공데이터 · 협업 요구사항을 그 글로 씁니다 — 옮긴 문장은 RFP_GROUNDED 로 source 에 그 글을 그대로 두고 source_ids 에 task 를 답니다.
- 과제소개서 발췌가 없으면 기관의 현황 · 문제를 가정 문장(「~라면 ~어렵다」)으로 채우지 않습니다. 「기관 현황 · 문제: (담당자 입력)」 줄은 지시가 있는 소항목에만 한 번 둡니다.
쉬운 문장(30차 — 담당자 「내용이 어렵다」):
- 한 문장에 한 뜻만 씁니다. 문장은 80자 안팎, 120자를 넘기지 않습니다.
- 「·」로 늘어놓는 것은 셋까지입니다. 넘으면 문장을 나누거나 개조식으로 씁니다.
- 같은 산출물 목록 · 같은 문장을 되풀이하지 않습니다.
- 기관 현황 숫자(건수 · 인원 · 금액)는 한 절에서 한 번만, 같은 기준 연도로 씁니다 — 절마다 다른 해를 골라 되풀이하지 않습니다.
- 소항목 안에서 짧은 소제목이나 개조식 줄(「○ …」 · 「- …」)을 써도 됩니다.
- 본문에는 우리 계획만 씁니다. 「과제소개서 발췌」 · 「근거 조각」 · 「source_id」 · 「단정하지 않고」 · 「지어내지」 같은 작성 사정은 쓰지 않습니다 — 확인할 것은 blanks 에 씁니다.
- 양식 안내에 「없으면 ○○」이 있으면 근거가 없을 때 그대로 ○○로 씁니다(예: 유사 개발 이력이 없으면 「해당없음」). 다른 종류의 실적으로 대신하지 않습니다.
- 역량(skills)의 level=proven 은 회사가 스스로 적은 값입니다 — 「검증된 · 인증된 · 공인」이라고 쓰지 않습니다.
- 추진 계획 본문에서 일정표를 개월차별로 다시 읽지 않습니다. 일정표 행은 과업 단계(기관 협의 · 개발 · 검증 · 산출물 · 계약 등)로 고릅니다.
- 사업 추진일정 표: 협약 기간 안에서 과업 단계마다 한 줄 · 추진 기간은 「1~2개월차」처럼 개월차로 적습니다(달력 날짜를 지어내지 않습니다).
- 사업비 집행계획 표: 허용 비목마다 한 줄 · 금액(amount_krw)은 비워 둡니다(null) · 산출근거에는 담당자가 적을 산식 한 줄을 씁니다
  (예: 「개발 인력 (담당자 입력)명 × 월 (담당자 입력)원 × 5개월」). 금액을 지어내지 않습니다."""

REVIEW_PROMPT = f"""당신은 이 지원사업의 평가위원입니다. 공고의 평가 항목마다 초안을 채점합니다(scores).
{llm_client.SOURCE_GUARD}
- grade: 상(그대로 제출해도 설득력 있음) · 중(보완하면 됨) · 하(평가위원이 감점할 수준) 중 하나.
- reason: 그렇게 본 이유 한 줄(칭찬은 적지 않습니다).
- unit_keys: 그 항목을 맡은 소항목 키.
- fixes: 고칠 문장 3개 이내 — sentence 에는 초안 문장을 **그대로** 옮기고, fix 에는 어떻게 고칠지 한 줄.
초안에 없는 기관명·데이터셋 이름·신청 절차를 채우라고 요구하지 않습니다 — 모르는 것은 담당자 확인으로 적습니다.
숫자를 지어내라고 요구하지 않습니다. reason · fix 안에서는 unit_key 대신 소항목 제목으로 부릅니다.
weaknesses 는 비워 둡니다."""
#: 무료(현물) 지원 공고에 덧붙이는 채점 지시 — 공고에 사업비가 없는데 「예산표를 덧붙이라」고 권했다(36차 PLAN-03 · 123852).
IN_KIND_REVIEW_RULE = "이 공고는 무료(현물) 지원입니다 — 사업비 · 예산표 · 자부담 · 자금 소요 계획을 요구하지 않습니다(그것으로 감점하지 않습니다)."


# ---------------------------------------------------------------------------
# 절(unit) · 근거 묶음
# ---------------------------------------------------------------------------

#: 평가 항목 이름 조각 → 그 항목을 겨냥하는 소항목의 낱말 (규칙).
_EVAL_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("이해도", ("공공데이터", "과제", "해결", "요구", "개요")),
    ("구성", ("역량", "팀", "인력", "수상", "대표자")),
    ("실현", ("추진", "일정", "산출물", "개발", "집행", "사업비", "기술", "경쟁력", "차별")),
    ("구체", ("추진", "산출물", "개발", "집행")),
    ("지속", ("사업화", "지속", "확산", "후속", "성장")),
    ("문제", ("배경", "필요", "개요", "시장")),
    ("성장", ("사업화", "전략", "자금", "추진")),
)

#: 공고 조항 갈래 → 그 조항을 받을 소항목 낱말 (규칙). 못 찾으면 첫 소항목.
_CLAUSE_TARGETS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("money",), ("집행", "예산", "사업비", "자금")),
    (("deadline",), ("추진", "일정")),
    (("location", "org_type", "sme", "founding_years", "headcount", "revenue", "exclusion"), ("역량", "팀", "구성")),
    (("prerequisite", "role", "strategic_industry"), ("과제 해결", "해결", "개발 방안", "아이템", "과제")),
)
#: 초안 절에 싣지 않는 조항 종류 — 제외 대상(탈락 점수 · 신청 개수 · 제외 업종)은 신청 자격 단계가 공고 인용으로 보여 준다
#: (공고문을 못 읽었으면 그 단계의 「제외 대상 — 원문 확인」 항목 · 27차 R26-14 바로잡음).
#: `route_clauses` 와 반영 셈(`support_plan_service.uncovered_quotes`)이 **같은 상수**를 읽는다(26차 ISSUE-147) —
#: 싣지 않은 조항을 「초안에 반영 안 됨」으로 세면 지울 수 없는 경고가 된다.
PLAN_SKIPPED_CLAUSE_KINDS: tuple[str, ...] = ("exclusion",)
CLAUSE_KINDS: tuple[str, ...] = (
    "location", "org_type", "sme", "founding_years", "headcount", "revenue",
    "prerequisite", "role", "strategic_industry", "exclusion", "money", "deadline",
)


def clause_id(kind: str, text: str) -> str:
    """조항의 영구 id — 같은 원문이면 같은 id(재생성 · AI 재작성에도 반영 셈이 흔들리지 않게)."""
    return "clause:" + hashlib.sha1(f"{kind}|{(text or '').strip()}".encode("utf-8")).hexdigest()[:10]


def form_units(form: dict[str, Any]) -> list[dict[str, Any]]:
    """양식 → 절 목록. 소항목이 있는 대항목은 소항목마다, 없는 대항목(일반 현황 · 기업 현황)은 칸 묶음 하나."""
    units: list[dict[str, Any]] = []
    tables = form.get("tables") or []
    for section in form.get("sections") or []:
        items = section.get("items") or []
        if items:
            for item in items:
                units.append({
                    "key": item["key"], "kind": "item", "title": item["title"], "optional": bool(item.get("optional")),
                    "major_key": section["key"], "major_title": section["title"], "guide": item.get("guide") or "",
                    "tables": [t["key"] for t in tables if t.get("item") == item["key"]],
                })
            loose = [t["key"] for t in tables if t.get("section") == section["key"] and not t.get("item")]
            if loose:
                units[-len(items)]["tables"] = loose + units[-len(items)]["tables"]
        else:
            units.append({
                "key": section["key"], "kind": "fields", "title": section["title"], "optional": False,
                "major_key": section["key"], "major_title": section["title"], "guide": "",
                "fields": section.get("fields") or [],
                "tables": [t["key"] for t in tables if t.get("section") == section["key"]],
            })
    return units


def eval_targets(unit: dict[str, Any], evaluation: dict[str, Any]) -> list[dict[str, Any]]:
    """절이 겨냥하는 평가 항목(규칙) — 항목 이름 조각의 힌트 낱말이 절 제목 · 안내에 있으면."""
    if unit["kind"] != "item" or unit.get("optional"):
        return []
    text = f"{unit['title']} {unit.get('guide') or ''}"
    scored: list[tuple[int, int, dict[str, Any]]] = []
    for index, item in enumerate(evaluation.get("items") or []):
        hints = {w for piece, words in _EVAL_HINTS if piece in item["name"] for w in words}
        score = sum(1 for w in hints if w in text)
        if score:
            scored.append((score, -index, {"id": f"eval:{index + 1}", "name": item["name"], "detail": item.get("detail")}))
    if not scored:
        return []
    best = max(s for s, _, _ in scored)
    return [entry for s, _, entry in sorted(scored, key=lambda x: (-x[0], -x[1])) if s == best][:2]


def _words(text: str) -> set[str]:
    return set(re.findall(r"[가-힣A-Za-z]{2,}", text or ""))


def route_clauses(units: list[dict[str, Any]], requirements) -> dict[str, list[dict[str, Any]]]:
    """공고 조항을 받을 절(규칙). 반영 셈은 이 조항 id 로 센다."""
    routed: dict[str, list[dict[str, Any]]] = {u["key"]: [] for u in units}
    if requirements is None or not getattr(requirements, "document_read", False):
        return routed
    writable = [u for u in units if u["kind"] == "item" and not u.get("optional")] or units
    for kind in CLAUSE_KINDS:
        if kind in PLAN_SKIPPED_CLAUSE_KINDS:
            continue  # 제외 조항(탈락 점수 · 신청 개수)은 자격 판정·점검표가 다룬다 — 계획서 절의 요구가 아니다
        for clause in requirements.of(kind):
            text = (clause.source_text or "").strip()
            if not text:
                continue
            target = None
            for kinds, words in _CLAUSE_TARGETS:
                if kind in kinds:
                    target = next((u for u in writable if any(w in u["title"] for w in words)), None)
                    break
            target = target or writable[0]
            entry = {"id": clause_id(kind, text), "kind": kind, "label": clause.label, "text": text}
            if all(e["id"] != entry["id"] for e in routed[target["key"]]):
                routed[target["key"]].append(entry)
    return routed


def company_sources(organization_id: str, evidence_scope: str | None) -> dict[str, Any]:
    """회사 쪽 원자료(안에서만 쓴다). 밖으로는 `llm_payload` 의 허용 목록만 나간다."""
    from app.services import delivery_capacity_service, organization_service

    try:
        profile = organization_service.load_profile(organization_id)
    except Exception:  # noqa: BLE001 — 프로필이 없어도 규칙 초안은 만든다
        profile = None
    capacity = delivery_capacity_service.load(organization_id)
    ledger_rows: list[dict[str, Any]] = []
    ledger_all: list[dict[str, Any]] = []
    if evidence_scope == "internal":
        from app.services import performance_match_service as _pm

        try:
            raw = _pm.load_ledger(_pm.ledger_path_for(organization_id))
            ledger_rows = [dict(r) for r in _pm.project_rows(raw)]
            # 역량 절은 지정 · 인증 · 저작권 행도 근거 후보(같은 원장 · 같은 칸 · 외부 사용 「가능」만 — 30차 §3-B)
            # 「회사 기본」(대표자 · 주소 같은 일반현황) 행은 빼고 — 일반현황은 문서를 조립할 때만 채운다(§2 · 30차 §4 마지막 검토)
            ledger_all = [dict(r) for r in _pm.eligible_rows(raw) if "회사 기본" not in str(r.get("field") or "")]
        except Exception:  # noqa: BLE001
            ledger_rows, ledger_all = [], []
    return {
        "profile": profile.model_dump(mode="json") if profile is not None else {},
        "capacity": capacity.model_dump(mode="json"),
        "ledger": ledger_rows,
        "ledger_all": ledger_all,
    }


def build_bundle(
    unit: dict[str, Any],
    *,
    form: dict[str, Any],
    clauses: list[dict[str, Any]],
    company: dict[str, Any],
    facts: list[str],
    matches: list[dict[str, Any]],
    annex: str | None,
) -> dict[str, Any]:
    """절 하나의 근거 묶음(규칙) — 안에서 검증 · 화면에 쓰는 전체. `form_examples` 는 넣지 않는다."""
    task = form.get("selected_task")
    targets = eval_targets(unit, form.get("evaluation") or {})
    capability_unit = any(w in unit["title"] for w in ("역량", "팀", "기술", "경쟁력", "구성"))
    # 근거 고르기(30차 §3-B · C-04): 과제(제목 · 기관 · 과제소개서 요구사항) 낱말과 겹치는 원장 행을 먼저 — 예전에는 소항목 제목
    # 낱말로만 매겨 「가상기업 데이터 분석 활용 지원사업」이 밀렸고, 역량 절에는 수행 실적 분야 행만 실어 지정 · 저작권 행이 빠졌다.
    # 보내는 칸(제목 · 연도 · 분야 · 발주 · 요약) · 범위(외부 사용 「가능」) · 개수(3)는 그대로.
    task_words = _words(f"{(task or {}).get('title') or ''} {(task or {}).get('agency') or ''} {annex or ''}")
    topic = _words(f"{unit['title']} {unit.get('guide') or ''}") | task_words
    pool = company.get("ledger_all") if capability_unit and company.get("ledger_all") is not None else company.get("ledger")
    ledger = [r for r in pool or [] if str(r.get("external_use") or "") == "가능"]

    def _rank(row: dict[str, Any]) -> tuple[int, int, int]:
        words = _words(f"{row.get('title')} {row.get('summary')} {row.get('field')}")
        year = str(row.get("year") or "0")
        return (-len(task_words & words), -len(topic & words), -int(year) if year.isdigit() else 0)

    ledger.sort(key=_rank)
    # 사람 수 · 매출이 든 규칙 사실은 싣지 않는다 — 「고용 인원: … 회사는 17인이다」가 그대로 나간다(허용 목록 밖).
    facts = [t for t in facts if not t.startswith(PRIVATE_FACT_PREFIXES)]
    # 실적 · 역량은 역량 절(과 기업 현황 칸)에만 — 여덟 절이 같은 실적 두 줄을 되풀이하지 않게.
    with_record = capability_unit or unit["kind"] == "fields"
    return {
        "unit": unit,
        "capability": capability_unit,
        "targets": targets,
        "clauses": clauses,
        "task": task,
        "annex": annex,
        "facts": [{"id": f"fact:{i + 1}", "text": text} for i, text in enumerate(facts)] if capability_unit else [],
        "ledger": [{**row, "id": f"ledger:{row.get('seq')}"} for row in ledger[:3]] if with_record else [],
        "profile": company.get("profile") or {},
        "capacity": company.get("capacity") or {},
        "evidence": [{**m, "id": m.get("id") or m.get("evidence_id")} for m in matches if m.get("selected")][:3] if capability_unit else [],
        "agreement": (form.get("agreement_period") or {}).get("text"),
        "agreement_months": (form.get("agreement_period") or {}).get("months"),
        "cutoff": (form.get("evaluation") or {}).get("cutoff"),
        "cap_krw": (form.get("budget") or {}).get("cap_krw"),
        "allowed_items": (form.get("budget") or {}).get("allowed_items") or [],
        "item_reference": (form.get("budget") or {}).get("item_reference"),
    }


#: 회사가 손으로 적은 글(원장 제목 · 요약 · 사업영역)에 섞인 주민등록번호 · 비밀 열쇠 꼴(2.7.0 · 계획 9) — 밖(LLM)으로 보내기 전에 가린다.
_RRN_RE = re.compile(r"(?<!\d)\d{6}\s*-\s*[1-4]\d{6}(?!\d)")
_TOKEN_RE = re.compile(r"\b(?:sk|pk|rk|ghp|gho|github_pat|xox[abpr])[-_][A-Za-z0-9_-]{16,}|\bBearer\s+[A-Za-z0-9._~+/-]{16,}=*"
                       r"|(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{40,}(?![A-Za-z0-9_-])")


def safe_text(value: Any) -> Any:
    """밖으로 보낼 회사 자유 글 — 전화 · 이메일(`mask_contact_text`) · 주민등록번호 · 비밀 열쇠 꼴을 가린다. 글이 아니면 그대로.
    입찰 제안서 · 사업계획서 작성기의 `llm_payload` 가 함께 쓴다."""
    from app.services import procurement_service

    if not isinstance(value, str):
        return value
    masked = procurement_service.mask_contact_text(value)
    return _TOKEN_RE.sub("(가림)", _RRN_RE.sub("(주민등록번호 가림)", masked))


def llm_payload(bundle: dict[str, Any]) -> dict[str, Any]:
    """**밖(LLM)으로 보내는 본문은 이 함수 하나로만 만든다** (§2 허용 목록).

    보내는 것: 공고문 발췌(조항 · 평가 기준 · 안내 문구 · 협약 기간 · 사업비 상한 · 허용 비목) · 고른 과제명(과제소개서 발췌) ·
    회사 프로필의 사업영역 · 인증 · 설립연도 · 활동 지역 · 실적 원장 중 외부 사용 「가능」 행의 제목 · 연도 · 분야 · 발주 · 요약 ·
    역량의 skills(name · level) · 보유(held == true) 자격 이름 · business_items 이름 · 채택 회사자료의 source_id 와 문서명.
    보내지 않는 것: 사업자등록번호 · 대표자 · 연락처 · 주소 · 매출 · 인원(developer_count 포함) · 회사 예산 상한 ·
    원장의 금액 · evidence_note · warnings · exclusion_reason · 조항 확인 메모 · team_note · note · 채택 회사자료 본문.
    """
    unit = bundle["unit"]
    profile = bundle.get("profile") or {}
    capacity = bundle.get("capacity") or {}
    task = bundle.get("task")
    capable = bool(bundle.get("capability"))
    payload: dict[str, Any] = {
        "form_item": {"key": unit["key"], "title": unit["title"], "section": unit["major_title"], "guide": unit.get("guide") or ""},
        "evaluation": [{"source_id": t["id"], "name": t["name"], "detail": t.get("detail")} for t in bundle.get("targets") or []],
        "notice": {
            "clauses": [{"source_id": c["id"], "text": c["text"]} for c in bundle.get("clauses") or []],
            "agreement_period": bundle.get("agreement"),
            "budget_cap_krw": bundle.get("cap_krw") if "budget" in unit.get("tables", []) else None,
            "allowed_budget_items": bundle.get("allowed_items") if "budget" in unit.get("tables", []) else [],
            "budget_item_reference": bundle.get("item_reference") if "budget" in unit.get("tables", []) else None,
        },
        "task": (
            {"source_id": f"task:{task.get('no')}", "no": task.get("no"), "agency": task.get("agency"), "title": task.get("title"),
             "annex_excerpt": bundle.get("annex")}
            if task else None
        ),
        # 회사 조각마다 source_id — 회사 주장은 이 id 로만 뒷받침한다(공고·과제 id 로는 회사 근거가 되지 않는다).
        "company": {
            # 사업영역도 역량 절에만 — 3차 시험 실행에서 같은 소개 문장(「당사는 AI SaaS … 사업영역으로」)이 여덟 절을 열었다.
            "business_domains": {"source_id": "profile:domains", "values": [str(d) for d in profile.get("business_domains") or []]} if capable else None,
            # 인증 · 설립연도 · 자격 · 품목은 역량 절에만 — 여덟 절이 같은 회사 소개 문장으로 시작하지 않게.
            "certifications": [{"source_id": f"profile:cert:{name}", "name": name} for name in _certifications(profile)] if capable else [],
            "founded_year": {"source_id": "profile:founded", "value": profile.get("founded_year")} if capable else None,
            # 활동 지역도 역량 절에만 — 27차 검수 D4: 표준 양식 초안에서 여덟 절 중 일곱 절의 회사 근거가 이 한 줄이었다.
            "activity_regions": {"source_id": "profile:regions", "values": [str(r) for r in profile.get("preferred_regions") or []]} if capable else None,
            "facts": [{"source_id": f["id"], "text": f["text"]} for f in bundle.get("facts") or []],
            "performance": [
                # 회사가 손으로 적은 글은 연락처 · 주민등록번호 · 비밀 열쇠 꼴을 가린다(2.7.0 · `safe_text`)
                {"source_id": r["id"], "title": safe_text(r.get("title")), "year": r.get("year"), "field": safe_text(r.get("field")),
                 "client_agency": safe_text(r.get("agency")), "summary": safe_text(r.get("summary"))}
                for r in bundle.get("ledger") or []
            ],
            "skills": [{"source_id": f"skill:{s.get('name')}", "name": s.get("name"), "level": s.get("level")}
                       for s in capacity.get("skills") or []] if bundle.get("capability") else [],
            "credentials": [{"source_id": f"cap:cred:{name}", "name": name} for name in _credentials(capacity)] if capable else [],
            "business_items": [{"source_id": f"cap:item:{name}", "name": name} for name in _business_items(capacity)] if capable else [],
            "documents": [{"source_id": str(m.get("id")), "document_name": m.get("document_name") or m.get("title")} for m in bundle.get("evidence") or []],
        },
        "tables": [key for key in unit.get("tables", []) if key in ("schedule", "budget")],
    }
    return payload


def source_texts(bundle: dict[str, Any]) -> dict[str, str]:
    """source_id → 대조할 원문(안). 검증이 회사 근거 문장의 숫자 · 기관명 · 연도를 여기서 찾는다."""
    texts: dict[str, str] = {}
    for target in bundle.get("targets") or []:
        texts[target["id"]] = f"{target['name']} {target.get('detail') or ''}"
    for clause in bundle.get("clauses") or []:
        texts[clause["id"]] = clause["text"]
    task = bundle.get("task")
    if task:
        texts[f"task:{task.get('no')}"] = f"{task.get('agency') or ''} {task.get('title') or ''} {bundle.get('annex') or ''}"
    for fact in bundle.get("facts") or []:
        texts[fact["id"]] = fact["text"]
    for row in bundle.get("ledger") or []:
        texts[row["id"]] = " ".join(str(row.get(k) or "") for k in ("year", "field", "title", "agency", "summary"))
    capacity = bundle.get("capacity") or {}
    if bundle.get("capability"):
        for skill in capacity.get("skills") or []:
            texts[f"skill:{skill.get('name')}"] = str(skill.get("name"))
    for match in bundle.get("evidence") or []:
        texts[str(match.get("id"))] = str(match.get("document_name") or match.get("title") or "")
    profile = bundle.get("profile") or {}
    texts["profile:domains"] = " ".join(str(d) for d in profile.get("business_domains") or [])
    texts["profile:founded"] = f"{profile.get('founded_year') or ''}년 설립"
    texts["profile:regions"] = " ".join(str(r) for r in profile.get("preferred_regions") or [])
    if bundle.get("capability"):
        for name in _certifications(profile):
            texts[f"profile:cert:{name}"] = name
        for name in _credentials(capacity):
            texts[f"cap:cred:{name}"] = name
        for name in _business_items(capacity):
            texts[f"cap:item:{name}"] = name
    else:
        texts.pop("profile:founded", None)
        texts.pop("profile:regions", None)  # 보내지 않은 조각은 근거가 될 수 없다(D4)
        texts.pop("profile:domains", None)
    return texts


def _certifications(profile: dict[str, Any]) -> list[str]:
    return [str(c.get("name")) if isinstance(c, dict) else str(c) for c in profile.get("certifications") or []]


#: 사업계획서 「보유 인증」에 넣지 않는 준비 상태 줄 — 나라장터 입찰 등록 · 공동인증서는 인증이 아니다(31차 §3-B · 마지막 검토).
_NOT_A_CREDENTIAL = ("입찰참가자격", "공동인증서")


def _ledger_head(row: dict[str, Any]) -> str:
    """실적 목록 행의 분야 → 기본 초안 머리말. 수행 실적 · 지정 · 선정 · 지식재산(31차 R30-25)."""
    field = str(row.get("field") or "")
    if "지식재산" in field or "저작권" in field:
        return "지식재산 후보"
    if "지원사업" in field or "기관자격" in field or "지정" in field or "인증" in field:
        return "지정 · 선정 후보"
    return "수행 실적 후보"


def _credentials(capacity: dict[str, Any]) -> list[str]:
    # 유효기간이 지난 줄은 「있음」이어도 회사 근거로 쓰지 않는다(31차 마지막 검토 — 만료된 확인서가 「보유 인증」으로 나갔다).
    today = storage.kst_today().isoformat()
    return [
        str(c.get("name")) for c in capacity.get("credentials") or []
        if c.get("held") is True
        and not any(word in str(c.get("name") or "") for word in _NOT_A_CREDENTIAL)
        and not (c.get("valid_until") and str(c.get("valid_until"))[:10] < today)
    ]


def _business_items(capacity: dict[str, Any]) -> list[str]:
    return [str(i) for i in capacity.get("business_items") or []]


# ---------------------------------------------------------------------------
# 규칙 초안(공고 양식 뼈대)
# ---------------------------------------------------------------------------


def _sentence(text: str, kind: str | None, source: str | None = None, ids: list[str] | None = None, **extra: Any) -> dict[str, Any]:
    row: dict[str, Any] = {"text": text, "type": kind, "source": source, "source_ids": ids or []}
    if kind is None:
        row["note"] = True
    row.update(extra)
    return row


def rule_unit(unit: dict[str, Any], bundle: dict[str, Any], *, company_name: str | None) -> dict[str, Any]:
    """절 하나의 규칙 내용 — 지어내지 않는다. 겨냥 평가 항목 · 공고 요구 인용 · 회사 사실 · 실적 후보 · 빈칸."""
    sentences: list[dict[str, Any]] = []
    fields: list[dict[str, Any]] = []
    blanks: list[dict[str, str]] = []
    task = bundle.get("task")
    if unit["kind"] == "fields":
        profile = bundle.get("profile") or {}
        ledger = bundle.get("ledger") or []
        for field in unit.get("fields") or []:
            label = field["label"]
            value, ids = HUMAN_INPUT, []
            if label == "과제명":
                value = f"{task['title']}" if task else TASK_PENDING
                ids = [f"task:{task['no']}"] if task else []
            elif label == "기업명" and company_name:
                value = company_name
            elif label.startswith("사업분야") and profile.get("business_domains"):
                value, ids = " · ".join(str(d) for d in profile["business_domains"]), ["profile:domains"]
            elif label == "사업수행 실적" and ledger:
                value = " / ".join(f"{r.get('year') or ''} {r.get('title')}".strip() for r in ledger)
                ids = [r["id"] for r in ledger]
            human = bool(field.get("human_only"))
            fields.append({"label": label, "value": value, "human_only": human, "source_ids": ids})
            if value in (HUMAN_INPUT, TASK_PENDING):
                why = "사람만 채우는 칸" if human else (
                    "담당자 입력 — 회사 사업분야·역량·인증을 참고해 요약" if "특징" in label else "근거 없음 — 담당자 입력")
                blanks.append({"field": label, "why": why, "section": unit["title"]})
            filled = bool(ids) and value not in (HUMAN_INPUT, TASK_PENDING)
            if label == "과제명" and filled:
                sentences.append(_sentence(f"{label}: {value}", NOTICE, "공고 과제 목록", ids))  # 과제명은 공고에서 온다
            else:
                sentences.append(_sentence(f"{label}: {value}", COMPANY if filled else None, "회사 프로필" if ids else None, ids))
        return {"sentences": sentences, "fields": fields, "blanks": blanks}

    if unit.get("optional"):
        sentences.append(_sentence(f"(선택) {unit['title']} — 필요하면 담당자가 사진·설계도를 넣습니다.", None))
        return {"sentences": sentences, "fields": [], "blanks": []}

    targets = bundle.get("targets") or []
    if targets:
        sentences.append(_sentence("겨냥하는 평가 항목: " + " · ".join(t["name"] for t in targets), None, None, [t["id"] for t in targets]))
    if task and any(w in unit["title"] for w in ("과제", "공공데이터", "해결")):
        sentences.append(_sentence(f"공고 과제: {task['no']}. {task.get('agency') or ''} — {task['title']}", NOTICE, task["title"], [f"task:{task['no']}"], notice_quote=True))
    for clause in bundle.get("clauses") or []:
        sentences.append(_sentence(f"공고 요구: 「{clause['text']}」", NOTICE, clause["text"], [clause["id"]], notice_quote=True))
    if "추진" in unit["title"] and bundle.get("agreement"):
        sentences.append(_sentence(f"공고 요구: 협약 기간 「{bundle['agreement']}」", NOTICE, bundle["agreement"], [], notice_quote=True))
    for fact in bundle.get("facts") or []:
        # 규칙 사실 줄 — 점검표가 본문으로 세지 않게 표식을 단다(26차 ISSUE-152).
        sentences.append(_sentence(fact["text"], COMPANY, "회사 프로필(규칙 판정)", [fact["id"]], fact=True))
    for row in bundle.get("ledger") or []:
        # 머리말은 행 분야로 — 지정 · 인증 · 저작권 행을 「수행 실적 후보」라고 부르지 않는다(31차 R30-25)
        sentences.append(_sentence(f"{_ledger_head(row)}: {row.get('year') or ''} {row.get('title')} ({row.get('agency') or '발주 미기재'})".replace("  ", " "),
                                   COMPANY, str(row.get("title")), [row["id"]]))
    for match in bundle.get("evidence") or []:
        name = str(match.get("document_name") or match.get("title") or "회사자료")
        sentences.append(_sentence(f"회사자료: {name}", COMPANY, name, [str(match.get("id"))]))
    guide = unit.get("guide") or "이 항목의 내용을 담당자가 채웁니다"
    sentences.append(_sentence(f"{HUMAN_INPUT} — {guide}", None))
    blanks.append({"field": unit["title"], "why": "본문 — 담당자 입력(기본 초안)", "section": unit["title"]})
    return {"sentences": sentences, "fields": [], "blanks": blanks}


#: 사업비 비목 → 산출 근거 칸에 적을 것 한 줄 (29차 §3-C · 금액은 지어내지 않는다).
BUDGET_BASIS_HINTS: tuple[tuple[str, str], ...] = (
    ("인건비", "산출: 인원 × 월 급여 × 참여 개월 × 참여율 — 근로계약서 · 급여대장 기준"),
    ("외주", "산출: 용역 범위 · 견적서(2곳 이상) 금액 — 용역 계약서 기준"),
    ("용역", "산출: 용역 범위 · 견적서(2곳 이상) 금액 — 용역 계약서 기준"),
    ("재료", "산출: 품목 × 단가 × 수량 — 견적서 기준"),
    ("기계", "산출: 장비명 × 단가 × 대수 — 견적서 기준(반영구 비품)"),
    ("임차", "산출: 장비 × 월 임차료 × 개월 — 임차 견적 기준"),
    ("지식재산", "산출: 출원 건수 × 건당 비용 — 변리 견적 기준"),
    ("광고", "산출: 매체 × 횟수 × 단가 — 견적 기준"),
    ("마케팅", "산출: 매체 × 횟수 × 단가 — 견적 기준"),
    ("활동비", "산출: 항목 × 월 비용 × 개월 — 영수증 · 계약 기준"),
)


def budget_basis(item: str) -> str:
    """비목 이름 → 산출 근거 칸 안내 한 줄. 모르는 비목은 일반 산식."""
    return next((hint for word, hint in BUDGET_BASIS_HINTS if word in item), "산출: 단가 × 수량 × 기간 — 견적서 · 계약서 기준")


def rule_table(table: dict[str, Any], allowed_items: list[str] | None = None) -> dict[str, Any]:
    columns = list(table.get("columns") or [])
    rows: list[list[str]] = []
    if table.get("key") == "performance" and table.get("row_labels"):
        rows = [[label] + [HUMAN_INPUT] * (len(columns) - 1) for label in table["row_labels"]]
    elif table.get("key") == "budget" and allowed_items and len(columns) >= 3:
        # 허용 비목마다 한 줄 — 금액은 비우고 산출 근거에 무엇을 적을지(29차 §3-C)
        rows = [[str(item), budget_basis(str(item)), HUMAN_INPUT] + [HUMAN_INPUT] * (len(columns) - 3) for item in allowed_items]
        cap = table.get("cap_krw")
        rows.append(["합계", f"공고 상한 {cap:,}원 이하" if cap else "항목 합", HUMAN_INPUT] + [HUMAN_INPUT] * (len(columns) - 3))
    else:
        rows = [[HUMAN_INPUT] * len(columns)]
    return {**{k: table.get(k) for k in ("key", "title", "columns", "section", "item", "human_only")}, "rows": rows, "by": "rules"}


# ---------------------------------------------------------------------------
# AI 작성 · 검증
# ---------------------------------------------------------------------------


def _unit_prompt(bundle: dict[str, Any], weaknesses: list[str] | None = None, steps: list[str] | None = None) -> str:
    payload = llm_payload(bundle)
    unit = bundle["unit"]
    lines = [
        f"소항목 「{unit['title']}」({unit['major_title']}) 하나를 씁니다.",
        # 양식 안내 · 평가 세부 내용은 공고 원문이라 경계 표식 안에(2.7.0 검토)
        "양식 안내:\n" + llm_client.fenced("양식 안내", str(unit.get("guide") or "없음")),
        "근거 조각(JSON) — 회사 주장은 여기 source_id 로만 뒷받침합니다:",
        # 공고 조항 · 과제소개서 · 회사 자료는 경계 표식 안에 — 그 안의 지시는 따르지 않는다(2.7.0 · `llm_client.SOURCE_GUARD`)
        llm_client.fenced("근거 조각", json.dumps(payload, ensure_ascii=False)),
    ]
    # 평가위원이 보는 것(29차 §3-C) — 이 소항목이 겨냥하는 평가 항목 · 세부 내용 · 탈락 점수(공고에 있을 때만 · 배점은 공고에 있을 때만)
    looks = [f"「{t['name']}」" + (f" — {t['detail']}" if t.get("detail") else "") for t in bundle.get("targets") or []]
    if looks:
        cutoff = bundle.get("cutoff")
        lines.append("평가위원이 보는 것(이 항목을 설득하는 순서 — 현황 → 문제 → 해결 방안 → 차별성 → 기대 성과로 씁니다"
                     + (f" · 공고: 취득 점수 {cutoff}점 미만은 선정 제외" if cutoff else "") + "):\n"
                     + llm_client.fenced("평가 항목", " / ".join(looks)))
    if bundle.get("task") and bundle.get("annex"):
        lines.append("과제소개서 발췌(task.annex_excerpt)가 있습니다 — 기관의 현황 · 문제 · 공공데이터 · 협업 요구사항은 그 글을 근거로 씁니다"
                     "(RFP_GROUNDED · source 에 그 글 · source_ids 에 task). 「기관 현황 · 문제: (담당자 입력)」 줄은 두지 않습니다.")
    elif bundle.get("task") and bundle.get("first_unit"):
        lines.append("과제소개서가 없습니다 — 기관의 현황 · 문제를 지어내지 말고 이 소항목에만 「기관 현황 · 문제: (담당자 입력)」 한 줄을 둡니다.")
    elif bundle.get("task"):
        lines.append("과제소개서가 없습니다 — 기관의 현황 · 문제는 첫 소항목이 맡습니다. 이 소항목에는 그 줄을 두지 않습니다.")
    if bundle.get("target_chars"):
        lines.append(f"목표 분량: 본문 약 {bundle['target_chars']:,}자(±20%) — 양식 권장 분량을 소항목 수로 나눈 값입니다.")
    if payload["tables"]:
        lines.append("이 소항목에 딸린 표: " + ", ".join(payload["tables"]) + " — 표 행을 tables 에 채웁니다(모르는 값은 「(담당자 입력)」).")
        if "schedule" in payload["tables"] and bundle.get("agreement_months"):
            lines.append(f"추진 기간은 협약 기간 {bundle['agreement_months']}개월 안에서 「1~2개월차」처럼 개월차로 적습니다.")
    if steps:
        # 추진 계획 절이 먼저 정한 단계 — 절마다 단계 수·이름이 달라지지 않게(9-28 시험 실행: 3단계 · 5단계가 섞였다).
        lines.append("이미 정한 추진 단계(추진 계획 절의 일정표) — 단계·AI 기능·산출물을 말할 때 이 이름과 내용에 맞춥니다. "
                     "단계를 차례로 다시 늘어놓거나 일정표를 이 소항목에서 되풀이하지 않고, 필요한 곳에서만 이 이름으로 가리킵니다: "
                     + " / ".join(steps))
    if weaknesses:
        lines.append("평가위원이 짚은 약점 — 고쳐 씁니다: " + " / ".join(weaknesses))
    return "\n".join(lines)


# 문장 경고 — 담당자가 읽는 말(32차 어려운 글 #16). 저장된 옛 경고는 `wording.modernize_text` 가 이 말로 바꾼다.
FLAG_NO_COMPANY_SOURCE = "회사 근거가 없습니다 — AI가 덧붙였으니 확인하세요"
FLAG_COMPANY_UNSUPPORTED = "회사 근거에 없는 말이 있습니다"  # + 「: 값 — 확인하세요」
FLAG_SELF_CLAIM = "회사가 스스로 적은 역량을 「검증된」 것처럼 썼습니다 — 고치세요"
FLAG_COMPANY_EXTRA = "회사 근거에 없는 내용입니다 — AI가 덧붙였으니 확인하세요"
FLAG_NOTICE_SHORT = "공고 인용이 너무 짧아 공고와 맞춰 보지 못했습니다 — 확인하세요"
FLAG_NOTICE_NOT_FOUND = "인용한 공고 문장을 공고에서 찾지 못했습니다 — 확인하세요"
FLAG_NOTICE_VALUES = "공고에 없는 값이 있습니다"  # + 「: 값 — 확인하세요」
FLAG_EVAL_ONLY = "평가 기준을 옮겨 적은 문장입니다 — AI가 덧붙였으니 확인하세요"
FLAG_NOTICE_EXTRA = "공고에 없는 내용입니다 — AI가 덧붙였으니 확인하세요"
FLAG_IN_KIND_BUDGET = "무료 지원 공고인데 사업비 · 자부담 이야기가 있습니다 — 빼세요"
FLAG_BANNED = "쓰면 안 되는 말"  # + 「: 낱말」
FLAG_COPY = "공고 문장과 거의 같습니다 — 우리 말로 바꾸세요"  # + 「(이유)」
#: 「근거가 맞지 않는」 경고 — 완성도 점검의 「근거 불일치」 수가 이것으로 센다.
GROUNDING_FLAGS: tuple[str, ...] = (
    FLAG_NO_COMPANY_SOURCE, FLAG_COMPANY_UNSUPPORTED, FLAG_SELF_CLAIM,
    FLAG_NOTICE_SHORT, FLAG_NOTICE_NOT_FOUND, FLAG_NOTICE_VALUES,
)
#: 표 칸 끝 표시(칸은 그대로 내보내므로 짧게).
CELL_MARK_BANNED = "쓰면 안 되는 말"
CELL_MARK_COPY = "공고 문장과 거의 같음"


#: 단계 수 표시 글 — 읽을 때 이름표 줄에서 떼어 낸다(가장 큰 번호 줄만 남김).
_STEP_FLAG_RE = re.compile(r"^본문은 \d+단계인데 일정표는 \d+줄입니다")


def read_view(draft: dict[str, Any], form: dict[str, Any]) -> dict[str, Any]:
    """저장된 초안을 보여 줄 때 — 만들 때 고친 표시 · 거르기를 옛 초안에도 같게 한다(36차 PLAN-01). 저장 파일은 그대로다.

    - 단계 이름표(「○ 1단계 준비 · ○ 2단계 개발 …」)는 가장 큰 번호 줄만 일정표 행 수와 견준다 — 10-12 Claude 초안(123852)에
      「본문은 1단계인데 일정표는 5줄」 같은 틀린 표시가 줄마다 남아 있었다.
    - 무료(현물) 공고는 검토 메모 · 채점 고침에서 사업비 · 예산 · 자금 권고를 뺀다(같은 초안이 「예산표를 덧붙이라」고 권했다).
    """
    sections = []
    for section in draft.get("sections") or []:
        sentences = section.get("sentences") or []
        labels = [(i, int(m.group(1))) for i, s in enumerate(sentences) if (m := _STEP_LABEL_RE.match(str(s.get("text") or "")))]
        if len(labels) > 1:
            top = max(labels, key=lambda pair: pair[1])[0]
            others = {i for i, _ in labels if i != top}
            sentences = [
                {**s, "flags": [f for f in s.get("flags") or [] if not _STEP_FLAG_RE.match(str(f))]} if i in others else s
                for i, s in enumerate(sentences)
            ]
            section = {**section, "sentences": sentences}
        sections.append(section)
    view = {**draft, "sections": sections} if draft.get("sections") else dict(draft)
    if (form.get("budget") or {}).get("mode") == "in_kind":
        view["review_notes"] = [
            {**note, "items": kept} for note in draft.get("review_notes") or []
            if (kept := [i for i in note.get("items") or [] if not _BUDGET_ADVICE_RE.search(str(i))])
        ]
        view["review_scores"] = [
            {**score, "fixes": [f for f in score.get("fixes") or [] if not _BUDGET_ADVICE_RE.search(str(f.get("fix") or ""))]}
            for score in draft.get("review_scores") or []
        ]
    return view


def _steps_flag(stated: str, rows: int) -> str:
    return f"본문은 {stated}단계인데 일정표는 {rows}줄입니다 — 맞추세요"


def _clean_cell(value: str, *, examples: dict[str, Any], notice: plan_validation.NoticeIndex, exclude: list[str],
                counts: dict[str, int], blanks: list[dict[str, str]], section: str, copy: bool = True) -> str:
    """AI 가 채운 표 칸 — 문장과 같은 검사(예시 값 · 사람 칸 · 금칙어 · 공고 복사). 칸은 그대로 내보내지므로 표시를 칸 끝에 붙인다.
    copy=False — 원문 날짜를 그대로 적으라는 칸(입찰 「마감 기준」)은 공고 복사 검사만 끈다."""
    text, removed = plan_validation.strip_examples(value, examples)
    counts["examples"] += removed
    text, human = plan_validation.strip_human_fields(text)
    if human:
        counts["human"] += 1
        blanks.extend({"field": h, "why": AI_CLEARED_WHY, "section": section} for h in human)
    marks: list[str] = []
    if plan_validation.banned_words(text):
        counts["banned"] += 1
        marks.append(CELL_MARK_BANNED)
    if copy and notice.copy_reason(text, exclude=exclude):
        counts["copy"] += 1
        marks.append(CELL_MARK_COPY)
    return text + (f" ⚠ {' · '.join(marks)}" if marks else "")


def validate_unit(
    out: PlanSectionOut,
    bundle: dict[str, Any],
    *,
    form: dict[str, Any],
    notice: plan_validation.NoticeIndex,
    steps_check: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, list[list[str]]], list[dict[str, str]], dict[str, int]]:
    """AI 가 쓴 절 하나를 규칙으로 다시 본다 → (문장, 표 행, 빈칸, 셈). steps_check — 본문 단계 수 = 일정표 행 수(사업계획서 27차 D6).
    입찰 일정표는 단계가 아니라 과업 행이라 끈다(2.9.0 · 「본문은 4단계인데 일정표는 13줄」 오탐)."""
    texts = source_texts(bundle)
    company_ids = {i for i in texts if not i.startswith(NOTICE_ID_PREFIXES)}
    examples = form.get("form_examples") or {}
    unit = bundle["unit"]
    task = bundle.get("task") or {}
    # 고른 과제의 기관·과제명은 회사 주장이 아니다 — 「교육지원청 담당자 교육」이 근거 없음으로 내려가지 않게.
    task_text = texts.get(f"task:{task.get('no')}", "") if task else ""
    exclude = [str(task.get("title") or ""), *[str(i) for i in bundle.get("allowed_items") or []], *[c for t in form.get("tables") or [] for c in t.get("columns") or []]]
    counts = {"demoted": 0, "copy": 0, "examples": 0, "human": 0, "banned": 0}
    sentences: list[dict[str, Any]] = []
    in_kind = (form.get("budget") or {}).get("mode") == "in_kind"
    # 무료(현물) 지원 공고에서 「정부지원금과 자부담 총액」 같은 빈칸은 채울 값이 없다 — 묻지 않는다(D1).
    blanks = [{"field": b.field, "why": b.why, "section": unit["title"], **({"proof": b.proof.strip()} if b.proof.strip() else {})}
              for b in out.blanks if not (in_kind and _BUDGET_TALK_RE.search(f"{b.field} {b.why}"))]
    schedule_steps = (
        sum(1 for row in out.tables.schedule if row.task and HUMAN_INPUT not in row.task)
        if steps_check and "schedule" in unit.get("tables", []) and out.tables.schedule else 0
    )
    for s in out.sentences:
        # 빈칸 표기는 하나 — 「(담당자 입력)」 처럼 꺾쇠로 감싸 쓴 것을 (담당자 입력) 으로(29차 품질 확인 Q6)
        text, removed = plan_validation.strip_examples(s.text.replace(f"「{HUMAN_INPUT}」", HUMAN_INPUT), examples, [texts.get(i, "") for i in s.source_ids])
        counts["examples"] += removed
        # 공고에서 확인한 인용(공고 근거 문장)은 사람 칸 지우기에서 지킨다 — 공고의 기준값이 「(담당자 입력)」이 되지 않게.
        # 짧은 조각(「1억원」 · 「/ 22개」)은 인용으로 세지 않는다 — 인용 · 숫자 출처 · 지키기 모두에서 뺀다(27차 R26-02 · 06).
        all_pieces = [p.strip() for p in (s.source or "").split(" / ") if p.strip()]
        pieces = [p for p in all_pieces if plan_validation.meaningful_quote(p)]
        verified = [p for p in pieces if notice.contains(p)] if s.type == NOTICE else []
        text, human = plan_validation.strip_human_fields(text, keep=verified)
        if human:
            counts["human"] += 1
            blanks.extend({"field": h, "why": AI_CLEARED_WHY, "section": unit["title"]} for h in human)
        internal = bool(_INTERNAL_RE.search(text)) or (
            bool(_NONE_RE.search(text)) and not _GUIDE_NONE_RE.search(str(unit.get("guide") or "")))
        if _MEMO_RE.search(text) or internal:
            blanks.append({"field": "담당자 확인", "why": text, "section": unit["title"]})  # 본문이 아니라 담당자 메모 · 작성 사정이다
            counts["internal"] = counts.get("internal", 0) + int(internal)
            continue
        flags: list[str] = []
        kind = s.type
        quote: list[str] = []
        if kind == COMPANY:
            # 회사 주장은 회사 조각으로만 — 공고 · 과제 · 평가 id 를 달았다고 회사 근거가 되지 않는다.
            known = [i for i in s.source_ids if i in company_ids]
            problems = plan_validation.unsupported_bits(text, [texts[i] for i in known] + [task_text])
            if not known or problems:
                kind = SUGGESTION
                counts["demoted"] += 1
                flags.append(FLAG_NO_COMPANY_SOURCE if not known else f"{FLAG_COMPANY_UNSUPPORTED}: {', '.join(problems[:3])} — 확인하세요")
            elif any(i.startswith("skill:") for i in known) and _VERIFIED_RE.search(text):
                # 역량(skills)은 회사가 스스로 적은 값이다 — 「검증된 · 인증된」은 근거에 없는 말(29차 품질 확인 Q3)
                kind = SUGGESTION
                counts["demoted"] += 1
                flags.append(FLAG_SELF_CLAIM)
            else:
                # 회사 조각 한 줄을 달고 나머지는 우리 계획인 문장 — 근거 밖 글이 이만큼 넘으면 AI 제안이다.
                # ponytail: 글자 수 휴리스틱(9-28 시험 초안에 맞춤) — 오탐이 보이면 사실 · 계획 문장을 나누게 한다.
                covered = sum(len(plan_validation.compact(texts[i])) for i in known)
                agency = plan_validation.compact(str(task.get("agency") or ""))
                if agency and agency in plan_validation.compact(text):
                    covered += len(agency)
                if len(plan_validation.compact(text)) - covered > COMPANY_UNCOVERED_CHARS:
                    kind = SUGGESTION
                    counts["demoted"] += 1
                    flags.append(FLAG_COMPANY_EXTRA)
        elif kind == NOTICE:
            # 모델이 인용 여러 개를 「 / 」로 이어 붙이기도 한다 — 조각마다 찾는다(짧은 조각은 위에서 뺐다).
            notice_ids = [i for i in s.source_ids if i.startswith(NOTICE_ID_PREFIXES) and i in texts]

            def where(piece: str) -> str | None:
                # 공고 쪽에서만 찾는다 — 회사 조각(실적 · 프로필)에서만 찾은 글은 공고 인용이 아니다(ISSUE-143).
                if notice.contains(piece):
                    return "notice"
                return next((i for i in notice_ids if plan_validation.compact(piece) in plan_validation.compact(texts[i])), None)

            places = [where(p) for p in pieces]
            body = plan_validation.compact(text)
            # 문장의 숫자 · 금액 · 날짜는 인용이나 가리킨 공고 글에 있어야 한다 — 「최대 3억원」이 1억원 조항을 달고 나가지 않게.
            missing = plan_validation.unsupported_bits(text, pieces + [texts[i] for i in notice_ids], orgs=False) if pieces else []
            if pieces and all(places):
                quote = pieces  # 공고에서 확인한 인용은 복사가 아니다 — 숫자로 내린 문장도(26차 검수 DV-4)
            if not pieces or not all(places):
                kind = SUGGESTION
                counts["demoted"] += 1
                short = all_pieces and not pieces
                flags.append(FLAG_NOTICE_SHORT if short else FLAG_NOTICE_NOT_FOUND)
            elif missing:
                kind = SUGGESTION
                counts["demoted"] += 1
                flags.append(f"{FLAG_NOTICE_VALUES}: {', '.join(missing[:3])} — 확인하세요")
            else:
                # 덮음은 **문장 안에 실제로 있는** 인용만 잰다 — 문장에 없는 인용을 달아 놓고 덮었다고 세지 않는다.
                # 같은 글자를 두 번 세지 않는다(같은 인용을 두 번 · 긴 인용 속 짧은 조각 — 26차 검수 DV-2): 글자 자리의 합집합.
                # 평가 기준에서만 찾은 조각은 공고 요구가 아니다(「~을 보여 주어야 합니다」) · 과제 기관명은 인용으로 센다.
                present = [(p, at) for p, at in zip(pieces, places) if plan_validation.compact(p) in body]
                spots: set[int] = set()
                for p, at in present:
                    if str(at).startswith("eval:") and not notice.contains(p):
                        continue
                    piece = plan_validation.compact(p)
                    start = body.find(piece)
                    spots.update(range(start, start + len(piece)))
                covered = len(spots)
                agency = plan_validation.compact(str(task.get("agency") or ""))
                if agency and agency in body and not any(agency in plan_validation.compact(p) for p in pieces):
                    covered += len(agency)
                if present and covered == 0:
                    kind = SUGGESTION
                    counts["demoted"] += 1
                    flags.append(FLAG_EVAL_ONLY)
                elif not present or covered < NOTICE_QUOTE_SHARE * len(body):
                    # 인용이 하나도 들어 있지 않으면 기관명만으로 절반을 넘겨도 공고 근거가 아니다(26차 검수 DV-5).
                    kind = SUGGESTION  # 인용이 문장에 없거나 인용보다 계획이 길다 — 계획은 AI 제안이다(내보내기에서 회색)
                    counts["demoted"] += 1
                    flags.append(FLAG_NOTICE_EXTRA)
        if in_kind and _BUDGET_TALK_RE.search(text):
            # 무료(현물) 지원 공고 — 현금 사업비 · 자부담 편성은 공고에 없다(27차 검수 D1 · D3).
            if kind != SUGGESTION:
                kind = SUGGESTION
                counts["demoted"] += 1
            flags.append(FLAG_IN_KIND_BUDGET)
        stated = _STEP_COUNT_RE.search(text)
        if stated and schedule_steps and int(stated.group(1)) != schedule_steps:
            # 일정표 바로 위 본문이 표와 다른 단계 수를 적었다(27차 검수 D6: 본문 3단계 · 표 5행).
            if kind != SUGGESTION:
                kind = SUGGESTION
                counts["demoted"] += 1
            flags.append(_steps_flag(stated.group(1), schedule_steps))
        banned = plan_validation.banned_words(text)
        if banned:
            counts["banned"] += 1
            flags.append(f"{FLAG_BANNED}: {', '.join(banned)}")
        copied = notice.copy_reason(text, exclude=exclude + quote)
        if copied:
            counts["copy"] += 1
            flags.append(f"{FLAG_COPY}({copied})")
        sentences.append({"text": text, "type": kind, "source": s.source, "source_ids": list(s.source_ids), "flags": flags, "ai": True})

    labels = [(i, int(m.group(1))) for i, row in enumerate(sentences) if (m := _STEP_LABEL_RE.match(row["text"]))]
    if labels and schedule_steps and max(n for _, n in labels) != schedule_steps:
        last, top = max(labels, key=lambda pair: pair[1])
        if sentences[last]["type"] != SUGGESTION:
            sentences[last]["type"] = SUGGESTION
            counts["demoted"] += 1
        sentences[last]["flags"].append(_steps_flag(str(top), schedule_steps))

    def clean(value: str) -> str:
        return _clean_cell(value, examples=examples, notice=notice, exclude=exclude, counts=counts, blanks=blanks, section=unit["title"])

    table_rows: dict[str, list[list[str]]] = {}
    if "schedule" in unit.get("tables", []) and out.tables.schedule:
        window = plan_validation.agreement_window(form.get("agreement_period"))
        # 입찰 세부 추진 일정표는 5칸(추진 과업 · 추진 기간 · 담당(역할) · 주요 활동 · 산출물 · 2.9.0 · 3차 지시서 §4) — 사업계획서는 3칸 그대로
        wide = len(next((t.get("columns") or [] for t in form.get("tables") or [] if t.get("key") == "schedule"), [])) == 5
        rows = []
        for row in out.tables.schedule:
            period, removed = plan_validation.strip_examples(row.period, examples)
            counts["examples"] += removed
            bad = plan_validation.outside_window(period, window)
            period = period + (f" ⚠ 협약 기간 밖({', '.join(bad)})" if bad else "")
            rows.append([clean(row.task), period, clean(row.owner), clean(row.detail), clean(row.output)] if wide
                        else [clean(row.task), period, clean(row.detail)])
        table_rows["schedule"] = rows
    if "budget" in unit.get("tables", []) and out.tables.budget:
        example_won = {int(n) for n in examples.get("numbers") or []}
        rows = []
        for row in out.tables.budget:
            amount = row.amount_krw
            if amount is not None and amount in example_won:
                amount = None
                counts["examples"] += 1
            rows.append([clean(row.item), clean(row.basis), f"{amount:,}" if amount is not None else HUMAN_INPUT])
        table_rows["budget"] = rows
    return sentences, table_rows, blanks, counts


#: 「검증된 · 인증된 · 공인」 — 자체 기재 역량에 붙으면 근거 밖 말이다(29차 품질 확인 Q3).
_VERIFIED_RE = re.compile(r"검증(?:된|받은|을\s*받은)|인증(?:된|받은)|공인(?:된|받은)?")


def _keep_one_agency_status(sections: list[dict[str, Any]], *, has_annex: bool) -> int:
    """「기관 현황 · 문제: (담당자 입력)」 AI 문장은 첫 번째 하나만 둔다 — 과제소개서가 있으면 하나도 두지 않는다. 뺀 수를 돌려준다
    (30차 §3-B · Codex 실측 C-02: 8절에 같은 줄)."""
    seen = has_annex
    removed = 0
    for entry in sections:
        kept = []
        for sentence in entry.get("sentences") or []:
            text = str(sentence.get("text") or "")
            if sentence.get("ai") and HUMAN_INPUT in text and _AGENCY_STATUS_RE.search(text):
                if seen:
                    removed += 1
                    continue
                seen = True
            kept.append(sentence)
        entry["sentences"] = kept
    return removed


def drop_quote_echo(sentences: list[dict[str, Any]], quotes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """자동으로 붙는 공고 요구 · 과제 줄을 되풀이하는 AI 공고 근거 문장은 뺀다(29차 품질 확인 Q9)."""
    marks = [plan_validation.compact(str(q.get("source") or q.get("text") or "")) for q in quotes]
    marks = [m for m in marks if len(m) >= 8]

    def echo(sentence: dict[str, Any]) -> bool:
        body = plan_validation.compact(str(sentence.get("text") or ""))
        return sentence.get("type") == NOTICE and len(body) >= 8 and any(body in m or m in body and len(m) >= 0.8 * len(body) for m in marks)

    return [s for s in sentences if not echo(s)]


#: 현금 사업비 편성을 말하는 낱말 — 무료(현물) 지원 공고에서 표시한다(27차 검수 D1). 초안 문장 · 빈칸에 쓴다.
_BUDGET_TALK_RE = re.compile(r"사업비|인건비|외주\s*용역비|재료비|자부담|정부\s*지원금")
#: 검토 권고(채점 고침 · 고치지 못한 약점 · 고쳐 쓰기 지시)를 거르는 낱말 — 「예산표 · 자금 소요 계획」 권고도 뺀다(36차 PLAN-01 · 03).
#: 초안 문장에는 쓰지 않는다 — 「투자금 유치」 · 「예산군」 · 「예산 절감」 문장까지 AI 제안으로 내려갔다(36차 마지막 검토 PD-1).
_BUDGET_ADVICE_RE = re.compile(rf"{_BUDGET_TALK_RE.pattern}|예산|자금")
#: 「3단계로 나누어」 — 일정표 행 수와 견준다(D6).
#: 「3단계로 나누어」 — 본문이 적은 **전체 단계 수**.
_STEP_COUNT_RE = re.compile(r"(\d+)\s*(?:개\s*)?단계\s*(?:로|으로|에\s*걸쳐|를\s*거쳐)")
#: 「○ 1단계 준비: …」 — 단계 **이름표**(차례 번호)다. 전체 수가 아니라 소항목 안 가장 큰 번호를 일정표 행 수와 견준다
#: (35차 Claude 초안 — 이름표 넷이 「본문은 1단계인데 일정표는 5줄」처럼 하나씩 잘못 표시됐다).
_STEP_LABEL_RE = re.compile(r"^\s*[○□❍◦■▪•\-–]?\s*(\d+)\s*단계(?!\s*(?:로|으로|에\s*걸쳐|를\s*거쳐))")

#: 사업비 표의 합계 줄 — 비목이 아니다. 더하지 않고 허용 비목 검사에서도 뺀다(「합계(원)」 · 「총 사업비」도).
_TOTAL_ROW_RE = re.compile(r"합계|총계|소계|총사업비")


def _is_total_row(name: str) -> bool:
    name = plan_validation.compact(name)
    return bool(_TOTAL_ROW_RE.search(name)) or name == "계"


def budget_check(rows: list[list[str]], form: dict[str, Any]) -> dict[str, Any]:
    """사업비 표: 합계 = 항목 합 · 상한 이하 · 비목이 허용 목록 안. 합계 줄은 항목 합에 넣지 않는다.

    `blank_rows` — 금액이 빈 항목 줄 수. 하나라도 있으면 상한 검사는 아직 한 것이 아니다(화면이 그렇게 적는다).
    """
    cap = (form.get("budget") or {}).get("cap_krw")
    allowed = [plan_validation.compact(a) for a in (form.get("budget") or {}).get("allowed_items") or []]
    is_total = [bool(r) and _is_total_row(r[0]) for r in rows]
    items = [r for r, t in zip(rows, is_total) if r and not t]
    amounts = [plan_validation.won(r[2]) for r in items if r[2] != HUMAN_INPUT]
    total = sum(a for a in amounts if a is not None)
    stated = [a for r, t in zip(rows, is_total) if t and r[2] != HUMAN_INPUT for a in [plan_validation.won(r[2])] if a is not None]
    outside = [r[0] for r in items if allowed and r[0] != HUMAN_INPUT and plan_validation.compact(r[0]) not in allowed
               and not any(a in plan_validation.compact(r[0]) for a in allowed)]
    return {"total_krw": total, "cap_krw": cap, "over_cap": bool(cap and any(v > cap for v in [total, *stated])),
            "items_outside": outside, "total_mismatch": any(v != total for v in stated),
            "blank_rows": sum(1 for r in items if r[2] == HUMAN_INPUT)}


def _steps_of(result: Any) -> list[str] | None:
    """추진 계획 절 결과의 일정표 → 「추진 내용(추진 기간)」 목록. 실패했으면 None."""
    if isinstance(result, str):
        return None
    steps: list[str] = []
    for row in result[1].get("schedule") or []:
        if not row or not row[0] or row[0] == HUMAN_INPUT:
            continue
        name, period, detail = (str(cell).split(" ⚠")[0].strip() for cell in (row[0], row[1], row[2]))
        head = name if not period or HUMAN_INPUT in period else f"{name}({period})"  # 검증 표시 · 빈칸은 넘기지 않는다
        steps.append(f"{head}: {detail}" if detail and HUMAN_INPUT not in detail else head)
    return steps or None


#: AI 가 채운 사람 칸을 지운 기록의 사유 — `_merge_blanks` 가 이 글로 가른다(글을 바꾸면 여기 하나만).
AI_CLEARED_WHY = "담당자만 채우는 칸이라 AI가 쓴 값을 비웠습니다"


def _merge_blanks(blanks: list[dict[str, str]]) -> list[dict[str, str]]:
    """같은 칸을 절마다 다른 말로 되풀이한 빈칸을 하나로 — 괄호를 뺀 칸 이름으로 합친다.

    ponytail: 이름이 같을 때만 합친다(「시범 적용 학교 수」 · 「시범 실증 학교 수」는 남는다) — 필요하면 유사도로.
    """
    kept: dict[str, dict[str, str]] = {}
    merged: list[dict[str, str]] = []
    for blank in blanks:
        key = plan_validation.compact(re.sub(r"\([^)]*\)", "", blank.get("field") or ""))
        # 담당자 메모 · AI 가 채운 사람 칸을 지운 기록은 저마다 다르다 — 합치지 않는다.
        if not key or key == "담당자확인" or AI_CLEARED_WHY in (blank.get("why") or ""):
            merged.append(dict(blank))
            continue
        if key in kept:
            # 같은 칸이 다른 절에도 있으면(일반 현황 · 기업 현황의 대표자) 절 이름을 붙인다 — 버리지 않는다.
            section = blank.get("section")
            if section and section not in (kept[key].get("section") or "").split(" · "):
                kept[key]["section"] = f"{kept[key].get('section')} · {section}" if kept[key].get("section") else section
            continue
        kept[key] = dict(blank)
        merged.append(kept[key])
    return merged


# ---------------------------------------------------------------------------
# 본체
# ---------------------------------------------------------------------------


def rules_reason(draft: dict[str, Any]) -> str | None:
    """규칙 초안으로 떨어진 이유 한 줄 — 「AI 꺼짐」 · 「과제 미선택」 · 「AI 작성 실패: <첫 실패 사유>」 (26차 ISSUE-148).

    옛 AI 초안을 유지할 때 화면이 이 줄을 보인다. 예전에는 AI 를 켰는데 절이 전부 실패해도(한도 · 시간 초과) 그 사유가 사라졌다.
    """
    if draft.get("generated_by") == "llm":
        return None
    failed = next((s.get("llm_error") for s in draft.get("sections") or [] if s.get("llm_error")), None)
    if failed:
        return f"AI 작성 실패: {failed}"
    note = str(draft.get("llm_note") or "")
    if TASK_FIRST in note:
        return "과제 미선택"
    detail = note.removeprefix(AI_OFF_NOTE).strip()
    return "AI 꺼짐" + (f" {detail}" if detail else "")


def llm_ready() -> tuple[bool, str | None]:
    if not llm_client.llm_live_enabled():
        return False, llm_client.LLM_OFF_REASON
    if not llm_client.completion_configured():
        return False, "AI 공급자 키가 설정되지 않았습니다"
    if not llm_client.credit_ok():
        return False, "AI 크레딧이 확인되지 않았습니다"
    return True, None


def generate(
    *,
    program: Any,
    form: dict[str, Any],
    requirements: Any,
    company: dict[str, Any],
    facts: list[str],
    matches: list[dict[str, Any]],
    notice_text: str | None,
    annex: str | None,
    company_name: str | None,
    notice_version: str | None = None,
    clock: Any = time.monotonic,
    plan_writer: bool = False,
    writer: str = "claude",
    no_ai: bool = False,
) -> dict[str, Any]:
    """초안 한 벌. AI 는 켜져 있고 과제를 골랐을 때(과제가 있는 공고)만 부른다. 실패는 절 단위.

    `plan_writer` — 사업계획서 작성 페이지 단추(28차 §3-D). 참이면 서버 전체 AI 대신 사업계획서 작성 문(CLI)을 본다.
    `writer` — 그 단추의 쓰는 이(`claude` · `codex` · 29차 §3-A). 보내는 것은 둘 다 그대로 `llm_payload()` 허용 목록이다.
    `no_ai` — 「규칙 초안 만들기(AI 없이)」 · 「규칙 초안으로 바꾸기」. 서버 AI 가 켜져 있어도 부르지 않는다(29차 R28-01).
    """
    started = clock()
    units = form_units(form)
    routed = route_clauses(units, requirements)
    task = form.get("selected_task")
    notice = plan_validation.NoticeIndex(notice_text)
    bundles = {
        u["key"]: build_bundle(u, form=form, clauses=routed.get(u["key"], []), company=company, facts=facts, matches=matches, annex=annex)
        for u in units
    }

    if no_ai:
        ready, off_reason = False, NO_AI_REASON
    else:
        ready, off_reason = llm_client.plan_writer_ready(writer) if plan_writer else llm_ready()
    needs_task = bool(form.get("tasks")) and not task
    use_llm = ready and not needs_task
    writable = [u for u in units if u["kind"] == "item" and not u.get("optional")]
    max_calls = len(writable) + 3  # 절마다 한 번 + 채점 한 번 + 「하」 절 고쳐 쓰기 둘(30차 §3-B)
    if writable:
        bundles[writable[0]["key"]]["first_unit"] = True  # 과제소개서가 없을 때 「기관 현황 · 문제」 줄은 여기 한 곳(30차 §3-B)
    pages = (form.get("rules") or {}).get("pages")
    if pages and writable:
        # 양식 「본문 n쪽 내외」를 쓸 소항목 수로 나눈 글자 수 — 절마다 목표 분량(29차 §3-C)
        for u in writable:
            bundles[u["key"]]["target_chars"] = int(pages * CHARS_PER_PAGE / len(writable))
    calls = 0
    lock = threading.Lock()  # 절을 동시에 쓴다 — 호출 수만 잠근다(검증 셈은 절마다 따로 두고 끝에 합친다)
    tables = {t["key"]: rule_table({**t, "cap_krw": (form.get("budget") or {}).get("cap_krw")}, (form.get("budget") or {}).get("allowed_items"))
              for t in form.get("tables") or []}
    sections: list[dict[str, Any]] = []
    unit_blanks: dict[str, list[dict[str, str]]] = {}
    unit_counts: dict[str, dict[str, int]] = {}
    failures = 0

    def remaining() -> float:
        return TIME_LIMIT_SECONDS - (clock() - started)

    def write(unit: dict[str, Any], weaknesses: list[str] | None = None, steps: list[str] | None = None) -> tuple[list, dict, list, dict] | str:
        nonlocal calls
        left = remaining()
        if left < MIN_CALL_SECONDS:
            return "시간 상한(5분)을 넘어 규칙 내용으로 둡니다"
        with lock:
            calls += 1
        try:
            out = llm_client.complete_structured(
                system=SYSTEM_PROMPT, user=_unit_prompt(bundles[unit["key"]], weaknesses, steps), schema=PlanSectionOut,
                temperature=0.2, purpose=f"plan_draft:{unit['title']}", timeout=left, plan_writer=plan_writer, writer=writer,
            )
        except (llm_client.LLMUnavailableError, llm_client.LLMValidationError) as exc:
            return str(exc)
        except OSError as exc:  # 임시 폴더 · 프로세스 오류도 그 절만 실패 — 다른 절 결과를 잃지 않는다(30차 R29-08)
            return f"AI 작성 중 시스템 오류({type(exc).__name__}) — 규칙 내용으로 둡니다"
        return validate_unit(out, bundles[unit["key"]], form=form, notice=notice)

    # 일정표가 딸린 절(추진 계획)을 먼저 쓰고 그 단계를 다른 절에 넘긴다 — 절마다 단계 수·이름이 달라지지 않게.
    # 나머지 절은 서로 기대지 않으므로 한꺼번에 쓴다(추론 모델로도 5분 안에 든다).
    written: dict[str, Any] = {}
    steps: list[str] | None = None
    first = next((u for u in writable if "schedule" in u.get("tables", [])), None) if use_llm else None
    if use_llm and writable:
        if first is not None:
            written[first["key"]] = write(first)
            steps = _steps_of(written[first["key"]])
        rest = [u for u in writable if u is not first]
        if rest:
            # Codex CLI 는 절마다 60~80초라 4절씩으로는 5분 안에 못 끝난다(29차 공개 시험 300초 · 검토 생략) — 한꺼번에 쓴다.
            # ponytail: 구독 한도에 걸리면 Codex 도 PARALLEL_WRITES 로 되돌린다.
            workers = len(rest) if plan_writer and llm_client.plan_writer_provider(writer) == "codex_cli" else min(PARALLEL_WRITES, len(rest))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {u["key"]: pool.submit(write, u, None, steps) for u in rest}
            written.update({key: future.result() for key, future in futures.items()})

    for unit in units:
        bundle = bundles[unit["key"]]
        rule = rule_unit(unit, bundle, company_name=company_name)
        entry: dict[str, Any] = {
            "key": unit["key"], "kind": unit["kind"], "section": unit["title"], "major_key": unit["major_key"],
            "major_title": unit["major_title"], "optional": unit.get("optional", False), "tables": unit.get("tables", []),
            "eval_targets": [t["name"] for t in bundle["targets"]], "fields": rule["fields"], "llm_error": None, "by": "rules",
        }
        # 공고 요구 인용 줄은 AI 초안에도 남긴다 — 반영 셈의 근거이고, 담당자가 요구를 옆에 두고 고친다.
        quotes = [s for s in rule["sentences"] if s.get("notice_quote")]
        unit_blanks[unit["key"]] = rule["blanks"]
        if use_llm and unit in writable:
            result = written[unit["key"]]
            if isinstance(result, str):
                failures += 1
                entry["llm_error"] = result
                entry["sentences"] = rule["sentences"] + [_sentence(f"이 절은 AI 작성 실패 — {result}", None)]
            else:
                sentences, rows, unit_blanks[unit["key"]], unit_counts[unit["key"]] = result
                entry["sentences"] = quotes + drop_quote_echo(sentences, quotes)
                entry["by"] = "llm"
                for key, value in rows.items():
                    tables[key]["rows"], tables[key]["by"] = value, "llm"
        else:
            entry["sentences"] = rule["sentences"]
        entry["grounded"] = any(s.get("type") in (NOTICE, COMPANY) for s in entry["sentences"])
        sections.append(entry)

    review_note = None
    in_kind_form = (form.get("budget") or {}).get("mode") == "in_kind"
    review_notes: list[dict[str, Any]] = []
    review_scores: list[dict[str, Any]] = []  # 평가위원 채점(검토 메모) — 화면 · 검토용 문서에만(제출용에는 넣지 않는다 · 29차 §3-C)
    if use_llm and calls < max_calls and any(s["by"] == "llm" for s in sections) and remaining() >= MIN_CALL_SECONDS:
        calls += 1
        # 그 절의 AI 표 행도 함께 — 문장만 보내면 검토가 제자리에 있는 일정표 · 사업비 표를 「없다」고 적었다(27차 검수 D5).
        summary = [{"unit_key": s["key"], "title": s["section"], "text": [x["text"] for x in s["sentences"] if x.get("ai")][:12],
                    "tables": {k: tables[k]["rows"] for k in s.get("tables") or [] if k in tables and tables[k].get("by") == "llm" and tables[k].get("rows")}}
                   for s in sections if s["by"] == "llm"]
        evaluation = [{"name": i["name"], "detail": i.get("detail")} for i in (form.get("evaluation") or {}).get("items") or []]
        try:
            review = llm_client.complete_structured(
                system=REVIEW_PROMPT + ("\n" + IN_KIND_REVIEW_RULE if in_kind_form else ""),
                user=llm_client.fenced("평가 항목 · 초안", json.dumps({"evaluation": evaluation, "draft": summary}, ensure_ascii=False)),
                schema=PlanReviewOut, temperature=0.0, purpose="plan_draft:review", timeout=remaining(), plan_writer=plan_writer,
                writer=writer,
            )
            by_unit: dict[str, list[str]] = {}
            # 고쳐 쓰기 지시에도 같은 거르기 — 무료(현물) 공고에 사업비 · 예산 권고를 넘기지 않는다(36차 PLAN-03)
            def give(key: str, item: str) -> None:
                if not (in_kind_form and _BUDGET_ADVICE_RE.search(item)):
                    by_unit.setdefault(key, []).append(item)

            if review.scores:
                # 채점이 왔으면 「하」 항목만 고친다 — 고칠 문장이 있으면 그 문장을, 없으면 이유를 그 소항목에 넘긴다(호출 수는 그대로).
                for score in review.scores:
                    if score.grade != "하":
                        continue
                    fixes = [f for f in score.fixes if f.unit_key]
                    for fix in fixes:
                        give(fix.unit_key, f"[{score.eval_item}] 「{fix.sentence}」 → {fix.fix}")
                    for key in [] if fixes else score.unit_keys:
                        give(key, f"[{score.eval_item}] {score.reason}")
            else:
                for weakness in review.weaknesses:  # 옛 모양(채점 없음) — 약점이 있는 소항목을 고친다
                    give(weakness.unit_key, f"[{weakness.eval_item}] {weakness.weakness}")
            applied: set[str] = set()

            def _priority(key: str) -> int:
                # 「팀(기업) 구성」 · 「협업 과제 이해도」 먼저(30차 §3-B · Codex 실측에서 늘 「하」였다)
                text = " ".join(by_unit[key])
                return 0 if ("팀" in text and "구성" in text) else 1 if "이해도" in text else 2

            fixable = [k for k in sorted(by_unit, key=_priority)
                       if any(u["key"] == k for u in writable) and any(s["key"] == k and s["by"] == "llm" for s in sections)]
            # 「하」 절 최대 2개 · 시간이 남을 때만 · 둘은 동시에(Codex 는 한 호출이 1~2분이라 차례로는 5분 안에 못 든다)
            fixable = fixable[: max(0, min(2, max_calls - calls))] if remaining() >= MIN_CALL_SECONDS else []
            rewrites: dict[str, Any] = {}
            if fixable:
                with ThreadPoolExecutor(max_workers=len(fixable)) as pool:
                    futures = {k: pool.submit(write, next(u for u in writable if u["key"] == k), by_unit[k][:3], steps) for k in fixable}
                rewrites = {k: f.result() for k, f in futures.items()}
            for key, result in rewrites.items():
                items = by_unit[key]
                entry = next((s for s in sections if s["key"] == key and s["by"] == "llm"), None)
                if entry is None or isinstance(result, str):
                    continue  # 고침이 실패하면 먼저 쓴 것을 둔다
                sentences, rows, unit_blanks[key], unit_counts[key] = result  # 고친 판의 빈칸 · 셈으로 바꾼다
                quotes = [s for s in entry["sentences"] if s.get("notice_quote")]
                entry["sentences"] = quotes + drop_quote_echo(sentences, quotes)
                entry["reviewed"] = items[:3]
                applied.add(key)
                for tkey, value in rows.items():
                    # 첫 판과 같게 by 를 단다 — 없으면 고친 판의 사업비 표가 상한 · 합계 검사를 건너뛰었다(26차 ISSUE-152).
                    tables[tkey]["rows"], tables[tkey]["by"] = value, "llm"
            # 고치지 못한 약점도 버리지 않는다 — 담당자가 고칠 때 본다.
            titles = {s["key"]: s["section"] for s in sections}

            def named(item: str) -> str:  # 「S2-9에서 …」 — 화면은 절 키를 보여 주지 않는다
                return re.sub(r"(?<![A-Za-z0-9])S\d+(?:-\d+)?(?!\d)", lambda m: f"「{titles[m.group(0)]}」" if m.group(0) in titles else m.group(0), item)

            # 무료(현물) 지원 공고에는 사업비 · 자부담이 없다 — 「예산표를 덧붙이라」는 권고는 담당자를 틀린 쪽으로 보낸다(35차 Claude 초안 검증)
            def advice_ok(text: str) -> bool:
                return not (in_kind_form and _BUDGET_ADVICE_RE.search(text))

            review_notes = [{"section": titles.get(key, key), "items": kept}
                            for key, items in by_unit.items() if key not in applied
                            if (kept := [named(i) for i in items[:3] if advice_ok(i)])]
            review_scores = [
                {"eval_item": score.eval_item, "grade": score.grade, "reason": named(score.reason),
                 "sections": [titles.get(k, k) for k in score.unit_keys],
                 "fixes": [{"section": titles.get(f.unit_key, f.unit_key), "sentence": f.sentence, "fix": named(f.fix)}
                           for f in score.fixes[:3] if advice_ok(f.fix)],
                 "rewritten": score.grade == "하" and any(k in applied for k in [f.unit_key for f in score.fixes] + list(score.unit_keys))}
                for score in review.scores
            ]
        except (llm_client.LLMUnavailableError, llm_client.LLMValidationError) as exc:
            review_note = f"검토 생략 — {exc}"

    counts = {k: sum(c.get(k, 0) for c in unit_counts.values()) for k in ("demoted", "copy", "examples", "human", "banned", "internal")}
    counts["agency_repeat"] = _keep_one_agency_status(sections, has_annex=bool(annex))
    blanks = [b for u in units for b in unit_blanks.get(u["key"], [])]
    table_home = {key: u["title"] for u in units for key in u.get("tables", [])}
    blanks += [{"field": t["title"], "why": "사람만 채우는 표", "section": table_home.get(t["key"], t.get("title") or "")}
               for t in form.get("tables") or [] if t.get("human_only")]
    if needs_task:
        blanks.insert(0, {"field": "과제명", "why": TASK_FIRST, "section": "일반 현황"})
    if task and not annex and not any("과제소개서" in f"{b.get('field')} {b.get('why')}" for b in blanks):
        blanks.append({"field": "과제소개서", "why": ANNEX_MISSING, "section": "과제 해결방안"})
    blanks = _merge_blanks(blanks)

    generated_by = "llm" if any(s["by"] == "llm" for s in sections) else "rules"
    if not use_llm:
        # 꺼져 있을 뿐이면 한 줄로 · 키 · 크레딧이 문제면 그 사유를 붙인다.
        detail = off_reason if off_reason and off_reason not in (llm_client.LLM_OFF_REASON,) else None
        llm_note = f"{AI_OFF_NOTE} — {TASK_FIRST}" if (ready and needs_task) else AI_OFF_NOTE + (f" ({detail})" if detail else "")
    elif failures:
        llm_note = f"AI 작성 실패 절 {failures}개 — 그 절은 규칙 내용으로 둡니다"
    else:
        llm_note = None
    if review_note:
        llm_note = f"{llm_note} · {review_note}" if llm_note else review_note

    budget_rows = tables.get("budget", {}).get("rows") or []
    all_sentences = [s for sec in sections for s in sec["sentences"]]
    return {
        "program_id": getattr(program, "id", None),
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": generated_by,
        "provider": (llm_client.plan_writer_provider(writer) if plan_writer else llm_client.completion_provider()) if generated_by == "llm" else None,
        "model": (llm_client.plan_writer_model(writer) if plan_writer else llm_client.completion_model()) if generated_by == "llm" else None,
        "notice_version": notice_version,
        "form_source": form.get("source"),
        "form_notice": form.get("notice"),
        "form_title": form.get("title"),
        "selected_task": task,
        "sections": sections,
        "tables": list(tables.values()),
        "blanks": blanks,
        "llm_note": llm_note,
        "review_notes": review_notes,
        "review_scores": review_scores,
        "attempts": {"logical_calls": calls, "max_logical_calls": max_calls, "sdk_max_retries": llm_client.COMPLETION_MAX_RETRIES,
                     "schema_attempts_per_call": llm_client.MAX_ATTEMPTS},
        "validation": {**counts, "budget": budget_check(budget_rows, form) if tables.get("budget", {}).get("by") == "llm" else None},
        "sentence_count": len(all_sentences),
        "ai_sentence_count": sum(1 for s in all_sentences if s.get("type") == SUGGESTION),
        "elapsed_seconds": round(clock() - started, 1),
    }
