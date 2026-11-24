"""AI·AI교육 공고 후보 필터 (키워드 기반, 규칙만 사용).

CLAUDE.md 4-B의 1차/2차 키워드를 그대로 쓴다.
이 단계는 '의미 유사도(Semantic Matching)'가 아니라 **키워드 매칭**이며,
매칭된 키워드를 근거로 함께 남긴다. 임베딩 기반 적합도는 Phase 3에서 추가한다.

등급
    high  : AI 키워드 + 2차 키워드(교육·컨설팅 **또는** 개발) 매칭 → 후보
    low   : 한쪽만 매칭(AI만 / 교육·컨설팅만), 또는 팀 규모를 넘는 개발 사업 → 후보 아님
    none  : 매칭 없음

`low` 는 «지운 것»이 아니라 «내린 것»이다. API 는 `include_low=true` 로 그대로 돌려준다.
**다만 지금 화면에는 그 스위치가 없다** — 프론트엔드에서 `include_low` 를 보내는 호출부가
한 곳도 없다(2026-09-10 확인). 그래서 강등된 공고는 현재 UI 에서는 볼 수 없다.
「조용히 사라지면 놓친 줄도 모른다」는 원칙을 지키려면 화면에 스위치를 붙여야 한다.

`medium` 은 예전에 「AI 키워드만 매칭」에 주던 등급이고, 지금은 **아무 공고도 받지 않는다**.
AI 단독 공고는 「AI타워ㆍ지하주차장 …」·「AI-Science 데이터센터 신축사업 설계용역」처럼
«AI» 가 건물·센터 **이름의 일부**로 쓰인 것이 대부분이라 기본 화면에서 내렸다
(2026-09-10 실수집 87건 기준: AI 단독 4건 중 3건이 이 유형).
값 자체는 예전 캐시·스냅샷 JSON 에 남아 있어 Literal 에서 빼지 않는다.

2차 키워드는 두 갈래다 — 회사가 교육·컨설팅과 개발을 모두 하기 때문이다.
개발 사업은 예산으로 규모를 한 번 더 보고, 3인 팀 상한을 넘으면 `low` 로 낮춘다(빼지는 않는다).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from app.schemas.procurement import ProcurementNotice

# 1차: AI 관련 키워드
AI_KEYWORDS: tuple[str, ...] = (
    "AI",
    "인공지능",
    "생성형",
    "생성AI",
    "ChatGPT",
    "챗GPT",
    "LLM",
    "Copilot",
    "머신러닝",
    "딥러닝",
    # AI 기술 어휘 — 공고명에 「AI」가 없어도 이 말이 있으면 AI 사업이다.
    # 샘플에듀 개발진이 실제로 구현해 본 영역이기도 하다.
    "RAG",
    "검색증강",
    "챗봇",
    "에이전트",
    "프롬프트",
    "임베딩",
    "벡터DB",
    # 38차 §3-A — AX(AI 전환) · GPT 도 AI 낱말이다. 「AX 컨설팅」 · 「M.AX 아카데미」가 AI 사업인데 낱말표에 없었다(recheck30).
    "AX",
    "GPT",
)

# 2차: 업무(교육·컨설팅) 키워드
#: 나라장터를 **공고명으로 찾을 때** 쓰는 키워드 (0920.md §4-A-1).
#:
#: `AI_KEYWORDS` 전부를 쓰지 않는 이유는 호출 예산 때문이다. 키워드 하나가 호출 하나이고
#: 예산은 15회다. 그래서 실제로 공고명에 자주 쓰이는 핵심만 고른다 — 여기서 빠진 말
#: (`생성AI`·`ChatGPT`·`Copilot`·`검색증강`·`임베딩`·`벡터DB`)은 대개 「AI」나 「생성형」과
#: 함께 적히므로, 받아 온 뒤 `classify()` 가 그 말들로 후보를 가린다.
#:
#: 실측(2026-09-17, 30일 창, 마감 전): AI 193 · 인공지능 7 · 생성형 7.
#:
#: **38차 §3-A — 회사 사업영역(`profile.business_domains`) 기준으로 넓혔다**(담당자 결정 2026-10-14).
#: recheck30: 매출 공고 47건 중 25건이 나라장터에 있는데 제목에 AI 낱말이 없어 받지 않았다(AX · ESG 컨설팅 ·
#: 교육 위탁운영 · 과정 · 콘텐츠 개발 · 아카데미 · 디지털 역량). 실측(2026-10-15 · 30일 창 · 마감 전 · 용역,
#: `docs/reports/2026-11-04_round38_progress.md` L1 표): 교육 177 · 콘텐츠 63 · 역량강화 47 · 디지털 47 · 컨설팅 32 ·
#: AX 22 · 교과목 6 · 강의 6 · 아카데미 8 · 부트캠프 7 · 이러닝 3 · ESG 3 · 지속가능 5 · 전략 수립 15.
#:
#: 고른 기준 — 나라장터 공고명 검색은 **부분 일치**다(띄어쓰기 무시 — 「역량강화」 = 「역량 강화」 = 47건). 그래서
#: 「교육」 하나가 교육운영 · 교육과정 · 교육훈련 · 평생교육을 모두 덮어 따로 넣지 않는다. 「교육」이 없는 본업 제목을
#: 덮는 말만 더한다(콘텐츠 · 강의 · 교과목 · 이러닝 · 아카데미 · 부트캠프 · 역량강화 · 디지털 · 컨설팅 · 전략 수립 · AX · ESG · 지속가능).
#: 넣지 않은 것과 이유: 위탁운영 86(대부분 시설 · 주차 위탁운영 — 교육 위탁운영은 「교육」이 덮음) · 데이터 81(데이터센터 ·
#: 자료 구축 — AI 데이터 사업은 「AI」가 덮음) · 연수 47(해외연수 · 연수원 시설 — 직무연수는 「교육」 · 「역량강화」가 대개 덮음) ·
#: 정보화 15(정보화 전략 컨설팅은 「컨설팅」 · 「전략 수립」이 덮음) · K-MOOC 4 · 리터러시 1(「콘텐츠」 · 「디지털」이 덮음) ·
#: GPT · ChatGPT · Copilot 0 · DX 2 · 워크숍 4 · 직무 7 · SW · 소프트웨어 17 · 클라우드 9 · 지속가능 5(「ESG」 · 「전략 수립」이 덮음).
#: AI 쪽에서 뺀 것: 생성형 · LLM · 프롬프트 — 10-15 저장본에서 「AI」 · 「인공지능」 없이 이 말로만 받은 공고가 0건이다
#: (분류 낱말 `AI_KEYWORDS` 에는 그대로 있다). 그 자리를 「e-Learning」(「SNUH e-Learning 위탁운영」)에 쓴다.
#: 잡음(교육여행 · 안전교육 등)은 버리지 않고 `classify` 가 비추천과 사유로 둔다(D15).
#: 하루 호출: 키워드 × 7일 창 다섯 약 110회(2.8.1 — 조달청 조회 기간 상한 7일) + 자격 하루치 4~6회 — `g2b_client.MAX_COLLECT_CALLS` 안.
COLLECT_KEYWORDS: tuple[str, ...] = (
    "AI",
    "인공지능",
    "챗봇",
    "에이전트",
    "머신러닝",
    "딥러닝",
    "RAG",
    # 38차 §3-A — 회사 사업영역(교육 · 과정 · 콘텐츠 개발 · 컨설팅 · AX · ESG · 디지털 역량)
    "교육",
    "콘텐츠",
    "강의",
    "교과목",
    "이러닝",
    "e-Learning",
    "아카데미",
    "부트캠프",
    "역량강화",
    "디지털",
    "컨설팅",
    "전략 수립",
    "AX",
    "ESG",
)

WORK_KEYWORDS: tuple[str, ...] = (
    "교육",
    "실무교육",
    "역량강화",
    "연수",
    "아카데미",
    "교육운영",
    "교육과정",
    "강사",
    "컨설팅",
    "업무자동화",
    "디지털전환",
    "디지털 전환",
    "DX",
)

#: 38차 §3-A — 더한 업무 낱말. **제목에서만 본다.** 설명 칸의 조달 분류명(「행사기획 · 운영서비스」)에 「기획」이 들어 있어
#: 그대로 보면 AI 행사 · 포럼 장비 대행까지 후보가 됐다(같은 저장본 전후 덤프에서 확인).
#: 「AI동행 데모데이 기획 · 운영」이 업무 낱말이 없어 관련 낮음으로 숨었다(recheck30).
WORK_TITLE_KEYWORDS: tuple[str, ...] = (
    "역량 강화",
    "기획",
    "워크숍",
    "퍼실리테이션",
    "부트캠프",
    "경진대회",
    "계획 수립",
    "전략 수립",
    "교과목",
    "강의",
    "이러닝",
    "콘텐츠 개발",
    "콘텐츠 제작",
    "과정 운영",
    "과정운영",
    "과정 개발",
    "과정개발",
    "마이크로디그리",
    # 39차 §3-A(P9) — 「AI 캠프 프로그램 운영」 · 「AI 해커톤 운영」(work_kinds 의 「프로그램 운영」과 같은 뜻 · AI 경로에서만)
    "프로그램 운영",
    # 40차 §3-B — 학교 교과 · 수업(「K-LXP 활용 교과에 대한 생성형 AI 지원」 · 「AI 활용 수업 지원」) — 41차 CLASSIFY-R40-10 낱말 경계
    # (「교과서」 · 「수업료」는 아니다 · `_WORK_BOUNDARY`)
    "교과",
    "수업",
    "해커톤",
    "특강",
    # 41차 G4 — 해커톤과 같은 경진 운영 꼴(「AI 드래프톤 운영」이 「AI 낱말만」으로 접혔다)
    "아이디어톤",
    "드래프톤",
)

#: AI 낱말 없이도 **회사 본업 갈래**인 제목 낱말 (38차 §3-A · 담당자 결정 1).
#:
#: 회사자료 사업영역: 「AI·AX 교육 및 인력양성 · ESG·공급망·지속가능경영 · 공공 위탁교육 및 과정개발」.
#: 그래서 교육 운영 · 과정 · 콘텐츠 · 교과목 개발 · 컨설팅 · ESG · AX · DX · 디지털 역량은 AI 낱말이 없어도 후보다.
#: **제목만 본다** — 설명 칸에는 조달 분류명(「교육 및 전문직종/기술서비스 > 교육서비스」)이 들어 있고, 기관명에는
#: 「교육청」이 들어 있어 그대로 보면 교육청의 공사 · 급식 공고까지 본업이 된다.
CORE_TERMS: tuple[str, ...] = (
    "교육",
    "연수",
    "역량강화",
    "역량 강화",
    "아카데미",
    "부트캠프",
    "교과목",
    "강의",
    "이러닝",
    "e-Learning",
    "K-MOOC",
    "원격수업",
    "리터러시",
    "컨설팅",
    "ESG",
    "지속가능경영",
    "AX",
    "DX",
    "디지털 전환",
    "디지털전환",
    "디지털 역량",
    "디지털역량",
    "워크숍",
    "퍼실리테이션",
    "과정 운영",
    "과정운영",
    "과정 개발",
    "과정개발",
    "마이크로디그리",
    # 40차 §3-B — 마이크로러닝(이러닝 콘텐츠의 한 꼴 · 「마이크로러닝스토어(MLS) 콘텐츠 변환」이 수집 낱말만으로 접혔다)
    "마이크로러닝",
    # 39차 §3-A(P9 · COLLECT-08) — 「AI 위협탐지 대응 실무인력 양성」 · 「DSC공유대학 온라인 콘텐츠 개발」이 접혔다.
    # `work_kinds` 교육 정규식(인력 · 인재 양성 · 양성 과정 · 프로그램 운영)과 같은 뜻으로 맞춘다 — 맨 「양성」은 넣지 않는다
    # (「하이퍼링커 양성 플랫폼 구축」처럼 양성 프로그램에 쓸 물건을 만드는 사업이 끌려온다).
    "인력양성",
    "인력 양성",
    "인재양성",
    "인재 양성",
    "양성과정",
    "양성 과정",
    "양성교육",
    "양성 교육",
    "양성사업",
    "양성 사업",
    "양성 프로그램",
    # 「콘텐츠 개발」 · 「프로그램 운영」은 넣지 않는다 — 같은 저장본에서 먹자골목 · 미식 · 관광 콘텐츠와 창업 · 지역 IP 프로그램이 끌려왔다.
    # 「프로그램 운영」은 AI 경로의 업무 낱말(`WORK_TITLE_KEYWORDS`)로만 본다.
    "온라인 콘텐츠",
    "교육 콘텐츠",
    "교육콘텐츠",
    "교육컨텐츠",
    "공유대학",
    "해커톤",
    "특강",
)

#: 본업 판정 전에 제목에서 지우는 **기관 이름** 조각 — 「OO교육청」 · 「OO교육지원청」의 「교육」은 일이 아니다.
_ORG_TOKENS = re.compile(
    r"\S*?(교육지원청|교육청|교육대학교|교육대학|교육부|교육학술정보원|교육정보원|교육연구정보원|교육과정평가원|교육개발원"
    r"|교육시설안전원|교육행정|교육시설과|교육시설|교육원|교육연수원|교육연구원|교육재단"
    # 39차 §3-A(P1 · COLLECT-01) — 시스템 · 망 · 방송 이름 자리. 「광주교육정보시스템」 · 「부산교육망센터」 · 「전북교육포털」 · 「통합교육포털」.
    r"|교육방송|교육정보|교육망|교육포털|교육콜센터"
    # 40차 §3-B(G1) — 건물 · 전시관 · 센터 이름 자리(「대구교육역사관 상설전시실 「대구교육관」 개편」 · 「승강기교육센터 고도화」).
    # 「교육관리(시스템)」는 이름이 아니다.
    r"|교육역사관|교육관(?!리)|교육센터"
    # 43차 M3 · BRIEF-06 — 사업 · 기관 이름 속 「교육」(「다자녀 교육지원포인트 사업 콜센터 운영」 · 「교육행재정 통합 상담센터 위탁운영」)
    r"|교육지원포인트|교육행재정)"
)

#: **AI 낱말이 있어도** 본업이 아닌 일 — 여행 · 국외연수 · 차량 · 시설 공사 · 건축 설계 · 검사 (38차 §3-A · D15).
#: 「AI·디지털 기반 교육혁신 국외연수 대행」은 여행 용역이고, 「교육시설과 시설공사 하자검사」는 공사 검사다.
#: 설계공모 · 공간 재조성 설계(그리고 AI 낱말이 없을 때 「건립」 — `NONCORE_SOFT`)는 L2(넓힌 수집 실제 1회)에서 샘플에듀 실무순 1위로 올라온 거짓 본업이다
#: (「수성구 농악 전수교육관 건립 용역사업 집행계획(설계공모)」 · 「GSP 교육·연구·산학협력 공간 재조성을 위한 설계용역」 — 38차 §3-G).
#: 「교육과정 설계」 같은 본업 「설계」는 막지 않게 낱말을 좁게 둔다(설계공모 · 설계용역 · 실시 · 기본 · 건축설계).
NONCORE_HARD: tuple[str, ...] = (
    "수학여행",
    "교육여행",
    "현장체험학습",
    "해외연수",
    "국외연수",
    "공무국외",
    "국외 역량강화",
    "해외 현장",
    "차량 임차",
    "차량임차",
    "버스 임차",
    "시설공사",
    "신축공사",
    "증축공사",
    "보수공사",
    "개보수",
    "리모델링",
    "하자검사",
    "해외배송",
    "설계공모",
    "설계용역",
    "설계 용역",
    "실시설계",
    "기본설계",
    "건축설계",
    "재조성",
    "공간조성",
    "공간 조성",
    "인테리어",
    # 담당자 결정(10-16 · AI + 시스템 구축 · 도입) 뒤 실제 자료에서 끌려온 것 — 행사 음향 장비 · 실습실 장비 설치는 본업이 아니다
    "음향",
    "장비 설치",
    "철거",
    "건설사업관리",
    # 39차 §3-A(P4 · COLLECT-04 · D19) — 농촌 기초생활거점 · 주민(지역)역량강화는 지역개발 사업이다(「역량강화」 낱말로 본업이 됐다).
    "기초생활거점",
    "지역역량강화",
    "지역 역량강화",
    "지역역량 강화",
    "주민역량강화",
    "주민 역량강화",
    # 39차 §3-A(P5) — 공간 설계 · 기자재(「AX혁신센터 공간 설계 및 기자재 구입·설치」 18.7억)
    "공간 설계",
    "공간설계",
    "기자재",
    # 39차 §3-A — 인허가 · 인증 취득 컨설팅 · 공적개발원조 정책(검수자 판정 「의료 · 인허가 · ODA · 정보보호 인증」 · precision.md (a))
    "인허가",
    "허가를 위한",
    "GMP",
    "ISMS",
    "EDCF",
    "공적개발원조",
    # 43차 M3 — 공공건축 기획(「피지컬AI 실증단지 구축사업 공공건축 기획용역」 · AI 낱말이 있어도 건축 일)
    "공공건축",
    "건축 기획",
    "건축기획",
)

#: 나라 이름 + 연수 · 견학 · 탐방(43차 — 「해외 · 국외」 낱말 없이 나라 이름만 적은 국외연수).
_COUNTRY_TRIP_RE = re.compile(
    r"(?:미국|일본|중국|유럽|독일|영국|프랑스|핀란드|덴마크|스웨덴|네덜란드|싱가포르|캐나다|호주|베트남|대만|이스라엘)[^,]{0,20}?(?:연수|견학|탐방|시찰)"
)

#: 40차 D26 — 「설계 용역」은 교수 · 교육과정 · 콘텐츠 설계(교수설계)일 때는 본업이다(「모듈형 교육 콘텐츠 기획 및 설계 용역」이 접혔다).
_INSTRUCTIONAL_DESIGN_RE = re.compile(r"(?:교수|교육\s*과정|커리큘럼|교육\s*(?:콘텐츠|컨텐츠)|콘텐츠|컨텐츠|학습|수업)\s*(?:기획\s*(?:및|과|·|ㆍ)?\s*)?설계")
_DESIGN_HARD: frozenset[str] = frozenset({"설계용역", "설계 용역"})

#: AI 낱말이 **없을 때만** 본업에서 빼는 교육 · 일 — 샘플에듀 사업영역(AI · 디지털 · ESG · 위탁교육 과정)이 아닌 갈래.
NONCORE_SOFT: tuple[str, ...] = (
    "안전교육",
    "안전보건",
    "산업안전",
    "안전 교육",
    "소방",
    "재난",
    "민방위",
    "법정의무",
    "의무교육",
    "성희롱",
    "성폭력",
    "폭력예방",
    "학교폭력",
    "청렴",
    "금연",
    "음주",
    "운전",
    "수련",
    "숙박",
    "급식",
    "조리",
    "미용",
    "요양",
    "보육",
    "간호",
    "체육",
    "수영",
    "승마",
    "골프",
    "문화예술",
    "국악",
    "음악",
    "미술",
    "무용",
    "공연",
    "축제",
    # 「OO교육관 건립」 — AI 낱말이 함께 있으면(「AI 기반 법률서비스 환경 구축 및 … 건립사업 PMC」 · 사업담당자 GPT 「파트너형」) 본업 쪽 일도 있어 빼지 않는다(38차 §3-G)
    "건립",
    "행사대행",
    "행사 대행",
    "홍보",
    "인쇄",
    "배송",
    "청소",
    "경비",
    "방역",
    "소독",
    "조경",
    "주차",
    "임차",
    "구매",
    "장비",
    "물품",
    "검진",
    "보험",
    "감수성",
    "시설",
    "성과공유회",
    # 40차 §3-B(G3) — 행사(「통합성과대회」 · 「사례 발표회 및 역량강화 워크숍」 · 「워크숍 개최」)
    "성과대회",
    "발표회",
    "워크숍 개최",
    # 39차 §3-A(P6 · D19) — 체험장 · 생태 · 숲 체험교육, 어학
    "체험장",
    "생태교육",
    "생태 교육",
    "생태체험",
    "숲체험",
    "숲 체험",
    "숲교육",
    "숲 교육",
    "산림교육",
    "외국어",
    "어학",
    "영어캠프",
    "영어 캠프",
    # 43차 M3 · BRIEF-06 — 누리집 · SNS 채널 운영(「법교육 누리집 및 SNS 채널 운영」) · 스키 강습(하이원 「외국인 스키 강습」)
    "누리집",
    "SNS 채널",
    "SNS채널",
    "스키",
    "스노보드",
)

#: `NONCORE_SOFT` 중 **낱말 경계**로 보는 것(39차 COLLECT-07) — 「청소」는 청소년, 「보험」은 건강보험공단, 「시설」은 시설공단에도 들어 있다.
_SOFT_BOUNDARY: dict[str, re.Pattern[str]] = {
    "청소": re.compile(r"청소(?!년)"),
    "보험": re.compile(r"(?<!건강)보험(?!공단|공사|연구원|개발원)"),
    "시설": re.compile(r"시설(?!공단|관리공단|안전공단)"),
    # 40차 CLASSIFY-08 — 「한국외국어대학교 · 외국어대 · 외국어고」는 기관 이름이다
    "외국어": re.compile(r"외국어(?!대학|대|고등학교|고)"),
}
#: 교육 운영과 함께 오면 접지 않는 `NONCORE_SOFT` 낱말(39차 §3-A — 「경기도자영업아카데미 이러닝 임차 · 운영」).
_SOFT_EDU_OK: frozenset[str] = frozenset({"임차"})
_EDU_OPERATION_RE = re.compile(r"(교육|이러닝|과정|아카데미|강의|연수|프로그램)[^,]{0,12}운영|운영\s*위탁|위탁\s*운영")
#: 온라인 교육 콘텐츠 개발은 주제와 상관없이 본업이다(실무 문서 §2.3-8 · 「재난안전분야 온라인 교육컨텐츠(K-MOOC) 개발」이 「재난」으로 접혔다).
#: 40차 G8 · CLASSIFY-04 — 맨 「온라인 콘텐츠」는 교육 낱말이 함께 있을 때만(공연 · 홍보 · 관광 온라인 콘텐츠가 본업이 됐다).
_ONLINE_CONTENT_RE = re.compile(r"K-?MOOC|이러닝|e-?Learning|온라인\s*교육\s*(?:콘텐츠|컨텐츠)|원격\s*(?:교육|수업|연수)\s*(?:콘텐츠|컨텐츠)", re.I)
_BARE_ONLINE_CONTENT_RE = re.compile(r"온라인\s*(?:콘텐츠|컨텐츠)")
_EDU_CONTEXT_RE = re.compile(r"교과목|강좌|강의|교육|이러닝|공유대학|K-?MOOC|수업|교과|학습|훈련|연수|과정", re.I)


def online_edu_content(text: str) -> bool:
    """온라인 교육 콘텐츠인가 — K-MOOC · 이러닝 · 온라인 교육 콘텐츠, 또는 맨 「온라인 콘텐츠」 + 교육 낱말."""
    return bool(_ONLINE_CONTENT_RE.search(text) or (_BARE_ONLINE_CONTENT_RE.search(text) and _EDU_CONTEXT_RE.search(text)))

#: 조달분류(세부)가 본업이 아닌 일을 말하는 것 (39차 D19 · recheck31 P6 · P7 — 지금까지는 「더하기」만 하고 부정 신호로 안 썼다).
NEGATIVE_CLASSES: tuple[str, ...] = (
    "국내여행", "국외여행", "숙박서비스", "항공여객운송", "건설및지역개발연구조사", "어학교육", "외국어교육",
)
#: 40차 §3-B(G3) — 행사 · 공연 · 전시 · 홍보 대행 조달분류. **공고명에 교육 운영 낱말이 있으면 접지 않는다** — 「신규기관 역량강화 교육 운영」 ·
#: 「AI 부트캠프 … 교육 프로그램 운영」 · 「퍼실리테이션 워크숍 기획 · 운영」도 행사기획 · 회의기획 분류로 나온다(기준 답안 본업).
EVENT_CLASSES: tuple[str, ...] = (
    "행사기획및대행", "공연기획및대행", "축제기획및대행", "회의기획및대행", "전시회기획및대행", "전시장치설치", "홍보및마케팅", "온라인홍보및방송콘텐츠",
)
#: 교육 · 경진 운영 꼴(「AI 마스터 과정 3기 운영」 · 「해커톤 운영」 · 「AI 창업 경진대회」 · 「평생교육 … 프로그램 위탁운영」)이면 행사 분류여도
#: 접지 않는다 — 주제가 없는 교육 프로그램은 §3-C 「주제 확인」이 본업 덩어리 뒤로 보낸다(숨기지 않음).
#: 41차 CLASSIFY-R40-02 — 교육 위탁 · 위탁교육 · 역량강화 과정 · 워크숍형 교육 · 교육 콘텐츠 제작도 교육 일이다 · 아카데미 · 연수 · 특강 ·
#: 워크숍은 **AI 낱말이 함께일 때만**(`_EVENT_EDU_AI_OK_RE` · 행사기획 분류로 나온 「AI 창업 아카데미 용역」 · 「미래역량강화 교육 위탁 용역」이
#: 비추천으로 접혔다 — 40차 회귀. AI 낱말 없는 「OO무대예술아카데미 운영」 · 「지역조직 역량 강화 워크숍 운영 대행」은 문화 · 행사 일이다).
_EVENT_EDU_OK_RE = re.compile(
    r"교육\s*(?:운영|프로그램|과정|용역|위탁)|위탁\s*교육|과정\s*(?:\d+\s*기\s*)?운영|프로그램\s*(?:위탁\s*)?운영|부트캠프|퍼실리테이션|강의|강좌|교과목"
    r"|이러닝|K-?MOOC|해커톤|아이디어톤|드래프톤|경진대회|챌린지"
    r"|역량\s*강화\s*(?:과정|교육|프로그램|연수)|워크숍\s*(?:형\s*)?교육"
    r"|(?:교육|강의)\s*(?:영상\s*)?(?:콘텐츠|컨텐츠|영상)\s*(?:개발|제작)",
    re.I,
)
_EVENT_EDU_AI_OK_RE = re.compile(r"아카데미|연수(?!원)|특강|워크숍")


def event_edu_ok(title: str, *, ai: bool) -> bool:
    """행사 · 홍보 분류(또는 공고명의 행사 꼴)여도 접지 않는 교육 일 꼴인가 — 아카데미 · 연수 · 특강 · 워크숍은 AI 낱말이 함께일 때만."""
    return bool(_EVENT_EDU_OK_RE.search(title) or (ai and _EVENT_EDU_AI_OK_RE.search(title)))
#: 조달분류가 없을 때(사전규격) 공고명의 행사 · 전시 꼴 — 교육 일 꼴(`_EVENT_EDU_OK_RE`)이 없으면 본업이 아니다(41차 CLASSIFY-R40-03 ·
#: 「CES 공동관 조성 · 운영」 · 「AI+ 페스타 행사 기획 · 운영 대행」이 선제준비 본업에 섰다).
#: 마지막 검토 — 맨 「대행」은 넣지 않는다(「AI 리터러시 교육 대행」 · 「AX 전략 수립 컨설팅 대행」을 접었다) · 참가자 「초청」 대행은 행사다.
_EVENT_TITLE_RE = re.compile(r"행사|전시|공동관|페스타|페스티벌|박람회|축제|부스(?!트)|초청")
#: 정보시스템 유지관리 · 운영 조달분류 — 공고명에 AI 낱말이 있으면 접지 않고 유형이 D(연구 · 감리 · 구매 덩어리)다.
IT_MAINTENANCE_CLASSES: tuple[str, ...] = ("정보시스템유지관리", "소프트웨어유지")
#: 제목의 정보시스템 유지관리 · 운영(39차 D19 · P1) — 「EBS 방송 및 교육 인터넷서비스 통합 운영」 · 「광주교육정보시스템 유지관리 및 보안관제」.
IT_MAINTENANCE_TITLE_RE = re.compile(
    r"(시스템|포털|교육망|통신망|정보망|전산망|네트워크|홈페이지|누리집|인터넷서비스|정보서비스|웹서비스|LMS|플랫폼|전산|클라우드)"
    # 43차 — 사이에 괄호 이름이 끼면 12자를 넘는다(「운영시스템(디지털 직업교육허브) 유지관리」)
    r"[^,·]{0,22}?(유지\s*관리|유지\s*보수|운영\s*지원|보안\s*관제|통합\s*운영)"
)
#: AI 낱말 없는 웹 · 시스템 구축(39차 §3-A · P1) — 본업 낱말이 「교육」 · 「연수」뿐이고 교육 일 낱말이 없으면 「교육」은 이름이다
#: (「경제금융교육 통합 홈페이지 구축」 · 「경기교육 지방공무원 인사관리 플랫폼 구축」 · 「소상공인교육원 홈페이지 리뉴얼」).
#: 40차 §3-B(G1) — 「서비스 개발」 · 「센터 고도화」도 시스템 구축이다(「캄보디아 교육사업 PLP 서비스 개발」 · 「승강기교육센터 고도화」).
#: 「서비스 · 센터」는 바로 뒤에 개발 동사가 올 때만이다(「고용서비스 종사자 교육 개편방안 연구」는 시스템 구축이 아니다).
_SYSTEM_BUILD_RE = re.compile(
    r"(시스템|포털|홈페이지|누리집|플랫폼|LMS|앱|어플리케이션|전산)[^,·]{0,12}?(구축|고도화|개발|리뉴얼|개편|도입|구현|개선|정비)"
    r"|(?:서비스|센터)\s*(?:개발|구축|고도화|리뉴얼|개편)"
)
_EDU_WORK_RE = re.compile(r"교육\s*(?:운영|과정|프로그램|콘텐츠|컨텐츠)|과정\s*운영|강의|강좌|교재|컨설팅|연수\s*운영|콘텐츠\s*개발")
#: 시스템 이름 자리(그 앞 낱말 하나 포함) — 「역량기반 교육과정 시스템 고도화」의 「교육과정」은 시스템 이름이라 교육 일이 아니다(40차 G1).
_SYSTEM_NAME_RE = re.compile(r"\S*\s*(?:시스템|포털|홈페이지|누리집|플랫폼|LMS|앱|어플리케이션|전산)")

# 2차: 개발(구축·솔루션) 키워드.
#
# 교육·컨설팅과 **나란한 2차 키워드**다. 1차(AI) 키워드와 함께 잡혀야 후보가 되므로,
# 「상수도 관제시스템 구축」처럼 AI와 무관한 대형 SI는 여기 걸려도 후보가 되지 않는다.
#
# RAG·챗봇·에이전트는 여기가 아니라 **1차(AI) 키워드**에 있다 — 개발 어휘가 아니라 AI 기술이라,
# 공고명에 「AI」가 없어도 그 자체로 AI 사업으로 봐야 하기 때문이다.
# 일반 SI 어휘(시스템·구축)는 범위가 너무 넓어 넣지 않았다 — AI 키워드와 겹쳐도
# 3명이 감당할 수 없는 대형 사업이 대부분이라 규모 판정으로 걸러야 한다(TEAM_BUDGET_CEILING).
DEV_KEYWORDS: tuple[str, ...] = (
    "개발",
    "고도화",
    "구현",
    "솔루션",
    "소프트웨어",
    "자동화",
    "웹서비스",
    "홈페이지",
    "플랫폼",
    "대시보드",
    "API",
    "데이터 분석",
    "데이터분석",
)

#: 담당자 결정(2026-10-16) — **공고명**에 AI 낱말과 함께 「구축 · 도입 · 시스템」이 있으면 개발 갈래 후보다
#: (「Multi-modal AI Agent 및 Graph RAG 시스템 구축」 · 「AI 학사상담 챗봇 시스템 구축」 · 「생성형 AI 구독 서비스 도입」).
#: 37차까지는 이 꼴이 「AI 낱말만」이라 후보가 아니었다. **제목(기관 이름 조각을 뺀)에서만** 본다 — 설명 · 조달 분류명의
#: 「정보시스템개발서비스」는 거의 모든 SI 공고에 붙어, 거기서 보면 위 DEV_KEYWORDS 주석의 「너무 넓다」가 그대로 돌아온다.
#: AI 낱말도 제목에 있어야 한다. 시설 공사 · 설계 · 건립 같은 본업 아님은 이보다 먼저 거른다(`noncore_of`).
AI_BUILD_TITLE_KEYWORDS: tuple[str, ...] = ("구축", "도입", "시스템")
#: 기수가 낀 과정 운영(「과정 3기 운영」) — `WORK_TITLE_KEYWORDS` 의 「과정 운영」과 같은 뜻(40차).
_COURSE_RUN_RE = re.compile(r"과정\s*\d+\s*기\s*운영")
#: 「AI … 운영」 + 조달분류 예외(classify)를 쓰는 교육 운영 분류(40차 CLASSIFY-10).
EDU_OPERATION_CLASSES: tuple[str, ...] = ("취업지원교육", "기타교육서비스")
_FACILITY_OPERATION_RE = re.compile(r"(?:센터|데이터센터|관|허브)\s*(?:위탁\s*)?운영")
#: 장비 · 서버 구축은 이 결정 밖이다 — CLAUDE.md §4-C 「AI GPU 서버 구축 → 낮은 적합도」(소프트웨어 · 서비스 구축만 개발 갈래).
#: 40차 §3-B(G6) — 보드 · 생산 · 시제품도 하드웨어다(「엣지 AI 캐리어보드 개발 및 생산」).
AI_HARDWARE_TITLE_KEYWORDS: tuple[str, ...] = ("GPU", "서버", "하드웨어", "스토리지", "장비", "인프라", "보드", "생산", "시제품")
#: 41차 CLASSIFY-R40-01 — 「보드 · 생산」은 낱말 경계로 본다(「대시보드 · 스토리보드 · 키보드 · 생산성 · 생산관리」는 소프트웨어 일이다 —
#: 「AI 기반 대시보드 구축」이 「AI 장비 일」로 접혔다). 「대시보드」는 위 `DEV_KEYWORDS` 의 개발 낱말이다.
_HARDWARE_BOUNDARY: dict[str, re.Pattern[str]] = {
    "보드": re.compile(r"(?<!대시)(?<!스토리)(?<!키)보드"),
    "생산": re.compile(r"생산(?!성|관리)"),
}


def hardware_of(title: str) -> list[str]:
    """제목의 AI 장비 · 서버 낱말(`AI_HARDWARE_TITLE_KEYWORDS` · 보드 · 생산은 낱말 경계)."""
    return [k for k in AI_HARDWARE_TITLE_KEYWORDS
            if (_HARDWARE_BOUNDARY[k].search(title) if k in _HARDWARE_BOUNDARY else _contains(title, k))]
#: 제목 맨 앞의 괄호 표시(「[정보화/중앙/헬스케어인공지능연구과]」 같은 부서 · 분류 이름) — 그 안의 AI 낱말은 사업 내용이 아니다.
#: **부서 · 분류 이름 꼴만** 지운다(빗금이 있거나 과 · 팀 · 부 · 실 · 단 · 센터 · 연구소로 끝남) — 「(AI)활용 시범사업」 · 「[AI앵커]」의 AI 는 남긴다.
_LEADING_LABEL_RE = re.compile(r"^\s*[\[［【(（]([^\]］】)）]{0,60})[\]］】)）]\s*")
_DEPT_LABEL_RE = re.compile(r"/|(?:과|팀|부|실|단|센터|연구소|연구원)$")


def strip_dept_labels(title: str) -> str:
    """제목 맨 앞 괄호 표시 중 부서 · 분류 이름 꼴만 지운 것(그 밖의 앞 괄호는 그대로)."""
    kept: list[str] = []
    text = title or ""
    while (match := _LEADING_LABEL_RE.match(text)) is not None:
        if not _DEPT_LABEL_RE.search(match.group(1).strip()):
            kept.append(match.group(0))
        text = text[match.end():]
    return "".join(kept) + text

CandidateTier = Literal["high", "medium", "low", "none"]

# 짧은 영문 키워드는 다른 단어에 섞이기 쉽다 (MAIN의 AI 등). 앞뒤가 영문자면 매칭에서 뺀다.
# 38차 §3-A — 다만 **소문자 바로 뒤의 대문자 낱말**은 합성어의 마디다(「KAIST CTxAI」 · 「eduAI」). 「MAIN」 · 「KAIST」처럼
# 대문자 바로 뒤는 여전히 뺀다. AX · GPT 도 짧은 영문이다(「TAX」 · 「MAX」 · 「FAX」를 AX 로 읽지 않게).
_SHORT_ASCII = {"AI", "DX", "LLM", "API", "RAG", "AX", "GPT"}

# 교육 없이 개발만 하는 사업에 「규모가 크다」는 메모를 붙이는 기준(원). 이 값을 넘어도 **후보에서 빼거나
# 등급을 낮추지 않는다**(34차 R33-S2 · 담당자 결정 「숨기지 않고」) — 순위는 점수의 규모 항목과 사업 규모 줄
# (회사가 적은 최대 사업비)이 뒤로 보낸다. 예전에는 `low` 로 낮춰 기본 목록에서 17건이 조용히 빠졌다.
#
# 근거: 작은 개발진을 가정한다. 인건비 중심 공공 개발사업에서 소수 인원이 감당할 수 있는 범위를
# 넉넉히 잡은 값이며, **회사가 정할 값이지 시스템이 계산한 값이 아니다.**
# 규모를 판단할 수 없는 공고(예산 없음)는 낮추지 않는다 — 모르는 것을 크다고 단정하지 않는다.
TEAM_BUDGET_CEILING = 300_000_000


def _contains(text: str, keyword: str) -> bool:
    """키워드 포함 여부. 짧은 영문 키워드는 단어 경계를 확인한다."""
    if keyword in _SHORT_ASCII:
        pattern = rf"(?<![A-Za-z]){re.escape(keyword)}(?![A-Za-z])"
        if re.search(pattern, text, re.IGNORECASE) is not None:
            return True
        # 합성어 마디: 소문자 바로 뒤에 **대문자 그대로** 붙은 낱말(「CTxAI」). 대소문자를 가린다 — 「domain」의 ai 는 아니다.
        return re.search(rf"(?<=[a-z]){re.escape(keyword)}(?![A-Za-z])", text) is not None
    if keyword.lower() in text.lower():
        return True
    # 39차 COLLECT-09 — 나라장터 공고명 검색은 띄어쓰기를 무시한다(「전략수립」 · 「전략 수립」). 띄어 쓴 낱말은 붙여서도 본다.
    return " " in keyword and keyword.replace(" ", "").lower() in text.replace(" ", "").lower()


def _collect_word(title: str) -> tuple[str, bool] | None:
    """공고명에 걸리는 수집 낱말과 「추가 낱말인가」. 기본 낱말이 먼저다(기존 분류 그대로) · 없으면 None."""
    hit = next((k for k in COLLECT_KEYWORDS if _contains(title, k)), None)
    if hit is not None:
        return hit, False
    from app.services import collect_keywords_service  # 함수 안 — 그 모듈이 이 모듈의 COLLECT_KEYWORDS 를 쓴다(순환 import)

    extra = next((w for w in collect_keywords_service.extra_words() if collect_keywords_service.matches(title, w)), None)
    return (extra, True) if extra is not None else None


def _first(text: str, terms: tuple[str, ...]) -> str | None:
    """`terms` 중 `text` 에 처음 걸리는 낱말. 「부트캠프」 안의 「캠프」처럼 더 긴 본업 낱말 안에 든 것은 세지 않는다."""
    for term in terms:
        if _contains(text, term):
            return term
    return None


def core_title(title: str) -> str:
    """본업 판정에 쓰는 제목 — 기관 이름 조각(「OO교육청」)을 지운 것."""
    return _ORG_TOKENS.sub(" ", title or "")


#: 41차 G4 — 교육기관(대학 · 학교 · 능력개발원 · 인재개발원 · 교육원 · 연수원 · 훈련원)이 내는 「콘텐츠 개발」은 교육 콘텐츠다
#: (「OO대학교 … 마이크로 콘텐츠 개발」 · 「OO능력개발원 콘텐츠 개발」이 「콘텐츠 개발만」으로 접혔다). 맨 「콘텐츠 개발」은 여전히 본업이 아니다
#: (먹자골목 · 관광 콘텐츠 — `CORE_TERMS` 주석). 기관 이름은 공고명에서만 본다.
_EDU_INSTITUTION_RE = re.compile(r"대학교|대학원|대학|학교|능력개발원|인재개발원|교육원|연수원|훈련원")
_CONTENT_DEV_RE = re.compile(r"(?:콘텐츠|컨텐츠)\s*개발")


def core_terms_of(title: str) -> list[str]:
    """제목(기관 이름 뺀)에 걸린 본업 낱말. 맨 「온라인 콘텐츠」는 교육 낱말이 함께 있을 때만(40차 G8 · CLASSIFY-04) ·
    교육기관 공고명의 「콘텐츠 개발」은 본업(41차 G4)."""
    text = core_title(title)
    terms = matched_keywords(text, CORE_TERMS)
    if "온라인 콘텐츠" in terms and not _EDU_CONTEXT_RE.search(_BARE_ONLINE_CONTENT_RE.sub(" ", text)):
        terms.remove("온라인 콘텐츠")
    if not terms and _CONTENT_DEV_RE.search(text) and _EDU_INSTITUTION_RE.search(title or ""):
        terms.append("교육기관 콘텐츠 개발")
    return terms


#: 「해외 · 국외」와 함께 오면 여행 성격인 낱말 — 「해외 AI 선진사례 벤치마킹 용역」은 견학 여행이다.
_ABROAD_TRIP = ("벤치마킹", "선진사례", "탐방", "견학", "연수")


#: 40차 §3-B(G7) — AI 낱말이 있어도 홍보 · 마케팅 · 축제는 본업이 아니다(「제주 로컬 브랜드의 AI 활용 콘텐츠 제작 및 홍보」).
#: 공고명에 교육 · 컨설팅 낱말이 함께 있거나(「AI 홍보 마케팅 실무 교육」 · 「AI 마케팅 아카데미」 · 「AI 마케팅 컨설팅」) AI 구축 · 도입 ·
#: 시스템 · 플랫폼 · 솔루션이면(담당자 결정 10-16 개발 갈래) 접지 않는다 — 41차 CLASSIFY-R40-04(40차는 글자 「교육」 하나만 봤다).
_AI_SOFT: tuple[str, ...] = ("홍보", "마케팅", "축제")
#: 홍보관 · 전시관 · 체험관 — 시설이라 「구축」이어도 개발 갈래가 아니다(마지막 검토).
_AI_SOFT_HALL_RE = re.compile(r"홍보관|전시관|체험관")
_AI_SOFT_OK_RE = re.compile(
    r"교육|연수|아카데미|부트캠프|캠프|특강|강의|과정|역량\s*강화|워크숍|컨설팅|구축|도입|시스템|플랫폼|솔루션"
)


def noncore_of(title: str, *, ai: bool) -> str | None:
    """본업이 아닌 일이면 사유 한 줄. AI 낱말이 있으면 `NONCORE_HARD` 와 홍보 · 마케팅 · 축제(교육 낱말 없을 때)만 본다."""
    text = core_title(title)
    hard = next((t for t in NONCORE_HARD if _contains(text, t) and not (t in _DESIGN_HARD and _INSTRUCTIONAL_DESIGN_RE.search(text))), None)
    if hard is None and _COUNTRY_TRIP_RE.search(text):
        hard = "국외연수"  # 43차 — 「글로벌 SW교육 프로그램(미국 CES) 연수 대행」(나라 이름 + 연수 · 견학 = 국외연수)
    if hard is None and ("해외" in text or "국외" in text):
        trip = _first(text, _ABROAD_TRIP)
        hard = f"해외 · {trip}" if trip else None
    if hard:
        return f"본업이 아닌 일 — 공고명의 「{hard}」({_hard_kind(hard)})"
    if ai:
        promo = _first(text, _AI_SOFT)
        if promo and (_AI_SOFT_HALL_RE.search(text) or not _AI_SOFT_OK_RE.search(text)):
            return f"본업이 아닌 일 — 공고명의 「{promo}」(홍보 · 마케팅 · 축제 — AI 를 쓰는 홍보는 회사 사업영역 밖)"
        return None
    soft = _first_soft(text, skip=lambda term: term in _SOFT_EDU_OK and bool(_EDU_OPERATION_RE.search(text)))
    if soft and not online_edu_content(text):
        return f"본업이 아닌 교육 · 일 — 공고명의 「{soft}」(회사 사업영역 AI · 디지털 · ESG · 위탁교육 과정 밖)"
    publish = _first(text, _PUBLISHING)
    if publish and set(core_terms_of(title)) <= _EDUCATION_NAME_TERMS and not _WORK_WORD_RE.search(text):
        # 본업 낱말이 「교육」 · 「연수」뿐이면 잡지 · 시설 이름이다 — 「2027~2028년 교육광장 발간 용역」(L2 · 38차 §3-G).
        # 「ESG 경영전략 수립 및 ESG 경영보고서 발간」처럼 다른 본업 낱말이 있으면 본업이다.
        return f"본업이 아닌 일 — 공고명의 「{publish}」(책 · 잡지를 펴내는 일 · 본업 낱말은 「교육」뿐)"
    return None


def _first_soft(text: str, *, skip=None) -> str | None:
    """`NONCORE_SOFT` 중 처음 걸리는 낱말 — 청소 · 보험 · 시설 · 외국어는 낱말 경계로 본다(39차 COLLECT-07 · 40차 CLASSIFY-08).

    `skip(term)` 이 참인 낱말(교육 운영과 함께 온 「임차」)은 건너뛰고 **다음 낱말을 계속 찾는다** — 면제 낱말 하나가 뒤의 체험장 ·
    외국어 · 장비까지 덮었다(40차 CLASSIFY-07)."""
    for term in NONCORE_SOFT:
        pattern = _SOFT_BOUNDARY.get(term)
        if (pattern.search(text) if pattern else _contains(text, term)) and not (skip and skip(term)):
            return term
    return None


#: `NONCORE_HARD` 낱말 묶음별 사유 괄호 글(40차 CLAIMS-05 — 39차에 더한 EDCF · 인허가에도 「여행 · 국외연수 …」가 붙었다).
_HARD_KINDS: tuple[tuple[frozenset[str], str], ...] = (
    (frozenset({"수학여행", "교육여행", "현장체험학습", "해외연수", "국외연수", "공무국외", "국외 역량강화", "해외 현장"}), "여행 · 국외연수"),
    (frozenset({"해외배송"}), "배송 · 운송"),  # 41차 CLASSIFY-R40-12
    (frozenset({"차량 임차", "차량임차", "버스 임차"}), "차량 임차"),
    (frozenset({"기초생활거점", "지역역량강화", "지역 역량강화", "지역역량 강화", "주민역량강화", "주민 역량강화"}), "농촌 · 지역개발"),
    (frozenset({"인허가", "허가를 위한", "GMP", "ISMS"}), "인허가 · 인증 취득"),
    (frozenset({"EDCF", "공적개발원조"}), "공적개발원조(ODA) 정책 · 사업"),
    (frozenset({"음향", "장비 설치", "기자재"}), "장비 · 기자재"),
)


def _hard_kind(term: str) -> str:
    if term.startswith("해외 · "):
        return "여행 · 견학"
    return next((kind for terms, kind in _HARD_KINDS if term in terms), "시설 공사 · 설계 · 검사")


def event_title_of(title: str) -> str | None:
    """조달분류가 없는 공고(사전규격)의 공고명이 행사 · 전시 · 대행 꼴이고 교육 일 꼴이 없으면 사유 한 줄(41차 CLASSIFY-R40-03).

    나라장터 입찰은 조달분류(`EVENT_CLASSES`)로 거른다 — 사전규격은 그 칸이 없어 「CES 공동관 조성 · 운영」 · 「AI+ 페스타 행사 대행」이
    본업으로 섰다. 숨기지 않고 사유와 함께 접는다(D15)."""
    text = core_title(title)
    hit = _EVENT_TITLE_RE.search(text)
    if hit is None or event_edu_ok(text, ai=bool(matched_keywords(strip_dept_labels(text), AI_KEYWORDS))):
        return None
    return f"공고명의 「{hit.group(0)}」 — 본업 아님(행사 · 전시 · 대행 · 공고명에 교육 운영 낱말 없음)"


def negative_of(notice: ProcurementNotice, *, ai: bool, core: list[str]) -> str | None:
    """조달분류 · 제목이 본업이 아닌 일을 말하면 사유 한 줄 (39차 D19 · recheck31 P1 · P6 · P7). 숨기지 않고 사유와 함께 접는다(D15).

    - 정보시스템 유지관리 · 운영(조달분류 또는 제목) — 공고명에 AI 낱말이 있으면 접지 않는다(유형 D · 연구 · 감리 · 구매 덩어리).
    - 여행 · 숙박 · 항공 · 건설및지역개발연구조사 · 어학 조달분류 — AI 낱말이 있어도 접는다.
    - AI 낱말 없는 웹 · 시스템 구축인데 본업 낱말이 이름 속 「교육」 · 「연수」뿐.
    """
    title = core_title(notice.title)
    raw = notice.raw_data if isinstance(notice.raw_data, dict) else {}
    klass = str(raw.get("procurement_class") or "")
    maintenance_class = _first(klass, IT_MAINTENANCE_CLASSES) if klass else None
    # 유지관리 꼴은 **이름 조각을 지우기 전** 제목에서 찾는다 — 「부산교육망센터 통합 유지관리」의 「교육망」이 이름 조각이다.
    maintenance_title = IT_MAINTENANCE_TITLE_RE.search(strip_dept_labels(notice.title or ""))
    if maintenance_class or maintenance_title:
        if ai:
            return None
        if maintenance_class:
            return f"조달분류 「{klass}」 — 본업 아님(정보시스템 유지관리 · 운영)"
        return f"공고명 「{maintenance_title.group(0)}」 — 본업 아님(정보시스템 유지관리 · 운영)"
    if klass and _first(klass, NEGATIVE_CLASSES):
        return f"조달분류 「{klass}」 — 본업 아님(여행 · 숙박 · 운송 · 지역개발 · 어학)"
    if klass and _first(klass, EVENT_CLASSES) and not event_edu_ok(title, ai=ai):
        return f"조달분류 「{klass}」 — 본업 아님(행사 · 공연 · 전시 · 홍보 대행 · 공고명에 교육 운영 낱말 없음)"
    if (
        not ai and core and set(core) <= _EDUCATION_NAME_TERMS and _SYSTEM_BUILD_RE.search(title)
        and not _EDU_WORK_RE.search(_SYSTEM_NAME_RE.sub(" ", title))
    ):
        return "공고명이 웹 · 시스템 구축이고 「교육」은 이름 안에만 있습니다 — 본업 아님(AI 아닌 웹 · 시스템 구축)"
    return None


#: 펴내는 일 — 본업 낱말이 「교육」 · 「연수」뿐일 때만 본업에서 뺀다(`noncore_of`).
_PUBLISHING: tuple[str, ...] = ("발간",)
_EDUCATION_NAME_TERMS: frozenset[str] = frozenset({"교육", "연수"})
#: 「교재 발간 및 교육 운영」처럼 일 낱말이 함께 있으면 펴내는 일만이 아니다.
_WORK_WORD_RE = re.compile(r"운영|개발|과정|프로그램|강의|컨설팅")


#: 41차 CLASSIFY-R40-10 — 업무 낱말 중 낱말 경계로 보는 것(「교과서」 · 「수업료」는 학교 교과 · 수업 일이 아니다).
_WORK_BOUNDARY: dict[str, re.Pattern[str]] = {"교과": re.compile(r"교과(?!서)"), "수업": re.compile(r"수업(?!료)")}


def matched_keywords(text: str, keywords: tuple[str, ...]) -> list[str]:
    return [k for k in keywords if (_WORK_BOUNDARY[k].search(text) if k in _WORK_BOUNDARY else _contains(text, k))]


@dataclass(frozen=True)
class CandidateMatch:
    """키워드 매칭 결과. 판정 근거(matched_*)를 항상 함께 남긴다."""

    tier: CandidateTier
    matched_ai: list[str]
    matched_work: list[str]
    matched_dev: list[str] = field(default_factory=list)
    # 교육 없이 개발만 하는 큰 사업에 붙이는 메모. 등급은 그대로다(34차 R33-S2). 없으면 None.
    oversized_reason: str | None = None
    #: AI 낱말 없이 후보가 된 근거 — 제목의 본업 낱말(38차 §3-A). 비어 있으면 AI 경로다.
    core_terms: list[str] = field(default_factory=list)
    #: 후보가 아닌(`low`) 이유 한 줄 — 「본업이 아닌 교육 — 「안전교육」」 · 「AI 낱말만」 등(38차 · D15). 목록의 「관련 낮음」 사유로 그대로 간다.
    low_reason: str | None = None

    @property
    def is_candidate(self) -> bool:
        """기본 화면에 올릴 공고인가. **후보 판정의 단일 출처** — 다른 곳에서 등급을 다시 비교하지 않는다."""
        return self.tier == "high"

    def to_dict(self) -> dict[str, object]:
        return {
            "tier": self.tier,
            "matched_ai_keywords": self.matched_ai,
            "matched_work_keywords": self.matched_work,
            "matched_dev_keywords": self.matched_dev,
            "oversized_reason": self.oversized_reason,
            "core_terms": self.core_terms,
            "low_reason": self.low_reason,
            "method": "KEYWORD",
        }


def searchable_text(notice: ProcurementNotice) -> str:
    """공고명뿐 아니라 분류·설명까지 함께 본다 (제목만 보지 않는다 — CLAUDE.md 4-C)."""
    parts = [notice.title, notice.description or "", notice.agency]
    return " ".join(parts)


def _format_won(value: int) -> str:
    """사람이 읽는 금액. 억 단위로 줄여 적는다 (원문 숫자는 상세에 그대로 남는다)."""
    if value >= 100_000_000:
        return f"{value / 100_000_000:.1f}억원"
    return f"{value / 10_000:,.0f}만원"


def classify(notice: ProcurementNotice) -> CandidateMatch:
    """
    등급 판정.

    2차 키워드는 **교육·컨설팅(WORK)** 과 **개발(DEV)** 두 갈래다. 둘 중 하나만 걸려도
    1차(AI) 키워드와 함께라면 high 다 — 회사가 두 종류의 일을 모두 하기 때문이다.

    AI 키워드 **단독**은 후보가 아니다 (`low`). «AI» 가 건물·센터 이름인 공고가 대부분이라서다.

    교육 없이 개발만 하는 사업은 규모를 한 번 더 본다. 예산이 기준을 넘으면 메모만 붙이고 등급은
    그대로 둔다 — 순위는 점수의 규모 항목이 뒤로 보낸다(34차 R33-S2). 예산을 모르는 공고는 메모도 없다.
    """
    text = searchable_text(notice)
    title = strip_dept_labels(core_title(notice.title))
    # 39차 §3-A(P5 · COLLECT-05) — AI 경로의 AI · 업무 · 개발 낱말은 **제목(기관 이름 조각 · 앞 괄호 표시 뺀)에서만** 본다.
    # 설명 칸의 조달 분류명(「정보화교육서비스」 · 「정보시스템개발서비스」)과 기관명이 근거가 되면 감리 · 영향평가 · 인프라가
    # AI 교육 · 개발 후보가 됐다(4d47e34 주석의 뜻을 AI 경로 전체로).
    ai = matched_keywords(title, AI_KEYWORDS)
    work = matched_keywords(title, WORK_KEYWORDS) + matched_keywords(title, WORK_TITLE_KEYWORDS)
    dev = matched_keywords(title, DEV_KEYWORDS)
    hardware = hardware_of(title)
    if ai and not hardware:
        # 담당자 결정(10-16) — 제목의 AI 낱말 + 「구축 · 도입 · 시스템」은 개발 갈래(`AI_BUILD_TITLE_KEYWORDS`) · 장비 · 서버는 아님
        dev = list(dict.fromkeys([*dev, *matched_keywords(title, AI_BUILD_TITLE_KEYWORDS)]))
    if ai and not work and _COURSE_RUN_RE.search(title):
        work = ["과정 운영"]  # 40차 — 「AI 마스터 과정 3기 운영」(기수가 낀 과정 운영)
    klass = str((notice.raw_data or {}).get("procurement_class") or "") if isinstance(notice.raw_data, dict) else ""
    if ai and not work and _first(klass, EDU_OPERATION_CLASSES) and "운영" in title and not _FACILITY_OPERATION_RE.search(title):
        # 제목은 「AI … 운영 용역」이고 조달청이 **교육 운영**(취업지원교육 · 기타교육서비스)으로 분류했으면 교육 운영이다
        # (「AI 에이전트 기반 커리어 패스포트 운영」 · 취업지원교육서비스). 조달분류만으로는 후보가 되지 않는다 — 제목의 「운영」이 함께 있어야 한다
        # (위 「제목에서만」의 좁은 예외 · CLAUDE.md §4-B). 40차 CLASSIFY-10 — 정보화교육서비스는 빼고, 센터 · 데이터센터 · 관 · 허브 운영은 시설 운영이다.
        work = [klass]
    # 38차 §3-A — 본업 갈래(제목만) · 본업 아님 사유. AI 낱말이 있어도 여행 · 국외연수 · 차량 · 공사 · 검사는 후보가 아니다.
    core = core_terms_of(notice.title)
    noncore = noncore_of(notice.title, ai=bool(ai)) or negative_of(notice, ai=bool(ai), core=core)
    low_reason: str | None = None

    oversized: str | None = None
    if noncore:
        tier: CandidateTier = "low"
        low_reason = noncore
        core = []
    elif ai and (work or (dev and not hardware)):
        # 40차 G6 — AI + 개발 낱말이어도 장비 · 보드 · 생산이면(교육 · 컨설팅 낱말 없이) 장비 일이다(아래 「AI 낱말만」 갈래에서 사유)
        tier = "high"
    elif core:
        # AI 낱말이 없어도 회사 본업(교육 운영 · 과정 · 콘텐츠 개발 · 컨설팅 · ESG · AX · DX · 디지털 역량)이면 후보다.
        tier = "high"
        work = list(dict.fromkeys([*work, *core]))
    elif ai:
        # AI 키워드 **단독**으로는 후보로 올리지 않는다.
        # 「AI」는 AI타워·AI-Science 데이터센터·제조AI 확산센터처럼 **건물·센터 이름**에도 흔히 쓰인다
        # (실수집 87건을 돌려 보니 AI 단독 4건 중 3건이 시설 설계·안전조사 공고였다).
        # 회사가 할 수 있는 AI 사업이면 교육·컨설팅이든 개발이든 2차 키워드가 대개 함께 온다.
        tier = "low"
        low_reason = (
            f"공고명이 AI 장비 · 서버(「{hardware[0]}」) 일입니다 — 회사 본업(교육 · 컨설팅 · 소프트웨어 개발) 밖"
            if hardware
            else f"공고명에 AI 낱말({', '.join(ai[:2])})만 있고 교육 · 컨설팅 · 개발 낱말이 없습니다(건물 · 센터 이름일 수 있음)"
        )
    elif work:
        # 업무 낱말만 걸린 공고. 제목의 업무 낱말이 본업 갈래가 아니거나(「기획」 · 「계획 수립」만), 설명 · 기관명에만 있다.
        tier = "low"
        low_reason = f"공고명에 「{work[0]}」만 있고 본업(교육 · 과정 · 컨설팅 · ESG · AX · 디지털 역량) 낱말이 없습니다"
    elif matched_keywords(text, WORK_KEYWORDS):
        # 업무 낱말이 공고명의 일이 아니다 — 기관 · 시스템 이름 조각 안(「광주교육정보시스템」)이거나 설명(조달 분류명) · 기관명에만 있다(39차 P1 · P5).
        tier = "low"
        in_name = matched_keywords(notice.title or "", WORK_KEYWORDS)
        low_reason = (
            f"「{in_name[0]}」 낱말이 기관 · 시스템 이름 안에만 있습니다(일이 아님)"
            if in_name
            else f"교육 · 컨설팅 낱말이 공고명이 아니라 분류 · 기관명에만 있습니다({', '.join(matched_keywords(text, WORK_KEYWORDS)[:2])})"
        )
    elif (collected := _collect_word(notice.title)) is not None:
        # 38차 §3-A · D15 — 넓힌 수집 낱말(「디지털」 · 「콘텐츠」 · 「전략 수립」 등)로 받았지만 본업 낱말이 없는 공고.
        # 버리면 「없던 것」이 되므로 후보 아님(`low`)과 사유로 남긴다. 2.0.7 결정 ② — 추가 낱말로 받은 공고도 같다.
        tier = "low"
        hit, extra = collected
        low_reason = f"{'추가' if extra else '수집'} 낱말 「{hit}」로 받았지만 본업(교육 · 과정 · 컨설팅 · ESG · AX · 디지털 역량) 낱말이 없습니다"
    else:
        # 여기로 오는 것에는 **개발 키워드만 걸린 공고**도 포함된다 — 후보가 아니라 `none` 이다.
        # 「개발」은 도시개발·기술개발·백신개발처럼 소프트웨어와 무관한 데서도 흔히 쓰인다
        # (실제 600건을 돌려 보니 폐기물처리·백신 공고가 딸려 왔다).
        # 그래서 개발은 AI 키워드와 **함께** 걸릴 때만 후보가 된다.
        tier = "none"

    # 규모 메모는 **후보인 개발 사업에만** 붙인다 — 후보가 아닌 공고에 붙이면 엉뚱한 설명이 된다.
    if (
        dev
        and not work
        and tier == "high"
        and notice.budget is not None
        and notice.budget > TEAM_BUDGET_CEILING
    ):
        oversized = (
            f"예산 {_format_won(notice.budget)} — 교육 없이 개발만 하는 {_format_won(TEAM_BUDGET_CEILING)} 넘는 사업입니다"
            " — 후보로 두고, 회사가 맡을 수 있는 규모는 회사자료의 최대 사업비(사업 규모 줄 · 점수)로 봅니다."
        )

    return CandidateMatch(
        tier=tier,
        matched_ai=ai,
        matched_work=work,
        matched_dev=dev,
        oversized_reason=oversized,
        core_terms=core if tier == "high" and not (ai and (work or dev)) else [],
        low_reason=low_reason if tier == "low" else None,
    )


_TIER_ORDER = {"high": 0, "medium": 1, "low": 2, "none": 3}


def filter_candidates(
    notices: list[ProcurementNotice],
    *,
    include_low: bool = False,
) -> list[tuple[ProcurementNotice, CandidateMatch]]:
    """AI/교육 후보만 골라 등급·마감일 순으로 정렬해 반환한다."""
    results: list[tuple[ProcurementNotice, CandidateMatch]] = []
    for notice in notices:
        match = classify(notice)
        if match.is_candidate or (include_low and match.tier == "low"):
            results.append((notice, match))

    def sort_key(pair: tuple[ProcurementNotice, CandidateMatch]):
        notice, match = pair
        # 마감일이 없는 공고는 뒤로 보낸다.
        return (_TIER_ORDER[match.tier], notice.deadline_at is None, notice.deadline_at or notice.published_at)

    results.sort(key=sort_key)
    return results
