"""기업마당 지원사업 **신청** 분석.

입찰(나라장터) 분석과 화면 구조·디자인은 같지만 단계와 용어가 다르다.

    입찰:   참가자격 → 특이조건 → 요구사항 매트릭스 → 회사 근거 → 제안서 → AI Auditor
    지원사업: 신청자격 → 필수·우대조건 → 신청기간 → 제출서류 → 회사 적합 근거 → 사업계획서 → 신청 전 점검

쓰지 않는 말: 입찰자격 · 낙찰 · 투찰 · RFP · 제안서 평가항목 · 수주확률.

**원문에 없는 조건을 만들지 않는다.** 기업마당 목록 API에 없는 항목은 값을 지어내지 않고
`status="unknown"` + "원문 상세 확인 필요"로 남긴다. 상세 페이지·첨부파일을 검증하기 전까지 그대로 둔다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
import logging
from datetime import date, datetime, timedelta, timezone
from collections.abc import Sequence
from typing import Any, Final

from app.core import org_storage, storage
from app.schemas.business_opportunity import (
    APPLY_PERIOD_KIND_LABELS,
    SupportProgram,
    SupportRequirementItem,
)
from app.schemas.eligibility import EligibilityResult
from app.schemas.organization import AnalysisContext
from app.schemas.requirement import Requirement
from app.services import (
    bizinfo_service,
    company_service,
    eligibility_engine,
    evidence_service,
    opportunity_priority as priority,
    support_requirement_extractor,
)

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

UNKNOWN_NOTE = "원문 상세 확인 필요 — 현재 기업마당 목록 정보만으로는 판정할 수 없습니다."

# 지원 대상(trgetNm)에 실제로 나오는 값들. 기업 유형을 여기서만 읽는다.
_COMPANY_TYPES = ("중소기업", "소상공인", "사회적기업", "예비창업자", "창업기업", "중견기업", "소기업", "협동조합", "1인창조기업")

_REGION_TOKENS = (
    "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기", "강원",
    "충북", "충남", "전북", "전남", "경북", "경남", "제주",
)

# 제출서류 문구를 뽑을 단서 (신청방법 원문에서만 찾는다 — 지어내지 않는다).
_DOCUMENT_HINT = re.compile(r"(신청서|사업계획서|증빙|서류|제출|첨부|구비)")


class ProgramNotFoundError(LookupError):
    """현재 목록(실호출·캐시·샘플)에 없는 지원사업 id."""


def _item(key: str, label: str, value: str | None, *, source_field: str | None = None, note: str | None = None) -> SupportRequirementItem:
    """값이 있으면 confirmed, 없으면 unknown. 없는 값을 추측해 채우지 않는다."""
    if value and str(value).strip():
        return SupportRequirementItem(key=key, label=label, value=str(value).strip(), status="confirmed", source_field=source_field, note=note)
    return SupportRequirementItem(key=key, label=label, value=None, status="unknown", source_field=source_field, note=note or UNKNOWN_NOTE)


def _regions_of(program: SupportProgram) -> str | None:
    """지역은 별도 필드가 없다. 해시태그·기관명에 있는 지역명만 모은다 (없으면 미확인)."""
    haystack = " ".join([*program.hashtags, program.agency or "", program.title or ""])
    found = [r for r in _REGION_TOKENS if r in haystack]
    return ", ".join(dict.fromkeys(found)) or None


def _company_types_of(program: SupportProgram) -> str | None:
    text = f"{program.target or ''} {' '.join(program.hashtags)}"
    found = [t for t in _COMPANY_TYPES if t in text]
    return ", ".join(dict.fromkeys(found)) or None


# --------------------------------------------------------------------------
# 지원사업 자격 규칙 BIZ-* (0921.md §4-B)
#
# 나라장터와 **같은 결과 모양**(`EligibilityResult`)을 쓴다. 화면이 두 출처를 한 자리에서
# 같은 말로 그릴 수 있고, 「가능 · 확인 필요 · 불가」라는 한 벌의 어휘만 남는다.
# 요약문의 「☞」 문장은 **원문 그대로** 인용한다 — 대상 요건을 지어내지 않는다.
# --------------------------------------------------------------------------

#: 요약문에서 「회사가 맡을 역할」을 가리키는 낱말.
_ROLE_WORDS: tuple[tuple[str, str], ...] = (
    ("주관연구개발기관", "주관연구개발기관"),
    ("공급기업", "공급기업 (기술을 제공하는 쪽)"),
    ("수요기업", "수요기업 (도입하는 쪽)"),
    ("주관기관", "주관기관 (과제를 이끄는 쪽)"),
    ("참여기업", "참여기업"),
    ("컨소시엄", "컨소시엄 참여"),
)

#: 「창업 7년 이내」처럼 업력을 제한하는 문장.
_FOUNDED_WITHIN_RE = re.compile(r"창업\s*(\d+)\s*년\s*(?:이내|미만)")
#: 「5인 이상」처럼 인원을 제한하는 문장.
_HEADCOUNT_RE = re.compile(r"(\d+)\s*인\s*이상")


def _region_aliases(region: str | None) -> tuple[str, ...]:
    """소재지 하나를 기업마당 지역 태그와 같은 축(대표 이름)으로 펼친다.

    정식 시 · 도 이름(「부산광역시」 · 「서울특별시」 · 「경기도」 …)도 태그 짧은 이름으로 — 기업마당 지역 태그 표
    (`bizinfo_service.REGION_ALIASES`)가 단일 출처다(38차 RULES-06 · 예전에는 광주 · 전남만 알아 가상 예시 org-test-beta 에 거짓 불가 386건).
    """
    if not region:
        return ()
    text = region.strip()
    for name, aliases in bizinfo_service.REGION_ALIASES.items():
        if text == name or text in aliases:
            return (name,)
    return (text,)


def _requirement_quote(program: SupportProgram) -> str:
    """대상 요건 문장을 근거로 인용한다. 없으면 `trgetNm` 을 쓴다."""
    if program.requirement_sentences:
        return " / ".join(program.requirement_sentences[:2])
    return program.target or "(대상 표기 없음)"


def _rule(rule_id, label, status, source, reason, unlock=None) -> EligibilityResult:
    return EligibilityResult(
        rule_id=rule_id,
        label=label,
        status=status,
        method="RULE",
        source=source,
        reason=reason,
        unlock_condition=unlock,
    )


def _extractor_names_gwangju(line: str) -> bool:
    """줄에 광주가 함께 있는가(「광주·전남 지역 내 본사」 · 126823) — 늦게 들여온다(모듈 고리 방지)."""
    from app.services.support_requirement_extractor import names_gwangju

    return names_gwangju(line)


#: 요약 대상 줄의 「전남 · 전라남도 소재」 · 전남 사업의 「도내」(34차 §3-A-6).
_JEONNAM_ONLY_RE = re.compile(r"(?<![가-힣])(?:전남|전라남도)\s*(?:지역\s*)?(?:내\s*)?(?:소재|본사|사업장)")
_PROVINCE_ONLY_RE = re.compile(r"(?<![가-힣])도내(?![가-힣]*외)")


def _biz_region(program: SupportProgram, company) -> EligibilityResult:
    tags = list(program.region_tags)
    if not tags:
        return _rule(
            "BIZ-REGION", "지역", "CHECK",
            "해시태그·기관명에 지역 표시 없음",
            "지역 표시를 찾지 못했습니다. 전국 사업인지 지역 한정인지 공고 원문에서 확인하세요.",
        )
    mine = _region_aliases(company.location_region)
    basis = f"소재지({company.location_region})"
    if not mine:
        # 소재지 칸이 비었으면 **회사가 적은 활동 지역**으로 대신 본다. 지어내는 것이 아니라
        # 이미 적어 둔 값을 읽는 것이다 (0921 §4-B).
        for region in company.activity_regions:
            mine = mine + _region_aliases(region)
        if mine:
            basis = f"활동 지역({', '.join(company.activity_regions)})"
    source = f"지역 태그 {' · '.join(tags)}"
    if not mine:
        return _rule(
            "BIZ-REGION", "지역", "CHECK", source,
            "지역 한정 사업인데 회사 소재지가 아직 없습니다.",
            "회사자료에 소재지를 적으면 판정할 수 있습니다",
        )
    if any(tag in mine for tag in tags):
        line = program.requirement_sentences[0] if program.requirement_sentences else ""
        jeonnam_program = "[전남]" in (program.title or "") or "전라남도" in (program.agency or "")
        jeonnam_only = (_JEONNAM_ONLY_RE.search(line) or (jeonnam_program and _PROVINCE_ONLY_RE.search(line))) and not _extractor_names_gwangju(line)
        if "전남광주" in mine and jeonnam_only:
            # 공고문 경로의 「전라남도 소재」와 같은 판단 — 통합 이후 광주가 드는지 해석이 갈린다(34차 §3-A-6)
            return _rule(
                "BIZ-REGION", "지역", "CHECK", f"대상 요건 「{line[:80]}」",
                f"대상이 「전남(도내) 소재」입니다. {MERGED_REGION_NOTE}.",
                MERGED_REGION_UNLOCK,
            )
        return _rule(
            "BIZ-REGION", "지역", "PASS", source,
            f"회사 {basis}가 대상 지역에 듭니다.",
        )
    return _rule(
        "BIZ-REGION", "지역", "FAIL", source,
        f"대상 지역이 {', '.join(tags)} 이고 회사 {basis}는 거기에 없습니다.",
    )


#: 판정 규칙 판 — 대상 요건 · 소재 · 창업 연차 규칙이나 **판정 · 사유 문장**을 고치면 올린다. 판정 메모 열쇠
#: (`opportunity_service._inputs_stamp`)에 들어가 코드를 바꾼 날 목록이 옛 판정 · 옛 문장을 내지 않는다(31차 R30-06 — 목록 ·
#: 상세 · 내보내기가 갈렸다). 32 = 31차 §3-D 판정 문장 「~니다」 · 33 = 31차 마지막 검토(같은 갈래 진입 구절 · 본사를 둔 세부 지역) · 34 = 32차 R31-01~07 · 35 = 32차 §3-E 글(직접 신청 · 소재 가능 · 창업 연차 대안 · 점수 이유 낱말) · 36 = 32차 마지막 검토(괄호 안 절차 낱말 · 신청 자격 꼴) · 37 = 33차 §3-B 사업 규모(불허도 확인 필요 · 공동수급 판단 하나 · 문구) · 38 = 33차 §3-F(또는 공통 꼬리 · 창업 연차 경계 해 · 선행 선정 절차 꼴 · 「되려」 · 신청 종료 · 조직 형태 사유 · AI 의미 매칭 이름) · 39 = 33차 마지막 검토(창업 연차 경계 해의 다른 갈래 · 선행 선정 절차 꼴 · 혼합방식) · 40 = 34차 §3-A(나열 대상 · 갈래 줄 · 소재 갈래 · 지역 별칭 · 자격 미확인 · 기술 보유 · 소상공인만 · 선행 선정 절차 꼴) · 41 = 34차 §3-D(사업 규모 — 파트너 있음 · 교육 없는 큰 개발 사업도 후보) · 42 = 34차 §3-F(결격 줄 회사 쪽 · 반올림 같은 금액 · 창업 연차 사유를 다른 갈래 확인 필요에도) · 43 = 34차 마지막 검토(실적 조항 줄이 모두 가능이면 필드 줄 그대로 · 기술 보유 앞말 · 「광주·전남」 · 「X 관련 기업」 분야) · 44 = 「가능」 좁히기(10-10 담당자 결정 — 요약만 맞춘 공고 · 전략산업만 맞음 · 조건 붙은 인원 예외는 확인 필요 · 제외 조항 사유) · 45 = 확인 필요 중 회사 사실이 맞은 공고는 덜 깎기(10-10 담당자 결정) · 46 = 그 검토(인원 먼저 · 조건 붙은 예외는 공고 쪽 · 제외 조항 훈련기관 · 「가능」 사유의 제외 조항 안내) · 47 = 중소기업 확인서(10-10 담당자 결정 — 준비 상태 줄 · 구분 · BIZ-SME · 나라장터 기업 유형 조항 · 그 검토: 빗금 확인서 · 끊긴 직접생산 · 확인서로 못 가리는 조항 · 제외 이름표 괄호 · 법 조문 꼴 · 지원 비율 좁히기) · 48 = 35차 §3-A(회사 값을 적으면 생기는 거짓 불가 — 연구소는 보유 동사 대상 문장 · 서류 목록 · 매출 제외 목록 · 대상 문장 · 인원 예외 꼴 · 배정 비율 · 소상공인 함께 나열 · 조건 붙은 소상공인 · 공동수급 파트너 없음은 확인 필요) · 49 = 35차 §3-B(거짓 가능 · 맞음 — 실적 한 건 기준 먼저 · 원장으로 못 보는 갈래 · 컨설팅 실적 · 발주처 유형 · 예외 · 붙임 · 조건 문단의 형태 낱말 · 사회연대경제 관련 비영리 · 옛 광주 · 전남 · 나열 분야 같은 뜻 낱말 · 괄호 속 제외 문장 · 확인서 글머리 · 끊긴 중 소기업 · 중소기업자 중 소기업 · 줄임 도 이름 · 대출 · 이차보전 금액 · 반올림 금액) · 50 = 35차 §3-B 보충(기준 답안 — 조건을 붙여 회사 형태를 따로 받는 줄은 불가 대신 확인 필요 · 「전남형 · 광주형」 사업명은 옛 지역이 다른 회사에게 소재 해석 확인) · 51 = 35차 마지막 검토(건너뛰기 구간은 새 절 · 윗단 항목에서 끝남 · 한 줄 풀이 · 괄호 안 서류 낱말 · 연구소 우대 · 다음 줄 갈래 · 매출 또는 갈래 · 옛 지역 「구」 · 가점 소재 · 나열 분야 정규식 멈춤) · 52 = 36차 §3-A-5(상시 근로자 열리는 조건이 가리키는 곳 「회사자료 › 회사 프로필의 상시 근로자 수」 — 글만) · 53 = 36차 §3-B(대상 절에 규칙이 못 읽은 줄이 남으면 「가능」 대신 확인 필요 · 연구소 기업부설만 · 전담부서만 · 주관기관 자리에 한정된 연구소 · 소재는 확인 필요 · 과제 지역 소재 · 연구소 문장의 중소 · 중견기업 · 제외 · 서류 구간은 윗단 글머리에서 끝 · 자격 낱말이 함께 있는 머리는 제외 구간을 열지 않음 · 참여 · 신청 제외 머리 · 옛 지역은 이전 · 도내외 갈래를 먼저 · 줄바꿈된 이전 예정 · 「중 소기업ㆍ소상공인확인서」) · 55 = 37차 §3-G(촉박은 확인 필요 · 수행기관 모집 · 컨소시엄 필수 · 광역시 줄임말 · 순천향 · 전담부서 미포함 범위) · 56 = 37차 마지막 검토(「단독 신청 불가능」은 컨소시엄 선택 꼴이 아님 · 혼합 · 주계약 방식도 「함께 참가할 수 있음」) · 57 = 38차 §3-A(나라장터 분류 — AI 낱말 없는 본업 갈래 후보 · 본업 아님 사유 · AX · GPT · 짧은 영문 합성어 마디 · 넓힌 수집 낱말) · 58 = 38차 §3-B(유형(근사) — 제목 낱말 먼저 · 조달 분류명은 제목에 갈래가 없을 때만) · 59 = 38차 §3-E(참가자격 조항 추출기가 DOCX 를 읽음 — 직접 넣은 공고문 · 직접 넣은 공고 판정 사유 「공고문 아직 안 읽음」 · 「사람 확인 뒤 가능」) · 60 = 38차 §3-F(활동 지역 정식 이름 · 컨소시엄 필수 꼴(괄호 낀 · 조사 없는 · 「구성한 기업만」) · 역할 조항 중복 거르기가 필수 줄을 남김 · 경기 광주시 대체 때 갈래 단서 · 전담부서 미포함 창 기준점 · 「… 접수 불가」 부정 · 수행기관도 광주 · 전남 기관 자체). · 61 = 38차 §3-G(넓힌 수집 실제 1회에서 본 거짓 본업 — 설계공모 · 설계용역 · 공간 재조성 · 인테리어 · 철거 · 건설사업관리는 AI 낱말이 있어도 본업 아님 · 「건립」은 AI 낱말이 없을 때 · 「발간」은 본업 낱말이 「교육」 · 「연수」뿐이고 일 낱말이 없을 때 본업 아님) · 62 = 38차 마지막 검토(직접 넣은 공고 — 지역 제한 「전국」 · 「제한 없음」은 지역 목록이 아님 · 수혜 점수도 낮춘 판정으로 · 접수방식 부정은 괄호에서 끊음) · 63 = 담당자 결정 10-16(공고명에 AI 낱말 + 「구축 · 도입 · 시스템」이면 개발 갈래 후보 — 37차까지 「AI 낱말만」이라 후보 아님) · 64 = 39차 §3-A(분류 정밀도 — 조달분류 부정 신호 D19 · 정보시스템 유지관리 · 이름 속 「교육」 · AI 경로 제목에서만 · 농촌 · 체험 · 어학 · 인허가 · 본업 낱말 · 낱말 경계 · 띄어쓰기 무시) · 65 = 39차 §3-G(참가자격 조항 추출기 — 첫 표시 앞 줄 · 띄어 쓰지 않은 표시 · HWP 글꼴 기호 표시(RANK_BRIEF-03) · 근거 줄은 판정 조항만 · 「공고문 읽음 · 결정 조항 없음」) · 66 = 39차 §3-G MANUAL-01(직접 넣은 공고의 지역 제한 — 「지역 제한 없음 · - · 해당없음 · N/A」는 제한 없음 · 「○○ 제외」는 확인 필요 · 빈칸은 사람 칸 말) · 67 = 40차 §3-B(분류 묶음 — 이름 속 「교육」 건물 · 센터 · AI 아닌 서비스 개발 · 센터 고도화 · 시스템 이름 속 교육과정 · 행사 · 공연 · 전시 · 홍보 대행 조달분류(교육 운영 낱말 없을 때) · 성과대회 · 발표회 · AI 홍보 · 마케팅 · 축제 · 온라인 콘텐츠는 교육 낱말과 함께 · 장비 보드 · 생산 · 면제 낱말 뒤 계속 찾기 · 외국어 기관 이름 · 「AI … 운영」 예외는 교육 운영 분류 · 교수설계 · 마이크로러닝 · 교과 · 수업 · 유형 PMC 좁힘 · 기획연구 · 조사 · 방안 마련은 연구 · 데이터 구축 · 의료 AI 는 D · 연구 수식어 · 해커톤 · 특강 · 사전규격 대체 유형 · 사유 괄호 글 묶음별) · 68 = 40차 §3-C(주제 확인 — 담당자 결정 1 · D23 · 교육 · 컨설팅인데 공고명에 회사 사업 주제가 없으면 본업 덩어리 안에서 뒤로 · 선제준비 보임도 주제 맞음 먼저 · 꼬리표 한 곳 tags_of · 판정 · 점수 그대로) · 69 = 40차 §3-D(AI 적합도 보조 — 담당자 결정 2 · D24 · 켠 회사의 AI 「아님」 꼬리표를 「주제 확인」과 같은 자리로 · 판정 · 점수 · 접기 그대로) · 70 = 40차 §3-F(조항 추출기 판 3 — 여는 말 · 절 머리글 거르기 · 코드 없는 업종 이름 · 근거 줄 「판정 조항을 찾지 못함 — 원문 확인」 · 확인 기록은 원문 해시 먼저 · 같은 절 「단, … 예외 … 허용」이면 기업 유형 불가 → 확인 필요) · 71 = 40차 §3-G(MANUAL-01 — 사람이 적은 지역 제한은 조각마다 시 · 도 이름이 나올 때만 참가 가능 지역 목록 · 「외 · 이외 · 타지역 · 비수도권 · 불가」는 빼는 꼴 · 지역 이름 없는 글은 확인 필요 · 사람이 적은 글로 「불가」를 내지 않음) · 72 = 40차 §3-H(SCREEN-02 — 「마감까지 n일」 · 「마감 n일 남음」을 D-day 와 같은 KST 달력 날짜 차 · 실제 마감(등록마감이 이르면 그쪽) · 0 이면 「오늘 마감」 · 사전규격 본공고 여럿 · 발주계획 본공고 나옴 · 판정 · 점수 그대로) · 73 = 40차 마지막 검토(추출기 판 4 — 여는 말 거르기는 「기타」 줄만 · 선제준비에도 AI 꼬리표 · 조항 파일 덮기 막음은 공개 폴더도) · 74 = 41차 2-A(분류 · 주제 — 행사 분류 예외에 교육 위탁 · 역량강화 과정 · 교육 콘텐츠 제작 · AI 낱말과 함께인 아카데미 · 연수 · 특강 · 워크숍 · 사전규격 행사 · 전시 · 대행 꼴은 본업 아님 · 대체 유형 「그 밖 A1」 없앰 · 장비 보드 · 생산 · 교과 · 수업 낱말 경계 · AI 홍보 예외 넓힘 · 맨 「진단」은 B1 아님 · 의료 AI · 영향평가 D · 교육 낱말 목록 맞춤 · 드래프톤 · 교육기관 콘텐츠 개발 · 주제 낱말 대소문자 · 띄어쓰기 · AI 약어 · 교육과정 컨설팅 · 정보보안 갈래 · 접힌 행에는 주제 확인 없음 · 점수순 회사의 선제준비 순서 그대로) · 76 = 41차 마지막 검토(사전규격 맨 「대행」으로 접지 않음 · 참가자 초청은 행사 · 지역 + 업종 등록 문장은 지역 조항(추출기 판 6) · 온보드 · 화이트보드는 장비 · 낱말 속 scribe 아님 · 홍보관 구축은 시설 · 대체 유형 공유대학 · 이러닝 · 양성) · 75 = 41차 2-C(추출기 판 5 — 업종 코드 목록 줄에서 절이 끊기지 않음 · 표 꼴 다음 절 머리 · 코드 없는 업종 등록 문장은 업종 조항 · 여는 말 꼴 · 확인 기록은 해시가 같으면 가장 최근 · 다른 줄에 붙은 옛 번호 확인은 유령 「다시 확인」으로 두지 않음) · 77 = 42차 §2(업종 조항 「모두 · 및 · 와 · 과」는 코드가 모두 맞아야 가능 — 하나만 맞으면 확인 필요 · 「또는 · 중 1개 이상」은 하나 · 브리핑 TOP 판단 칸 꼬리표 한 번) · 78 = 42차 마지막 검토(업종 사이 「및」도 접속사 · 「또는」은 업종 사이 구간에서만 — 「단독 또는 공동수급」에 속지 않게) · 79 = 43차 §2-A(실제 마감 = 공고문 일정표의 가장 이른 마감 · 개찰일은 마감 아님 · 입찰 마감 빈칸은 「마감 미상」 · 필수 현장설명 줄 · 시간 등급 TU) · 80 = 43차 §2-B · §2-C(실적 조항 · 회사 단위 확인 · 0단계 · 직접생산 품명 · 공급기업 제외 · 디지털 제품 · 대기업 참여 제한 · 통합특별시 시 · 군 · 구 · 결정 4 사업영역 제목 먼저 · 가명정보 · 이러닝 임차 · 제작 D · 수행기관 모집 유형 제목만 · 이름 속 교육 · 누리집 · 공공건축 · 스키 · 수요기관 기준 광주 · 전남 · 기업마당 전국 태그 · 수행기관 반감 · 호남권 · 같은 사업 묶음 · 수혜 긴급 뒤 · 참여자 전액 지원) · 81 = 43차 §2-D · §2-E(「왜 맞나」 근거 낱말 경계 · 기관 이름 조각 · 수혜 사업 고객 유형 일치 없음 · 공고문 열기 실패 줄) · 82 = 43차 §2-F(사전규격 조달분류 · 실수요기관 → 입찰과 같은 분류 규칙 · 직접 넣은 공고 「상시 · 미정」 · 참가신청 마감 · 사람이 본업 확인 · 직찰 접수방식 · 직접 넣은 공고의 나라장터 전용 문장 없앰) · 83 = 43차 §2-I(기업마당 「광주광역시」 소재는 회사 옛 지역(광주)일 때만 가능 · 소재 사유 글 · 창업 연차 경계 해는 일반현황 개업일로 · 회사 선행 사업 이름이 조항에 있으면 「없음」보다 먼저 확인 필요 · 「검수자 조사」 · 본공고 번호가 목록 밖인 사전규격은 「본공고 나옴」) · 84 = 43차 마지막 검토(빼는 문장 꼴 실적 · 지역 · 기업 형태 조항은 회사 단위 확인으로 통과하지 않음 · 직접생산 품명이 맞아도 증명서 유효기간 확인 필요 · 질의 기한은 마감 아님(추출기 판 8)). · 85 = 44차 2-A(공고문 일정표 마감이 입찰 · 등록 마감보다 이르면 상세 · 목록 판정에도 그 줄 · R36-J-03) · 86 = 44차 2-B(결정 4 — 업종 없음 · 공동수급 허용 · 모름은 확인 필요 · 파트너형 덩어리 · 결격 조항 「통과」는 등록 · 제재 · 체납 낱말이 있을 때만 · 부도 · 회생 · 상호출자는 확인 필요 · 대괄호 업종 코드는 업종 조건 · R36-J-04) · 87 = 44차 마지막 검토(추출기 판 10 — 「부터 N일간 · N일 이내」는 기간 · 「시작 · 개시 및 마감: A ~ B」는 끝 날짜 · 표 머리줄 칸은 갈래 낱말로 · 평가 · 개찰 날짜에 칸 이름 안 붙임 · 「24:00까지」는 그날 끝 · 「입찰참가자격을 등록한 자」도 회사 단위 확인 · 직접 넣은 입찰 · 수행 불가는 「참여」 거절) · 88 = 45차 M16(발주 예정 표도 유형(근사) · 주제 확인 순서 · 유형 B2 · D 는 사유와 함께 접음 · 입찰 · 사전규격 판정 · 점수 그대로) · 89 = 10-31 대표 확인(기업마당 조직 형태 — 「상법상 회사(법인), 개인사업자 또는 협동조합」을 나열한 법적 정의 줄(여성기업 · 장애인기업 정의)은 조직 형태 요건이 아님 · 118204 여성기업 육성사업 「사회적협동조합만 대상 → 불가」 · 대상 문장이 「소재 공방」처럼 다른 업종 낱말로 끝나도 BIZ-TARGET-INDUSTRY 확인 필요 · 127455 소재만 맞아 거짓 「가능」)
RULES_VERSION: Final[int] = 89

#: v1 이 「모르겠다」고 할 때의 사유. v2 는 이 결과를 **바닥으로 잇지 않는다** —
#: 공고문 조항이 더 나은 근거이고, 못 찾은 것은 새 종합 규칙이 이미 「확인 필요」로 읽는다.
TARGET_UNKNOWN_REASON: Final[str] = "기업마당 요약만으로는 알 수 없습니다 — 공고 원문의 지원대상을 확인하세요."


#: 대상 문장에 남은, **규칙이 읽지 못한 요건** (30차 §3-E · 담당자 결정). 「가능」은 대상 요건이 모두 회사 사실로
#: 가려졌을 때만 — 창업 연차 · 인증 하나가 맞아도 이것이 남으면 「확인 필요」 + 원문 인용이다(126779 대전 이전 ·
#: 119834 광(光) 관련 · 119567 농식품 · 126314 수요과제 기술 · 126731 일본 진출).
_UNREAD_TARGET_TERMS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("지역 이전", re.compile(r"이전(?:을|한|하|\s*완료|\s*희망)")),
    # 「OO구(에) 소재 · OO시 · OO군 소재 · 관내」 — 광역 · 특별시 단위는 지역 규칙이 본다(31차 R30-04 · 120608 김포 · 119332 하남).
    # 「담양군에 본사를 둔 · 나주시 내에 소재한 · 부여군에 본부를 두고 있는」도 같은 요건이다(31차 마지막 검토 · 126613).
    # 「대구 소재」의 「구」는 광역시 이름이라 뺀다.
    ("세부 지역", re.compile(
        r"관내|[가-힣]{1,6}(?:(?<!대)구|(?<!광역)(?<!특별)(?<!자치)(?<!서울)(?<!부산)(?<!대구)(?<!인천)(?<!대전)(?<!울산)(?<!세종)시|군)"
        r"(?:\s*(?:내|관내))?\s*(?:에\s*)?(?:소재|본사|본점|본부|사업장|주사무소)")),
    ("업종 · 분야", re.compile(r"분야|업종|관련\s*기업|농식품|식품\s*기업|제조\s*기업|기술을\s*보유|기술\s*보유")),
    ("기업 인증", re.compile(r"(?<![가-힣])(?:벤처기업|이노비즈|메인비즈|여성기업|장애인기업|소셜벤처)")),
    ("진출 · 희망", re.compile(r"진출|희망")),
    ("개인 대상", re.compile(r"거주|청년|만\s*\d+\s*세|수료자|참여자")),
    ("인력", re.compile(r"인력|채용")),
)
#: 아직 그 지위가 아닌 회사를 찾는 말 — 「~(으)로 진입하려는 · 지정받으려는 · 인증받으려는」. 「인증받은 · 인증된 ·
#: 지정된 · 전환한」은 이미 그 지위라 여기에 들지 않는다(31차 R30-01 — 동사 줄기만 보다가 거짓 불가가 났다).
_ASPIRING_RE = re.compile(r"진입\s*하(?:고자|려)|지정\s*받(?:고자|으려)|인증\s*받(?:고자|으려)|전환\s*하(?:고자|려)|되고자|되려")
#: 인증 낱말 바로 뒤 「(으)로 · 이 · 가」 — 그 뒤 몇 글자 안에 진입 · 전환 꼴이 오는지 본다(「으로서」는 지위를 밝히는 말).
_ASPIRING_LEAD_RE = re.compile(r"\s*(?:(?:으로|로)(?!서)|(?:이|가)\s*(?=되고자|되려))")
#: 진입 꼬리를 자르는 곳 — 접속 표현 · 다음 인증 낱말(32차 R31-02: 「사회적기업이거나 사회적기업으로 전환하려는」 ·
#: 「사회적기업이며 마을기업으로 지정받고자」의 앞 「사회적기업」이 진입 꼴로 읽혀 거짓 불가가 났다).
_ASPIRING_TAIL_CUT_RE = re.compile(r"이거나|거나|이며|이나|이고|및|,|ㆍ")
_CERT_WORD_RE = re.compile(r"(?<![가-힣])(?:예비\s*)?(?:사회적기업|마을기업|협동조합|자활기업|벤처기업|이노비즈|메인비즈|여성기업|장애인기업|소셜벤처)")
#: 회사 인증 낱말이 아닌데 그 낱말을 품은 이름 — 판정 전에 지운다(32차 R31-04: 「중소벤처기업부」의 「벤처기업」).
_NOT_CERT_NAMES_RE = re.compile(r"중소벤처기업부|중소벤처기업진흥공단|중기부")
#: 지정 · 인증을 **주는** 공고의 제목 — 「예비사회적기업 지정계획」.
_DESIGNATION_TITLE_RE = re.compile(r"지정\s*계획|지정\s*공고|인증\s*계획|지정\s*신청")
#: 법령 이름 — 「사회적기업 육성법」 안의 낱말은 회사 인증과 맞춰 보지 않는다.
_LAW_NAME_RE = re.compile(r"「[^」]*」")
#: 창업 연차 「불가」를 막는 대안 표시 — 「또는 · 혹은 · 이거나 · 쉼표 · ※ … 경우」(31차 R30-03 · 126314 「※ 신사업 분야의
#: 경우 창업 10년 이내」). 이것이 있으면 상한을 넘어도 「확인 필요」다. 괄호 안 쉼표(「(단순 유통, 판매업 제외)」)는 대안이 아니다.
_FOUNDING_ALT_RE = re.compile(r"또는|혹은|이거나|※[^)]*경우")
_PAREN_RE = re.compile(r"\([^()]*\)")


#: 괄호 안 단서 — 「(신산업 분야기업은 10년 이내까지 인정)」(119754 TIPS) · 「(… 경우)」 · 「(단, …)」. 「(단순 유통 …)」 · 조건 자체인
#: 「(창업 7년 이내)」(117583)는 아니다 — 「N년 이내」만으로는 단서로 보지 않는다(32차 R31-03).
_PAREN_CLUE_RE = re.compile(r"\([^()]*(?:인정|경우|단[\s,])[^()]*\)")


def _founding_alternative(line: str) -> bool:
    return bool(_FOUNDING_ALT_RE.search(line) or "," in _PAREN_RE.sub(" ", line) or _PAREN_CLUE_RE.search(line))


def _target_branches(text: str) -> list[str]:
    """대상 문장을 대안 갈래로 — 괄호 밖의 「또는」에서만 나눈다(괄호 안 나열은 한 갈래).

    쉼표는 나누지 않는다 — 공고는 쉼표를 「그리고」로도 쓴다(「창업 7년 이내 기업으로, 대전으로 이전을 완료한 기업」 ·
    126482 「…대표자이자, …」). 쉼표로 나누면 뒤 조건을 버려 거짓 「가능」이 났다(30차 §4 마지막 검토)."""
    branches, depth, current, i = [], 0, "", 0
    while i < len(text):
        ch = text[i]
        if ch in "([「":
            depth += 1
        elif ch in ")]」":
            depth -= 1
        if depth <= 0 and text.startswith("또는", i):
            branches.append(current)
            current = ""
            i += 2
            continue
        current += ch
        i += 1
    branches.append(current)
    out = [b.strip(" ,") for b in branches if b.strip(" ,")]
    if len(out) > 1:
        # 「A 또는 B로서 …」 · 「A 또는 B 중 …」 — 마지막 갈래의 이 꼬리는 모든 갈래에 걸린다. 버리면 A 갈래가 꼬리 조건 없이
        # 맞아 거짓 「가능」이 났다(33차 R32-02 · 122863 「…벤처기업 또는 창업 예정인 자로서 제조 분야의 AX … 개발하려는 자」).
        tail = _SHARED_TAIL_RE.search(out[-1])
        if tail:
            shared = out[-1][tail.start():].strip()
            out = [f"{b} {shared}" for b in out[:-1]] + [out[-1]]
    return out


#: 「또는」 갈래 모두에 걸리는 꼬리의 시작 — 「(으)로서」 · 「중」(R32-02).
_SHARED_TAIL_RE = re.compile(r"(?:으로서|로서|\s중\s)")


#: 갈래를 가로질러 보는 위치 조건(R31-07).
_LOCATION_TERMS: Final[frozenset[str]] = frozenset({"세부 지역", "지역 이전"})
#: 조직 형태 — 주식회사가 아닌 신청자를 찾는 낱말(R31-05 · R31-06).
_ORG_FORM_RE = re.compile(r"(?<![가-힣])(?:마을기업|협동조합|사회적협동조합|자활기업|비영리|법인\s*[ㆍ·]\s*단체)")
_TENANT_RE = re.compile(r"입주\s*기업|입주\s*예정")


def _founding_branch_terms(branch: str, company) -> list[str]:
    """창업 연차로 맞은 갈래에 함께 있는 엄한 조건 — 회사 인증의 진입 구절 · 조직 형태(회사 인증에 없는 것) · 입주기업(R31-06)."""
    held = [c for c in company.certifications if c]
    terms: list[str] = []
    if any(any(_aspiring_flags(branch, c)) for c in held):
        terms.append("진입 · 전환하려는 기업")
    forms = {m.group(0) for m in _ORG_FORM_RE.finditer(branch)} - set(held)
    if forms:
        terms.append("조직 형태(" + " · ".join(sorted(forms)) + ")")
    if _TENANT_RE.search(branch):
        terms.append("입주기업")
    return terms


def _unread_terms(text: str, company) -> list[str]:
    held = set(company.certifications or ())
    found: list[str] = []
    for label, pattern in _UNREAD_TARGET_TERMS:
        hits = [m.group(0) for m in pattern.finditer(text)]
        if label == "기업 인증":
            hits = [h for h in hits if h not in held]
        if hits and label not in found:
            found.append(label)
    return found


def _cert_matches(text: str, cert: str) -> list[re.Match[str]]:
    """인증 낱말이 **낱말로** 나온 자리 — 앞에 한글이 붙으면 다른 낱말이다(32차 R31-04: 「예비사회적기업」 안의 「사회적기업」)."""
    return list(re.finditer(rf"(?<![가-힣]){re.escape(cert)}", text))


def _has_cert(text: str, cert: str) -> bool:
    return bool(_cert_matches(text, cert))


def _aspiring_flags(text: str, cert: str) -> list[bool]:
    """`text` 안 인증 낱말 하나하나가 「아직 그 지위가 아닌 기업」을 찾는 꼴인지 — 「사회적기업으로 진입하고자」는 참 ·
    「사회적기업으로 인증받은」 · 「(예비)사회적기업」은 거짓(31차 R30-01)."""
    flags: list[bool] = []
    for m in _cert_matches(text, cert):
        tail = text[m.end(): m.end() + 30]
        cuts = [c.start() for c in (_ASPIRING_TAIL_CUT_RE.search(tail), _CERT_WORD_RE.search(tail)) if c]
        if cuts:
            tail = tail[: min(cuts)]
        lead = _ASPIRING_LEAD_RE.match(tail)
        aspiring = _ASPIRING_RE.search(tail, lead.end()) if lead else None
        flags.append(bool(aspiring and aspiring.start() - lead.end() <= 12))
    return flags


def _biz_target(program: SupportProgram, company, today: date) -> EligibilityResult:
    quote = _requirement_quote(program)
    # 판정은 **지원대상 줄**(요약문 첫 「☞」)로만 — 둘째 줄은 지원내용이라 「사회적기업 재정지원사업」 같은 낱말이 섞인다(30차 §3-E).
    full_line = (
        _NOT_CERT_NAMES_RE.sub(" ", _LAW_NAME_RE.sub(" ", program.requirement_sentences[0])) if program.requirement_sentences else ""
    )
    line = full_line
    source = f"대상 요건 「{quote}」"
    # 분류 이름(`trgetNm`)은 대상 줄에 인증 낱말이 없을 때만 본다 — 창업 연차 갈래를 버린 경로에서는 다시 붙이지 않는다(R30-02).
    use_category = True
    fallback = False
    founding_note = ""
    founded_all = list(_FOUNDED_WITHIN_RE.finditer(line)) or list(_FOUNDED_WITHIN_RE.finditer(f"{line} {program.target or ''}"))
    if founded_all and not company.founded_year:
        # 설립 연도를 모르면 창업 연차 갈래는 판정하지 않는다 — 다른 갈래(인증)로 가능이면 그대로, 아니면 확인 필요(32차 R31-06)
        others = [b for b in _target_branches(line) if not _FOUNDED_WITHIN_RE.search(b)]
        other = _cert_target(program, company, " ".join(others), full_line, source, use_category=False) if others else None
        if other is not None and other.status == "PASS":
            return other
        years_text = " · ".join(dict.fromkeys(f"창업 {m.group(1)}년" for m in founded_all))
        return _rule(
            "BIZ-TARGET", "대상 요건", "CHECK", source,
            f"창업 연차 요건({years_text})인데 회사 설립 연도가 아직 없습니다.",
            "회사자료에 설립 연도를 적으면 판정할 수 있습니다",
        )
    if founded_all and company.founded_year:
        limits = [int(m.group(1)) for m in founded_all]
        years = today.year - company.founded_year
        made = f"우리 회사는 {company.founded_year}년 설립(설립 뒤 {years}년)"
        if (
            years == min(limits)
            and not any(n > years for n in limits)
            and not [b for b in _target_branches(line) if not _FOUNDED_WITHIN_RE.search(b)]
        ):
            # 설립 연도만 있으면 연도 차이가 상한과 같은 해는 설립 월에 따라 맞기도 안 맞기도 한다(33차 R32-03 · 나라장터 쪽과 같은 규칙).
            # 다른 갈래(「… 또는 벤처기업」)가 있으면 아래 갈래 경로로 다시 본다 — 경계 해가 상한을 넘은 해보다 나쁘게 나왔다(마지막 검토)
            return _rule(
                "BIZ-TARGET", "대상 요건", "CHECK", source,
                f"창업 {years}년 이내 요건 — {made}이라 설립 월에 따라 다릅니다. 공고 기준일과 설립일을 견줘 확인하세요.",
            )
        if years < min(limits):
            founded_branch = next((b for b in _target_branches(line) if _FOUNDED_WITHIN_RE.search(b)), line)
            stricter = _founding_branch_terms(founded_branch, company)
            if stricter:
                # 같은 갈래에 진입 구절 · 조직 형태 · 입주기업이 함께 있으면 창업 연차만으로 가능이 아니다(32차 R31-06)
                return _rule(
                    "BIZ-TARGET", "대상 요건", "CHECK", source,
                    f"창업 {min(limits)}년 이내 요건은 맞습니다({made}). 다만 같은 조건에 회사 자료로 가리지 못한 것"
                    f"({' · '.join(stricter)})이 있습니다 — 「{founded_branch.strip()[:100]}」",
                )
            return _target_pass(
                program, company, full_line, founded_all[0].group(0), source,
                f"창업 {min(limits)}년 이내 요건 — {made}이라 맞습니다.",
                branch=founded_branch,
            )
        if years > max(limits) and not _founding_alternative(line):
            # 상한을 모두 넘고 다른 갈래 · 단서가 없을 때만 불가 — 불가는 목록에서 숨는다(R30-03).
            return _rule(
                "BIZ-TARGET", "대상 요건", "FAIL", source,
                f"창업 {max(limits)}년 이내 요건인데 {made}입니다.",
            )
        others = [b for b in _target_branches(line) if not _FOUNDED_WITHIN_RE.search(b)]
        if not others:
            years_text = " · ".join(dict.fromkeys(f"창업 {n}년" for n in limits))
            return _rule(
                "BIZ-TARGET", "대상 요건", "CHECK", source,
                f"창업 연차 요건에 단서 · 다른 조건이 있습니다({years_text}) — {made}이라 공고 원문에서 어느 조건에 드는지 확인하세요"
                f"(「{line.strip()[:100]}」).",
            )
        # 「창업 3년 이내 기업 또는 사회적기업」 — 창업 연차가 없는 다른 갈래로 다시 본다. 갈래 하나가 안 맞는다고 불가로
        # 숨기지 않는다(목록에서 불가는 숨는다 · 30차 §4 마지막 검토).
        line = " ".join(others)
        use_category = False
        fallback = True
        # 상한 하나 이상을 채우면 「맞지 않습니다」가 거짓이다 — 어느 조건에 드는지만 남는다(32차 R31-20)
        founding_note = (
            f" 창업 연차는 {company.founded_year}년 설립(설립 뒤 {years}년)이라 창업 {max(limits)}년 이내 조건에는 맞습니다 — 공고 원문에서 어느 조건에 드는지 확인하세요."
            if years < max(limits)
            else f" 창업 연차는 {company.founded_year}년 설립(설립 뒤 {years}년)이라 설립 월에 따라 다릅니다 — 공고 원문에서 확인하세요."
            if years == max(limits)
            else " 창업 연차 조건은 맞지 않습니다 — 공고 원문에서 확인하세요."
        )
    result = _cert_target(program, company, line, full_line, source, use_category=use_category)
    if result is not None:
        if fallback and result.status == "FAIL":
            # 창업 연차 갈래를 대안으로 버린 경로다 — 분명한 불가가 아니다(R30-03).
            return result.model_copy(update={"status": "CHECK", "reason": result.reason + founding_note})
        if fallback and result.status == "CHECK":
            # 다른 갈래도 확인 필요면 창업 연차 사유(경계 해 포함)를 함께 — 사라졌었다(34차 R33-06)
            return result.model_copy(update={"reason": result.reason + founding_note})
        return result
    headcount = _HEADCOUNT_RE.search(f"{line} {program.target or ''}")
    if headcount and company.employee_count is None:
        return _rule(
            "BIZ-TARGET", "대상 요건", "CHECK", source,
            f"「{headcount.group(0)}」 요건인데 회사 상시 근로자 수가 아직 없습니다.{founding_note}",
            "회사자료 › 회사 프로필의 「상시 근로자 수」를 적으면 판정할 수 있습니다",
        )
    return _rule(
        "BIZ-TARGET", "대상 요건", "CHECK", source, TARGET_UNKNOWN_REASON + founding_note,
    )


def _cert_target(program: SupportProgram, company, line: str, full_line: str, source: str, *, use_category: bool) -> EligibilityResult | None:
    """회사 인증으로 대상 요건을 본다 — 없으면 None.

    인증 낱말 하나하나를 「이미 그 지위면 대상」(맞음) · 「아직 아닌 기업을 찾음」(진입 · 전환)으로 가른다(31차 R30-01).
    - 진입 · 전환 꼴이 하나도 없는 인증이 있으면 그 갈래로 가능 쪽(남은 조건은 `_target_pass`) — 회사 인증이 여럿이면
      맞는 갈래 하나로 충분하다(「사회적기업으로 진입하고자 하는 기업 또는 데이터바우처 공급기업」).
    - 같은 인증이 두 뜻으로 함께 나오면 확인 필요.
    - 모든 갈래가 회사가 이미 가진 지위로 「진입 · 전환」하려는 기업만 찾을 때만 불가(126791).
    """
    held = [c for c in company.certifications if c]
    branches = _target_branches(line) or [line]
    fit: tuple[str, str] | None = None
    mixed: str | None = None
    aspiring: list[str] = []

    def seeking(branch: str) -> str | None:
        """이 갈래가 회사가 이미 가진 인증으로 「진입 · 전환하려는」 기업을 찾으면 그 인증."""
        return next((c for c in held if any(_aspiring_flags(branch, c))), None)

    for cert in held:
        flags = _aspiring_flags(line, cert)
        if not flags:
            continue
        if not any(flags):
            if fit is None:
                # 「사회적기업으로 진입하고자 하는 여성기업」 — 여성기업이 맞아도 같은 갈래가 사회적기업이 아닌 기업을
                # 찾으므로 맞는 갈래가 아니다(31차 마지막 검토 — 거짓 가능). 그런 갈래뿐이면 확인 필요.
                own = [b for b in branches if _has_cert(b, cert)]
                clean = next((b for b in own if seeking(b) is None), None)
                if clean is not None:
                    fit = (cert, clean)
                elif mixed is None:
                    mixed = seeking(own[0]) if own else cert
        elif all(flags):
            aspiring.append(cert)
        elif mixed is None:
            mixed = cert
    if fit is None and mixed is None and not aspiring and use_category:
        # 대상 줄에 없고 분류 이름(`trgetNm`)에만 있는 인증 — 대상 줄 전체를 한 갈래로 본다.
        category = next((c for c in held if c in (program.target or "")), None)
        if category:
            forms = sorted({m.group(0) for m in _ORG_FORM_RE.finditer(line)} - {category})
            if forms:
                # 분류 이름에만 「사회적기업」이 있고 대상 줄은 마을기업 · 협동조합 같은 다른 조직 형태를 찾는다(32차 R31-05)
                return _rule(
                    "BIZ-TARGET", "대상 요건", "CHECK", source,
                    # 사실만 — 「비영리 법인 제외」도 「비영리를 찾습니다」로 거꾸로 읽혔다(33차 R32-10)
                    f"공고 분류에는 「{category}」이(가) 있지만 대상 줄에 「{' · '.join(forms)}」이(가) 적혀 있습니다 — 공고 원문에서 확인하세요"
                    f"(「{line.strip()[:80]}」).",
                )
            fit = (category, line)
    if fit is not None:
        cert, branch = fit
        if _DESIGNATION_TITLE_RE.search(program.title or ""):
            # 지정 · 인증을 주는 공고 — 이미 그 지위인 회사가 대상인지 원문을 봐야 한다(126516 · 분명하지 않으면 확인 필요).
            return _rule(
                "BIZ-TARGET", "대상 요건", "CHECK", source,
                f"지정 · 인증을 주는 공고입니다 — 이미 「{cert}」인 회사가 대상인지 공고 원문에서 확인하세요.",
            )
        return _target_pass(program, company, full_line, cert if _has_cert(branch, cert) else "", source,
                            f"대상 요건의 「{cert}」을(를) 우리 회사가 갖고 있습니다.", branch=branch)
    if mixed is not None:
        # 「사회적기업, (예비)사회적기업으로 진입하고자 하는 일반 기업」 — 한 줄에 두 뜻. 분명하지 않으면 확인 필요.
        return _rule(
            "BIZ-TARGET", "대상 요건", "CHECK", source,
            f"대상 요건 일부는 아직 「{mixed}」이(가) 아닌 기업을 찾습니다 — 공고 원문에서 확인하세요(「{line.strip()[:80]}」).",
        )
    if aspiring:
        cert = aspiring[0]
        if all(any(any(_aspiring_flags(b, c)) for c in aspiring) for b in branches):
            # 「(예비)사회적기업으로 진입하고자 하는 일반 기업」 — 이미 그 지위인 회사는 대상이 아니다(126791 · 분명하면 불가).
            return _rule(
                "BIZ-TARGET", "대상 요건", "FAIL", source,
                f"공고는 아직 「{cert}」이(가) 아닌 기업을 찾습니다(「{line.strip()[:80]}」) — 우리 회사는 이미 그 지위입니다.",
            )
        return _rule(
            "BIZ-TARGET", "대상 요건", "CHECK", source,
            f"공고는 아직 「{cert}」이(가) 아닌 기업이나 다른 조건의 기업을 찾습니다 — 다른 조건은 회사 자료로 가리지 못했으니 공고 원문에서 확인하세요"
            f"(「{line.strip()[:80]}」).",
        )
    return None


def _target_pass(program: SupportProgram, company, full_line: str, matched: str, source: str, reason: str,
                 *, branch: str | None = None) -> EligibilityResult:
    """맞은 요건 밖에 **규칙이 읽지 못한 요건**이 남았으면 「확인 필요」 + 맞은 갈래 원문(30차 §3-E).

    못 읽은 조건은 **대상 줄 전체**에서 찾는다 — 「본사 또는 공장」처럼 구 안의 「또는」에서 갈래를 잘라 뒤 조건(관내 ·
    이전)을 버리지 않게(31차 R30-05). 인용은 맞은 갈래 그대로(맞은 낱말이 대상 줄에 없으면 대상 줄 전체)."""
    branches = _target_branches(full_line) or [full_line]
    if branch is None:
        branch = next((b for b in branches if matched and matched in b), " ".join(branches))
    # 위치 조건(세부 지역 · 지역 이전)은 「본사 또는 공장」처럼 갈래를 가로지르므로 대상 줄 전체에서, 나머지는 맞은 갈래에서만 본다
    # (32차 R31-07 — 다른 갈래의 조건으로 맞은 갈래를 내리고 인용이 어긋났다 · 126235).
    location = [t for t in _unread_terms(full_line, company) if t in _LOCATION_TERMS]
    others = [t for t in _unread_terms(branch, company) if t not in _LOCATION_TERMS]
    unread = location + others
    if unread:
        outside = any(t not in _unread_terms(branch, company) for t in location)
        # 공통 꼬리를 붙인 갈래는 원문에 그대로 있는 글이 아니다 — 인용은 대상 줄 전체(R32-02)
        quote = full_line if outside or branch not in full_line else branch
        return _rule(
            "BIZ-TARGET", "대상 요건", "CHECK", source,
            f"{reason.rstrip('.')}. 다만 대상 요건에 회사 자료로 가리지 못한 조건({' · '.join(unread)})이 있습니다 — 「{quote.strip()[:100]}」",
        )
    return _rule("BIZ-TARGET", "대상 요건", "PASS", source, reason)


def _biz_period(program: SupportProgram, today: date) -> EligibilityResult:
    if program.apply_period_kind in ("always_open", "until_budget"):
        return _rule(
            "BIZ-PERIOD", "접수 기간", "PASS",
            f"접수 기간 {program.apply_period_text or '(원문 없음)'}",
            "상시·예산 소진 시까지 접수합니다. 조기 마감 여부만 공고 원문에서 확인하세요.",
        )
    if program.apply_end is None:
        return _rule(
            "BIZ-PERIOD", "접수 기간", "CHECK",
            f"접수 기간 {program.apply_period_text or '(원문 없음)'}",
            "접수 종료일을 읽지 못했습니다. 공고 원문에서 확인하세요.",
        )
    if program.apply_end < today:
        return _rule(
            "BIZ-PERIOD", "접수 기간", "FAIL",
            f"접수 종료 {program.apply_end}", "접수가 이미 끝났습니다.",
        )
    return _rule(
        "BIZ-PERIOD", "접수 기간", "PASS",
        f"접수 종료 {program.apply_end}", f"{program.apply_end}까지 접수합니다.",
    )


def _biz_role(program: SupportProgram) -> EligibilityResult | None:
    haystack = f"{program.summary or ''} {' '.join(program.requirement_sentences)}"
    roles = [label for word, label in _ROLE_WORDS if word in haystack]
    if not roles:
        return None
    return _rule(
        "BIZ-ROLE", "회사가 맡을 역할", "PASS",
        "요약문에서 찾은 낱말", " · ".join(dict.fromkeys(roles)),
    )


# --------------------------------------------------------------------------
# 판정 v2 — **공고문 조항으로** 판정한다 (0924.md §4-A-4 · ISSUE-096)
#
# 요약문만 볼 때는 거의 모두 「확인 필요」였다. 기준 답안과 견주면 1순위가 앱 66위,
# 불가인 것이 27위 「우선 검토」였다. 조건은 공고문에만 있다 — 그것을 읽고 나서의 규칙이
# 아래 아홉이다. 결과 모양은 나라장터와 같다(`EligibilityResult`).
#
# 규율 하나: **못 찾은 조항은 「없음」이 아니라 「확인 필요」다.** 근거 없이 「불가」를 내면
# 담당자가 그 공고를 아예 못 보게 된다 — 그것이 가장 나쁜 고장이다.
# --------------------------------------------------------------------------

#: 회사가 «될 수» 없는 법인격·지정 형태. 인증·지정을 받아야만 되는 것들이다.
#: 공고가 이 중 하나만 대상으로 하면, 회사가 그것을 갖고 있지 않은 한 신청할 수 없다.
#: 대상 목록 속 「기업」 한 낱말(쉼표 · 가운뎃점으로 나열) — 「10인 이상 기업, 공공기관, …」(34차 R33-D4).
_GENERIC_COMPANY_RE = re.compile(r"(?<![가-힣])(?:중소\s*)?기업\s*[,，·ㆍ]|[,，·ㆍ]\s*(?:중소\s*)?기업(?![가-힣])")

_CORPORATE_FORMS: tuple[str, ...] = (
    "사회적기업", "예비사회적기업", "사회적협동조합", "마을기업", "자활기업",
    "사회연대경제기업", "비영리법인·단체", "유치기업", "1인창조기업",
)

#: **소상공인은 법인격이 아니라 규모다** (0925 §4-A-3 · 소상공인기본법 제2조).
#:
#: 8차는 「소상공인만 대상」을 조직 형태로 보고 **불가** 7건을 냈다. 근거 없는 확정이었다 —
#: 회사가 소상공인인지 아닌지는 **상시근로자 수**로 정해지고, 그 수는 아직 미입력이다.
SMALL_BUSINESS_LIMITS: dict[str, int] = {"제조업 등": 10, "그 밖": 5}
SMALL_BUSINESS_UNLOCK = "회사자료 › 회사 프로필의 「상시 근로자 수」를 적으면 판정할 수 있습니다"

#: 회사 인증이 덮는 형태. 「사회연대경제기업」은 사회적기업·마을기업 등을 아우르는 상위 이름이다.
_FORM_COVERED_BY: dict[str, tuple[str, ...]] = {
    "사회적기업": ("사회적기업",),
    "예비사회적기업": ("예비사회적기업",),
    "사회연대경제기업": ("사회적기업", "예비사회적기업", "마을기업", "사회적협동조합", "자활기업"),
    "마을기업": ("마을기업",),
    "사회적협동조합": ("사회적협동조합",),
    "자활기업": ("자활기업",),
    "비영리법인·단체": ("비영리법인", "비영리단체"),
    "유치기업": ("유치기업",),
    "1인창조기업": ("1인창조기업",),
    "소상공인": ("소상공인",),
}

#: 인원 요건의 예외를 받을 수 있는 회사 인증. 공고문이 「사회적기업 등은 예외」라고 적는다.
_WAIVER_CERTIFICATIONS = ("사회적기업", "예비사회적기업", "벤처기업", "혁신형")
#: 예외에 **조건이 붙은** 꼴 — 「지침상 인정 요건 충족 시 10인 미만 기업도 참여 가능」(125426). 인증만으로 예외에 든다고 닫지 않는다.
_CONDITIONAL_WAIVER_RE = re.compile(r"충족\s*시|인정\s*요건|지침|요건을\s*갖춘|경우에\s*한")

#: 「회사가 제공자로 들어가는」 역할. 신청 주체가 못 되어도 여기로는 들어간다.
_INDIRECT_ROLES: dict[str, str] = {
    "supplier": "공급기업",
    "pilot_supplier": "실증공급기업",
    "tech_partner": "기술기업",
}
#: 신청 주체가 되는 쪽. 이 둘이 함께 있으면 «두 축 구조»다 — 도입기업이 신청하고 공급기업이 수행한다.
_APPLICANT_ROLES: dict[str, str] = {"adopter": "도입기업", "demand": "수요기업"}

#: 「주관기관 모집」류 — 기업 지원사업이 아니라 **운영기관**을 뽑는 공고다.
_OPERATOR_CALL_RE = re.compile(r"(주관기관|운영기관|수행기관|전문기관|관리기관)\s*(?:공개)?\s*모집")


def is_operator_call(program: SupportProgram) -> bool:
    """사업을 운영할 기관을 뽑는 공고인가(제목) — 「수행기관 모집(매출)」 갈래(37차 D5 · 실무 문서 §4.2)."""
    return bool(_OPERATOR_CALL_RE.search(program.title or ""))

#: 소재 요건에서 「전라남도」는 통합 이후 해석이 갈린다 (0924 §2).
#: 광주 북구가 드는지는 **사람이 센터에 확인할 일**이다 — 앱은 확정하지 않는다.
MERGED_REGION_NOTE = "전남광주 통합 이후 「전라남도 소재」에 광주가 드는지 해석 확인 필요"
MERGED_REGION_UNLOCK = "전남사회적경제통합지원센터(061-276-1333)에 소재 요건 해석을 확인하면 판정할 수 있습니다"

#: 「제조업이어야 한다」처럼 회사 업종과 어긋나는 소재·업종 요건에 붙는 말.
LOCATION_UNLOCK = "지점·사업장을 그 지역에 두면 가능합니다"


def _region_of_agency(agency: str | None) -> str | None:
    """소관기관 이름에서 시·도를 읽는다. 중앙부처면 None(= 전국)."""
    if not agency:
        return None
    from app.services import bizinfo_service

    tags = bizinfo_service.region_tags_of(agency)
    return tags[0] if tags else None


def _executing_region(program: SupportProgram) -> tuple[str, str] | None:
    """**수행기관**이 다른 시·도의 기관인가 (0925 §4-A-4). `(지역, 기관이름)` 또는 None.

    「경북창조경제혁신센터」·「제주창조경제혁신센터」·「○○테크노파크」가 수행하는 사업은
    그 지역 기업을 위한 것인 경우가 많은데, 소관기관은 중앙부처라 지금 규칙으로는 안 걸렸다.

    **공고명이 그 지역을 함께 말할 때만** 센다. 그러지 않으면 「서울창조경제혁신센터」가
    운영하는 전국 사업(민관협력 오픈이노베이션)까지 서울 사업으로 읽힌다 — 실제로 그 공고는
    전국 창업기업이 대상이다.
    """
    name = program.executing_agency
    if not name:
        return None
    region = _region_of_agency(name)
    if not region:
        return None
    from app.services import bizinfo_service

    if region not in bizinfo_service.region_tags_of(program.title):
        return None
    return region, name


def _company_forms(company) -> set[str]:
    """회사가 가진 형태. 인증 목록에서 읽는다 — 지어내지 않는다."""
    text = " ".join(company.certifications)
    return {form for form, needles in _FORM_COVERED_BY.items() if any(n in text for n in needles)}


def _location_pass_reason(alias: str, mine: str, where: str | None = None) -> str:
    """소재 가능 문장. 「광주광역시」 요구는 회사 주소가 옛 광주 지역일 때만 — 「회사 주소(북구)가 옛 광주광역시 지역이라 맞습니다」.

    43차 BIZ-16 — 예전 글 「(「광주광역시」는 전남광주에 듭니다)」는 논리가 뒤집혀 있었다(요구 지역이 회사 지역 안에 든다는 말)."""
    if where:
        return f"공고가 「{alias}」 소재를 요구합니다 — 회사 주소({where})가 옛 광주광역시 지역이라 맞습니다."
    same = f"(회사 소재 {mine})" if alias != mine else ""
    return f"공고가 「{alias}」 소재를 요구합니다 — 회사 소재가 거기에 있어 맞습니다{same}."


def _role_limited_location(rule: EligibilityResult, requirements) -> EligibilityResult:
    """주관기관 자리에만 걸린 소재 요건은 「불가」로 닫지 않는다 — 공동 · 참여 자리가 따로 있다(36차 R35-DV-03 · 127025)."""
    if rule.status != "FAIL":
        return rule
    limited = next((c for c in requirements.of("location") if c.detail.get("role_limited") and c.source_text == rule.source), None)
    if limited is None:
        return rule
    role = limited.detail.get("role") or "주관기관"
    return _rule(
        rule.rule_id, rule.label, "CHECK", rule.source,
        f"{rule.reason} 다만 이 소재 요건은 {role} 자리에만 걸립니다 — 공동 · 참여 자리로 신청할 수 있는지 공고 원문에서 확인하세요.",
    )


def _biz_location(requirements, program, company) -> EligibilityResult:
    """BIZ-LOCATION — **공고문의 소재 요건** vs 회사 소재 (0924 §4-A-4)."""
    clauses = requirements.of("location")
    mine = company.location_region
    bound = requirements.of("operator_region")
    operator = _region_of_agency(program.executing_agency)
    if bound and not clauses and operator and mine and operator != mine:
        # 「지역정보보호지원센터가 속한 지역기업을 지원」 + 수행기관 인천테크노파크(123800) — 공고명이 지역을 말하지 않아도 그 지역
        # 기업 대상이다. 지역 이름을 직접 쓰지 않아 불가로 닫지 않는다(10-10 중소기업 확인서 감사). 전국 기관이면 지역센터로 신청한다.
        return _rule(
            "BIZ-LOCATION", "소재 요건", "CHECK", bound[0].source_text,
            f"수행기관({program.executing_agency})이 속한 지역 기업을 지원하는 공고입니다 — 회사 소재는 {mine}이라 대상인지 공고 원문에서 확인하세요.",
        )
    if not clauses:
        # 공고문을 읽었는데 소재 요건이 없다. 태그가 다른 지역을 가리키면 확인 필요로 둔다.
        tags = [t for t in program.region_tags if t]
        if tags and mine and mine not in tags:
            return _rule(
                "BIZ-LOCATION", "소재 요건", "CHECK", f"지역 태그 {' · '.join(tags)}",
                f"공고문에서 소재 요건을 찾지 못했습니다. 지역 표시는 {', '.join(tags)}이고 회사 소재는 {mine}입니다.",
            )
        # **소관기관이 다른 시·도면 그 지역 기업을 위한 사업일 수 있다.**
        #
        # 기업마당 해시태그는 지자체 사업에도 열일곱 시·도를 전부 달아 놓는 경우가 많아
        # (실측: 경북·강원 사업의 태그에 전국이 들어 있었다) 태그로는 가릴 수 없다.
        # 소관기관 이름은 지어낸 값이 아니라 원문 필드다.
        agency_region = _region_of_agency(program.agency)
        if agency_region and mine and agency_region != mine:
            return _rule(
                "BIZ-LOCATION", "소재 요건", "CHECK", f"소관기관 {program.agency}",
                f"공고문에 소재 제한 문장은 없지만 소관기관이 {program.agency}입니다."
                f" 회사 소재는 {mine}이라 그 지역 기업 대상인지 공고 원문에서 확인하세요.",
            )
        # 통합특별시 안에서도 **통합 전 전남 · 광주** 사업일 수 있다 — 「전남형」 사업명이면 옛 광주 주소 회사는
        # 대상인지 해석이 갈린다(125345 기준 답안 「소재 해석 확인」 · 35차). 회사 주소로 옛 지역을 모르면 건드리지 않는다.
        old_side = _old_region_of_program(program)
        if mine == "전남광주" and old_side and company.location_old_region and old_side != company.location_old_region:
            side_text = "옛 전라남도" if old_side == "전남" else "옛 광주광역시"
            mine_text = "옛 광주광역시" if company.location_old_region == "광주" else "옛 전라남도"
            return _rule(
                "BIZ-LOCATION", "소재 요건", "CHECK", f"수행기관 {program.executing_agency or program.agency}",
                f"공고문에 소재 제한 문장은 없지만 {side_text} 쪽 사업으로 보입니다(사업명 「…형」). 회사 주소는 {mine_text} 지역이라"
                " 대상인지 공고 원문 · 운영기관에 확인하세요.",
            )
        # **수행기관**도 같은 뜻이다 (0925 §4-A-4). 공고명이 그 지역을 함께 말할 때만 센다.
        executing = _executing_region(program)
        if executing and mine and executing[0] != mine:
            return _rule(
                "BIZ-LOCATION", "소재 요건", "CHECK", f"수행기관 {executing[1]}",
                f"공고문에 소재 제한 문장은 없지만 수행기관이 {executing[1]}이고 공고명도"
                f" 「{executing[0]}」을 말합니다. 회사 소재는 {mine}이라 그 지역 기업 대상인지"
                " 공고 원문에서 확인하세요.",
            )
        return _rule(
            "BIZ-LOCATION", "소재 요건", "PASS", "공고문 원문",
            "공고문에서 소재를 제한하는 문장을 찾지 못했습니다 — 전국 대상으로 봅니다.",
        )
    if not mine:
        return _rule(
            "BIZ-LOCATION", "소재 요건", "CHECK", clauses[0].source_text,
            "공고문이 소재를 제한하는데 회사 소재지가 아직 없습니다.",
            "회사자료에 소재지를 적으면 판정할 수 있습니다",
        )
    # 「우대」 소재는 요건이 아니다(34차 §3-A-3 · 122910) — 우대뿐이면 나머지 판정을 막지 않고 확인 필요로 둔다.
    required = [c for c in clauses if not c.detail.get("preferred")]
    if not required:
        return _rule(
            "BIZ-LOCATION", "소재 요건", "CHECK", clauses[0].source_text,
            f"공고문의 「{clauses[0].detail.get('alias') or '지역'}」 소재는 우대 조건으로 보입니다(요건이 아님) — 공고 원문에서 확인하세요.",
        )
    clauses = required
    old = next((c for c in clauses if c.detail.get("old_region")), None)
    if old is not None and mine == "전남광주" and len({c.detail["old_region"] for c in clauses if c.detail.get("old_region")}) > 1:
        return _rule(
            "BIZ-LOCATION", "소재 요건", "CHECK", old.source_text,
            "공고문이 옛 광주 · 옛 전남 지역을 함께 말합니다 — 어느 쪽 요건인지 공고 원문에서 확인하세요.",
        )
    if old is not None and mine == "전남광주":
        # 「전남광주통합특별시 내 옛 전라남도 지역」 — 첫 별칭(통합특별시)에서 멈추면 광주 회사도 「맞음」이었다(126999 · 35차 R34S-04).
        want = str(old.detail["old_region"])
        want_text = "옛 광주광역시" if want == "광주" else "옛 전라남도"
        have = company.location_old_region
        if have is None:
            return _rule(
                "BIZ-LOCATION", "소재 요건", "CHECK", old.source_text,
                f"공고가 {want_text} 지역을 요구합니다 — 회사 주소로 옛 광주 · 전남 어느 쪽인지 가리지 못했습니다. 공고 원문과 주소를 확인하세요.",
            )
        have_text = "옛 광주광역시" if have == "광주" else "옛 전라남도"
        # 옛 지역이 다르더라도 「이전 예정」 · 「도내/외 모두」 · 「전국 소재」 갈래가 있으면 불가로 닫지 않는다(36차 R35-RULE-04)
        side = next((c for c in clauses if c.detail.get("mixed") or c.detail.get("outside_ok") or c.detail.get("relocation")), None)
        if have != want and side is not None:
            why = (
                "역할(주관 · 참여)에 따라 소재 요건이 다릅니다(「전국 소재」 갈래가 함께 있음)" if side.detail.get("mixed")
                else "그 지역으로 옮기는(이전) 기업도 대상입니다" if side.detail.get("relocation")
                else "프로그램마다 소재 요건이 다릅니다(「도내/외」 · 도외 기업 갈래가 있음)"
            )
            return _rule(
                "BIZ-LOCATION", "소재 요건", "CHECK", old.source_text,
                f"공고가 {want_text} 지역을 요구하고 회사 주소는 {have_text} 지역이지만 {why} — 우리 회사가 들어갈 갈래가 있는지 공고 원문에서 확인하세요.",
            )
        if have == want:
            return _rule(
                "BIZ-LOCATION", "소재 요건", "PASS", old.source_text,
                f"공고가 {want_text} 지역을 요구합니다 — 회사 주소가 {have_text} 지역이라 맞습니다.",
            )
        return _rule(
            "BIZ-LOCATION", "소재 요건", "FAIL", old.source_text,
            f"공고가 {want_text} 지역을 요구하는데 회사 주소는 {have_text} 지역입니다.",
            LOCATION_UNLOCK,
        )
    # 「광주시」(광역시 줄임말)는 경기도 광주시와 겹친다 — 소관 · 수행기관 지역으로 가린다(37차 recheck29 R36-RV-05).
    ambiguous = [c for c in clauses if c.detail.get("ambiguous")]
    if ambiguous and mine in ("전남광주", "경기"):
        side = _region_of_agency(program.executing_agency) or _region_of_agency(program.agency)
        if side is None:
            return _rule(
                "BIZ-LOCATION", "소재 요건", "CHECK", ambiguous[0].source_text,
                "공고문의 「광주시 소재」가 광주광역시인지 경기도 광주시인지 소관 · 수행기관으로 가리지 못했습니다 — 공고 원문에서 확인하세요.",
            )
        if side == "경기":
            # 경기도 광주시다 — 광역 요건이 아니라 그 시의 요건으로 본다(아래 시 · 군 판정).
            # 광역 표시만 걷고 이전 · 도내외 · 전국 갈래 단서는 남긴다(38차 RULES-04 — 통째로 바꾸면 갈래가 사라져 불가가 됐다).
            clauses = [
                c.model_copy(update={"detail": {
                    **{k: v for k, v in c.detail.items() if k not in ("region", "alias", "metro_short", "ambiguous")},
                    "city": "광주시(경기)", "site": c.detail.get("site", "소재"),
                }}) if c.detail.get("ambiguous") else c
                for c in clauses
            ]
    # 「전라남도 · 전남」 요건은 통합 이후 해석이 갈린다 — 확정하지 않는다.
    merged = [c for c in clauses if c.detail.get("alias") in ("전라남도", "전남")]
    matched = [c for c in clauses if c.detail.get("region") == mine and c.detail.get("alias") not in ("전라남도", "전남")]
    if matched:
        clause = matched[0]
        alias = str(clause.detail.get("alias") or mine)
        if alias in ("광주광역시", "광주"):
            # 43차 BIZ-16 — 「광주광역시」 요구는 옛 광주 지역(5개 구)만이다. 회사의 옛 지역을 보지 않아 옛 전남 주소 회사(여수)도
            # 「가능」이었다(「전라남도」는 확인 필요로 두면서 비대칭 · H2 와 같은 꼴).
            old = getattr(company, "location_old_region", None)
            if old != "광주":
                where = getattr(company, "location_district", None) or old
                why = (
                    f"회사 주소({where})는 옛 전라남도 지역입니다 — 통합 뒤 「광주광역시」 소재 요건에 드는지 공고 원문에서 확인하세요"
                    if old == "전남"
                    else "회사 주소가 옛 광주광역시 지역(5개 구)인지 모릅니다 — 회사 프로필 주소(구)를 적거나 공고 원문에서 확인하세요"
                )
                return _rule("BIZ-LOCATION", "소재 요건", "CHECK", clause.source_text, f"공고가 「{alias}」 소재를 요구합니다. {why}.")
            return _rule(
                "BIZ-LOCATION", "소재 요건", "PASS", clause.source_text,
                _location_pass_reason(alias, mine, getattr(company, "location_district", None) or "광주"),
            )
        return _rule(
            "BIZ-LOCATION", "소재 요건", "PASS", clause.source_text,
            # 불가 문장(「…를 요구하는데 회사 소재는 …입니다」)과 한 글자만 달라 불가로 읽혔다 — 맞는다고 적는다(32차 어려운 글)
            _location_pass_reason(alias, mine),
        )
    if merged:
        return _rule(
            "BIZ-LOCATION", "소재 요건", "CHECK", merged[0].source_text,
            f"공고문이 「전라남도 소재」를 요구합니다. {MERGED_REGION_NOTE}.",
            MERGED_REGION_UNLOCK,
        )
    # 역할마다 · 프로그램마다 소재가 다르다 — 「경북 소재 제조기업과 전국소재 지원 기업의 컨소시엄」(120334) ·
    # 「도내/외 기업」(126827). 한쪽 갈래로 들어갈 수 있으니 불가로 닫지 않는다(34차 §3-A-3).
    branch = next((c for c in clauses if c.detail.get("mixed") or c.detail.get("outside_ok") or c.detail.get("relocation")), None)
    if branch is not None:
        why = (
            "역할(주관 · 참여)에 따라 소재 요건이 다릅니다(「전국 소재」 갈래가 함께 있음)" if branch.detail.get("mixed")
            else "그 지역으로 옮기는(이전) 기업도 대상입니다" if branch.detail.get("relocation")
            else "프로그램마다 소재 요건이 다릅니다(「도내/외」 · 도외 기업 갈래가 있음)"
        )
        return _rule(
            "BIZ-LOCATION", "소재 요건", "CHECK", branch.source_text,
            f"공고문이 「{branch.detail.get('alias') or branch.detail.get('city') or '지역'} 소재」를 말하지만 {why} — 우리 회사가 들어갈 갈래가 있는지 공고 원문에서 확인하세요.",
        )
    # 시·군 요건 — 회사 주소에 그 이름이 없으면 불가다.
    cities = [c for c in clauses if c.detail.get("city")]
    if cities:
        return _rule(
            "BIZ-LOCATION", "소재 요건", "FAIL", cities[0].source_text,
            f"공고문이 「{cities[0].detail['city']} 소재」를 요구하는데 회사 소재는 {mine}입니다.",
            LOCATION_UNLOCK,
        )
    clause = clauses[0]
    return _rule(
        "BIZ-LOCATION", "소재 요건", "FAIL", clause.source_text,
        f"공고문이 「{clause.detail.get('alias') or '다른 지역'} 소재」를 요구하는데 회사 소재는 {mine}입니다.",
        LOCATION_UNLOCK,
    )


#: 통합 전 전남 · 광주 쪽 사업의 표시 — 사업명 「전남형 · 광주형」. 수행기관 이름(「전남인력개발원」)은 쓰지 않는다 — 전국 사업을
#: 지역 기관이 운영하는 경우가 많다(122145 미래내일 일경험 · 기준 답안 「가능」).
_OLD_SIDE_TITLE_RE = re.compile(r"(전남|광주)형")


def _old_region_of_program(program) -> str | None:
    """사업이 통합 전 어느 쪽 것인가 — 「전남」 · 「광주」 · 모르면 None."""
    title = _OLD_SIDE_TITLE_RE.search(program.title or "")
    if title:
        return "광주" if title.group(1) == "광주" else "전남"
    return None


def _biz_org_type(requirements, company) -> EligibilityResult | None:
    """BIZ-ORG-TYPE — 조직 형태. 회사가 «될 수» 없는 형태만 불가로 본다."""
    every = requirements.of("org_type")
    clauses = [c for c in every if not c.detail.get("conditional")]
    conditional = [c for c in every if c.detail.get("conditional")]
    wanted = {c.detail.get("org_type") for c in clauses} & set(_CORPORATE_FORMS)
    if not wanted:
        # 「공공기관·대학·연구기관」만 나온 것은 공동 참여 기관 이야기다 — 회사 자격 요건이 아니다.
        return None
    mine = _company_forms(company)
    hit = sorted(f for f in wanted if set(_FORM_COVERED_BY.get(f, ())) & {*mine, *company.certifications} or f in mine)
    source = next((c.source_text for c in clauses if c.detail.get("org_type") in wanted), "")
    if hit:
        return _rule(
            "BIZ-ORG-TYPE", "조직 형태", "PASS", source,
            f"공고문이 요구하는 형태 중 「{hit[0]}」을(를) 회사가 갖고 있습니다.",
        )
    # 「기업, 공공기관, 지방공기업, 비영리단체, 비영리법인 등」 — 여럿을 나열한 목록이다(34차 R33-D4 · 122145). 목록에 「기업」이
    # 있으면 회사(주식회사)가 대상에 든다 — 비영리 하나만 남겨 「그것만 대상」이라 단정하지 않는다. 사회연대경제 형태만 나열한
    # 목록(마을기업 · 협동조합 · 사회적기업 …)은 그 형태가 아닌 회사에게 여전히 분명한 불가다.
    generic = next((c.source_text for c in clauses if _GENERIC_COMPANY_RE.search(c.source_text)), None)
    if generic is not None:
        return _rule(
            "BIZ-ORG-TYPE", "조직 형태", "PASS", generic,
            "공고문 대상 목록에 「기업」이 있습니다(다른 형태와 함께 나열) — 우리 회사가 대상에 듭니다.",
        )
    # 「→ 사회적기업이면서 참여대상에 해당하는 기업은 … 경우에 한하여 참여 가능」(126473) — 회사 형태에 조건이 붙은 길이 따로 있다.
    # 대상 목록에는 없어도 분명한 불가가 아니다(기준 답안 「센터에 함께 확인」 · 35차).
    path = next(
        (c for c in conditional
         if (f := c.detail.get("org_type")) and (set(_FORM_COVERED_BY.get(f, ())) & {*mine, *company.certifications} or f in mine)),
        None,
    )
    if path is not None:
        return _rule(
            "BIZ-ORG-TYPE", "조직 형태", "CHECK", path.source_text,
            f"공고문 대상 목록({' · '.join(sorted(wanted))})에는 회사 형태가 없지만, 「{path.detail['org_type']}」에 조건을 붙여 따로 받는 줄이 있습니다"
            " — 우리 회사가 그 조건에 드는지 공고 원문 · 운영기관에 확인하세요.",
        )
    return _rule(
        "BIZ-ORG-TYPE", "조직 형태", "FAIL", source,
        f"공고문이 {' · '.join(sorted(wanted))}만 대상으로 하는데 회사는 그 형태가 아닙니다.",
        f"{sorted(wanted)[0]} 지정을 받으면 가능합니다",
    )


#: 「지원 대상」 칸이 이 낱말 하나면, 신청하려면 **그 확인서·지정**이 있어야 한다.
#:
#: 기업마당 `trgetNm` 은 몇 가지 값만 쓴다(실측 1,620건: 중소기업 1,238 · 소상공인 226 ·
#: 창업벤처 97 · 사회적기업 41 · 장애인기업 8 · 여성기업 5 · 마을기업 1 · 협동조합 1).
#: 그중 **확인서로 정해지는 것**만 여기 둔다 — 「중소기업」·「소상공인」은 규모라 다른
#: 규칙(`_biz_small_business`·`_biz_headcount`)이 상시근로자 수로 판정한다.
_CERTIFIED_TARGETS: dict[str, str] = {
    "장애인기업": "장애인기업",
    "여성기업": "여성기업",
    "청년기업": "청년기업",
    "사회적기업": "사회적기업",
    "마을기업": "마을기업",
    "협동조합": "사회적협동조합",
}


def _biz_target_certification(program, company) -> EligibilityResult | None:
    """BIZ-TARGET-CERT — 대상이 **특정 인증 형태만**이다 (ISSUE-126 · prompt_05 §4-E-2).

    「2026년 장애인 창업 컨설팅지원 대상자 모집 공고」의 지원 대상은 `장애인기업` 하나다.
    회사의 보유 인증에 그것이 없으면 신청할 수 없는데, 14차까지는 이 사실이 판정에 들어오지
    않아 **57점 · 27위**로 목록 상단 가까이 있었다(기준 답안: 상위 30 밖).

    **불가로 닫지 않는다.** 확인서는 받을 수 있는 것이고, 회사가 이미 갖고 있는데 회사자료에
    안 적었을 수도 있다. 「확인 필요 — 회사 쪽」으로 두면 점수는 0.4 로 내려가고(0925 §4-A-1
    의 눈금), 「무엇이 있으면 열리는가」가 화면에 남는다.

    **갖고 있으면 아무 말도 하지 않는다** — 지금까지의 다른 규칙이 그대로 판정한다.
    """
    target = (program.target or "").strip()
    form = _CERTIFIED_TARGETS.get(target)
    if form is None:
        return None
    if any(form in (cert or "") for cert in company.certifications):
        return None
    return _rule(
        "BIZ-TARGET-CERT",
        "지원 대상",
        "CHECK",
        f"지원 대상: {target}",
        f"공고의 지원 대상이 「{target}」인데 회사자료의 보유 인증에 없습니다.",
        f"{form} 확인서가 있으면 가능합니다",
    )


#: 「○○ 기업」의 ○○ 가 이 낱말이면 **다른 업종**이다.
#:
#: `support_kinds.EXCLUDED_WORDS` 에서 **업종을 가리키는 것만** 골랐다. 저쪽에는 융자·보증
#: 같은 금융 수단과 박람회·경진대회 같은 행사 형태도 섞여 있는데, 그것들은 「업종」이 아니라
#: 「받는 것의 종류」라 여기 오면 안 된다.
_OTHER_INDUSTRY_WORDS: tuple[str, ...] = (
    "바이오", "의료기기", "임상", "섬유", "뷰티", "화장품", "식품", "FOOD", "푸드",
    "반도체", "조선", "해양", "에너지", "원전", "건설", "부동산", "게임", "반려동물",
    "이차전지", "공예", "서점", "관광", "음식", "농업", "어업", "축산", "전통시장",
    "무기체계", "부품국산화", "공방",
)

#: 「의료기기 개발 기업」·「식품제조ㆍ가공업체」처럼 **업종 + 기업**을 한 덩어리로 잡는다.
#: 사이에 12글자까지 허용한다 — 「바이오 산업 관련 중소ㆍ중견기업」이 실제 문장이다.
#: 「소재 공방」처럼 업종 낱말이 곧 대상 이름이면 뒤에 「기업」이 없어도 잡는다(10-31 최종 점검 · 127455 — 소재만 맞아 거짓 「가능」).
_OTHER_INDUSTRY_RE = re.compile(
    r"(" + "|".join(map(re.escape, _OTHER_INDUSTRY_WORDS)) + r")(?:[^\n]{0,12}?(?:기업|업체|기관|사업자|법인)|(?<=공방)(?![가-힣]))"
)


#: 「블록체인 기술 보유」 · 「AI 기술을 보유한」 · 「디지털헬스케어 관련 기술을 보유한」 — 분야 기술 보유 요건(34차 §3-A-6).
_SKILL_HELD_RE = re.compile(r"([가-힣A-Za-z]{2,10})\s*(?:관련\s*)?기술\s*(?:을\s*)?보유")
#: 분야가 아닌 앞말 — 「제품 또는 기술」 · 「구현 기술」 · 「숙련기술보유자」(사람)(34차 마지막 검토 · 실제 저장본 127035 · 126909 · 126786 · 123790).
_NOT_A_SKILL_FIELD = frozenset({"관련", "또는", "및", "구현", "숙련", "해당", "우수", "핵심", "원천", "자체", "보유", "기반"})
#: 「에이지테크 관련 기업」 — 분야가 회사 사업영역에 없으면 소재만 맞았다고 「가능」으로 닫지 않는다(34차 마지막 검토 · 126823).
_RELATED_FIELD_RE = re.compile(r"([가-힣A-Za-z]{2,12})\s*관련\s*(?:기업|업체)")
#: 「ITㆍSW 및 데이터센터 관련 기업」 — 「관련 · 기술」 앞의 나열 갈래 전부(35차 R34S-02 · 122609).
#: 나열 구분은 기호 · 띄어 쓴 「및 · 또는」 · 「와 · 과 + 띄어쓰기」만 — 글자 안의 「과 · 와 · 및」까지 구분으로 보면 띄어쓰기 없는 긴 줄에서
#: 되짚기가 지수로 늘어 목록 판정이 멈췄다(60자 15초 · 35차 마지막 검토).
_FIELD_SEP = r"\s*[·ㆍ,/]\s*|\s+(?:및|또는)\s+|(?:와|과)\s+"
_FIELD_LIST_RE = re.compile(r"((?:[가-힣A-Za-z]{2,12}(?:" + _FIELD_SEP + r"))+[가-힣A-Za-z]{2,12})\s*(?:관련\s*)?(?:기업|업체|기술)")
_FIELD_SPLIT_RE = re.compile(_FIELD_SEP)
#: 같은 뜻 낱말 — 분야를 회사 사업영역과 견줄 때 글자가 달라도 같은 것으로 본다.
_FIELD_SYNONYMS: tuple[tuple[str, ...], ...] = (
    ("AI", "인공지능", "AX"),
    ("SW", "소프트웨어", "S/W"),
    ("IT", "ICT", "정보통신"),
)


def _field_in(field: str, mine: str) -> bool:
    """분야 하나가 회사 사업영역에 있는가 — 같은 뜻 낱말 표로 견준다(AI = 인공지능 · SW = 소프트웨어 · IT = ICT)."""
    words = next((group for group in _FIELD_SYNONYMS if field.upper() in (w.upper() for w in group)), (field,))
    return any(w.lower() in mine.lower() for w in words)


def _listed_fields(sentence: str, end: int) -> list[str]:
    """`end` 에서 끝나는 「X · Y 및 Z」 나열 갈래 — 나열이 아니면 빈 목록."""
    for match in _FIELD_LIST_RE.finditer(sentence):
        if match.start() <= end <= match.end() + 4:
            return [f for f in _FIELD_SPLIT_RE.split(match.group(1)) if f and f not in _NOT_A_SKILL_FIELD]
    return []


def _biz_target_industry(program, profile_domains: tuple[str, ...]) -> EligibilityResult | None:
    """BIZ-TARGET-INDUSTRY — 대상이 **다른 업종의 기업**이다 (ISSUE-126 · prompt_05 §4-E-2).

    §4-E-2 는 인증 형태(장애인기업·여성기업…)를 말하지만, 같은 모양이 업종에도 있다.
    「2026년 AI 융합 에스테틱 의료기기 글로벌 사업화」의 대상 문장은 원문 그대로
    「전국 소재 AI 융합 에스테틱 **의료기기 개발 기업**」이다. 회사는 AI 교육·컨설팅·SaaS 라
    그 기업이 아닌데, 14차까지 이 사실이 판정에 들어오지 않았다.

    14차에 이 공고가 64위였던 것은 **다른 규칙의 거짓 양성 덕**이었다 — 「참여기업 모집」을
    개인 모집으로 읽어 점수를 깎고 있었다(ISSUE-125). 그 거짓 양성을 걷어내자 12위로
    올라왔다. 맞는 자리에 두려면 맞는 근거가 필요하다.

    **불가로 닫지 않는다.** 회사가 그 분야 일을 해 본 적이 있는데 회사자료에 안 적었을 수
    있다. 「확인 필요 — 회사 쪽」으로 두면 점수는 내려가고 「무엇이 있으면 열리는가」가 남는다.

    근거는 **대상 문장 원문**이다 — 기업마당이 공고문에서 뽑아 둔 「☞ 대상」 줄이다.
    """
    mine = " ".join(profile_domains)
    for sentence in program.requirement_sentences or ():
        skill = next((m for m in _SKILL_HELD_RE.finditer(sentence) if m.group(1) not in _NOT_A_SKILL_FIELD), None)
        if skill and any(_field_in(f, mine) for f in (_listed_fields(sentence, skill.end(1)) or [skill.group(1)])):
            skill = None
        if skill:
            # 「블록체인 기술 보유 및 해외 진출 역량이 있는 블록체인 중소기업」(126841) — 공고문 경로가 이 요건을 안 봐 거짓 「가능」이었다(34차 §3-A-6)
            return _rule(
                "BIZ-TARGET-INDUSTRY",
                "지원 대상",
                "CHECK",
                sentence,
                f"공고가 「{skill.group(0).strip()}」을(를) 요구하는데 회사 사업영역에 「{skill.group(1)}」이(가) 없습니다.",
                f"회사자료의 사업영역에 「{skill.group(1)}」이(가) 있으면 가능합니다",
            )
        related = next((m for m in _RELATED_FIELD_RE.finditer(sentence) if m.group(1) not in _NOT_A_SKILL_FIELD), None)
        if related and any(_field_in(f, mine) for f in (_listed_fields(sentence, related.end(1)) or [related.group(1)])):
            related = None
        if related:
            return _rule(
                "BIZ-TARGET-INDUSTRY",
                "지원 대상",
                "CHECK",
                sentence,
                f"공고가 대상으로 부르는 것은 「{related.group(0).strip()}」인데 회사 사업영역에 「{related.group(1)}」이(가) 없습니다.",
                f"회사자료의 사업영역에 「{related.group(1)}」이(가) 있으면 가능합니다",
            )
        match = _OTHER_INDUSTRY_RE.search(sentence)
        if match is None:
            continue
        industry = match.group(1)
        if industry in mine:
            return None
        return _rule(
            "BIZ-TARGET-INDUSTRY",
            "지원 대상",
            "CHECK",
            sentence,
            f"공고가 대상으로 부르는 것은 「{match.group(0).strip()}」인데 회사 사업영역에 「{industry}」이(가) 없습니다.",
            f"회사자료의 사업영역에 「{industry}」이(가) 있으면 가능합니다",
        )
    return None


_SMALL_BUSINESS_NOT_ONLY_RE = re.compile(
    r"중소|중견|(?<![가-힣])기업|소상공인\s*기본법|소상공인기본법|시행령|부당|불법|제재|위반"
    # 「소상공인 및 사회적기업」처럼 다른 형태와 함께 나열된 줄(35차 R34S-06)
    r"|사회적\s*기업|협동\s*조합|마을\s*기업|자활\s*기업|사회연대경제|비영리|대학|연구\s*기관|공공\s*기관|1인\s*창조"
)


def _biz_sme(requirements, company, today: date) -> EligibilityResult | None:
    """BIZ-SME — 공고문이 「중소기업」을 요구할 때 회사자료 준비 상태의 「중소기업(소상공인) 확인서」로 본다(10-10 담당자 결정).

    「가능」은 중소기업 **하나만** 요구하는 줄(`clean`)이 있을 때만 — 「… 중소기업 중 지역 전략산업 영위기업」처럼 같은 줄에 다른 조건이
    있으면 그 조건을 규칙이 못 읽었으니 확인 필요다(10-10 「가능」 좁히기). 「없음」 · 지난 유효기간도 불가로 닫지 않는다 — 받을 수 있다.
    """
    clauses = requirements.of("sme")
    if not clauses:
        return None
    clean = next((c for c in clauses if c.detail.get("clean")), None)
    qualified = next((c for c in clauses if c.detail.get("qualified")), None)
    source = (clean or clauses[0]).source_text
    state = eligibility_engine.sme_state(company, today)
    if state == "unknown":
        return _rule(
            "BIZ-SME", "중소기업 확인서", "CHECK", source,
            "공고가 「중소기업」을 요구합니다 — 회사자료 준비 상태의 중소기업(소상공인) 확인서가 아직 「모름」입니다.",
            SME_UNLOCK,
        )
    # 확인서를 받아도 같은 줄의 다른 조건 때문에 가능이 안 되는 공고에는 「발급받으면 가능」을 약속하지 않는다(10-10 검토)
    passable = clean is not None and qualified is None
    also = "" if passable else " 같은 줄에 규칙이 읽지 못한 조건도 있어 공고 원문을 함께 보세요."
    if state == "none":
        return _rule(
            "BIZ-SME", "중소기업 확인서", "CHECK", source,
            "공고가 「중소기업」을 요구하는데 회사자료 준비 상태에 중소기업(소상공인) 확인서가 「없음」입니다." + also,
            "중소기업(소상공인) 확인서를 발급받으면 가능합니다" if passable else None,
        )
    if state == "expired":
        return _rule(
            "BIZ-SME", "중소기업 확인서", "CHECK", source,
            f"공고가 「중소기업」을 요구하는데 중소기업(소상공인) 확인서 유효기간({company.sme_valid_until})이 지났습니다." + also,
            "중소기업(소상공인) 확인서를 새로 발급받으면 가능합니다" if passable else None,
        )
    if clean is None or qualified is not None:
        rest = (qualified.detail.get("rest") if qualified is not None else None) or next(
            (c.detail.get("rest") for c in clauses if c.detail.get("rest")), None
        )
        source = (qualified or clauses[0]).source_text
        return _rule(
            "BIZ-SME", "중소기업 확인서", "CHECK", source,
            "중소기업 요건은 확인서로 맞습니다. 다만 같은 줄에 규칙이 읽지 못한 조건이 있습니다"
            + (f" — 「{rest}」" if rest else "") + " — 공고 원문에서 확인하세요.",
        )
    return _rule(
        "BIZ-SME", "중소기업 확인서", "PASS", source,
        "공고가 「중소기업」을 요구하고 회사는 중소기업(소상공인) 확인서가 있습니다(회사자료 준비 상태).",
    )


#: 중소기업 확인서가 「모름」일 때 — 무엇을 적으면 판정되는가.
SME_UNLOCK: Final[str] = "회사자료 준비 상태에 중소기업(소상공인) 확인서를 적으면 판정할 수 있습니다"


def _biz_small_business(requirements, program, company, today: date) -> EligibilityResult | None:
    """BIZ-SMALL-BUSINESS — 「소상공인만 대상」은 **상시근로자 수**로 판정한다 (0925 §4-A-3).

    소상공인기본법 제2조: 광업·제조업·건설업·운수업은 상시근로자 10명 미만, **그 밖의 업종은
    5명 미만**. 회사는 소프트웨어 개발·교육이라 「그 밖」이다.

    회사 상시근로자 수가 **미입력**이면 「확인 필요」다 — 「소상공인이 아니다」라고 단정하지
    않는다. 8차가 그렇게 단정해 7건을 「불가」로 닫았다.
    """
    # 「중견 · 중소기업, 소상공인」 · 「중소기업 및 소상공인」처럼 함께 나열된 줄, 법 이름(「소상공인기본법 시행령」) ·
    # 제재 문장(「부당 · 불법행위 … 소상공인의」)은 「소상공인만 대상」이 아니다(34차 §3-A-7 · 126842 · 116741 · 117131 · 126980).
    listed = [c for c in requirements.of("org_type") if c.detail.get("org_type") == "소상공인"]
    only = [c for c in listed if not _SMALL_BUSINESS_NOT_ONLY_RE.search(c.source_text)]
    if listed and not only:
        return None  # 공고문 줄이 함께 나열이면 기업마당 분류(target) 대체로 다시 들어가지 않는다(35차 R34S-06)
    if not only and (program.target or "").strip() != "소상공인":
        return None
    limit = SMALL_BUSINESS_LIMITS["그 밖"]
    source = only[0].source_text if only else f"지원 대상 {program.target}"
    # 확인서 구분이 있으면 그것이 먼저다(10-10 담당자 결정 「구분도 적음」) — 소상공인 확인서는 정부가 확인한 사실이다
    if eligibility_engine.sme_state(company, today) == "valid" and company.sme_grade in ("소상공인", "중기업"):
        if company.sme_grade == "소상공인":
            return _small_business_pass(
                only, source, "소상공인만 대상이고 회사 중소기업(소상공인) 확인서 구분이 「소상공인」입니다.",
            )
        return _rule(
            "BIZ-SMALL-BUSINESS", "소상공인 여부", "FAIL", source,
            "소상공인만 대상인데 회사 중소기업(소상공인) 확인서 구분이 「중기업」입니다.",
        )
    if company.employee_count is None:
        return _rule(
            "BIZ-SMALL-BUSINESS", "소상공인 여부", "CHECK", source,
            f"소상공인만 대상인데 회사 상시 근로자 수가 아직 없습니다."
            f" 소상공인기본법은 그 밖의 업종을 상시근로자 {limit}명 미만으로 봅니다.",
            SMALL_BUSINESS_UNLOCK,
        )
    if company.employee_count < limit:
        return _small_business_pass(
            only, source, f"소상공인만 대상이고 회사는 상시근로자 {company.employee_count}명으로 {limit}명 미만입니다.",
        )
    return _rule(
        "BIZ-SMALL-BUSINESS", "소상공인 여부", "FAIL", source,
        f"소상공인만 대상인데 회사는 상시근로자 {company.employee_count}명으로 {limit}명 이상입니다.",
    )


#: 「소상공인」 줄의 머리(「지원대상 :」 · 글머리)와 「소상공인」을 지우고도 글이 남으면 다른 조건이 붙은 줄이다 —
#: 「위기 소상공인으로 선별되어 위기 알림톡을 받은 자」(121182) · 「디지털 취약계층 소상공인」(122273). 규칙이 못 읽는 조건이다.
_SMALL_BUSINESS_LABEL_RE = re.compile(
    r"^[^가-힣]*(?:[(\[]?\s*(?:지원|신청|모집|참여|참가|사업)\s*(?:대상|자격)\s*[)\]]?\s*[:：]?)?|소상공인|[^가-힣A-Za-z0-9]+"
)


def _small_business_pass(only, source: str, reason: str) -> EligibilityResult:
    """소상공인 여부가 맞을 때 — 같은 줄에 다른 조건이 붙었으면 「가능」으로 닫지 않는다(35차 · 「가능」은 대상 요건이 모두 가려질 때만)."""
    rest = _SMALL_BUSINESS_LABEL_RE.sub(" ", only[0].source_text).strip() if only else ""
    if rest:
        return _rule(
            "BIZ-SMALL-BUSINESS", "소상공인 여부", "CHECK", source,
            f"소상공인 여부는 맞습니다 — 같은 줄의 다른 조건(「{_shorten_quote(only[0].source_text)}」)은 공고 원문에서 확인하세요.",
        )
    return _rule("BIZ-SMALL-BUSINESS", "소상공인 여부", "PASS", source, reason)


def _shorten_quote(text: str, limit: int = 50) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _biz_headcount(requirements, company) -> EligibilityResult | None:
    """BIZ-HEADCOUNT — 고용 인원. 예외 문장이 있고 회사가 그 예외에 들면 가능이다."""
    clauses = [c for c in requirements.of("headcount") if c.detail.get("comparator") == "이상"]
    if not clauses:
        return None
    clause = clauses[0]
    need = clause.detail.get("count")
    # 인원을 직접 채웠으면 예외를 볼 필요가 없다 — 예외 검사가 앞서면 인증 있는 회사가 오히려 확인 필요로 떨어졌다(검토 10-10)
    if company.employee_count is not None and company.employee_count >= need:
        return _rule(
            "BIZ-HEADCOUNT", "고용 인원", "PASS", clause.source_text,
            f"「{need}인 이상」 요건이고 회사는 {company.employee_count}인입니다.",
        )
    waiver = requirements.of("headcount_waiver")
    covered = [c for c in _WAIVER_CERTIFICATIONS if any(c in cert for cert in company.certifications)]
    if waiver and covered:
        if _CONDITIONAL_WAIVER_RE.search(waiver[0].source_text):
            # 예외에 조건이 붙었다 — 인증 하나로 예외에 든다고 닫지 않는다(「가능」 좁히기 · 125426). 할 일은 공고 · 지침을
            # 읽는 것이라 열리는 조건(회사 쪽)을 달지 않는다 — 회사 쪽이면 「이번 주 할 일」에서 빠졌다(검토 10-10)
            reason = (
                f"「{need}인 이상」 요건에 예외가 있지만 조건이 붙어 있습니다 — 회사({covered[0]})가 그 조건을 갖췄는지"
                " 공고 원문 · 지침에서 확인하세요."
            )
            if company.employee_count is None:
                reason += f" 상시 근로자가 {need}인 이상이면 예외 없이 맞습니다(회사자료 › 회사 프로필에 적으면 판정)."
            return _rule("BIZ-HEADCOUNT", "고용 인원", "CHECK", waiver[0].source_text, reason)
        return _rule(
            "BIZ-HEADCOUNT", "고용 인원", "PASS", waiver[0].source_text,
            f"「{need}인 이상」 요건이지만 공고문에 예외가 있고 회사는 {covered[0]}입니다.",
        )
    if company.employee_count is None:
        return _rule(
            "BIZ-HEADCOUNT", "고용 인원", "CHECK", clause.source_text,
            f"공고문에 「{need}인 이상」 기준이 있는데 회사 상시 근로자 수가 아직 없습니다.",
            "회사자료 › 회사 프로필의 「상시 근로자 수」를 적으면 판정할 수 있습니다",
        )
    return _rule(
        "BIZ-HEADCOUNT", "고용 인원", "FAIL", clause.source_text,
        f"「{need}인 이상」 요건인데 회사는 {company.employee_count}인입니다.",
    )


def _named_program(company, source: str) -> str | None:
    """회사 선행 사업 줄(「없음 확인」 줄 빼고) 중 공고문 조항에 이름이 나오는 것 — 세 글자 이상 낱말 하나라도(43차 COMPANY-09)."""
    text = re.sub(r"\s+", "", source or "")
    for name in company.completed_programs or ():
        if name.strip().startswith("없음"):
            continue
        if any(len(token) >= 3 and token in text for token in re.split(r"[^0-9A-Za-z가-힣]+", name)):
            return name.strip()
    return None


def _biz_age(requirements, company, today: date) -> EligibilityResult | None:
    """BIZ-AGE — 창업 연차. 여러 갈래가 있으면 **하나만 맞아도** 가능이다."""
    clauses = requirements.of("founding_years")
    if not clauses:
        return None
    if company.founded_year is None:
        return _rule(
            "BIZ-AGE", "창업 연차", "CHECK", clauses[0].source_text,
            "공고문이 창업 연차를 제한하는데 회사 설립 연도가 아직 없습니다.",
            "회사자료에 설립 연도를 적으면 판정할 수 있습니다",
        )
    years = today.year - company.founded_year
    ok = [c for c in clauses if years < int(c.detail.get("years") or 0)]
    edge = [c for c in clauses if years == int(c.detail.get("years") or 0)]
    if not ok and edge:
        # 43차 COMPANY-07 — 일반현황 개업일이 있으면 경계 해를 날짜로 가른다(없거나 기준일에 따라 갈리면 아래처럼 확인 필요)
        from app.services.eligibility_engine import founding_edge

        dated = founding_edge(company, int(edge[0].detail.get("years") or 0), today)
        if dated is not None:
            return _rule("BIZ-AGE", "창업 연차", dated[0], edge[0].source_text, f"「창업 {edge[0].detail.get('years')}년 이내」 요건 — {dated[1]}.")
        # 설립 연도만 있으면 상한과 같은 해는 설립 월에 따라 다르다(33차 R32-03)
        return _rule(
            "BIZ-AGE", "창업 연차", "CHECK", edge[0].source_text,
            f"「창업 {years}년 이내」 요건 — 우리 회사는 {company.founded_year}년 설립(설립 뒤 {years}년)이라 설립 월에 따라 다릅니다. "
            "공고 기준일과 설립일을 견줘 확인하세요.",
        )
    if ok:
        limit = ok[0].detail.get("years")
        return _rule(
            "BIZ-AGE", "창업 연차", "PASS", ok[0].source_text,
            f"「창업 {limit}년 이내」 요건 — 우리 회사는 {company.founded_year}년 설립(설립 뒤 {years}년)이라 맞습니다.",
        )
    limit = max(int(c.detail.get("years") or 0) for c in clauses)
    clue = next((c for c in clauses if _founding_alternative(c.source_text)), None)
    if clue is not None:
        # 「(신산업 분야기업은 10년 이내까지 인정)」 같은 단서가 있으면 분명한 불가가 아니다 — 불가는 목록에서 숨는다(32차 R31-03)
        return _rule(
            "BIZ-AGE", "창업 연차", "CHECK", clue.source_text,
            f"「창업 {limit}년 이내」 요건에 단서 · 다른 조건이 있습니다 — 우리 회사는 {company.founded_year}년 설립(설립 뒤 {years}년)이라 "
            "공고 원문에서 어느 조건에 드는지 확인하세요.",
        )
    return _rule(
        "BIZ-AGE", "창업 연차", "FAIL", clauses[0].source_text,
        f"「창업 {limit}년 이내」 요건인데 우리 회사는 {company.founded_year}년 설립(설립 뒤 {years}년)입니다.",
    )


def _biz_revenue(requirements, company) -> EligibilityResult | None:
    """BIZ-REVENUE — 매출 하한. 회사 매출이 미입력이면 확인 필요다."""
    clauses = [c for c in requirements.of("revenue") if c.detail.get("comparator") == "이상"]
    if not clauses:
        return None
    targets = [c for c in clauses if c.detail.get("target")]
    clause = (targets or clauses)[0]
    need = int(clause.detail.get("krw") or 0)
    if not targets and company.revenue_krw_last_year is not None:
        # 대상 문장이 아닌 매출 기준(배점표 · 갈래 중 하나 · 「…이상인 경우」) — 넘으면 막을 것이 없고, 못 미치면 요건인지부터 본다.
        # 「맞음」으로도 세지 않는다(덜 깎기의 근거가 되므로 대상 문장에서 온 것만 · 35차 R34-DATA-02)
        if company.revenue_krw_last_year >= need:
            return None
        return _rule(
            "BIZ-REVENUE", "매출 요건", "CHECK", clause.source_text,
            f"공고문에 「{clause.label}」이 있습니다 — 모든 신청자에게 걸리는 요건인지(갈래 중 하나 · 평가 배점일 수 있음) 공고 원문에서 확인하세요.",
        )
    if company.revenue_krw_last_year is None:
        return _rule(
            "BIZ-REVENUE", "매출 요건", "CHECK", clause.source_text,
            f"공고문이 「{clause.label}」을 요구하는데 회사 매출이 아직 없습니다." if targets else
            f"공고문에 「{clause.label}」이 있는데 회사 매출이 아직 없습니다 — 모든 신청자에게 걸리는 요건인지(갈래 · 평가 배점일 수 있음)도 공고 원문에서 확인하세요.",
            "회사자료에 지난해 매출을 적으면 판정할 수 있습니다",
        )
    if company.revenue_krw_last_year >= need:
        return _rule("BIZ-REVENUE", "매출 요건", "PASS", clause.source_text, f"「{clause.label}」 요건을 넘습니다.")
    return _rule(
        "BIZ-REVENUE", "매출 요건", "FAIL", clause.source_text,
        f"「{clause.label}」 요건인데 회사 매출은 그에 못 미칩니다.",
    )


def _biz_prerequisite(requirements, company, profile_domains: tuple[str, ...]) -> EligibilityResult | None:
    """BIZ-PREREQ — 선행 사업·연구소·제품/데이터 보유·공급기업 등록."""
    clauses = requirements.of("prerequisite")
    if not clauses:
        return None
    results: list[tuple[str, str, str, str | None]] = []  # (status, label, source, unlock)
    for clause in clauses:
        key = clause.detail.get("requirement")
        source = clause.source_text
        if key == "research_department":
            lab_only = bool(clause.detail.get("lab_only"))
            # 「전담부서 미포함」 공고에는 전담부서를 신고해도 안 열린다 — 열리는 조건은 연구소 인정이다(36차 R35-DV-02)
            unlock = "기업부설연구소 인정을 받으면 가능합니다" if lab_only else "연구개발전담부서를 신고하면 가능합니다"
            kind = getattr(company, "research_department_kind", None)
            if clause.detail.get("option") and company.has_research_department is not True:
                results.append(("CHECK", "「기업부설연구소 · 전담부서 보유」는 여러 갈래 중 하나입니다 — 우리 회사가 다른 갈래로 신청할 수 있는지 공고 원문에서 확인하세요.", source, None))
            elif company.has_research_department is True and lab_only and kind == "dept_only":
                results.append(("CHECK", "공고는 기업부설연구소만 인정합니다(연구개발전담부서 미포함) — 회사는 연구개발전담부서만 있습니다.", source, unlock))
            elif company.has_research_department is True and lab_only and kind is None:
                results.append(("CHECK", "공고는 기업부설연구소만 인정합니다 — 회사가 둔 것이 기업부설연구소인지 연구개발전담부서인지 아직 없습니다.", source,
                                "회사자료에 연구소 종류(기업부설연구소 · 연구개발전담부서만)를 고르면 판정할 수 있습니다"))
            elif company.has_research_department is True:
                results.append(("PASS", "기업부설연구소를 보유하고 있습니다." if kind == "lab" else "기업부설연구소·전담부서를 보유하고 있습니다.", source, None))
            elif company.has_research_department is False and clause.detail.get("role_limited"):
                # 「주관연구개발기관이 기업인 경우」처럼 자리에 한정되고 공동 · 참여 자리가 따로 있다(36차 R35-DV-03 · 126756 · 127025)
                results.append(("CHECK", f"연구소 요건은 {clause.detail.get('role') or '주관기관'} 자리에만 걸립니다 — 공동 · 참여 자리로 신청할 수 있는지 공고 원문에서 확인하세요.", source, unlock))
            elif company.has_research_department is False:
                results.append(("FAIL", "기업부설연구소·연구개발전담부서가 없습니다." if not lab_only else "공고가 기업부설연구소를 요구하는데 회사에는 없습니다.", source, unlock))
            else:
                results.append(("CHECK", "기업부설연구소·전담부서 보유 여부가 아직 없습니다.", source,
                                "회사자료에 연구소·전담부서 보유 여부를 적으면 판정할 수 있습니다"))
        elif key in ("completed_program", "prior_selection"):
            what = "선행 과제 완료 판정" if key == "completed_program" else "다른 사업의 선정 업소·기업"
            if clause.detail.get("option"):
                # 대상 제품 표의 한 줄 · 트랙 하나 — 다른 갈래로 들어갈 수 있다(34차 §3-A-2 · 126672 · 119692)
                results.append(("CHECK", f"「{what}」은(는) 여러 갈래(트랙 · 대상 제품) 중 하나입니다 — 우리 회사가 다른 갈래로 신청할 수 있는지 공고 원문에서 확인하세요.", source, None))
            elif _named_program(company, source):
                # 43차 COMPANY-09 — 회사 값에 그 사업 이름이 있으면 「없음」 갈래보다 먼저(선정된 사업의 선정기업 대상 공고가 숨었다)
                results.append(("CHECK", f"공고문의 「{what}」에 회사 선행 사업 「{_named_program(company, source)}」이(가) 맞는지 공고 원문에서 확인하세요.", source, None))
            elif company.completed_programs_confirmed_none:
                # 「확인됨」이 아니라 누가 적은 값인지 — 회사자료 「완료한 선행 사업」의 「없음 확인」 줄(검수자 조사)
                results.append(("FAIL", f"공고문이 「{what}」을(를) 요구하는데 회사에는 해당하는 것이 없습니다(검수자 조사 · 회사자료 「완료한 선행 사업」).", source, None))
            elif company.completed_programs:
                results.append(("CHECK", f"회사의 선행 사업이 공고문의 「{what}」과 같은지 공고 원문에서 확인하세요.", source, None))
            else:
                results.append(("CHECK", f"공고문이 「{what}」을(를) 요구하는데 회사 선행 사업 이력이 아직 없습니다.", source,
                                "회사자료에 완료한 선행 사업을 적으면 판정할 수 있습니다"))
        elif key == "supplier_registration":
            if company.supplier_registrations:
                results.append(("PASS", f"공급기업 등록이 있다({company.supplier_registrations[0]}).", source, None))
            else:
                results.append(("CHECK", "공급기업 등록 여부가 아직 없습니다.", source,
                                "공급기업으로 등록하면 가능합니다"))
        elif key == "digital_product":
            # 43차 M20 · COMPANY-06 — 사업영역 낱말(「개발」 · 「서비스」)로 통과시키지 않는다. 회사가 적은 **보유 제품 이름**이 있을 때만 가능.
            if company.digital_products:
                results.append(("PASS", f"보유 디지털 제품(서비스) 「{company.digital_products[0]}」(회사자료).", source, None))
            else:
                results.append(("CHECK", "보유한 디지털 제품(서비스) 이름이 회사자료에 아직 없습니다.", source,
                                "회사자료에 보유 디지털 제품(서비스)을 적으면 판정할 수 있습니다"))
        elif key == "score_threshold":
            # 신청 전에 넘어야 할 자가진단 · 평가 점수 — 회사 자료로 알 수 없다(120566 · 10-10)
            results.append(("CHECK", "공고가 신청 전에 넘어야 할 점수(자가진단 · 평가)를 정했습니다 — 회사가 먼저 그 점수를 받아 봐야 합니다.", source, None))
        elif key == "data_product":
            if company.data_products:
                results.append(("PASS", f"인증·평가 대상 데이터 상품이 있다({company.data_products[0]}).", source, None))
            else:
                results.append(("CHECK", "인증·평가할 데이터 상품 보유 여부가 아직 없습니다.", source,
                                "회사자료에 데이터 상품을 적으면 판정할 수 있습니다"))
        else:
            results.append(("CHECK", "공고문이 요구하는 보유 요건을 회사 자료로 확인하세요.", source, None))
    for status in ("FAIL", "CHECK", "PASS"):
        hit = [r for r in results if r[0] == status]
        if hit:
            return _rule("BIZ-PREREQ", "선행·보유 요건", status, hit[0][2], hit[0][1], hit[0][3])
    return None


#: 「수행기관 모집(매출)」 사유 — 공고문을 읽었든 안 읽었든 같은 말(37차 D5 · 실무 문서 §4.2).
OPERATOR_CALL_REASON = (
    "수행기관 모집(매출) — 지원금을 받는 사업이 아니라 사업을 운영할 기관을 뽑는 공고입니다."
    " 입찰처럼 수행 자격(기관 요건 · 실적 · 인력)을 공고 원문에서 확인하세요."
)

#: 컨소시엄 필수 · 선택 꼴은 추출기에 한 벌(역할 조항 중복 거르기도 같은 꼴을 본다 · 38차 RULES-01 · 03).
_CONSORTIUM_REQUIRED_RE = support_requirement_extractor.CONSORTIUM_REQUIRED_RE
_CONSORTIUM_OPTIONAL_RE = support_requirement_extractor.CONSORTIUM_OPTIONAL_RE


def _operator_call_rule(program: SupportProgram) -> EligibilityResult:
    """D5 — 「주관 · 운영 · 수행 · 전문 · 관리기관 모집」은 불가(숨김)가 아니라 「수행기관 모집(매출)」 · 확인 필요(37차)."""
    return _rule("BIZ-ROLE", "회사가 맡을 자리", "CHECK", program.title or "", OPERATOR_CALL_REASON)


def _consortium_gap(requirements, company) -> EligibilityResult | None:
    """R36-RV-03 — 컨소시엄 구성이 필수인데 회사 파트너가 「있음」이 아니면 확인 필요(125370 한-독 2+2 · 4개 기관 필수)."""
    clause = next(
        (
            c for c in requirements.of("role")
            if c.detail.get("role") == "consortium" and support_requirement_extractor.consortium_required(c.source_text)
        ),
        None,
    )
    if clause is None or getattr(company, "joint_bid_available", None) is True:
        return None
    return _rule(
        "BIZ-ROLE", "회사가 맡을 자리", "CHECK", clause.source_text,
        "공고가 컨소시엄 구성을 요구합니다 — 함께 참여할 기관을 확보했는지 회사자료 「공동수급 파트너」에 적거나 확인하세요.",
        "컨소시엄 파트너 확보 시",
    )


def _biz_role_v2(requirements, program, company=None) -> tuple[EligibilityResult, str | None]:
    """BIZ-ROLE — **회사가 맡을 자리**. 간접 역할이면 그 이름을 함께 돌려준다.

    돌려주는 둘째 값이 「간접(공급기업)」 같은 표시다. 없으면 None(= 신청 주체).
    """
    roles = {c.detail.get("role") for c in requirements.of("role")}
    title = program.title or ""
    if _OPERATOR_CALL_RE.search(title):
        # D5(37차) — 불가로 숨기지 않는다. 매출 공고(수행기관 모집)이고 수행 자격은 원문을 봐야 안다.
        return _operator_call_rule(program), None
    # 컨소시엄을 회사가 **직접** 꾸려야 할 때만 본다(R36-RV-03) — 도입기업이 기술기업과 꾸리는 두 축 구조에서 회사가 기술기업(간접)이면
    # 컨소시엄은 신청하는 도입기업의 몫이다.
    gap = _consortium_gap(requirements, company)
    indirect = [label for key, label in _INDIRECT_ROLES.items() if key in roles]
    applicant = [label for key, label in _APPLICANT_ROLES.items() if key in roles]
    if indirect and applicant:
        # 제목이 우리가 될 수 있는 신청 주체를 이미 부르고 있으면 직접 신청이다.
        if any(label in title for label in applicant):
            if gap is not None:
                return gap, None
            return (
                _rule("BIZ-ROLE", "회사가 맡을 자리", "PASS", title, f"공고가 {applicant[0]}을(를) 모집합니다."),
                None,
            )
        return (
            _rule(
                "BIZ-ROLE", "회사가 맡을 자리", "CHECK",
                next((c.source_text for c in requirements.of("role")), title),
                f"신청하는 곳은 {applicant[0]}이고, 우리 회사는 {indirect[0]}(으)로 참여합니다.",
            ),
            f"간접({indirect[0]})",
        )
    if gap is not None:
        return gap, None
    if roles:
        label = next((c.label.replace("역할: ", "") for c in requirements.of("role")), "직접 신청")
        return (_rule("BIZ-ROLE", "회사가 맡을 자리", "PASS", title, f"공고문이 말하는 자리: {label}"), None)
    return (_rule("BIZ-ROLE", "회사가 맡을 자리", "PASS", title, "우리 회사가 직접 신청합니다."), None)


#: 회사 사실과 맞부딪히는 제외 조항. **좁게** 본다 — 넓히면 근거 없이 「불가」가 된다.
_EXCLUSION_HITS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"훈련기관"), "훈련기관", "교육 · 훈련을 주 사업으로 하는 훈련기관은 제외 대상입니다."),
)


def _biz_exclusion(requirements, company) -> EligibilityResult | None:
    """BIZ-EXCLUSION — 제외 조항이 **회사 사실과 맞으면** 불가다."""
    clauses = requirements.of("exclusion")
    if not clauses:
        return None
    certifications = " ".join(company.certifications)
    for clause in clauses:
        for pattern, needle, reason in _EXCLUSION_HITS:
            if pattern.search(clause.source_text) and needle in certifications and "주 사업" in clause.source_text:
                return _rule("BIZ-EXCLUSION", "제외 조항", "FAIL", clause.source_text, reason)
    for clause in clauses:
        for pattern, needle, _reason in _EXCLUSION_HITS:
            if pattern.search(clause.source_text) and needle in certifications:
                # 「훈련기관은 제외」처럼 「주 사업」 없이 쓴 조항 — 회사가 훈련기관 인증이 있으면 해당하는지 단정하지 않는다(검토 10-10)
                return _rule(
                    "BIZ-EXCLUSION", "제외 조항", "CHECK", clause.source_text,
                    f"제외 조항에 「{needle}」이(가) 있고 회사도 {needle} 인증이 있습니다 — 해당하는지 공고 원문에서 확인하세요.",
                )
    # 규칙이 회사 사실로 가리는 것은 훈련기관 제외뿐이다 — 「회사에 해당하는 것은 없습니다」라고 쓰면 체납 · 체불 · 중복 지원
    # 같은 나머지를 확인한 것처럼 읽혔다(「가능」 좁히기 감사 · 122145 · 123682).
    return _rule(
        "BIZ-EXCLUSION", "제외 조항", "PASS", clauses[0].source_text,
        f"제외 조항 {len(clauses)}건을 찾았습니다 — 체납 · 체불 · 중복 지원 같은 회사 형편은 규칙이 가리지 못하니 신청 전에"
        " 공고 원문을 보고 직접 확인하세요.",
    )


#: 회사가 「ICT 업종」임을 가리키는 말. **회사가 적어 둔** 사업영역·사업자등록증 종목에서 읽는다.
_ICT_WORDS: tuple[str, ...] = ("ICT", "SW", "소프트웨어", "정보통신", "데이터", "인공지능", "AI", "디지털")


def _biz_strategic_industry(requirements, company, profile_domains: tuple[str, ...]) -> EligibilityResult | None:
    """BIZ-STRATEGY — 공고문이 **회사 지역의 전략산업**으로 우리 업종을 지목하는가.

    「호남권 광주 ICT, 모빌리티, 헬스케어, 문화콘텐츠」 같은 표다. 회사 소재가 광주이고
    그 뒤 목록에 우리 업종이 있으면, 이 공고는 회사를 우선 대상으로 부르고 있는 것이다.
    없으면 **규칙 자체를 만들지 않는다** — 「불가」로 읽힐 문장을 만들지 않는다.
    """
    clauses = requirements.of("strategic_industry")
    if not clauses or not company.location_region:
        return None
    aliases = ("광주광역시", "광주", "전라남도", "전남", "호남") if company.location_region == "전남광주" else ()
    if not aliases:
        return None
    mine = " ".join(profile_domains)
    for clause in clauses:
        text = clause.source_text
        for alias in aliases:
            at = text.find(alias)
            if at < 0:
                continue
            # 우리 지역 이름 뒤에서 다음 지역 이름 전까지가 그 지역의 업종 목록이다.
            tail = text[at + len(alias) : at + len(alias) + 60]
            hit = next((w for w in _ICT_WORDS if w in tail and (w in mine or w in ("ICT", "정보통신"))), None)
            if hit:
                # 근거는 **원문 그대로**이되 우리 몫만 잘라 인용한다 — 표 한 줄이 2,000자다.
                quote = text[max(0, at - 4) : at + len(alias) + 60]
                return _rule(
                    "BIZ-STRATEGY", "지역 전략산업", "PASS", quote,
                    f"공고문이 회사 지역({alias})의 전략산업으로 「{hit}」를 지목합니다 — 회사가 우선 대상입니다.",
                )
    return None


def _biz_money(requirements) -> EligibilityResult | None:
    """BIZ-MONEY — 받는 것·부담을 **원문 그대로** 한 줄로. 판정이 아니라 정보다."""
    clauses = requirements.of("money")
    if not clauses:
        return None
    line = " · ".join(dict.fromkeys(c.label for c in clauses[:3]))
    return _rule("BIZ-MONEY", "받는 것·부담", "PASS", clauses[0].source_text, line)


def _money_clauses(requirements) -> list:
    """돈 조각 중 **앞뒤가 맞는 것**만 남긴다.

    뭉개진 표 한 줄에서 「…(수요기업 부담)정부지원(80%)수요기업 부담(20%)…」 처럼 읽히면
    자부담이 80% 로 잡힌다. 정부지원 비율과 **같은 수**인 자부담은 그 오독이다 —
    둘을 합치면 160% 가 된다. 그런 조각은 근거로 쓰지 않는다.
    """
    clauses = requirements.of("money")
    government = {
        float(c.detail.get("percent") or 0)
        for c in clauses
        if c.detail.get("kind") == "government_share"
    }
    if not government:
        return clauses
    return [
        c
        for c in clauses
        if not (c.detail.get("kind") == "self_share" and float(c.detail.get("percent") or 0) in government)
    ]


def money_line(requirements) -> str | None:
    """「받는 것 · 부담」 한 줄. 화면·엑셀이 같은 문장을 쓴다.

    **문서에 나온 순서가 아니라 큰 값부터** 고른다. 「기관부담 10%·13%·15%·25%」처럼
    구간이 여럿이면 앞의 셋만 적었을 때 회사에 해당하는 25% 가 빠졌다.
    """
    clauses = _money_clauses(requirements)
    if not clauses:
        return None
    picked: list[str] = []
    free = [c for c in clauses if c.detail.get("kind") == "free"]
    if free:
        picked.append(free[0].label)
    amounts = [c for c in clauses if c.detail.get("kind") in ("cap", "range", "monthly")]
    if amounts:
        largest = max(amounts, key=lambda c: int(c.detail.get("high_krw") or c.detail.get("krw") or 0))
        picked.append(largest.label)
    for kind in ("government_share", "self_share"):
        shares = [c for c in clauses if c.detail.get("kind") == kind]
        if shares:
            picked.append(max(shares, key=lambda c: float(c.detail.get("percent") or 0)).label)
    if not picked:
        picked = [c.label for c in clauses[:3]]
    return " · ".join(dict.fromkeys(picked))


def company_meaning_line(
    program: SupportProgram,
    requirements,
    *,
    indirect: str | None,
    gate: str,
    closed: bool = False,
) -> str | None:
    """**「회사에 뜻하는 것」 한 줄** (0924 §4-A-6) — 역할 · 받는 것 · 부담 · 마감.

    기준 답안 표의 「받는 것 / 부담 / 회사 역할」 열과 같은 뜻이다. 원문에서 읽은 것만
    적는다 — 못 읽었으면 그 조각을 뺀다.
    """
    parts: list[str] = []
    if indirect:
        parts.append(indirect)
    elif closed:
        # 신청이 끝난 공고에 「신청 주체가 될 수 없음」이라고 적었다 — 회사 자격과 상관없는 이유다(32차 뜻 틀린 곳).
        # 화면 말은 「신청 종료」다 — 「신청 마감 · 10월 7일 마감」으로 두 번 마감이라 했다(33차 R32-09)
        parts.append(f"신청 종료({program.apply_end.month}월 {program.apply_end.day}일)" if program.apply_end else "신청 종료")
    elif gate == "FAIL":
        parts.append("신청 대상 아님")
    else:
        # 「신청 주체」는 행정 말이다 — 역할 판정 사유(「우리 회사가 직접 신청합니다」)와 같은 말로(32차 R31-18)
        role = next((c.label.replace("역할: ", "") for c in requirements.of("role")), None)
        parts.append(f"직접 신청{f'({role})' if role else ''}")
    money = money_line(requirements)
    if money:
        parts.append(money)
    # **「자부담 없음」은 공고문이 그렇게 적었을 때만** (0925 §4-C-2).
    #
    # 10차는 「무료」가 있고 자부담 비율이 없으면 「자부담 없음」이라고 적었다 — 지어낸 말이다.
    # 공고문이 자부담을 말하지 않은 것은 「없다」가 아니라 「모른다」다.
    if any(c.detail.get("kind") == "no_self_burden" for c in requirements.of("money")):
        parts.append("자부담 없음")
    if closed and not indirect:
        pass  # 종료 날짜는 첫 조각에 적었다
    elif program.apply_end:
        parts.append(f"{program.apply_end.month}월 {program.apply_end.day}일 마감")
    elif program.apply_period_text:
        parts.append(program.apply_period_text)
    return " · ".join(dict.fromkeys(parts)) or None


def clause_quotes(requirements, *, limit: int = 4) -> list[str]:
    """화면·엑셀이 그대로 보여 줄 **원문 인용**. 자격을 가르는 갈래를 먼저 담는다.

    **지원대상 절의 첫 문장이 맨 앞이다** (0925 §4-B-3). 조항을 하나도 못 찾은 공고에서는
    그것이 담당자가 가장 먼저 읽어야 할 줄인데, 10차는 제외 조항 머리글(「< 지원 제외 대상」)을
    첫 인용으로 보여 줬다.
    """
    order = ("location", "org_type", "headcount", "headcount_waiver", "founding_years",
             "revenue", "prerequisite", "exclusion", "role", "money")
    out: list[str] = []
    if requirements.target_sentence:
        out.append(requirements.target_sentence)
    for kind in order:
        for clause in requirements.of(kind):
            if clause.source_text not in out:
                out.append(clause.source_text)
            if len(out) >= limit:
                return out
    return out


#: 「받는 것」이 얼마나 큰가. 규모 항목의 근거다 (0924 §4-B-1).
BENEFIT_SCORES: dict[str, float] = {"free": 1.0, "large": 0.8, "medium": 0.6, "small": 0.4}

#: 「큰 금액」의 경계. 사업화 자금·과제비가 이 위다.
_BENEFIT_LARGE_KRW = 50_000_000
_BENEFIT_MEDIUM_KRW = 10_000_000


#: **회사 사실이 요건과 맞았다**고 말할 수 있는 규칙 (0925 §4-A-1).
#:
#: 이 중 하나라도 PASS 여야 「가능」이다. 소재 규칙은 **조항을 근거로** 통과했을 때만 센다 —
#: 「제한 문장을 못 찾았다」는 회사 사실이 아니라 «못 찾았다»이기 때문이다.
#: `BIZ-TARGET` 은 요약문 경로(v1)의 같은 뜻이다 — 「사회적기업」·「창업 n년 이내」 일치.
COMPANY_MATCH_RULES: tuple[str, ...] = (
    "BIZ-ORG-TYPE", "BIZ-PREREQ", "BIZ-HEADCOUNT", "BIZ-AGE", "BIZ-REVENUE",
    "BIZ-STRATEGY", "BIZ-SMALL-BUSINESS", "BIZ-TARGET", "BIZ-SME",
)


def company_match_of(requirements, rules) -> list[str]:
    """회사 «사실» 때문에 통과한 규칙들. 비어 있으면 「가능」이라고 말할 수 없다."""
    by_id = {r.rule_id: r for r in rules}
    matched = [
        rule_id
        for rule_id in COMPANY_MATCH_RULES
        if rule_id in by_id and by_id[rule_id].status == "PASS"
    ]
    location = by_id.get("BIZ-LOCATION")
    if location is not None and location.status == "PASS" and requirements.of("location"):
        matched.append("BIZ-LOCATION")
    return matched


#: 사유에 적을 규칙 수 상한. `opportunity_priority` 와 같은 값이다.
_GATE_FAIL_LIMIT: Final[int] = 2

#: 「왜 맞나」에 이름으로 적을 회사 사실 — 규칙마다 한 마디 (0925 §4-D-4).
#:
#: 10차의 이 줄은 「지원사업 · 인력 · 전남광주」였다 — 분류와 지역 해시태그다.
#: 담당자가 「왜 맞나」에서 알고 싶은 것은 **회사의 무엇이 이 요건과 맞았나**다.
COMPANY_FACT_WORDS: dict[str, str] = {
    "BIZ-LOCATION": "소재",
    "BIZ-ORG-TYPE": "조직 형태",
    "BIZ-PREREQ": "보유·선행 요건",
    "BIZ-HEADCOUNT": "고용 인원",
    "BIZ-SMALL-BUSINESS": "소상공인 범위",
    "BIZ-AGE": "창업 연차",
    "BIZ-REVENUE": "매출",
    "BIZ-STRATEGY": "지역 전략산업",
    "BIZ-TARGET": "지원 대상",
    "BIZ-SME": "중소기업 확인서",
}

#: 회사 사실이 하나도 맞지 않았을 때. **빈 줄로 두지 않는다** — 없다는 것도 사실이다.
# 머리 「왜 맞나」와 내용이 반대로 읽혔다(「맞는다고 확인된 조건이 없습니다」) — 아직 확인한 것이 없다는 사실로(32차 어려운 글 #2)
NO_COMPANY_FACT = "아직 회사자료로 확인한 맞는 점이 없습니다 — 공고 원문의 지원대상을 보세요"


def company_fact_line(requirements, rules) -> str:
    """「왜 맞나」(기업마당) — **맞은 회사 사실만** 이름과 근거로 (0925 §4-D-4)."""
    by_id = {r.rule_id: r for r in rules}
    parts: list[str] = []
    for rule_id in company_match_of(requirements, rules):
        rule = by_id[rule_id]
        word = COMPANY_FACT_WORDS.get(rule_id, rule.label)
        parts.append(f"{word}: {rule.reason}")
    return " · ".join(parts[:3]) or NO_COMPANY_FACT


#: 「확인 필요」 사유의 머리말. 대상 절 원문을 그대로 뒤에 붙인다.
UNCONFIRMED_PREFIX = "공고문에서 대상 요건을 확정하지 못했습니다"
UNCONFIRMED_NO_SECTION = "공고문에 지원대상 절을 찾지 못했습니다"
#: 대상 절에 규칙이 못 읽은 줄이 남았다 — 회사 사실이 몇 개 맞아도 「가능」이 아니다(36차 R35-DV-01 · 연구소 「있음」이면 새로 가능 4건 중
#: 3건이 거짓이었다: 125778 인지부품 개발 · 제조 기업 · 126756 으뜸기업 6기 · 127025 경북 본점).
UNHANDLED_TARGET_PREFIX = "공고문 대상 줄을 규칙이 다 읽지 못했습니다 — 회사가 이 대상에 드는지 공고 원문에서 확인하세요"
#: 공고문을 못 읽고 요약의 대상 줄만 맞춘 공고 — 요약 밖 조건(업종 · 협력사 · 보증부 대출 · 판매할 상품)이 있었다
#: (「가능」 좁히기 감사 · 요약 경로 「가능」 6건이 모두 틀림 — 123466 · 125339 · 126919 · 127016 · 119434 · 124218).
SUMMARY_ONLY_PREFIX = "공고문을 아직 읽지 못해 기업마당 요약의 대상 줄만 회사 자료와 맞췄습니다 — 공고 원문의 신청 자격을 확인하세요"
#: 「가능」의 근거가 될 수 없는 맞음 — 지역 전략산업은 **우선 선정** 가산이지 자격이 아니다(123682 「해당분야에 해당되지 않은 경우
#: ‘기타’로 신청 가능」). 「왜 맞나」에는 그대로 적는다.
_PREFERENCE_ONLY_MATCHES: Final[frozenset[str]] = frozenset({"BIZ-STRATEGY"})
#: 「가능」 사유 끝의 할 일 — 제외 조항(체납 · 체불 · 중복 지원)은 회사 자료로 가리지 못한다(담당자 결정 10-10 「제외 조항은 지금처럼」).
EXCLUSION_REMINDER = "제외 조항 {n}건(체납 · 체불 · 중복 지원 등)은 신청 전에 공고 원문을 보고 직접 확인하세요"


def verdict_of(requirements, rules, *, indirect: str | None) -> tuple[str, str]:
    """**「가능·확인 필요·불가」와 그 사유** (0925 §4-A-1).

    10차까지는 「FAIL 도 CHECK 도 없으면 가능」이었다. 그래서 공고문을 읽을수록 판정이
    후해졌다 — 조항을 못 찾은 공고가 전부 「가능」이 됐고, 30일 목록의 「가능」 60건 중
    44건에 회사 사실과 맞은 요건이 **하나도 없었다**(재검증 §3 ISSUE-096).

    CLAUDE.md §11 「Evidence 가 없는데 충족 판정 금지」 · §4-D 「모호하면 CHECK」 그대로:

        불가       FAIL 규칙이 하나라도 있다
        가능       FAIL 없음 **그리고** 회사 사실이 요건과 맞았다
        확인 필요   그 밖 전부 — 사유에 **지원대상 절 원문**을 인용한다
    """
    failed = [r for r in rules if r.status == "FAIL"]
    if failed:
        return "FAIL", " · ".join(f"{r.label}: {r.reason}" for r in failed[:_GATE_FAIL_LIMIT])

    matched = company_match_of(requirements, rules)
    checks = [r for r in rules if r.status == "CHECK"]
    if checks:
        reason = " · ".join(f"{r.label}: {r.reason}" for r in checks[:_GATE_FAIL_LIMIT])
        return "CHECK", reason
    basis = [m for m in matched if m not in _PREFERENCE_ONLY_MATCHES]
    if basis:
        by_id = {r.rule_id: r for r in rules}
        facts = " · ".join(f"{by_id[m].label}: {by_id[m].reason}" for m in basis[:_GATE_FAIL_LIMIT])
        unhandled = getattr(requirements, "unhandled_targets", None) or []
        if requirements.document_read and unhandled:
            return "CHECK", f"{UNHANDLED_TARGET_PREFIX} — 「{unhandled[0][:80]}」 · 맞은 것 — {facts}"
        if not requirements.document_read:
            # 요약만으로는 「가능」이라 하지 않는다 — 공고문을 받아 읽으면 다시 판정한다(담당자 결정 10-10 「가능」 좁히기)
            return "CHECK", f"{SUMMARY_ONLY_PREFIX} · 맞은 것 — {facts}"
        exclusions = requirements.of("exclusion")
        if exclusions:
            # 「가능」은 대상 요건만 본다(담당자 결정 10-10) — 제외 조항은 회사 형편이라 사유에 할 일로 남긴다
            facts += f" · {EXCLUSION_REMINDER.format(n=len(exclusions))}"
        return "PASS", facts

    # 막는 것도 없고 맞은 것도 없다 — **「가능」이 아니라 「확인 필요」**다.
    if requirements.target_sentence:
        return "CHECK", f"{UNCONFIRMED_PREFIX} — 지원대상: 「{requirements.target_sentence}」"
    return "CHECK", UNCONFIRMED_NO_SECTION


#: 「주의」 줄이 세는 넷과 그것을 찾았다고 볼 조항 (0925 §4-D-1).
#:
#: 10차의 「주의」는 공고문을 읽었든 안 읽었든 똑같이
#: 「신청자격(업력·기업유형·중복지원 제한·제외 대상)은 공고 원문에서 확인해야 합니다」
#: 였다. 카드에서 가장 밝은 줄이 **이미 읽은 것을 읽으라는 말**이었다.
CAUTION_ITEMS: tuple[tuple[str, str], ...] = (
    ("founding_years", "창업 연차"),
    ("org_type", "기업 유형"),
    ("duplicate", "중복 신청 제한"),
    ("exclusion", "제외 대상"),
)

#: 「중복지원 제한」은 따로 갈래를 두지 않는다 — 공고문은 이것을 제외 절 안에 쓴다.
#: 그래서 어느 조항이든 원문에 「중복」이 있으면 찾은 것으로 본다.
_DUPLICATE_WORD = "중복"


def unfound_conditions(requirements) -> list[str]:
    """공고문을 읽고도 **못 찾은** 넷의 이름 (0925 §4-D-1). 다 찾았으면 빈 목록."""
    if not requirements.document_read:
        return []
    found_duplicate = any(
        _DUPLICATE_WORD in c.source_text for c in requirements.clauses
    )
    missing: list[str] = []
    for kind, label in CAUTION_ITEMS:
        if kind == "duplicate":
            if not found_duplicate:
                missing.append(label)
        elif not requirements.of(kind):
            missing.append(label)
    return missing


def clause_signals(requirements, rules, *, indirect: str | None, program: SupportProgram | None = None, company=None) -> dict:
    """순위가 쓰는 **조항 기반 신호** (0924 §4-B-1).

    - `read`          공고문을 읽었는가
    - `gate`          규칙 종합 (가능/확인 필요/불가)
    - `company_match` 회사 «사실»이 요건과 실제로 맞았는가 (인증·소재·보유·연차)
    - `benefit`       받는 것의 크기 (무료·큰 금액·…). 규모 항목이 이것을 쓴다.
    """
    gate, gate_reason = verdict_of(requirements, rules, indirect=indirect)
    matched = company_match_of(requirements, rules)

    benefit: str | None = None
    money = _money_clauses(requirements)
    if any(c.detail.get("kind") == "free" for c in money):
        benefit = "free"
    elif any(
        c.detail.get("kind") == "government_share" and float(c.detail.get("percent") or 0) >= 80
        for c in money
    ):
        benefit = "free"
    else:
        amounts = [int(c.detail.get("krw") or c.detail.get("high_krw") or 0) for c in money]
        top = max(amounts, default=0)
        if top >= _BENEFIT_LARGE_KRW:
            benefit = "large"
        elif top >= _BENEFIT_MEDIUM_KRW:
            benefit = "medium"
        elif top > 0:
            benefit = "small"
    # **「확인 필요」에도 두 가지가 있다.**
    #
    #   공고 쪽   「전라남도 소재」가 통합 이후 광주를 포함하는지 — 전화 한 통이면 풀린다.
    #   회사 쪽   매출·연구소·데이터 상품처럼 **회사가 아직 갖추지 못했거나 안 적은 것**.
    #
    # 뒤쪽은 지금 당장 손댈 수 없는 건이라 앞쪽과 같은 자리에 두면 「이번 주 할 일」이
    # 못 하는 일로 채워진다. 검수자가 E 그룹으로 뺀 것들이 정확히 그 모양이었다.
    company_side = [
        r.rule_id
        for r in rules
        if r.status == "CHECK"
        # `BIZ-TARGET-CERT` 도 회사 쪽이다 — 확인서를 받아 오기 전에는 못 하는 일이다
        # (ISSUE-126 · prompt_05 §4-E-2).
        and r.rule_id
        in ("BIZ-REVENUE", "BIZ-PREREQ", "BIZ-HEADCOUNT", "BIZ-TARGET-CERT", "BIZ-TARGET-INDUSTRY", "BIZ-SME", "BIZ-ROLE")
        # 고용 인원의 「조건 붙은 예외」 · 중소기업 줄의 「읽지 못한 조건」 확인은 공고를 읽는 일이다 — 회사 값이 비었거나 서류를
        # 갖춰야 할 때(열리는 조건이 있을 때)만 회사 쪽(검토 10-10). BIZ-ROLE 은 컨소시엄 파트너(열리는 조건)일 때만 회사 쪽(37차 R36-RV-03)
        and (r.rule_id not in ("BIZ-HEADCOUNT", "BIZ-SME", "BIZ-ROLE") or r.unlock_condition)
    ]
    return {
        "read": bool(requirements.document_read),
        "gate": gate,
        "gate_reason": gate_reason,
        # 「주의」 줄에 적을 것 — 읽은 공고에서 **못 찾은 넷** (0925 §4-D-1).
        "unfound": unfound_conditions(requirements),
        "company_match": bool(matched),
        "matched_rules": matched,
        "company_side_checks": company_side,
        "benefit": benefit,
        "indirect": bool(indirect),
        # 소관기관 · 수행기관이 다른 시·도인가. 전략적 가치가 이것을 본다 (0924 §4-B-1 · 43차 Q8 · BIZ-10 — 수행기관 경로에도).
        "other_region": _other_region(program, rules) if program is not None else any(
            r.rule_id == "BIZ-LOCATION" and r.source.startswith("소관기관") for r in rules
        ),
        # 광주 · 전남(호남권 포함) 한정 사업 — 나라장터와 같은 +0.2(43차 Q8).
        "home_region": _home_region_program(program, company) if program is not None and company is not None else False,
    }


#: 「호남권 · 광주ㆍ전북ㆍ전남」 — 우리 지역을 포함한다(43차 Q8 · 「호남권 AX랩」이 「전북 기업 대상인지 확인」으로 깎였다).
_HONAM_RE = re.compile(r"호남권|호남\s*지역|광주\s*[ㆍ·,]\s*전북\s*[ㆍ·,]\s*전남|전북\s*[ㆍ·,]\s*전남\s*광주")


def _honam(program: SupportProgram) -> bool:
    return bool(_HONAM_RE.search(" ".join(filter(None, [program.title, program.summary or "", program.target or "", program.agency, program.executing_agency or ""]))))


def _other_region(program: SupportProgram, rules) -> bool:
    """다른 시 · 도 사업인가 — 소관기관 · 수행기관 경로 모두(43차 BIZ-10). 옛 전남 · 광주 해석 줄 · 호남권은 다른 지역이 아니다."""
    if _honam(program):
        return False
    return any(
        r.rule_id == "BIZ-LOCATION" and r.status == "CHECK" and "옛 " not in r.reason
        and (r.source.startswith("소관기관") or r.source.startswith("수행기관") or r.reason.startswith("수행기관("))
        for r in rules
    )


def _home_region_program(program: SupportProgram, company) -> bool:
    """광주 · 전남(호남권 포함) 한정 사업인가 — 회사가 광주 · 전남일 때만."""
    from app.services import home_agencies

    if company.location_region != "전남광주":
        return False
    tags = {t for t in program.region_tags if t}
    if tags and tags <= {"광주", "전남", "전남광주"}:
        return True
    return _honam(program) or home_agencies.is_home(program.executing_agency) or (
        home_agencies.is_home(program.agency) and not tags - {"광주", "전남", "전남광주"}
    )


@dataclass(frozen=True)
class SupportJudgement:
    """지원사업 하나의 **판정 한 벌** (0925 §4-B-1 · ISSUE-097).

    ## 왜 이 자리에 있나

    10차까지 목록(`opportunity_service`)과 신청 분석(`build`)이 **다른 경로**로 판정했다.
    목록은 공고문을 읽고(v2 + 조항 신호) 판정했고, 신청 분석은 요약문만 보는 v1 이었다.
    그래서 같은 공고가 목록에서는 「85점 · 가능」, 신청 분석에서는 「57점 · 확인 필요 8건」
    이었다 — 담당자가 목록을 보고 들어가면 다른 답을 만났다(재검증 §3 ISSUE-097).

    **규칙을 두 벌 두지 않는다.** 두 화면이 이 함수 하나를 부른다.
    """

    requirements: Any
    rules: list[EligibilityResult]
    indirect: str | None
    signals: dict
    #: 「왜 맞나」 — 맞은 회사 사실만 (0925 §4-D-4).
    company_facts: str
    gate: str
    gate_reason: str
    relevance: Any
    components: list[Any]
    reasons: list[str]
    checks: list[str]
    source_score: dict
    score: int | None
    company_meaning: str | None
    clause_quotes: list[str]
    unlock_conditions: list[str]

    @property
    def verdict(self) -> str:
        """화면에 적는 말. 「간접(공급기업)」이면 그것이 판정 자리에 온다."""
        if self.indirect:
            return self.indirect
        return {"PASS": "가능", "CHECK": "확인 필요", "FAIL": "불가"}.get(self.gate, "미확인")


def judge(
    program: SupportProgram,
    fit,
    *,
    company,
    profile,
    source: str,
    today: date,
    requirements=None,
) -> SupportJudgement:
    """**목록과 신청 분석이 함께 쓰는 판정 한 벌** (0925 §4-B-1).

    공고문을 읽었으면 조항으로(v2), 못 읽었으면 요약문으로(v1) 판정한다. 어느 쪽이든
    종합은 `verdict_of` 하나가 정한다 — 「가능」은 회사 사실이 맞았을 때뿐이다.
    `requirements` 는 기업마당 공고문 저장소가 아닌 곳에서 뽑은 조항(직접 넣은 공고 · 38차 §3-E)일 때만 넘긴다.
    """
    from app.services import opportunity_priority as _priority
    from app.services import support_kinds as _kinds
    from app.services import support_requirement_extractor as _extractor

    if requirements is None:
        requirements = _extractor.load(program.id)
    domains = tuple(getattr(profile, "business_domains", ()) or ())
    indirect: str | None = None
    if requirements.document_read:
        rules, indirect = biz_rules_v2(
            program, requirements, company=company, today=today, profile_domains=domains
        )
    else:
        rules = biz_rules(program, company=company, today=today)
    signals = clause_signals(requirements, rules, indirect=indirect, program=program, company=company)
    gate, gate_reason = signals["gate"], signals["gate_reason"]
    relevance = _kinds.relevance_of(program)
    components, reasons, checks, source_score = _priority.score_support(
        program,
        fit,
        profile=profile,
        source=source,
        today=today,
        gate=gate,
        relevance=relevance,
        signals=signals,
    )
    return SupportJudgement(
        requirements=requirements,
        rules=rules,
        indirect=indirect,
        signals=signals,
        company_facts=company_fact_line(requirements, rules),
        gate=gate,
        gate_reason=gate_reason,
        relevance=relevance,
        components=components,
        reasons=reasons,
        checks=checks,
        source_score=source_score,
        score=_priority.normalize(components),
        company_meaning=company_meaning_line(
            program, requirements, indirect=indirect, gate=gate,
            closed=any(r.rule_id == "BIZ-PERIOD" and r.status == "FAIL" for r in rules),
        ),
        clause_quotes=clause_quotes(requirements),
        unlock_conditions=list(
            dict.fromkeys(
                r.unlock_condition for r in rules if r.unlock_condition and r.status in ("FAIL", "CHECK")
            )
        ),
    )


def biz_rules_v2(
    program: SupportProgram,
    requirements,
    *,
    company,
    today: date,
    profile_domains: tuple[str, ...] = (),
) -> tuple[list[EligibilityResult], str | None]:
    """공고문 조항으로 판정한다. 둘째 값은 「간접(공급기업)」 표시다 (없으면 None)."""
    results: list[EligibilityResult] = [_role_limited_location(_biz_location(requirements, program, company), requirements)]
    role_result, indirect = _biz_role_v2(requirements, program, company)
    for maybe in (
        _biz_org_type(requirements, company),
        _biz_sme(requirements, company, today),
        _biz_target_certification(program, company),
        _biz_target_industry(program, profile_domains),
        _biz_small_business(requirements, program, company, today),
        _biz_headcount(requirements, company),
        _biz_age(requirements, company, today),
        _biz_revenue(requirements, company),
        _biz_prerequisite(requirements, company, profile_domains),
        _biz_strategic_industry(requirements, company, profile_domains),
    ):
        if maybe is not None:
            results.append(maybe)
    results.append(role_result)
    for maybe in (_biz_exclusion(requirements, company), _biz_money(requirements)):
        if maybe is not None:
            results.append(maybe)
    results.append(_biz_period(program, today))
    # 불가가 하나라도 있으면 「간접」이라고 부르지 않는다 — 그 자리로도 못 들어간다.
    #
    # **소재 요건 하나만 막고 있을 때는 다르다.** 「광양시 소재 제조 공장을 보유한 기업」이
    # 참여기업이고 실증은 「실증공급기업」이 한다면, 회사는 참여기업이 될 수 없을 뿐
    # 실증공급기업으로는 들어간다 — 그것이 검수자가 「간접(공급기업)」이라 적은 뜻이다.
    failed = [r for r in results if r.status == "FAIL"]
    if failed and not (indirect and all(r.rule_id == "BIZ-LOCATION" for r in failed)):
        indirect = None
    elif indirect and failed:
        # 간접으로 들어가는 길이 있으니 「불가」로 닫지 않는다. 막힌 자리는 사유에 남는다.
        results = [
            r.model_copy(update={"status": "CHECK"}) if r.status == "FAIL" else r for r in results
        ]
    return results, indirect


def biz_rules(program: SupportProgram, *, company, today: date) -> list[EligibilityResult]:
    """지원사업 네 규칙. 판정은 「가능 · 확인 필요 · 불가」 셋뿐이다 (0921 §4-B)."""
    results = [
        _biz_region(program, company),
        _biz_target(program, company, today),
        _biz_period(program, today),
    ]
    # 공고문을 아직 읽지 않은 공고도 「주관기관 모집」을 거른다(37차 D5 · 기획서 1-10 — 예전에는 v2 에만 있었다).
    role = _operator_call_rule(program) if _OPERATOR_CALL_RE.search(program.title or "") else _biz_role(program)
    if role is not None:
        results.append(role)
    return results


# --------------------------------------------------------------------------
# 네 묶음 (신청자격 · 필수/우대조건 · 신청기간 · 제출서류)
# --------------------------------------------------------------------------


#: 신청자격 단계에 보여 줄 **공고문 조항** 갈래와 그 이름 (0925 §4-B-2).
CLAUSE_ITEMS: tuple[tuple[str, str], ...] = (
    ("location", "소재 요건"),
    ("org_type", "조직 형태"),
    ("headcount", "고용 인원"),
    ("founding_years", "창업 연차"),
    ("revenue", "매출 요건"),
    ("prerequisite", "선행·보유 요건"),
    ("role", "회사가 맡을 자리"),
    ("exclusion", "제외 조항"),
    ("money", "받는 것·부담"),
)

#: 공고문을 읽었는데 그 갈래를 못 찾았을 때. **「없음」이 아니다.**
CLAUSE_MISSING_NOTE = "공고문에서 찾지 못함 — 원문 확인"


def clause_items(requirements) -> list[SupportRequirementItem]:
    """공고문 조항을 **원문·쪽과 함께** 신청자격 단계에 싣는다 (0925 §4-B-2).

    10차까지 이 화면은 공고문을 읽지 않았다. 목록 카드에는 인용이 붙어 있는데 상세로
    들어가면 「기업마당 목록 정보만으로는 판정할 수 없습니다」뿐이었다.
    """
    out: list[SupportRequirementItem] = []
    for kind, label in CLAUSE_ITEMS:
        clauses = requirements.of(kind)
        if not clauses:
            out.append(
                SupportRequirementItem(
                    key=f"clause_{kind}", label=label, value=None, status="unknown",
                    source_field="공고문", note=CLAUSE_MISSING_NOTE,
                )
            )
            continue
        value = " / ".join(dict.fromkeys(c.label for c in clauses[:3]))
        quote = clauses[0]
        out.append(
            SupportRequirementItem(
                key=f"clause_{kind}",
                label=label,
                value=value,
                status="confirmed",
                source_field=f"공고문 {quote.page}쪽" if quote.page else "공고문",
                note=f"원문: 「{quote.source_text}」",
            )
        )
    return out


def eligibility_items(program: SupportProgram, requirements=None) -> list[SupportRequirementItem]:
    """신청자격 단계. **공고문을 읽었으면 그 조항이 먼저다** (0925 §4-B-2)."""
    summary = [
        _item("target", "지원 대상", program.target, source_field="trgetNm"),
        _item("company_type", "신청 가능 기업 유형", _company_types_of(program), source_field="trgetNm·hashtags"),
        _item("region", "지역", _regions_of(program), source_field="hashtags·jrsdInsttNm", note="해시태그·기관명에서 읽은 값입니다. 지역 제한 여부는 원문에서 확인하세요."),
    ]
    if requirements is not None and requirements.document_read:
        return [*clause_items(requirements), *summary]
    # 못 읽은 이유와 「그래서 무엇을 하라」를 함께 적는다 — 둘 중 하나만으로는 모자란다.
    why = requirements.document_note if requirements is not None else None
    note = f"{why} · {UNKNOWN_NOTE}" if why else UNKNOWN_NOTE
    return [
        *summary,
        _item("business_age", "창업 연차 조건", None, note=note),
        _item("excluded", "제외 대상", None, note=note),
    ]


def condition_items(program: SupportProgram) -> list[SupportRequirementItem]:
    field = " · ".join(filter(None, [program.category, program.subcategory])) or None
    return [
        _item("field", "지원 분야", field, source_field="pldirSportRealmLclasCodeNm·pldirSportRealmMlsfcCodeNm"),
        _item("summary", "사업 개요", program.summary, source_field="bsnsSumryCn"),
        _item("method", "지원 방식", None, note=UNKNOWN_NOTE),
        _item("scale", "지원 규모", None, note=UNKNOWN_NOTE),
        _item("self_burden", "자부담", None, note=UNKNOWN_NOTE),
        _item("preferred", "우대조건", None, note=UNKNOWN_NOTE),
    ]


def schedule_items(program: SupportProgram) -> list[SupportRequirementItem]:
    kind_label = APPLY_PERIOD_KIND_LABELS.get(program.apply_period_kind, "원문 확인 필요")
    if program.apply_start or program.apply_end:
        period = f"{program.apply_start or '시작일 미상'} ~ {program.apply_end or '종료일 미상'}"
        period_item = SupportRequirementItem(
            key="period", label="신청 기간", value=period, status="confirmed", source_field="reqstBeginEndDe", note=f"원문: {program.apply_period_text}"
        )
    elif program.apply_period_text:
        # '상시 접수'·'예산 소진시까지'를 날짜가 없다는 이유로 버리지 않는다.
        period_item = SupportRequirementItem(
            key="period",
            label="신청 기간",
            value=f"{program.apply_period_text} ({kind_label})",
            status="confirmed",
            source_field="reqstBeginEndDe",
            note="마감일이 지정되지 않았습니다. 조기 마감 여부를 원문에서 확인하세요.",
        )
    else:
        period_item = _item("period", "신청 기간", None, source_field="reqstBeginEndDe")
    return [
        period_item,
        _item("apply_method", "접수 방법", program.apply_method, source_field="reqstMthPapersCn"),
        _item("reception_url", "접수처 홈페이지", program.reception_url, source_field="rceptEngnHmpgUrl"),
    ]


def document_items(program: SupportProgram) -> list[SupportRequirementItem]:
    # 신청 서식 칸(fileNm)의 첨부 전부 — 30차 §3-A 부터 이름으로 종류(과제소개서 · 매뉴얼 · 서식)를 달지만 이 줄은 칸 기준 그대로
    forms = [a for a in program.attachments if a.index is not None]
    notices = [a for a in program.attachments if a.index is None]
    # 제출서류는 신청방법 원문에 적힌 문장만 옮긴다 (없는 서류 목록을 만들지 않는다).
    lines = [ln.strip(" -·\t") for ln in re.split(r"[\r\n]+", program.apply_method or "") if _DOCUMENT_HINT.search(ln)]
    return [
        _item("forms", "신청 서식 첨부", ", ".join(a.name for a in forms) or None, source_field="fileNm", note="첨부 서식이 목록에 없으면 공고 원문에서 내려받으세요."),
        _item("notice_file", "공고문", ", ".join(a.name for a in notices) or None, source_field="printFileNm"),
        _item("documents", "제출서류 (원문 발췌)", "\n".join(lines) or None, source_field="reqstMthPapersCn", note="신청방법 원문에서 서류 관련 문장만 옮긴 것입니다. 전체 목록은 공고문을 확인하세요."),
        _item("contact", "문의처", program.contact, source_field="refrncNm"),
    ]


# --------------------------------------------------------------------------
# 회사 적합 근거 (승인된 회사자료만)
# --------------------------------------------------------------------------


def _evidence_requirements(program: SupportProgram, items: list[SupportRequirementItem]) -> list[Requirement]:
    """근거 검색용 임시 항목. 저장하지 않으며 evidence_service 재사용을 위한 어댑터다."""
    texts: list[tuple[str, str]] = []
    if program.summary:
        texts.append(("사업 개요", program.summary))
    field = next((i.value for i in items if i.key == "field" and i.value), None)
    if field:
        texts.append(("지원 분야", f"{program.title} {field}"))
    if program.target:
        texts.append(("지원 대상", f"{program.target} 대상 {program.title}"))
    requirements: list[Requirement] = []
    for index, (title, content) in enumerate(texts[:9], start=1):
        requirements.append(
            Requirement(
                id=f"{program.id}:{index:03d}",
                procurement_id=program.id,
                requirement_id=f"REQ-{index:03d}",
                category="지원사업 신청",
                requirement_type="mandatory",
                title=title,
                content=content,
                source_text=content,
                item_type="ELIGIBILITY",
            )
        )
    return requirements


def _match_evidence(program: SupportProgram, items: list[SupportRequirementItem], *, context: AnalysisContext) -> tuple[list[dict], dict | None]:
    requirements = _evidence_requirements(program, items)
    if not requirements:
        return [], None
    result = evidence_service.match_requirements(requirements, context=context)
    scope = result.scope_info.model_dump(mode="json") if result.scope_info else None
    if not result.available:
        return [], scope
    label_of = {r.requirement_id: r.title for r in requirements}
    matches = [
        {
            "condition": label_of.get(m.requirement_id, m.requirement_id),
            "evidence_id": m.evidence_id,
            "document_name": m.document_name,
            "page": m.page,
            "source_text": m.source_text,
            "similarity_score": m.similarity_score,
            "selected": m.selected,
            "synthetic": m.synthetic,
        }
        for m in result.matches
    ]
    return matches, scope


# --------------------------------------------------------------------------
# 사업계획서 초안 뼈대 · 신청 전 점검
# --------------------------------------------------------------------------


#: 신청 자격 절에 인용할 조항 갈래. `requirements.of()` 에 실재하는 이름만 쓴다.
ELIGIBILITY_CLAUSE_KINDS: tuple[str, ...] = (
    "location", "org_type", "sme", "founding_years", "headcount", "revenue",
    "prerequisite", "role", "strategic_industry", "exclusion",
)

#: 공고문을 읽었는데 그 절의 조항이 하나도 없을 때. 「목록 정보에 없다」와 다른 말이다.
CLAUSE_MISSING_NOTE = "공고문에서 해당 조항을 찾지 못했습니다. 원문에서 직접 확인하세요."


def _clause_quotes(requirements, kinds: tuple[str, ...], *, limit: int = 4) -> list[str]:
    """조항 **원문 그대로**. 요약하지 않는다 (CLAUDE.md §11 · 0921 §4-B 생성 금지)."""
    quotes: list[str] = []
    for kind in kinds:
        for clause in requirements.of(kind):
            text = (clause.source_text or "").strip()
            if text and text not in quotes:
                quotes.append(text)
    return quotes[:limit]


def _matched_company_facts(requirements, rules) -> list[str]:
    """맞은 회사 사실만. `company_fact_line` 과 **같은 규칙**을 쓰되 줄이 아니라 목록으로."""
    by_id = {r.rule_id: r for r in rules}
    facts: list[str] = []
    for rule_id in company_match_of(requirements, rules):
        rule = by_id[rule_id]
        word = COMPANY_FACT_WORDS.get(rule_id, rule.label)
        facts.append(f"{word}: {rule.reason}")
    return facts


def draft_outline(
    program: SupportProgram,
    items: dict[str, list[SupportRequirementItem]],
    matches: list[dict],
    *,
    requirements=None,
    rules: Sequence[Any] = (),
) -> list[dict[str, Any]]:
    """사업계획서 목차 뼈대. 근거가 있는 것만 근거를 달고, 없으면 「확인 필요」로 남긴다.

    ## 왜 고쳤나 (ISSUE-112 · prompt_01 §4-D-1)

    뼈대가 **공고문을 안 봤다.** 126482 는 공고문에서 「과제별 최대 1억원」·「창업 7년
    이내」를 읽어 목록에 적어 놓고도, 05 예산·자부담은 「지원 규모·자부담 조건이 목록
    정보에 없습니다」로 굳어 있었고 02 는 무조건 「업력·제외 대상은 원문 확인 후 보완」
    이었다. 이미 손에 든 조항을 안 쓴 것이다.

    `requirements` 는 **선택 인자**다. 없거나 공고문을 못 읽은 공고는 지금 문구를 한
    글자도 바꾸지 않는다 — 기존 호출부와 테스트가 그대로 산다.

    더하는 키는 `quotes`(조항 원문)·`company_facts`(맞은 회사 사실) 둘뿐이다. 기존 네
    키(section·basis·grounded·note)의 뜻은 그대로다.
    """
    selected = [m for m in matches if m.get("selected")]
    read = requirements is not None and getattr(requirements, "document_read", False)

    eligibility_quotes = _clause_quotes(requirements, ELIGIBILITY_CLAUSE_KINDS) if read else []
    company_facts = _matched_company_facts(requirements, rules) if read else []
    money_clauses = _money_clauses(requirements) if read else []

    outline = [
        {"section": "사업 개요·추진 배경", "basis": "공고 원문(사업 개요)", "grounded": bool(program.summary), "note": None if program.summary else "공고 원문에서 개요를 확인해 채우세요.", "quotes": [], "company_facts": []},
        {
            "section": "신청 자격 충족 설명",
            "basis": "공고 원문(지원 대상) + 회사 프로필",
            "grounded": any(i.status == "confirmed" for i in items["eligibility"]),
            # 공고문을 읽었고 조항도 찾았으면 「원문 확인 후 보완」이라고 하지 않는다 —
            # 이미 원문을 인용해 두었기 때문이다.
            "note": (
                None
                if eligibility_quotes
                else CLAUSE_MISSING_NOTE
                if read
                else "창업 연차 · 제외 대상은 공고 원문에서 확인한 뒤 보완하세요."
            ),
            "quotes": eligibility_quotes,
            "company_facts": company_facts,
        },
        {
            "section": "수행 역량·유사 실적",
            "basis": f"승인된 회사자료 {len(selected)}건" if selected else "회사 근거 없음",
            "grounded": bool(selected),
            "note": None if selected else "아직 고른 회사 문장이 없습니다. 회사자료에서 자료를 올리고 쓸 문장을 고르세요.",
            "quotes": [],
            "company_facts": [],
        },
        {"section": "추진 계획·일정", "basis": "공고 원문(신청 기간)", "grounded": any(i.key == "period" and i.status == "confirmed" for i in items["schedule"]), "note": None, "quotes": [], "company_facts": []},
        (
            {
                "section": "예산·자부담 계획",
                "basis": " · ".join(dict.fromkeys(c.label for c in money_clauses[:3])),
                "grounded": True,
                "note": None,
                "quotes": [c.source_text for c in money_clauses[:3] if c.source_text],
                "company_facts": [],
            }
            if money_clauses
            else {
                "section": "예산·자부담 계획",
                "basis": "미확인",
                "grounded": False,
                # 공고문을 읽고도 못 찾은 것과 목록만 본 것은 다른 사실이다.
                "note": (
                    CLAUSE_MISSING_NOTE
                    if read
                    else "지원 규모·자부담 조건이 목록 정보에 없습니다. 공고문에서 확인해야 작성할 수 있습니다."
                ),
                "quotes": [],
                "company_facts": [],
            }
        ),
        {"section": "기대 효과", "basis": "공고 원문(지원 분야)", "grounded": bool(program.category), "note": None, "quotes": [], "company_facts": []},
    ]
    return outline


#: 초안이 아직 담지 않은 조항을 셀 때 보는 갈래. 신청 자격 절과 돈 절이 대상이다.
UNCOVERED_CLAUSE_KINDS: tuple[str, ...] = (*ELIGIBILITY_CLAUSE_KINDS, "money")


def uncovered_clauses(outline: list[dict[str, Any]], requirements) -> list[str]:
    """공고문 조항 중 **초안에 인용되지 않은 것** (prompt_01 §4-D-4).

    입찰 Auditor 의 축소판이다 — 규칙만 쓰고 LLM 을 부르지 않는다. Auditor 가 「RFP 필수
    요구사항 누락」을 세는 것과 같은 자리이고, 여기서는 「공고문 조항 누락」을 센다.

    비교는 **원문 문자열**로 한다. 초안이 조항을 인용할 때 원문 그대로 넣기 때문에
    (`_clause_quotes`), 같은 문장이 양쪽에 있으면 반영된 것이다. 요약·재작성은 하지
    않으므로 이 대조가 성립한다.
    """
    if requirements is None or not getattr(requirements, "document_read", False):
        return []
    quoted = {q.strip() for section in outline for q in section.get("quotes", []) if q}
    missing: list[str] = []
    from app.services.plan_draft_service import PLAN_SKIPPED_CLAUSE_KINDS  # 함수 안에서 — 모듈 순환을 피한다

    for kind in UNCOVERED_CLAUSE_KINDS:
        if kind in PLAN_SKIPPED_CLAUSE_KINDS:
            continue  # 초안이 싣지 않는 제외 조항 — 초안 경로와 같은 규칙(26차 검수 · ISSUE-147)
        for clause in requirements.of(kind):
            text = (clause.source_text or "").strip()
            if text and text not in quoted and text not in missing:
                missing.append(text)
    return missing


def pre_submit_checks(
    items: dict[str, list[SupportRequirementItem]],
    program: SupportProgram,
    *,
    uncovered: Sequence[str] = (),
    document_read: bool = False,
) -> list[str]:
    """신청 전 점검 (제안서 AI Auditor 와는 다른 개념 — 서류·조건 확인 목록).

    `uncovered` 는 초안이 아직 담지 않은 공고문 조항이다. 선택 인자라 넘기지 않으면
    예전과 같은 목록이 나온다 (기존 호출부·테스트 유지).
    """
    checks: list[str] = []
    if uncovered:
        checks.append(
            f"사업계획서 초안에 반영되지 않은 공고문 조항 {len(uncovered)}건 — "
            f"예: {uncovered[0][:60]}"
        )
    # 같은 꼴 12줄이 이어져 읽지 않게 됐다 — 못 찾은 항목을 한 줄로(32차 어려운 글 #12). 공고문에서 찾지도 않는 칸(지원 방식 ·
    # 규모 · 자부담 · 우대조건)과 역할 판정이 따로 있는 「회사가 맡을 자리」는 「찾지 못함」이라고 적지 않는다(32차 뜻 틀린 곳).
    labels = [
        entry.label
        for group in items.values()
        for entry in group
        if entry.status == "unknown" and entry.key not in NOT_SEARCHED_ITEM_KEYS
    ]
    if labels:
        checks.append(_unknown_check_line(labels, document_read=document_read))
    if not any(a.index is not None for a in program.attachments):
        checks.append("신청 서식 첨부가 목록에 없습니다. 공고 원문에서 서식을 내려받으세요.")
    if program.apply_period_kind in ("until_budget", "conditional"):
        checks.append(f"마감 조건 확인 — {program.apply_period_text}")
    checks.extend(general_procedure_checks(items, program))
    checks.append("제출 전 담당자 최종 검토 필요 (시스템이 신청을 대신 제출하지 않습니다).")
    return checks


#: 「신청 전 점검」의 **일반 절차** 줄(31차 §3-B · 제품 반영 안 2-3). 공고에서 찾은 조건이 아니므로 머리에
#: 「일반 절차」를 붙여 섞지 않는다(CLAUDE.md §11). 숫자 · 기간 · 비용은 문서에만(예외: 중소기업 확인서 3월 31일 만료).
GENERAL_PROCEDURE_HEAD: Final[str] = "[일반 절차 안내 · 공고문이 우선] "
CHECK_KSTARTUP: Final[str] = "K-Startup에 대표 본인 명의로 가입하고, 회사 이름의 인증서로 기업인증을 해 두세요(대표 개인 인증서로는 안 됩니다)."
CHECK_STARTUP_CERT: Final[str] = "창업기업 확인서 유효기간을 확인하세요. 새로 받으려면 시간이 걸립니다(공고마다 다름)."
CHECK_SME_CERT: Final[str] = "중소기업(소상공인) 확인서 유효기간을 확인하세요(매년 3월 31일 만료)."
CHECK_RECEIPT: Final[str] = "마지막에 접수가 끝났는지(K-Startup은 「제출완료」) 신청 내역에서 확인하고, 접수증을 PDF로 보관하세요."
CHECK_AGREEMENT: Final[str] = "선정되면 협약 확약서 · 협약 · 전용 계좌가 이어집니다. 사업비는 공고와 협약서 규정대로만 씁니다."
_KSTARTUP_RE = re.compile(r"k-?startup|케이스타트업", re.IGNORECASE)


def general_procedure_checks(items: dict[str, list[SupportRequirementItem]], program: SupportProgram) -> list[str]:
    """접수처 · 확인서 · 접수증 · 협약 — 처음 신청하는 사람이 공고문에서 놓치는 절차. 접수 방법 칸이 없는
    가짜 객체(테스트)도 깨지지 않게 `getattr` 로 읽는다."""
    method = " ".join(str(getattr(program, name, None) or "") for name in ("apply_method", "reception_url"))
    # 칸 이름(「창업 연차」 같은 빈 조항 자리)이 아니라 **찾은 값**만 본다 — 이름을 보면 모든 공고에 확인서 줄이 붙었다.
    eligibility = " ".join(
        [*(e.value or "" for e in items.get("eligibility", []) if e.status == "confirmed"),
         *(getattr(program, "requirement_sentences", None) or [])[:1], str(getattr(program, "target", None) or "")]
    )
    lines: list[str] = []
    if _KSTARTUP_RE.search(method):
        lines.append(CHECK_KSTARTUP)
    if "창업" in eligibility:
        lines.append(CHECK_STARTUP_CERT)
    if "중소기업" in eligibility:
        lines.append(CHECK_SME_CERT)
    lines += [CHECK_RECEIPT, CHECK_AGREEMENT]
    return [GENERAL_PROCEDURE_HEAD + line for line in lines]


#: 공고문에서 **찾지 않는** 칸 · 역할 판정(BIZ-ROLE)이 따로 있는 칸 — 「찾지 못함」 줄에 넣지 않는다.
NOT_SEARCHED_ITEM_KEYS: Final[frozenset[str]] = frozenset({"method", "scale", "self_burden", "preferred", "role", "clause_role"})


def _unknown_check_line(labels: Sequence[str], *, document_read: bool) -> str:
    """「확인 필요」 한 줄 (ISSUE-116 · prompt_02 §4-D).

    공고문을 **읽었는데도** 그 조항을 못 찾은 것과, 애초에 원문을 못 본 것은 다른 사실이다.
    126482 는 공고문을 읽고 조항까지 뽑아 놓고도 「소재 요건 미확인 — 공고 원문·첨부파일에서
    확인」이라고 적었다 — 담당자는 앱이 아직 원문을 안 봤다고 읽는다. 11차가 배너에서 고친
    규칙(ISSUE-113)을 점검 줄에도 그대로 적용한다.
    """
    names = " · ".join(dict.fromkeys(labels))
    if document_read:
        return f"공고문에서 못 찾은 항목: {names} — 원문에서 확인하세요"
    return f"기업마당 요약에 없는 항목: {names} — 공고 원문 · 첨부파일에서 확인하세요"

def _saved_plan_draft(program_id: str, context) -> dict[str, Any]:
    """저장된 사업계획서 초안. 없으면 빈 dict.

    `support_plan_service` 를 **함수 안에서** 가져온다 — 그쪽이 이 모듈의
    `UNCOVERED_CLAUSE_KINDS` 를 쓰므로 모듈 수준에서 서로 가져오면 순환이 된다.
    """
    if context is None:
        return {}
    from app.services import support_plan_service

    try:
        return support_plan_service.load(context=context, program_id=program_id)
    except OSError:
        return {}


def _uncovered_from_draft(draft: dict[str, Any], requirements) -> list[str]:
    from app.services import support_plan_service

    return support_plan_service.uncovered_quotes(draft, requirements)

# --------------------------------------------------------------------------
# 진입점
# --------------------------------------------------------------------------


#: 목록에서 빠진(마감) 지원사업의 공고 정보 사본 — 그 회사의 분석 폴더에 **저장된 초안 · 분석이 있을 때만** 남긴다(33차 §3-A-6).
#: 최신화하면 마감된 사업이 목록에서 빠져 126482(사업계획서 두 판)의 상세 · 새 초안이 404 였다.
PROGRAM_SNAPSHOT = "program.json"
ARCHIVED_SOURCE = "archived"
ARCHIVED_NOTE = "마감된 공고 — 목록에서 빠져 저장된 초안 · 분석만 볼 수 있습니다(새 초안은 만들 수 없습니다)"
#: 마감일 전에 목록에서 빠진 사업(34차 R33-A1) — 취소 · 변경 · 상시형 · 캐시 손상일 수 있어 「마감」으로 단정하지 않고 막지도 않는다.
DELISTED_NOTE = "기업마당 목록에서 내려간 공고(마감일 전) — 취소 · 변경됐을 수 있으니 원문 확인"


def archived_block(program: SupportProgram, source: str) -> str | None:
    """새 초안을 막을 사유. 사본이고 **마감일이 지났을 때만**(34차 R33-A1) — 목록에서 빠지기만 한 것은 막지 않는다."""
    return ARCHIVED_NOTE if source == ARCHIVED_SOURCE and _program_closed(program) else None


def remember_program(program: SupportProgram, organization_id: str) -> None:
    """저장된 초안 · 분석이 있는 사업이면 공고 정보 사본을 남긴다(같으면 다시 쓰지 않는다). 실패해도 상세는 그대로."""
    try:
        folder = org_storage.storage_for(organization_id).analysis_dir(program.id)
        if not folder.exists():
            return  # 저장된 것이 없는 사업은 남기지 않는다 — 목록에서 빠지면 그대로 빠진다
        path = folder / PROGRAM_SNAPSHOT
        payload = program.model_dump(mode="json")
        if storage.read_json(path, default=None) != payload:
            storage.write_json_atomic(path, payload)
    except Exception:  # noqa: BLE001 — 부가 기록이 상세를 막지 않는다
        logger.warning("지원사업 정보 사본을 남기지 못했습니다: %s", program.id, exc_info=True)


def archived_program(program_id: str, organization_id: str) -> SupportProgram | None:
    """목록에서 빠진 사업의 남겨 둔 공고 정보. 없거나 못 읽으면 None."""
    try:
        path = org_storage.storage_for(organization_id).analysis_dir(program_id) / PROGRAM_SNAPSHOT
        payload = storage.read_json(path, default=None)
        return SupportProgram.model_validate(payload) if isinstance(payload, dict) else None
    except Exception:  # noqa: BLE001 — 깨진 사본은 없는 것처럼(404)
        return None


def cached_programs(program_ids: set[str]) -> dict[str, SupportProgram]:
    """받아 둔 기업마당 목록에서 사업 몇 개(id → 사업). **네트워크를 부르지 않는다** — 저장본이 없으면 목록과 같은 가상 예시, 못 읽으면 빈 dict.

    (2.0.6) 「검토 중」이 지원사업 결정을 제목 없이 id 글자로 적었다(links-1) — 엑셀 「자격 판정 근거」와 같은 찾기를 한 곳에 둔다.
    """
    if not program_ids:
        return {}
    path = bizinfo_service.CACHE_FILE if bizinfo_service.CACHE_FILE.exists() else bizinfo_service.SAMPLE_FILE
    try:
        payload = storage.read_json(path, default=None)
    except storage.CorruptJsonError:
        return {}
    out: dict[str, SupportProgram] = {}
    for raw in (payload.get("items") or []) if isinstance(payload, dict) else []:
        if isinstance(raw, dict) and f"bizinfo-{raw.get('pblancId')}" in program_ids:
            program = bizinfo_service.map_program(raw)
            if program is not None:
                out[program.id] = program
    return out


def _listed_priority_label(program_id: str, *, organization_id: str, today: date, company: Any) -> str | None:
    """목록이 이 사업에 매긴 「우선 검토 · 검토 · 후순위」 — 목록 메모를 같은 `_label_cohort`(같은 출처 상위 15% · 관련 낮음은 후순위)로 다시 매긴다.

    (2.0.6 values-4) 상세는 점수만 보고 매겨, 레이더 「우선 검토」인 사업이 이 화면에서 「검토」로 적혔다. 메모가 없으면 None
    (`memoized_support_score` 와 같은 메모 · 같은 열쇠).
    """
    from app.services import opportunity_service

    stamp = opportunity_service._inputs_stamp()
    for key, outcome in opportunity_service._SUPPORT_MEMO.items():
        if key[0] != organization_id or key[2] != today or key[3] != company or key[4] != stamp:
            continue
        cohort, *_rest = opportunity_service._detached(outcome)
        opportunity_service._label_cohort(cohort)
        found = next((item.priority_label for item in cohort if item.id == program_id), None)
        if found is not None:
            return found
    return None


def _listed_practical_group(program_id: str, *, organization_id: str, today: date, company: Any) -> str | None:
    """목록 행의 분류 칸(「긴급」 · 「일반 접수 중」 …) — 목록 메모 속 이 사업의 사본에 목록과 같은 함수(`_annotate_practical`)로 매긴다.

    (2.0.6 cross-2) 실무순 회사(샘플에듀)의 목록 · 레이더는 분류 칸을 보이는데 이 화면만 「우선 검토 · 검토」였다. 칸은 항목마다 따로 매기므로
    이 사업 하나만 매긴다(메모 속 객체는 고치지 않는다). 메모가 없으면 None — `_listed_priority_label` 과 같은 메모 · 같은 열쇠.
    """
    from app.services import opportunity_service

    stamp = opportunity_service._inputs_stamp()
    for key, outcome in opportunity_service._SUPPORT_MEMO.items():
        if key[0] != organization_id or key[2] != today or key[3] != company or key[4] != stamp:
            continue
        found = next((item for item in outcome[0] if item.id == program_id), None)
        if found is not None:
            copy = found.model_copy()
            opportunity_service._annotate_practical([copy], organization_id=organization_id, now=storage.utc_now())
            return copy.practical_group
    return None


async def find_program(program_id: str, *, organization_id: str) -> tuple[SupportProgram, Any, str]:
    listing = await bizinfo_service.list_programs(organization_id=organization_id)
    for view in listing.items:
        if view.program.id == program_id:
            remember_program(view.program, organization_id)
            return view.program, view.support_fit, listing.source
    archived = archived_program(program_id, organization_id)
    if archived is not None:
        # 목록에서 빠진 사업 — 남겨 둔 공고 정보로 저장된 초안 · 분석을 보이게 한다(33차 §3-A-6)
        return archived, bizinfo_service.support_fit(archived, organization_id=organization_id), ARCHIVED_SOURCE
    raise ProgramNotFoundError(f"현재 목록에 없는 지원사업입니다: {program_id}")


def _program_closed(program) -> bool:
    """이 지원사업의 접수가 이미 끝났는가.

    마감 판정 규칙은 opportunity_service 한 곳에만 둔다 — 목록과 상세가 갈리면 안 된다.
    (예전에는 상세가 closed=False 로 굳어 있어서 접수가 끝난 사업이 상세에서는
     「검토」·「우선 검토」 배지로 나왔다.)
    """
    from app.services import opportunity_service

    deadline = opportunity_service._deadline_of_program(program)
    return opportunity_service._closed(deadline, storage.utc_now())


async def build(program_id: str, *, context: AnalysisContext) -> dict[str, Any]:
    program, fit, source = await find_program(program_id, organization_id=context.organization_id)
    profile = company_service.load_profile(context.organization_id)
    # **목록과 같은 시계다** (ISSUE-133 · prompt_07 §4-A).
    #
    # 여기가 `datetime.now()` 였을 때, 목록은 주입된 시계로 만든 메모 열쇠에 `today` 를
    # 넣고 상세는 실제 날짜로 열쇠를 만들어 **날짜가 다른 날 메모를 못 찾았다**. 화면
    # 두 개가 같은 사업에 다른 점수를 적었고(48 · 7), 운영에서도 자정 전후 요청이 그랬다.
    today = storage.kst_today()
    company = eligibility_engine.company_facts_for(context.organization_id)
    # 목록 메모를 보려면 저쪽을 부른다. 모듈 수준에서 서로 가져오면 순환이 된다
    # (`_program_closed` 도 같은 방식이다).
    from app.services import opportunity_service

    # **목록과 같은 함수로 판정한다** (0925 §4-B-1 · ISSUE-097).
    #
    # 10차까지 여기는 v1(요약문)만 봤다. 같은 공고가 목록에서 「85점 · 가능」,
    # 이 화면에서 「57점 · 확인 필요 8건」이었다.
    judgement = judge(
        program,
        fit,
        company=company,
        profile=profile,
        source=source,
        today=today,
    )
    requirements = judgement.requirements
    groups = {
        "eligibility": eligibility_items(program, requirements),
        "conditions": condition_items(program),
        "schedule": schedule_items(program),
        "documents": document_items(program),
    }
    all_items = [i for group in groups.values() for i in group]
    matches, scope = _match_evidence(program, groups["conditions"] + groups["eligibility"], context=context)
    scope = evidence_service.with_search_state(scope, context)  # 46차 H5 — 대시보드 · 정리표와 같은 지금 상태
    components, reasons, checks, source_score = (
        judgement.components, judgement.reasons, judgement.checks, judgement.source_score
    )
    # **목록이 이미 낸 점수를 먼저 읽는다** (prompt_05 §4-B-1 · ISSUE-129).
    #
    # 11차에 같은 함수(`judge`)를 쓰게 했는데도 두 화면이 갈렸다 — 입력이 시간에 따라
    # 달라졌기 때문이다(벡터가 생기는 순간 사업영역 점수가 바뀐다). 목록 메모가 살아
    # 있다는 것은 입력 지문(기업마당 캐시 · 공고문 목록 · **벡터 집합**)이 같다는 뜻이고,
    # 그러면 그 점수는 지금 계산해도 같은 값이다. 꺼내 쓰면 갈릴 창이 아예 없어진다.
    #
    # 다르면 **입력이 같은데 결과가 다른 것**이므로 버그다. 화면은 목록과 같은 값을
    # 보여 주고(담당자가 두 숫자를 보는 일이 없게), 로그에 남겨 다음에 찾을 수 있게 한다.
    score = judgement.score
    listed = opportunity_service.memoized_support_score(
        program.id, organization_id=context.organization_id, today=today, company=company
    )
    if listed is not None and listed != score:
        logger.warning(
            "목록과 상세의 점수가 다릅니다 (입력 지문은 같습니다): %s 목록 %s · 상세 %s",
            program.id, listed, score,
        )
    if listed is not None:
        score = listed
    biz = judgement.rules
    eligibility_gate, gate_reason = judgement.gate, judgement.gate_reason
    closed = _program_closed(program)
    # 초안을 먼저 만들고, 7단계가 그 초안을 읽어 «아직 안 담긴 조항»을 센다.
    outline = draft_outline(program, groups, matches, requirements=requirements, rules=biz)
    # 저장된 초안이 있으면 **그것**이 기준이다 (prompt_02 §4-B-6).
    # 12차는 뼈대의 인용으로 셌다. 담당자가 「생성」을 눌러 만든 초안이 있는데도 뼈대로
    # 세면, 초안에 담은 조항이 「미반영」으로 남아 고칠 수 없는 경고가 된다. 
    plan_draft = _saved_plan_draft(program.id, context)
    # 18차부터 이 자리가 주석 처리된 빈 괄호(= 빈 튜플)라 「미반영 조항」 점검 줄이 한 번도 나오지 않았다.
    # 25차 §4-C-9 가 반영 셈을 조항 id 로 세면서 되살린다.
    uncovered = (
        _uncovered_from_draft(plan_draft, requirements)
        if plan_draft.get("sections")
        else uncovered_clauses(outline, requirements)
    )

    return {
        "program_id": program.id,
        "organization_id": context.organization_id,
        "evidence_scope": context.evidence_scope,
        "source": source,
        "field_mapping_verified": bizinfo_service.FIELD_MAPPING_VERIFIED,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "program": program.model_dump(mode="json"),
        # 자격 규칙 결과. 나라장터와 같은 모양이라 화면이 한 벌로 그린다 (0921 §4-B).
        "eligibility_rules": [r.model_dump(mode="json") for r in biz],
        "support_fit": fit.model_dump(mode="json"),
        "company_priority_score": score,
        # 목록(opportunity_service)은 실제 마감 여부를 넣는데 상세만 False 로 굳어 있어서,
        # 같은 건이 목록에서는 「마감」, 상세에서는 「검토」로 갈렸다.
        # (2.0.6 values-4) 마감이 아니면 목록과 같은 규칙 — 관련 낮음은 「후순위」 · 「우선 검토」는 같은 출처 상위 15% 도(목록 메모가 있으면 그 값).
        "priority_label": (
            "마감" if closed
            else "후순위" if eligibility_gate == "FAIL" or (not judgement.relevance.related and judgement.relevance.reason)
            else _listed_priority_label(program.id, organization_id=context.organization_id, today=today, company=company)
            or priority.label_of(score, closed=False)
        ),
        # (2.0.6 cross-2) 목록과 같은 분류 칸(목록 메모가 없으면 None) · 회사 순서 방식 — 실무순 회사면 화면이 「우선 검토」 대신 분류 칸을 보인다(레이더 상세와 같은 규칙)
        "practical_group": _listed_practical_group(
            program.id, organization_id=context.organization_id, today=today, company=company
        ),
        "ranking_method": opportunity_service.ranking_method_of(context.organization_id),
        "eligibility_gate": eligibility_gate,
        "gate_reason": gate_reason,
        # **목록 카드와 글자까지 같은 값** (0925 §4-B-3).
        "participation": judgement.indirect,
        "company_meaning": judgement.company_meaning,
        "clause_quotes": judgement.clause_quotes,
        "unlock_conditions": judgement.unlock_conditions,
        "document_read": requirements.document_read,
        "document_note": requirements.document_note,
        "check_side": (
            ("company" if judgement.signals.get("company_side_checks") else "notice")
            if eligibility_gate == "CHECK"
            else None
        ),
        "closed": closed,
        # 목록에서 빠진 사업을 남겨 둔 공고 정보로 보이는 중(33차 §3-A-6). 새 초안은 마감일이 지났을 때만 막는다(34차 R33-A1)
        "archived": source == ARCHIVED_SOURCE,
        "archived_closed": source == ARCHIVED_SOURCE and closed,
        "archived_note": (ARCHIVED_NOTE if closed else DELISTED_NOTE) if source == ARCHIVED_SOURCE else None,
        "confidence": priority.confidence_of(components, source=source),
        "score_components": [c.model_dump(mode="json") for c in components],
        "source_specific_score": source_score,
        "reasons": reasons,
        "plan": {key: [i.model_dump(mode="json") for i in group] for key, group in groups.items()},
        "unknown_count": sum(1 for i in all_items if i.status == "unknown"),
        "confirmed_count": sum(1 for i in all_items if i.status == "confirmed"),
        "evidence_matches": matches,
        "evidence_summary": scope,
        "draft_outline": outline,
        "pre_submit_checks": [
            *checks,
            *pre_submit_checks(
                groups, program, uncovered=uncovered, document_read=requirements.document_read
            ),
        ],
        "note": (
            # 공고문을 읽었으면 「목록 정보만으로는」이 더 이상 사실이 아니다 (0925 §4-B-4).
            (
                f"공고문을 읽고 판정했습니다. 찾지 못한 조항 "
                f"{sum(1 for i in groups['eligibility'] if i.key.startswith('clause_') and i.status == 'unknown')}건은 "
                "「공고문에서 찾지 못함」으로 표시했습니다. "
                if requirements.document_read
                else f"{requirements.document_note or '공고문을 읽지 못했습니다'} — "
                "기업마당 목록 정보에 없는 조건은 「원문 상세 확인 필요」로 표시했습니다. "
            )
            + "신청서 제출은 담당자가 직접 합니다."
        ),
    }
