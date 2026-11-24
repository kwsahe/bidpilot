"""개발 수행역량 판정 결과 스키마.

**이 판정은 상태를 바꾸지 않는다.** GO/NO-GO 를 막지 않고, 자격판정(PASS/CHECK/FAIL)이나
추천등급을 덮어쓰지 않는다. 담당자가 「우리가 이걸 할 수 있나」를 판단할 때 쓰는 **힌트**다.

판정값이 넷인 이유 — 「모른다」와 「모자란다」를 섞지 않기 위해서다.

    supported : 공고 쪽 근거와 회사 쪽 사실이 **둘 다** 있고 서로 맞는다.
    gap       : 둘 다 있는데 어긋난다. 숫자 비교이거나, 사람이 «없다»고 적어 둔 것이다.
    unknown   : 한쪽이 없다. **«못 한다»는 뜻이 아니다.**
    info      : 판정하지 않고 공고 원문 사실만 옮겨 적는다 (예: 참가자격 등록 마감).

`unknown` 이 많은 것은 결함이 아니라 정직함이다. 회사자료가 채워질수록 줄어든다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

CAPABILITY_SCHEMA_VERSION = 1

CapabilityStatus = Literal["supported", "gap", "unknown", "info"]

#: 공고가 요구하는 «일의 종류». 하나의 공고가 여러 종류를 가질 수 있다
#: (예: 「AI 교육 플랫폼 구축 및 교육과정 운영」 = development + education).
WorkKind = Literal[
    "development",  # 개발·구축·고도화
    "education",  # 교육·연수·양성
    "consulting",  # 컨설팅·자문
    "supervision",  # 감리 — 남의 개발을 감독하는 일
    "research",  # 연구·조사·로드맵 수립
    "procurement",  # 물품·구독권·라이선스 구매·도입
    "construction",  # 공사·설계·시설
]

WORK_KIND_LABELS: dict[str, str] = {
    "development": "개발·구축",
    "education": "교육·연수",
    "consulting": "컨설팅·자문",
    "supervision": "감리",
    "research": "연구·조사",
    "procurement": "구매·도입",
    "construction": "공사·시설",
}

#: 목록 화면에서 「따로 보는」 축. 일곱 갈래를 사람이 고를 수 있는 크기로 **접은 것**이다.
#: 새 분류가 아니라 `WorkKind` 의 순수 투영이다 — 낱말 규칙은 `work_kinds.py` 한 곳에만 있다.
WorkTrack = Literal["education", "development", "other", "unclassified"]

WORK_TRACK_LABELS: dict[str, str] = {
    "education": "AI 교육·컨설팅",
    "development": "AI 개발·구축",
    # 감리·연구·구매·공사 — 갈래는 읽혔지만 우리가 «수행사»로 들어가는 일이 아닐 수 있다.
    "other": "그 밖 (감리·연구·구매·공사)",
    # 낱말로는 무슨 일인지 가릴 수 없었다. 「없다」가 아니라 「모른다」이므로 숨기지 않는다.
    "unclassified": "갈래 미분류",
}


class CapabilityEvidence(BaseModel):
    """판정 하나를 뒷받침하는 근거. **양쪽이 다 있어야** supported/gap 을 낼 수 있다."""

    #: 공고 쪽 근거 — 원문에서 그대로 따온 문장(또는 API 필드값).
    notice_quote: str | None = Field(default=None, max_length=600)
    #: 그 문장이 어디서 왔는가 — "공고명" · "과업지시서 p.2" · "공고 필드: 참가자격 등록 마감" 등.
    notice_where: str | None = Field(default=None, max_length=120)
    #: 회사 쪽 사실 — 회사자료에 적힌 내용.
    company_fact: str | None = Field(default=None, max_length=600)
    #: 그 사실의 출처 — "delivery_capacity.json · 담당자 구술 2026-09-10" 등.
    company_where: str | None = Field(default=None, max_length=200)


class CapabilityFinding(BaseModel):
    """항목 하나의 판정."""

    #: 항목 식별자 — CAP-WORKKIND · CAP-SKILL-rag · CAP-STAFFING …
    finding_id: str = Field(min_length=1, max_length=60)
    label: str = Field(min_length=1, max_length=80)
    status: CapabilityStatus
    #: 사람이 읽을 사유. **부재를 부정으로 적지 않는다** (아래 UNKNOWN 문구 규약 참고).
    reason: str = Field(min_length=1, max_length=600)
    evidence: CapabilityEvidence = Field(default_factory=CapabilityEvidence)
    #: 담당자가 다음에 할 일. 판정이 unknown 일 때 특히 중요하다.
    next_action: str | None = Field(default=None, max_length=300)


class CapabilityReport(BaseModel):
    """공고 하나에 대한 개발 수행역량 판정."""

    procurement_id: str
    organization_id: str
    #: 공고가 요구하는 일의 종류 (감지된 것 전부).
    work_kinds: list[WorkKind] = Field(default_factory=list)
    #: 개발 사업으로 볼 수 있는가. False 면 아래 기술 판정은 참고용에 가깝다.
    is_development: bool = False
    findings: list[CapabilityFinding] = Field(default_factory=list)
    #: 회사 역량자료가 기록돼 있는가. False 면 대부분의 판정이 unknown 이 된다.
    capacity_recorded: bool = False
    #: 공고 원문(요구사항)까지 읽고 판정했는가. False 면 공고명·요약만 본 것이다.
    used_requirements: bool = False
    counts: dict[str, int] = Field(default_factory=dict)
    #: 한 줄 요약. 단정하지 않는다.
    headline: str = Field(default="", max_length=400)
    evaluated_at: datetime | None = None
    schema_version: int = CAPABILITY_SCHEMA_VERSION
