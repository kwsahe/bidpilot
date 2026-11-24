"""실무 우선순위 (`ranking_method="practical"`) — 샘플에듀 = 사업담당자 방식 (37차 · 담당자 결정 2026-10-14).

사업담당자 인수인계 문서(§2.5 · §4.1 · §4.4)의 「최종 순서는 적합도 점수순이 아니다」를 옮긴 것이다.
기획서 `docs/reports/2026-11-01_gpt_workflow_plan.md` §4-1 1-1 ~ 1-4.

## 규율

- **점수(`company_priority_score`)를 바꾸지 않는다.** 여기는 「어떤 순서로 보여 주나」와 「어느 칸에 두나」만
  정한다. 점수는 어느 방식에서나 「회사 기준 검토 우선순위」 이름 그대로이고 낙찰 · 선정 확률이 아니다(CLAUDE.md §12).
- **마감은 점수가 아니라 정렬 키다.** 남은 기간은 **실제 마감**(참가자격 등록 마감이 더 이르면 그 날)으로 센다.
- 유형 A1~D 는 **근사치**다 — 사업담당자 운영매뉴얼 v1.2 를 아직 받지 못했다. 화면 · 파일에 「유형(근사)」으로 적는다.
- 판정을 새로 만들지 않는다. 분류 칸은 이미 있는 판정(가능 · 확인 필요 · 불가) · 관련 낮음 · 마감을 읽기만 한다.
- 값이 없으면 빈칸이다. 설명회는 날짜만 싣고 판정에 쓰지 않는다(필수 참석 여부는 공고문을 봐야 안다).
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Final, Iterable, Literal, Sequence

from app.schemas.business_opportunity import UnifiedOpportunity
from app.services import g2b_mapper
from app.services import opportunity_filter
from app.services import work_kinds as work_kinds_service

KST = timezone(timedelta(hours=9))

RankingMethod = Literal["score", "practical"]
RANKING_METHOD_LABELS: Final[dict[str, str]] = {"score": "점수순", "practical": "실무 우선순위"}
#: 회사 방식이 정하는 기본 정렬 — 목록 · 레이더 · 대시보드 첫 공고 · 고르기 칸이 함께 따른다(§3-C-4).
DEFAULT_SORT_OF_METHOD: Final[dict[str, str]] = {"score": "priority", "practical": "practical"}

#: 모집 성격 (기획서 1-1). 기업마당 수혜기업 모집은 매출 공고가 아니다(실무 문서 §4.2).
RECRUIT_BID: Final[str] = "입찰(매출)"
RECRUIT_OPERATOR: Final[str] = "수행기관 모집(매출)"
RECRUIT_BENEFIT: Final[str] = "수혜(지원금)"

#: 「최근 신규」 기간 — 실무순 · 브리핑의 「신규」는 7일이다. 첫 화면 띠 「새로 올라온 것」(3일)과 다른 값이다(D10).
FRESH_DAYS: Final[int] = 7
#: 3일 이하 꼬리표 (실무 문서 §2.5 「3일 이하: 원칙적으로 후순위」 · D3).
LATE_NOTE: Final[str] = "원칙적으로 후순위"
#: 대형 꼬리표 셋 (38차 D14 · DOCS-01) — **사업기회 행 꼬리표와 브리핑 판단 낱말이 같은 함수(`partner_tag`)를 쓴다.**
#: 실무 문서 §4.3 「공동수급 불가인데 파트너로 자격을 보완할 수 있다고 가정 금지」.
PARTNER_TAG_OK: Final[str] = "단독으로는 큼 · 파트너형"
PARTNER_TAG_NO: Final[str] = "단독으로는 큼 · 공동수급 불허"
PARTNER_TAG_UNKNOWN: Final[str] = "단독으로는 큼 · 공동수급 확인 필요"
#: 옛 이름(37차) — 공동수급 허용일 때의 꼬리표.
PARTNER_SCALE_TAG: Final[str] = PARTNER_TAG_OK
#: 44차 결정 4 — 등록 업종이 없는데 공동수급이 허용 · 모름인 공고(크기와 상관없이 파트너형 덩어리 · `eligibility_engine.industry_partner`)
INDUSTRY_PARTNER_TAG_OK: Final[str] = "업종 없음 · 파트너형(공동수급 허용)"
INDUSTRY_PARTNER_TAG_UNKNOWN: Final[str] = "업종 없음 · 파트너형(공동수급 확인 필요)"

#: 실무순 세 덩어리 (38차 D12 · 담당자 결정 4 — 실무 문서 §2.3-14 「대형 SI · 순수 연구는 후순위」 · TOP 이 A1~C 만 올리는 것과 같은 뜻).
BLOCK_CORE: Final[str] = "본업"
BLOCK_SIDE: Final[str] = "연구 · 감리 · 구매"
BLOCK_LARGE: Final[str] = "대형 · 파트너형 후보"
_BLOCK_ORDER: Final[dict[str, int]] = {BLOCK_CORE: 0, BLOCK_SIDE: 1, BLOCK_LARGE: 2}
#: 「대형 · 파트너형 후보」 덩어리의 분류 칸.
GROUP_PARTNER: Final[str] = "파트너형 후보"
#: 「주제 확인」 꼬리표(40차 결정 1 · D23) — 교육 · 컨설팅인데 공고명에 회사 사업 주제가 없는 공고. 숨기지도 접지도 않고 본업 덩어리 안에서
#: 주제가 맞는 공고 뒤에 둔다. 사업기회 행 · 쉬운 보기 · 브리핑 판단 칸 · 엑셀이 이 값 그대로다(`tags_of`).
TOPIC_TAG: Final[str] = "주제 확인 — 공고명에 회사 사업 주제가 없음"

TimeTier = Literal["T1", "T2", "T3", "T4", "TU", "T5", "T6"]
#: 시간 등급 이름(실무 문서 §4.1 「시간 우선순위」). TU = 마감 미상(43차 결정 1 — 입찰 마감이 비고 공고문 일정표도 못 읽음).
TIER_LABELS: Final[dict[str, str]] = {
    "T1": "공고 7일 이내 · 남은 21일 이상",
    "T2": "공고 14일 이내 · 남은 14일 이상",
    "T3": "사전규격(본공고 전)",
    "T4": "일반 접수 중",
    "TU": "마감 미상 — 공고문 일정표 확인",
    "T5": "남은 8~13일",
    "T6": "남은 7일 이하",
}
#: 마감 미상은 일반 접수 중 뒤 · 긴급 앞 — 실제 마감은 개찰 전이라 여유를 장담할 수 없다(공고문을 열어 볼 차례).
_TIER_ORDER: Final[dict[str, int]] = {"T1": 1, "T2": 2, "T3": 3, "T4": 4, "TU": 5, "T5": 6, "T6": 7}

#: 분류 칸 (기획서 1-4). 순서는 브리핑 · 엑셀이 칸을 적는 순서다.
GROUPS: Final[tuple[str, ...]] = ("선제준비", "신규+여유", "직접도전", "조건부", "일반 접수 중", "긴급", "파트너형 후보", "비추천", "제외")

#: 유형 서열(실무 문서 §2.5 4단계 · A1 > A2 > B1 > C > B2/D). 「수혜」는 매출 공고가 아니라 맨 뒤와 같은 자리다.
TYPE_ORDER: Final[dict[str, int]] = {"A1": 0, "A2": 1, "B1": 2, "C": 3, "B2": 4, "D": 4, "수혜": 4}
TYPE_LABELS: Final[dict[str, str]] = {
    "A1": "교육 운영",
    "A2": "교육 콘텐츠 · 과정 개발",
    "B1": "컨설팅",
    "B2": "연구",
    "C": "개발 · 구축",
    "D": "감리 · 구매 · 공사 · 미분류",
    "수혜": "지원금(수혜)",
}
#: D8 — 회사 단독 상한을 넘을 때 「대형」으로 보는 유형(개발 · 연구 · 그 밖).
_LARGE_TYPES: Final[frozenset[str]] = frozenset({"C", "B2", "D"})
#: 결정 2(39차 · 2026-10-18) — 교육 · 컨설팅(A1 · A2 · B1)은 회사 단독 상한의 **2배**를 넘으면 「대형 · 파트너형 후보」다.
#: 상한 ~ 2배 사이는 본업에 남기고 「규모 큼(단독 상한 n억)」 꼬리표만 단다(recheck31 P2 — 513억 운영 사업이 A1 이라 본업 1위였다).
_EDU_TYPES: Final[frozenset[str]] = frozenset({"A1", "A2", "B1"})
EDU_LARGE_FACTOR: Final[int] = 2

#: 교육 공고 중 A2(콘텐츠 · 교재 · 커리큘럼 · 과정개발).
_A2_RE: Final[re.Pattern[str]] = re.compile(r"콘텐츠|교재|교안|커리큘럼|과정\s*개발")

# 38차 §3-B-4 (PRACTICAL-03) — **제목 낱말을 먼저 본다.** 조달 분류명(「연구조사서비스」 · 「교육서비스」)이 갈래를 정하면
# 컨설팅 · 교육이 연구(B2)로, GPU 임차가 컨설팅(B1)으로, 「AI Professor 시스템 개발」이 교육(A1)으로 엇나갔다(recheck30).
#: 제목의 D — 임차 · 구매 · 감리 · 공사 · 검사.
#: 39차 §3-B-2 — PMC · 사업관리(ODA 프로젝트 관리 용역)는 컨설팅(B1)이 아니라 D 다(recheck31 P3 — 14.8~70.7억 ODA PMC 7건이 B1 이라 본업에 남았다).
#: 40차 RANK-02 — 「사업관리」는 **용역 · 위탁**일 때만 PMC 다(「사업관리체계 … AX … ISP 수립」은 컨설팅이 D 로 갔다).
#: 41차 G2 — 개인정보 · 보안 영향평가는 감리성 업무다(「… 시스템 개인정보 영향평가」가 개발(C)이었다).
_T_D: Final[re.Pattern[str]] = re.compile(
    r"임차|구매(?!\s*(?:주관|지원|연계))|감리|하자검사|(?:개인정보|보안)\s*영향\s*평가|PMC|(?:건설)?사업\s*관리\s*(?:용역|위탁|대행)"
    r"|(?:시설|신축|증축|보수|건축|전기|통신|소방|설비|토목|조경|정비|인테리어)\s*공사"
)
#: 40차 §3-B(G6) — AI 학습 데이터 구축 · 수집 · 가공 · 라벨링과 의료 AI(CDSS · CDW · 의료영상)는 우리가 수행사로 들어가는 개발이 아니다(D).
#: 공고명에 교육 낱말이 함께 있으면(「AI 학습데이터 구축 실무 교육」) 보지 않는다.
_T_D_DATA: Final[re.Pattern[str]] = re.compile(
    r"학습\s*(?:용\s*)?데이터\s*(?:구축|수집|가공|셋)|데이터\s*(?:수집|가공|정제|라벨링|표준화)|데이터셋\s*구축|라벨링|어노테이션"
)
#: 41차 G2 — 만성질환 · 보건의료 · Scribe(진료 기록 AI)도 의료 AI 다(「AI Scribe 솔루션 도입 및 실증(만성질환관리)」).
_T_D_MEDICAL: Final[re.Pattern[str]] = re.compile(
    r"CDSS|CDW|임상\s*의사\s*결정|의료\s*영상|의료\s*(?:AI|인공지능)|AI\s*의료|만성\s*질환|보건\s*의료|(?<![A-Za-z])Scribe(?![A-Za-z])", re.I
)
#: 제목의 C — 시스템 · 플랫폼 · 솔루션 · 앱 · 소프트웨어 · LMS 의 개발 · 구축 · 고도화.
_T_C: Final[re.Pattern[str]] = re.compile(r"(시스템|플랫폼|솔루션|앱|어플리케이션|소프트웨어|LMS|포털|서비스)[^,·]{0,12}?(개발|구축|고도화|도입)")
#: 제목의 A2 — 콘텐츠 · 교재 · 교과목 · 강의 · 이러닝 · K-MOOC · 커리큘럼 · 과정의 개발 · 제작(「교육」 낱말이 없어도).
#: 40차 §3-B — 「강의 (동)영상 제작」도 A2 다(「동영상 강의 영상 제작 사업」이 갈래 없이 개발(C)로 갔다).
_T_A2: Final[re.Pattern[str]] = re.compile(
    r"(콘텐츠|교재|교안|교과목|강의|강좌|이러닝|e-?Learning|K-?MOOC|커리큘럼|과정|수업모형|지도안)(?:\s*(?:동)?영상)?[^\s]{0,6}\s*(개발|제작)", re.I
)
#: 제목의 B1 — 컨설팅 · 전략 수립 · 로드맵 · 기본계획 · ISP(연구조사 분류명이 붙어도).
#: 39차 §3-B — 「과제 발굴 · 기획」 · 「기획 용역」도 컨설팅이다(「AX확산 신규 과제 발굴·기획 연구」 · 「AX 인프라 연계 실증 기획용역」이 연구(B2)였다).
#: 40차 §3-B(G5) — 「기획연구 · 기획 연구」(R&D 사업 기획연구)는 연구(B2)다 — B1 은 「과제 발굴 · 기획」 · 「기획 용역」만.
_T_B1_PLAN: Final[re.Pattern[str]] = re.compile(r"발굴\s*[·ㆍ・]?\s*기획|과제\s*기획|기획\s*용역")
#: 41차 CLASSIFY-R40-07 — 맨 「진단」은 넣지 않는다(「AI 기반 … 진단체계 개발」 · 「고장 진단 모델 개발」이 컨설팅이 됐다) — 역량 · 수준 ·
#: 성숙도 · 조직 · 경영 · 현황 진단 · 진단 컨설팅 꼴만. 연구 · 조사와 함께 온 맨 「진단」은 아래 `_T_B1_OVER_B2` 가 B1 로 본다.
_T_B1: Final[re.Pattern[str]] = re.compile(
    r"컨설팅|전략\s*수립|추진\s*전략|로드맵|기본\s*계획|계획\s*수립|ISP|ISMP|거버넌스\s*수립"
    r"|(?:역량|수준|성숙도|조직|경영|현황|디지털)\s*진단|진단\s*컨설팅",
    re.I,
)
#: 40차 §3-B(G4) — 연구 · 방안 · 실태가 컨설팅보다 먼저다. 다만 ISP · 컨설팅 · 진단 · 전략 수립이 함께 있으면 컨설팅(B1)이다
#: (「… 기반구축 사업 수요조사 및 추진전략 수립 용역」은 조사가 아니라 전략 컨설팅이다).
_T_B1_OVER_B2: Final[re.Pattern[str]] = re.compile(r"ISP|ISMP|컨설팅|진단|전략\s*수립|추진\s*전략", re.I)
#: 제목의 A1 — 교육 · 연수 · 아카데미 · 부트캠프 · 역량강화 · 워크숍 · 과정 운영 · 해커톤 · 특강(40차 D26 — 분류 낱말표와 같게).
_T_A1: Final[re.Pattern[str]] = re.compile(
    r"교육|연수|아카데미|부트캠프|역량\s*강화|워크숍|과정\s*운영|마이크로디그리|캠프|해커톤|아이디어톤|드래프톤|특강"
)
#: 데이터 · 의료 D 를 보지 않는 교육 낱말 — 41차 CLASSIFY-R40-06 · `_T_A1` 과 같은 목록 + 강의 · 인력 · 인재 양성 · 프로그램 운영 · 리터러시
#: (40차는 목록이 좁아 「의료 AI 해커톤 운영」 · 「의료영상 AI 역량강화 워크숍」이 의료 D 로 갔다).
_T_EDU_WORD: Final[re.Pattern[str]] = re.compile(
    _T_A1.pattern + r"|강의|강좌|교과목|인력\s*양성|인재\s*양성|양성\s*(?:과정|교육|프로그램)|프로그램\s*운영|리터러시"
)
#: 제목의 B2 — 연구. 40차 D26 — 「연구 · 행정 지원」 · 「연구자」 · 「연구원」처럼 수식어 · 사람 · 기관인 「연구」는 일이 아니다
#: (「한국해양과학기술원 연구 · 행정 지원 AI Agent 개발」이 개발(C)보다 먼저 연구로 갔다).
_T_B2: Final[re.Pattern[str]] = re.compile(r"연구(?![\s·ㆍ,/]*(?:행정|지원|실|소|원|센터|단|기관|자|진|팀))")
#: 기관 이름 속 「연구」(OO연구원 · 연구소 · 연구센터 · 연구재단 · 연구단) — 유형 근거가 아니다(40차 D26).
_RESEARCH_ORG_RE: Final[re.Pattern[str]] = re.compile(r"\S*(?:연구원|연구소|연구센터|연구재단|연구단)")
#: 39차 §3-B — 제목이 **연구 · 평가 용역**이면 「교육 · 역량강화」 낱말이 있어도 A1 보다 먼저 B2 다
#: (「건강피해조사 역량강화 방안 연구」 · 「교육혁신 거버넌스 … 발전 방안 연구」 · 「역량강화 사업 종료평가」가 A1 이었다).
#: 끝의 「연구 용역」만으로는 보지 않는다 — 교육과정 혁신 · 운영 체계 컨설팅도 「… 연구 용역」 이름을 쓴다(기준 답안 본업).
#: 40차 §3-B(G1 · G5 · G6) — 기획연구 · 실태조사 · 만족도 · 수요 · 요구도 조사 · 「방안 마련」도 연구다.
_T_B2_STRONG: Final[re.Pattern[str]] = re.compile(
    r"(?:방안|정책|기초|실태|타당성|학술|기획)\s*연구|종료\s*평가|성과\s*평가\s*용역"
    r"|(?:실태|만족도|수요|요구도|인식)\s*(?:및\s*\S{1,6}\s*)?조사|방안\s*마련"
)
#: 43차 M3 — 물건을 만드는 일(콘텐츠 · 영상 제작은 앞의 `_T_A2` 가 먼저 가져간다).
_T_MAKE: Final[re.Pattern[str]] = re.compile(r"설계\s*(?:및|·|ㆍ)?\s*제작|제작\s*(?:및\s*)?(?:설치|납품)|모듈\s*제작|시제품|양산|제조\s*(?:용역|및)")
#: 제목의 C(넓게) — 개발 · 구축 · 고도화.
_T_C_WIDE: Final[re.Pattern[str]] = re.compile(r"개발|구축|고도화")


def _title_type(title: str) -> tuple[str, str] | None:
    """제목만으로 정한 유형(근사)과 근거. 제목에 갈래가 없으면 None — 그때만 조달 분류명 갈래를 쓴다.

    39차 §3-B-1 — 「시스템 · 포털 · 망 + 유지관리 · 운영」은 A1 보다 먼저 D 다(「EBS … 교육 인터넷서비스 통합 운영」 513억이 A1 이었다).
    그 밖의 갈래는 **기관 · 시스템 이름 조각(「광주교육정보시스템」 · 「OO교육원」)을 지운 제목**에서 본다 — 이름 속 「교육」은 A1 이 아니다.
    """
    raw = opportunity_filter.strip_dept_labels(title or "")
    if opportunity_filter.IT_MAINTENANCE_TITLE_RE.search(raw):
        return "D", "공고명 시스템 · 포털 유지관리 · 운영"
    text = _RESEARCH_ORG_RE.sub(" ", opportunity_filter.core_title(raw))
    hit_d = _T_D.search(text)
    # 43차 Q2 · BRIEF-20 — 교육 · 이러닝과 함께 온 「임차 · 대여」는 교육 운영이다(「소상공인 이러닝 교육 임차 · 운영」이 D · 대형으로 갔다)
    # (「연수시설 임차」처럼 운영이 없으면 시설 빌리기라 D 그대로 — 비추천 접기의 「임차」 예외와 같은 꼴 `_EDU_OPERATION_RE`)
    if hit_d and not (hit_d.group(0) == "임차" and opportunity_filter._EDU_OPERATION_RE.search(text)):
        return "D", "공고명 임차 · 구매 · 감리 · 공사"
    if not _T_EDU_WORD.search(text) and not _T_B1_OVER_B2.search(text):
        # 교육 · 컨설팅 낱말이 함께 있으면 데이터 · 의료 꼴로 보지 않는다(「… 제조데이터 수집 컨설팅」은 컨설팅이다)
        if _T_D_MEDICAL.search(text):
            return "D", "공고명 의료 AI(CDSS · CDW · 의료영상)"
        if _T_D_DATA.search(text):
            return "D", "공고명 학습 데이터 구축 · 수집 · 가공"
    for pattern, typ, basis in (
        (_T_C, "C", "공고명 시스템 · 플랫폼 개발 · 구축"),
        (_T_A2, "A2", "공고명 콘텐츠 · 교과목 · 강의 · 과정 개발"),
        (_T_B1_PLAN, "B1", "공고명 과제 발굴 · 기획 용역"),
    ):
        if pattern.search(text):
            return typ, basis
    if _T_B2_STRONG.search(text):
        if not _T_B1_OVER_B2.search(text):
            return "B2", "공고명 연구 · 조사 · 평가 용역"
        # 연구 · 조사 + ISP · 컨설팅 · 진단 · 전략 수립 = 컨설팅(40차 G4 · 41차 — 맨 「진단」을 `_T_B1` 에서 뺀 뒤에도 같게)
        return "B1", "공고명 연구 · 조사 + 컨설팅 · 진단 · 전략 수립"
    if _T_B1.search(text) and _T_MAKE.search(text) and not _T_EDU_WORD.search(text):
        # 43차 M3 — 「UL인증 컨설팅 반영 … 컨버터 모듈 설계 및 제작 용역」은 컨설팅이 아니라 제작이다(D · 제조기업 오인 금지)
        return "D", "공고명 제작 · 제조(컨설팅 낱말이 있어도)"
    for pattern, typ, basis in (
        (_T_B1, "B1", "공고명 컨설팅 · 전략 수립 · 계획"),
        (_T_A1, "A1", "공고명 교육 · 연수 · 아카데미"),
        (_T_B2, "B2", "공고명 연구"),
        (_T_C_WIDE, "C", "공고명 개발 · 구축"),
    ):
        if pattern.search(text):
            return typ, basis
    return None
#: 감리 · 구매 · 공사 — 우리가 수행사로 들어가지 않는 일(work_kinds.NOT_OUR_ROLE 과 같은 축 · 연구는 B2 로 따로).
_D_KINDS: Final[frozenset[str]] = frozenset({"supervision", "procurement", "construction", "audit"})

# --------------------------------------------------------------------------
# 접수방식 (기획서 1-1 · 실무 문서 §2.5 3단계)
# --------------------------------------------------------------------------

METHOD_EMAIL: Final[str] = "이메일"
METHOD_ONLINE: Final[str] = "온라인/기관시스템(PMS)"
METHOD_VISIT: Final[str] = "방문"
METHOD_POST: Final[str] = "우편"
METHOD_UNKNOWN: Final[str] = "미상"
#: 직접 넣은 공고의 접수방식(양식의 말 그대로) 중 실무순 0 자리.
MANUAL_FAST_METHODS: Final[frozenset[str]] = frozenset({"이메일", "PMS/기관시스템", "온라인폼", "IRIS"})

_EMAIL_RE = re.compile(r"메일|e-?mail|@", re.I)
_ONLINE_RE = re.compile(r"온라인|홈페이지|누리집|시스템|접속|사이트|k-?startup|www\.|https?://|플랫폼|포털|구글|폼", re.I)
_VISIT_RE = re.compile(r"방문")
_POST_RE = re.compile(r"우편|등기")


def bizinfo_methods(text: str | None, reception_url: str | None) -> list[str]:
    """기업마당 신청방법 글 · 접수처 주소 → 「이메일 · 온라인/기관시스템(PMS) · 방문 · 우편」. 못 가리면 「미상」 하나.

    글이라 틀릴 수 있다 — 화면 · 파일에 원문 한 줄(`submission_text`)을 함께 싣는다.
    """
    body = text or ""
    found: list[str] = []
    if _said(_EMAIL_RE, body):
        found.append(METHOD_EMAIL)
    if _said(_ONLINE_RE, body) or (reception_url or "").strip():
        found.append(METHOD_ONLINE)
    if _said(_VISIT_RE, body):
        found.append(METHOD_VISIT)
    if _said(_POST_RE, body):
        found.append(METHOD_POST)
    return found or [METHOD_UNKNOWN]


#: 「이메일 접수 불가」 · 「방문 · 우편 접수는 받지 않음」 — 바로 뒤가 부정이면 그 방식이 아니다(38차 PRACTICAL-04 · 4건).
#: 괄호에서 끊는다 — 「온라인 접수(우편 접수 불가)」의 부정은 괄호 안 우편 몫이다(38차 검토).
_NEGATED_TAIL_RE = re.compile(r"^[^\n.;。(]{0,14}?(?:불가(?!피)|불인정|받지\s*않|하지\s*않|금지|안\s*됨)")


def _said(pattern: re.Pattern[str], body: str) -> bool:
    """그 방식을 **받는다고** 말한 곳이 하나라도 있는가 — 부정이 붙은 곳만 있으면 아니다."""
    return any(not _NEGATED_TAIL_RE.search(body[m.end():]) for m in pattern.finditer(body))


def g2b_methods(raw: dict | None) -> list[str]:
    """나라장터 `bidMethdNm`(전자입찰 · 직찰 · 전자시담) 그대로. 없으면 「미상」."""
    item = (raw or {}).get("item") if isinstance(raw, dict) else None
    value = str((item or {}).get("bidMethdNm") or "").strip()
    return [value] if value else [METHOD_UNKNOWN]


def method_rank(item: UnifiedOpportunity, *, home: bool) -> int:
    """같은 시간 등급 안의 접수방식 순서 — 이메일 · PMS · 온라인폼(0) → 광주 · 전남 기관 자체(1) → 직찰(2) → 전자입찰 · 미상(3).

    여럿이면 가장 앞선 것으로 본다. 기업마당의 방문 · 우편 접수는 기관에 직접 내는 것이라 직찰과 같은 자리(2)이고,
    소관 · 수행기관이 광주 · 전남이면 「기관 자체」(1)다.
    """
    methods = item.submission_methods or [METHOD_UNKNOWN]
    if item.source_type == "g2b":
        return 2 if any(m.startswith("직찰") for m in methods) else 3
    if item.source_type == "manual":
        # 직접 넣은 공고(38차 §3-E-3) — 이메일 · PMS · 온라인폼 · IRIS 0 → 광주 · 전남 기관 1 → 방문 · 우편 2 → 나라장터 · 미상 3.
        if any(m in MANUAL_FAST_METHODS for m in methods):
            return 0
        if home:
            return 1
        # 43차 M16 · SOURCE-11 — 「직찰 · 대학 자체 전자입찰」도 직찰 자리(2)
        return 2 if "방문/우편" in methods or any(m.startswith("직찰") for m in methods) else 3
    if METHOD_EMAIL in methods or METHOD_ONLINE in methods:
        return 0
    if METHOD_VISIT in methods or METHOD_POST in methods:
        return 1 if home else 2
    return 3


# --------------------------------------------------------------------------
# 유형 A1~D (근사 · 기획서 1-2)
# --------------------------------------------------------------------------


def type_of_kinds(kinds: Sequence[str], title: str, *, fallback: tuple[str, str] | None = None) -> tuple[str, str]:
    """유형(근사)과 그 근거. **제목 낱말을 먼저 보고**(38차 PRACTICAL-03), 제목에 갈래가 없을 때만 일의 종류(work_kinds ·
    조달 분류명 포함)를 쓴다. 점수에는 쓰지 않는다(D7).

    `fallback` — 제목 · 일의 종류 어디에도 갈래가 없을 때 「갈래 미분류 D」 대신 쓸 값(40차 D26 · 조달분류가 없는 사전규격)."""
    from_title = _title_type(title)
    if from_title is not None:
        if from_title[0] == "A1" and set(kinds) == {"development"}:
            # 39차 §3-B-1 — 제목에 「교육」이 있어도 일의 종류가 개발뿐이면 교육 운영(A1)이 아니다(RANK_BRIEF-01 · 13건).
            return "C", "공고명 「교육」 낱말은 있지만 일은 개발(일의 종류)"
        return from_title
    found = set(kinds)
    if found & _D_KINDS:
        return "D", "감리 · 구매 · 공사"
    if "research" in found:
        return "B2", "연구 용역"
    if "education" in found:
        if _A2_RE.search(title or ""):
            return "A2", "교육 + 콘텐츠 · 교재 · 과정 개발"
        return "A1", "교육 운영"
    if "consulting" in found:
        return "B1", "컨설팅"
    if "development" in found:
        return "C", "개발 · 구축"
    if fallback is not None:
        return fallback
    return "D", "갈래 미분류"


#: 40차 D26 — 사전규격 대체 유형에서 컨설팅(B1)으로 보는 본업 낱말.
_CONSULT_TERMS: Final[frozenset[str]] = frozenset({"컨설팅", "전략 수립", "계획 수립", "AX", "DX", "디지털 전환", "디지털전환", "ESG", "지속가능경영"})


#: 사전규격 대체 유형에서 교육 운영(A1)으로 보는 공고명 낱말 — 「AI · DX 혁신역량 성장지원 프로그램」은 컨설팅이 아니라 교육 프로그램이다.
#: 41차 — 교과 · 수업 · 강의 · 리터러시 · 워크숍 · 아이디어톤 · 드래프톤도(「K-LXP 활용 교과에 대한 생성형 AI 지원」은 학교 교과 일이다 ·
#: 40차 「그 밖 A1」을 없애며 잃지 않게).
_EDU_PROGRAM_RE: Final[re.Pattern[str]] = re.compile(
    r"프로그램|역량|교육|과정|캠프|아카데미|해커톤|아이디어톤|드래프톤|특강|연수|교과(?!서)|수업(?!료)|강의|강좌|리터러시|워크숍"
    r"|공유대학|이러닝|양성"
)


def prespec_fallback(match, title: str = "") -> tuple[str, str] | None:
    """조달분류가 없는 사전규격(40차 D26)의 대체 유형 — 후보(본업 낱말 · AI + 업무 · 개발)일 때만. 아니면 None(「갈래 미분류 D」 그대로).

    AI + 개발 낱말만이면 C · 공고명에 프로그램 · 역량 · 교육 …이 있으면 A1 · 컨설팅 · AX · DX · ESG 갈래 낱말이면 B1 ·
    **그 밖은 None**(「갈래 미분류 D」 — 41차 CLASSIFY-R40-03 · 40차는 그 밖을 A1 로 두어 「AI+ 페스타 행사 기획 · 운영 대행」이 본업에 섰다)."""
    if not getattr(match, "is_candidate", False):
        return None
    work = [*getattr(match, "matched_work", []), *getattr(match, "core_terms", [])]
    if getattr(match, "matched_dev", None) and not work:
        return "C", "사전규격 — 조달분류 없음 · 공고명 AI + 개발 낱말"
    if not _EDU_PROGRAM_RE.search(title or "") and any(term in _CONSULT_TERMS for term in work):
        return "B1", "사전규격 — 조달분류 없음 · 공고명 컨설팅 · AX · DX · ESG 낱말"
    if _EDU_PROGRAM_RE.search(title or ""):
        return "A1", "사전규격 — 조달분류 없음 · 공고명 본업 낱말(교육 · 역량 · 프로그램)"
    return None


def g2b_type(item: UnifiedOpportunity) -> tuple[str, str]:
    return type_of_kinds(item.work_kinds or [], item.title)


def bizinfo_type(title: str, summary: str | None, recruit_kind: str) -> tuple[str, str]:
    """기업마당 — 수혜면 「수혜」. 수행기관 모집(매출)이면 제목 · 요약을 나라장터와 같은 낱말표로 가린다."""
    if recruit_kind != RECRUIT_OPERATOR:
        return "수혜", "지원금을 받는 사업(매출 아님)"
    # 43차 M3 · BIZ-06 — 유형은 **제목에서만**(요약 속 「역량 강화」 한 마디로 실증 · 구매 주관기관 모집이 A1 「교육 운영」이 됐다)
    titled = _title_type(title)
    if titled is None:
        return "D", "수행기관 모집 · 갈래 미분류 D(제목에 갈래 낱말 없음)"
    return titled[0], f"수행기관 모집 · {titled[1]}"


# --------------------------------------------------------------------------
# 시간 등급 · 분류 · D8
# --------------------------------------------------------------------------


def effective_deadline(item: UnifiedOpportunity) -> datetime | None:
    """실제 마감 — 입찰 마감 · 참가자격 등록 마감 · 공고문 일정표 마감(참가신청 · 입찰등록 · 제출 · 필수 현장설명) 중 가장 이른 것
    (43차 결정 1 · 0922 §4-B-8). D-day · 남은 기간 · 시간 등급 · 할 일 기한 · 브리핑 · 엑셀이 모두 이 값 하나를 쓴다. 개찰일은 쓰지 않는다(H1)."""
    stamps = [d for d in (item.deadline, item.qualification_deadline, item.schedule_deadline) if d is not None]
    return min(stamps) if stamps else None


def deadline_kind(item: UnifiedOpportunity) -> str | None:
    """실제 마감의 이름 — 「참가신청 마감」 · 「입찰등록 마감」 · 「제출 마감」 · 「현장설명」(공고문) · 「등록 마감」(나라장터 참가자격 등록) ·
    「입찰 마감」 · 「신청 마감」(기업마당). 마감이 없으면 None."""
    real = effective_deadline(item)
    if real is None:
        return None
    if item.schedule_deadline is not None and item.schedule_deadline == real and (item.deadline is None or real < item.deadline):
        return item.schedule_deadline_label or "공고문 일정 마감"
    if item.qualification_deadline is not None and item.qualification_deadline == real and (item.deadline is None or real < item.deadline):
        return "등록 마감"
    if item.source_type == "bizinfo" or item.recruit_kind == RECRUIT_BENEFIT:
        return "신청 마감"
    return "입찰 마감"


#: 시각을 모르는 마감 뒤에 붙는 말(44차 M3) — 화면 `lib/deadline.TIME_UNKNOWN_NOTE` 와 같은 글.
TIME_UNKNOWN_NOTE: Final = "(시각 원문 확인)"


def deadline_time_known(item: UnifiedOpportunity) -> bool:
    """실제 마감의 시각을 아는가 — 실제 마감이 공고문 일정표 마감이고 그 줄에 날짜만 있었으면 False(44차 M3). 판정 · 순서는 그날 끝으로 센다."""
    real = effective_deadline(item)
    return not (real is not None and item.schedule_deadline is not None and real == item.schedule_deadline
                and item.schedule_deadline_time_known is False)


def deadline_stamp(item: UnifiedOpportunity) -> str:
    """실제 마감 「YYYY-MM-DD HH:MM」(KST) — 시각을 모르면 「YYYY-MM-DD (시각 원문 확인)」(엑셀 · CSV · 44차 M3). 마감이 없으면 빈 글."""
    real = effective_deadline(item)
    if real is None:
        return ""
    local = (real if real.tzinfo else real.replace(tzinfo=timezone.utc)).astimezone(KST)
    return f"{local:%Y-%m-%d %H:%M}" if deadline_time_known(item) else f"{local:%Y-%m-%d} {TIME_UNKNOWN_NOTE}"


def decision_text(item: UnifiedOpportunity, decision) -> str | None:
    """결정 한 줄(44차 M4) — 「참여 · 담당자 · 10/24」. 나라장터 · 직접 넣은 입찰 · 수행은 참여 낱말, 기업마당 · 직접 넣은 수혜는 신청 낱말
    (지원사업 화면 · 직접 넣기 탭의 결정 칸과 같은 낱말). 결정 파일이 없으면 None."""
    from app.services import decision_service

    if decision is None:
        return None
    support = item.source_type == "bizinfo" or (item.source_type == "manual" and item.recruit_kind == RECRUIT_BENEFIT)
    word = (decision_service.SUPPORT_LABELS if support else decision_service.BID_LABELS).get(decision.status, decision.status)
    if decision.status == "UNREVIEWED":
        return word
    when = f"{_kst_date(decision.decided_at):%m/%d}" if decision.decided_at else None
    return " · ".join(part for part in (word, decision.decided_by, when) if part)


def deadline_unknown(item: UnifiedOpportunity) -> bool:
    """마감 미상 — 나라장터 공고인데 입찰 마감도 등록 마감도 공고문 일정표도 없다(43차 결정 1). 개찰일만 있을 수 있다."""
    return item.source_type == "g2b" and item.opportunity_type != "pre_spec" and effective_deadline(item) is None


def deadline_display(item: UnifiedOpportunity, today: date, *, with_time: bool = False, year: bool = False) -> str:
    """실제 마감 한 칸(43차 M1 · 브리핑 · 엑셀 · 내려받기 · 이번 주 할 일이 같은 글) — 실제 마감이 입찰 마감보다 이르면 둘 다 적는다:
    「11/15(등록 마감) · 입찰 11/16」 · 「10/30(참가신청 마감) · 입찰등록 11/10」. 마감 미상은 「마감 미상 — 개찰 MM/DD(제출 마감 아님)」."""
    real = effective_deadline(item)
    if real is None:
        return deadline_unknown_text(item) if deadline_unknown(item) else (item.deadline_text or "마감일 없음")

    def fmt(moment: datetime, *, time_known: bool = True) -> str:
        local = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
        local = local.astimezone(KST)
        base = f"{local:%Y-%m-%d}" if year else (f"{local.month}/{local.day}" if local.year == today.year else f"{local:%y/%m/%d}")
        return f"{base} {local:%H:%M}" if with_time and time_known else base

    kind = deadline_kind(item)
    known = deadline_time_known(item)
    text = fmt(real, time_known=known)
    # 44차 M3 — 날짜만 있던 공고문 일정 마감은 23:59 를 적지 않는다: 「10/30(참가신청 마감 · 시각 원문 확인)」
    note = "" if known or not with_time else " · 시각 원문 확인"
    if kind and kind not in ("입찰 마감", "신청 마감"):
        text = f"{text}({kind}{note})"
    elif note:
        text = f"{text}{TIME_UNKNOWN_NOTE}"
    if kind and kind not in ("입찰 마감", "신청 마감"):
        if item.deadline is not None and item.deadline != real:
            text += f" · 입찰 {fmt(item.deadline)}"
    return text


def briefing_text(item: UnifiedOpportunity, today: date) -> str | None:
    """설명회 한 줄(43차 ELIG-06) — 공고문이 필수라 하면 「필수(불참 시 참가 불가)」 · 지났으면 「사실상 마감」, 공고문을 읽었는데 필수 표시가
    없으면 「필수 표시 없음」, 공고문을 못 읽었으면 「필수 참석인지는 공고문에서 확인」. 설명회가 없으면 None."""
    if item.briefing_at is None:
        return None
    local = (item.briefing_at if item.briefing_at.tzinfo else item.briefing_at.replace(tzinfo=timezone.utc)).astimezone(KST)
    when = f"설명회 {local:%m-%d %H:%M}"
    if item.briefing_required:
        return f"{when} — 필수(불참 시 참가 불가)" + (" · 지남 — 사실상 마감" if local.date() < today else "")
    if item.briefing_required is False:
        return f"{when} — 공고문에 필수 표시 없음"
    return f"{when} — 필수 참석인지는 공고문에서 확인"


def left_phrase(item: UnifiedOpportunity, today: date) -> str:
    """「남은 N일」 · 「오늘 마감」 · 「마감 미상」 · 「마감일 없음」(43차 BRIEF-18 — 「남은 오늘」을 쓰지 않는다)."""
    left = days_left(item, today)
    if left is None:
        return "마감 미상" if deadline_unknown(item) else "마감일 없음"
    return "오늘 마감" if left == 0 else f"남은 {left}일"


def deadline_unknown_text(item: UnifiedOpportunity) -> str:
    """「마감 미상 — 개찰 MM/DD(제출 마감 아님)」 · 개찰일도 없으면 「마감 미상 — 공고문 확인」."""
    if item.opening_at is not None:
        return f"마감 미상 — 개찰 {_kst_date(item.opening_at):%m/%d}(제출 마감 아님)"
    return "마감 미상 — 공고문 확인"


def _kst_date(moment: datetime) -> date:
    aware = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    return aware.astimezone(KST).date()


def days_left(item: UnifiedOpportunity, today: date) -> int | None:
    """실제 마감까지 남은 날(KST 달력 · 화면 D-day 와 같은 셈). 마감일이 없으면 None."""
    deadline = effective_deadline(item)
    return None if deadline is None else (_kst_date(deadline) - today).days


def age_days(item: UnifiedOpportunity, today: date) -> int | None:
    """공고(등록)일부터 오늘까지 지난 날. 공고일이 없으면 None."""
    return None if item.published_at is None else (today - _kst_date(item.published_at)).days


def time_tier(left: int | None, age: int | None, *, pre_spec: bool = False, unknown: bool = False) -> str:
    """시간 등급 T1~T6 (실무 문서 §4.1 「시간 우선순위」 · 기획서 1-3).

    - T1 공고 7일 이내 + 남은 21일 이상 · T2 공고 14일 이내 + 남은 14일 이상 · T3 사전규격(본공고 전 · 38차 §3-D)
    - T4 일반 접수 중(남은 14일 이상 또는 마감일 없음) · T5 남은 8~13일 · T6 남은 7일 이하
    마감일이 없는 공고는 T1 · T2 가 아니다 — 「남은 21일 이상」을 잴 수 없다(상시 · 예산 소진 시까지는 언제든 닫힌다).
    """
    if pre_spec:
        return "T3"
    if left is None and unknown:
        return "TU"
    if left is not None and left <= 7:
        return "T6"
    if left is not None and left <= 13:
        return "T5"
    if left is not None and age is not None:
        if age <= FRESH_DAYS and left >= 21:
            return "T1"
        if age <= 14 and left >= 14:
            return "T2"
    return "T4"


def group_of(item: UnifiedOpportunity, tier: str) -> str:
    """분류 칸 하나 (기획서 1-4). 위에서부터 처음 맞는 것. 「대형 · 파트너형 후보」 덩어리는 「파트너형 후보」 칸이다(38차 D12)."""
    if item.closed or item.eligibility_gate == "FAIL":
        return "제외"
    if item.relevance_note or not item.practical_candidate:
        return "비추천"
    if tier == "T3":
        return "선제준비"
    if item.practical_block == BLOCK_LARGE:
        return GROUP_PARTNER
    if tier in ("T5", "T6"):
        return "긴급"
    if tier == "T1":
        return "신규+여유"
    if item.eligibility_gate == "PASS":
        return "직접도전"
    if item.eligibility_gate == "CHECK" and (item.practical_company_gap or item.check_side == "company"):
        return "조건부"
    return "일반 접수 중"


# --------------------------------------------------------------------------
# 주제 확인 (40차 결정 1 · D23)
# --------------------------------------------------------------------------

#: 회사 사업 주제 낱말(D23 · 실무 문서 §2.3 · 회사 사업영역 AI · AX · 디지털 · ESG · 이러닝).
#: 검수자 기본 목록에 같은 갈래 낱말을 더했다 — 이러닝 갈래(온라인 · 사이버 · 원격 교육) · ESG 갈래(SDGs · 지속가능) · 디지털 기술 갈래
#: (컴퓨팅 · 클라우드 · 정보보호 · 블록체인 · XR). 기준 답안 「사이버교육 운영」 · 「SDGs 아카데미」가 주제 확인으로 갔다(40차 §3-C 측정).
TOPIC_TERMS: Final[tuple[str, ...]] = (
    "인공지능", "생성형", "챗봇", "에이전트", "ChatGPT", "Copilot", "머신러닝", "딥러닝", "디지털", "데이터", "소프트웨어", "코딩",
    "정보화", "업무자동화", "탄소중립", "이러닝", "e-Learning", "온라인 교육 콘텐츠", "메타버스",
    "온라인", "사이버교육", "사이버 교육", "원격교육", "원격 교육", "원격수업", "SDGs", "지속가능",
    "컴퓨팅", "클라우드", "정보보호", "사이버보안", "블록체인",
    # 41차 G3 — 정보보호 갈래(「침해사고 수사과정 교육」이 주제 확인으로 갔다)
    "정보보안", "침해사고", "해킹", "포렌식",
    # 43차 Q1 · M5 — 가명정보 · 개인정보(보호)는 데이터 · 정보보호 주제다(「가명정보 전문인력 양성 교육」이 주제 확인으로 81위였다)
    "가명정보", "개인정보",
)
#: 짧은 영문 주제 낱말 — 앞뒤가 영문자면 아니다(「MAIN」의 AI · 「TAX」의 AX). 41차 TOPIC-06 — 대소문자는 가리지 않는다(「Ai 리터러시」 ·
#: 분류기 `opportunity_filter._contains` 와 같게).
_TOPIC_ASCII_RE: Final[re.Pattern[str]] = re.compile(
    r"(?<![A-Za-z])(?:AI|LLM|RAG|DX|AX|SW|ESG|GPT|XR|VR|AR|IoT)(?![A-Za-z])", re.I
)
#: 대소문자를 가리는 꼴 — 소문자 바로 뒤의 「AI」 마디(「eduAI」) · AI 로 시작하는 약어(41차 TOPIC-03 · AICC · AIDT · AIoT · AICE · AIX · AIDX).
_TOPIC_CASED_RE: Final[re.Pattern[str]] = re.compile(r"(?<=[a-z])AI(?![A-Za-z])|(?<![A-Za-z])AI(?:CC|DT|oT|CE|X|DX)(?![A-Za-z])")
#: 교육과정 · 교과목 · 커리큘럼을 만들거나 고치는 일 — 유형이 A1 · B1 로 잡혀도 A2 처럼 주제와 상관없이 맞음(실무 문서 §2.3-8 · D23 의 A2 예외와 같은 뜻).
_CURRICULUM_WORK_RE: Final[re.Pattern[str]] = re.compile(
    r"교육\s*과정[^,]{0,6}?(?:개발|개편|혁신|설계|구축|체계|컨설팅|도입|고도화)|교과목\s*(?:개발|개편|컨설팅|설계)|커리큘럼"
)
#: 주제 낱말이 든 **학교 · 재단 · 진흥원 이름**(「디지털미디어고」 · 「OO데이터진흥원」)은 주제가 아니다. 「…사고」(침해사고)는 학교 이름이 아니다(41차 G3).
_TOPIC_ORG_SUFFIX_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:고등학교|중학교|초등학교|대학교|재단|진흥원|공사|공단|협회|(?<![보최광참재경신사])고)$"
)


def _topic_text(title: str) -> str:
    """주제를 볼 공고명 — 앞 괄호 부서 이름 · 기관 이름 조각(「OO교육청」)을 지우고, 주제 낱말이 든 학교 · 재단 이름 낱말을 뺀 것."""
    text = opportunity_filter.core_title(opportunity_filter.strip_dept_labels(title or ""))
    words = re.split(r"(\s+|[()\[\]「」『』<>·,])", text)
    return "".join(w for w in words if not (_TOPIC_ORG_SUFFIX_RE.search(w) and _has_topic(w)))


def _has_topic(text: str) -> bool:
    """주제 낱말이 있나 — 41차 TOPIC-07 띄어쓰기를 무시한다(「업무 자동화」 · 「탄소 중립」 · 공고명 검색과 같게)."""
    if _TOPIC_ASCII_RE.search(text) or _TOPIC_CASED_RE.search(text):
        return True
    squeezed = re.sub(r"\s+", "", text).lower()
    return any(re.sub(r"\s+", "", term).lower() in squeezed for term in TOPIC_TERMS)


def topic_of(item: UnifiedOpportunity) -> str | None:
    """「주제 확인」 꼬리표 하나 또는 None(주제 맞음 · 대상 아님) — **주제 판단은 이 함수 한 곳**(D23).

    대상: 나라장터 입찰 · 사전규격 · 직접 넣은 입찰(기업마당 · 직접 넣은 수혜 · 수행기관 모집은 아님).
    유형(근사) A1 · B1 이면 공고명에 회사 주제 낱말이 있어야 맞음 · A2(교육과정 · 콘텐츠 개발)는 주제와 상관없이 맞음(실무 문서 §2.3-8) ·
    C(AI 개발)는 맞음 · 그 밖(B2 · D)은 본업 덩어리 밖이라 대상 아님. 실무 문서 §2.3 의 일반 「직업훈련 · 교육훈련」도 주제 확인이다.
    """
    if item.source_type == "bizinfo" or (item.source_type == "manual" and item.recruit_kind != RECRUIT_BID):
        return None
    if item.fit_type not in ("A1", "B1"):
        return None
    text = _topic_text(item.title)
    if _CURRICULUM_WORK_RE.search(text):
        return None
    return None if _has_topic(text) else TOPIC_TAG


def tags_of(item: UnifiedOpportunity) -> list[str]:
    """행 꼬리표 — 대형(`partner_tag`) 또는 「규모 큼」(`scale_tag`) · 「주제 확인」 · AI 「본업 아닐 수 있음」.
    **사업기회 행 · 브리핑 판단 칸 · 엑셀 · 표가 이 한 함수의 값을 쓴다**(40차 RANK-05 — 「규모 큼」이 TOP 칸에만 붙었다).
    41차 REGRESS-08 — 대형 꼬리표도 넣는다(내려받은 파일 「꼬리표」 칸에 공동수급 불허가 빠졌다 · 브리핑 판단 칸은 낱말과 겹치면 한 번만)."""
    return [t for t in (item.partner_tag, item.scale_tag, item.topic_note, item.ai_fit_note, item.same_program_note) if t]


def is_partner_scale(item: UnifiedOpportunity, ceiling_krw: int) -> bool:
    """대형 — 개발 · 연구 · 그 밖(C · B2 · D)은 사업비가 회사 단독 상한을 넘을 때, 교육 · 컨설팅(A1 · A2 · B1)은 상한의 2배를
    넘을 때(결정 2 · 39차). **문턱 계산은 여기 한 곳** — 꼬리표(`partner_tag` · `scale_tag`)와 덩어리(`block_of`)가 함께 쓴다."""
    if not item.budget:
        return False
    if item.fit_type in _LARGE_TYPES:
        return item.budget > ceiling_krw
    if item.fit_type in _EDU_TYPES:
        return item.budget > ceiling_krw * EDU_LARGE_FACTOR
    return False


def scale_tag(item: UnifiedOpportunity, ceiling_krw: int) -> str | None:
    """「규모 큼(단독 상한 n억)」 — 교육 · 컨설팅(A1 · A2 · B1)이 상한보다 크고 2배 이하라 본업에 남는 공고(결정 2). 아니면 None."""
    if not item.budget or item.fit_type not in _EDU_TYPES or item.industry_partner:
        return None  # 44차 결정 4 — 업종 없음 · 파트너형은 파트너형 덩어리(「본업에 남김」 풀이가 틀린다)
    if ceiling_krw < item.budget <= ceiling_krw * EDU_LARGE_FACTOR:
        return f"규모 큼(단독 상한 {ceiling_krw / 100_000_000:g}억)"
    return None


def joint_state(item: UnifiedOpportunity) -> bool | None:
    """공동수급 허용인가 — 계약 · 낙찰 한 줄(ELIG-AWARD · `eligibility_engine._joint_text`)을 읽는다. 모르면 None."""
    line = item.award_line or ""
    if "함께 참가할 수 있음" in line:
        return True
    if "함께 참가할 수 없음" in line:
        return False
    return None


def partner_tag(item: UnifiedOpportunity, ceiling_krw: int) -> str | None:
    """대형 꼬리표 한 줄 — **사업기회 행과 브리핑 판단 낱말이 함께 쓰는 단 하나의 함수**(38차 D14 · DOCS-01). 대형이 아니면 None.
    등록 업종이 없는데 공동수급 허용 · 모름이면 크기와 상관없이 「업종 없음 · 파트너형(…)」(44차 결정 4)."""
    if item.industry_partner and item.recruit_kind not in (RECRUIT_BENEFIT, RECRUIT_OPERATOR):
        return INDUSTRY_PARTNER_TAG_OK if item.industry_partner == "allowed" else INDUSTRY_PARTNER_TAG_UNKNOWN
    if not is_partner_scale(item, ceiling_krw):
        return None
    state = joint_state(item)
    return PARTNER_TAG_OK if state is True else PARTNER_TAG_NO if state is False else PARTNER_TAG_UNKNOWN


def block_of(item: UnifiedOpportunity, ceiling_krw: int, *, home: bool) -> str:
    """세 덩어리 하나 (38차 D12).

    - 본업: A1 · A2 · B1 · C(대형 아님) · 기업마당 수혜 · 수행기관 모집 · 광주 · 전남 발주 대형(꼬리표만)
    - 연구 · 감리 · 구매: B2 · D(대형 아님)
    - 대형 · 파트너형 후보: 사업비 > 회사 단독 상한이고 C · B2 · D, 사업비 > 상한 × 2 이고 A1 · A2 · B1(결정 2 · 광주 · 전남 발주는 빼고)
    """
    if item.recruit_kind in (RECRUIT_BENEFIT, RECRUIT_OPERATOR):
        return BLOCK_CORE
    if item.industry_partner:
        return BLOCK_LARGE  # 44차 결정 4 — 업종 없음 · 공동수급 허용(모름)은 크기 · 광주 · 전남 발주와 상관없이 파트너형
    if is_partner_scale(item, ceiling_krw) and not home:
        return BLOCK_LARGE
    if item.fit_type in ("B2", "D"):
        return BLOCK_SIDE
    return BLOCK_CORE


def annotate(items: Iterable[UnifiedOpportunity], *, now: datetime, ceiling_krw: int, home_of=None) -> None:
    """시간 등급 · 덩어리 · 분류 칸 · 대형 꼬리표 · 3일 이하 꼬리표를 매긴다. 점수 · 판정은 건드리지 않는다.

    `home_of(item) -> bool` 은 광주 · 전남 기관인가(대형이어도 본업 덩어리에 남긴다). 사전규격(`opportunity_type="pre_spec"`)은
    T3 「선제준비」다(38차 §3-D — 37차까지는 `pre_spec` 을 아무도 넘기지 않았다).
    """
    today = _kst_date(now)
    for item in items:
        left = days_left(item, today)
        tier = time_tier(left, age_days(item, today), pre_spec=item.opportunity_type == "pre_spec", unknown=deadline_unknown(item))
        item.time_tier = tier  # type: ignore[assignment]
        home = bool(home_of(item)) if home_of else False
        item.practical_block = block_of(item, ceiling_krw, home=home)
        item.partner_tag = partner_tag(item, ceiling_krw)
        item.scale_tag = scale_tag(item, ceiling_krw)
        item.partner_scale = item.practical_block == BLOCK_LARGE
        item.practical_group = group_of(item, tier)  # type: ignore[assignment]
        # 40차 D23 — 「주제 확인」은 본업 덩어리 안에서만 뜻이 있다(점수순 회사도 꼬리표는 붙는다 · 순서는 실무순만 바뀜).
        # 41차 TOPIC-09 — 비추천 · 제외로 접힌 행에는 달지 않는다(풀이 「본업 칸 안에서 뒤에 둡니다」가 틀린다).
        folded = item.practical_group in ("제외", "비추천")
        item.topic_note = topic_of(item) if item.practical_block == BLOCK_CORE and not folded else None
        item.deadline_note = LATE_NOTE if (left is not None and 0 <= left <= 3 and not item.closed) else None


def practical_key(item: UnifiedOpportunity, *, today: date, home: bool) -> tuple:
    """실무 우선순위 정렬 키 (기획서 1-3 · 38차 D12 · D13).

    제외(마감 · 불가)는 맨 뒤, 비추천(관련 낮음 · 후보 아님)은 그 앞에 따로 모은다. 나머지는
    **덩어리(본업 → 연구 · 감리 · 구매 → 대형 · 파트너형 후보)** → 시간 등급 → T6 안에서 3일 이하는 4~7일 뒤(D13) →
    접수방식 → 유형 → 점수 높은 순 → 남은 기간 긴 순. 37차 「D8 = 그 등급 맨 뒤」는 덩어리로 바꿨다(담당자 결정 4).
    기업마당 지원금(수혜)만 점수 → 시간 등급 → 마감 빠른 순이다(39차 D17 · 매출 쪽은 그대로). 43차 Q12 — 수혜 긴급(13일 이하)은 그 뒤.
    """
    group = item.practical_group or "일반 접수 중"
    bucket = 2 if group == "제외" else 1 if group == "비추천" else 0
    left = days_left(item, today)
    score = item.company_priority_score
    tier = item.time_tier or "T4"
    # 직접 넣은 수혜도 같은 줄이다 — 실무 순번은 출처 전체에 매기고 브리핑 지원금 칸은 두 출처를 그 순번으로 섞어 세운다
    # (기업마당만 이 줄이면 30점 직접 넣은 수혜가 80점 기업마당 수혜보다 늘 앞에 섰다 · 39차 마지막 검토).
    if item.recruit_kind == RECRUIT_BENEFIT and item.source_type in ("bizinfo", "manual"):
        # 39차 D17 — 기업마당 지원금(수혜)은 **점수 먼저**: 회사 기준 검토 우선순위 → 시간 등급 → 마감 빠른 순. 수혜는 유형 서열이 모두
        # 같아 시간 등급이 순서를 정했다(recheck31: 점수 21~58 의 T1 · T2 가 「가능 · 80점」보다 앞). 「신규+여유」 등 칸은 꼬리표로 남는다.
        # 둘째 자리(1)는 다른 모양의 키와 섞여 견주지 않게 하는 갈래 표시다 — 순위는 갈래(출처) 안에서만 쓴다.
        deadline = effective_deadline(item)
        # 43차 Q12 — 수혜 긴급(13일 이하)은 점수 다음 자리로 내린다(탭 2~4위가 마감 8 · 8 · 4일 긴급 건이었다 · 탭 · 브리핑 지원금 1위를 같게)
        urgent = 1 if tier in ("T5", "T6") else 0
        return (bucket, 1, urgent, -(score if score is not None else -1), _TIER_ORDER.get(tier, 4),
                deadline.timestamp() if deadline else float("inf"), item.id)
    return (
        bucket,
        0,
        _BLOCK_ORDER.get(item.practical_block or BLOCK_CORE, 0),
        # 40차 결정 1 · 2 — 본업 덩어리 안에서 주제 맞음 → 「주제 확인」 · AI 「본업 아닐 수 있음」(같은 자리) · 그 안은 지금 순서 그대로
        topic_rank(item),
        _TIER_ORDER.get(tier, 4),
        1 if tier == "T6" and left is not None and left <= 3 else 0,
        method_rank(item, home=home),
        TYPE_ORDER.get(item.fit_type or "D", 4),
        -(score if score is not None else -1),
        # 남은 기간 긴 순 — 마감일이 없으면 가장 긴 것으로 본다(같은 등급 T4 안에서만 만난다).
        -(left if left is not None else 10_000),
        item.id,
    )


def topic_rank(item: UnifiedOpportunity) -> int:
    """본업 덩어리 안 주제 자리 — 맞음 0 · 「주제 확인」 · AI 「본업 아닐 수 있음」 1. 다른 덩어리 · 비추천 · 제외는 늘 0(41차 TOPIC-09)."""
    if (item.practical_block or BLOCK_CORE) != BLOCK_CORE or item.practical_group in ("제외", "비추천"):
        return 0
    return 1 if (item.topic_note or item.ai_fit_note) else 0


def order(items: Sequence[UnifiedOpportunity], *, now: datetime, home_of) -> list[UnifiedOpportunity]:
    """실무 우선순위로 세운 새 목록. `practical_order`(1부터)를 매긴다. `home_of(item) -> bool` 은 광주 · 전남 기관인가."""
    today = _kst_date(now)
    ranked = sorted(items, key=lambda i: practical_key(i, today=today, home=home_of(i)))
    for index, item in enumerate(ranked, start=1):
        item.practical_order = index
    return ranked


def g2b_dates(raw: dict | None) -> tuple[datetime | None, datetime | None]:
    """설명회 일시(`dcmtgOprtnDt`) · 공동수급협정 마감(`cmmnSpldmdAgrmntClseDt`). 없으면 None — 「없음」으로 단정하지 않는다."""
    item = (raw or {}).get("item") if isinstance(raw, dict) else None
    item = item or {}
    return (
        g2b_mapper.parse_datetime(str(item.get("dcmtgOprtnDt") or "")),
        g2b_mapper.parse_datetime(str(item.get("cmmnSpldmdAgrmntClseDt") or "")),
    )
