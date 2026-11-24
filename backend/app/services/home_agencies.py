"""광주 · 전남 기관 — **한 곳**(43차 M6 · Q7).

기관 이름 속 지명(광주 · 전남 · 여수 · 순천 · 목포 · 나주)만 보면 남부대 · 조선대 · 영암 조합 · 빛가람 혁신도시 국가기관(한국인터넷진흥원
등)이 「지역제한 표기가 없습니다」로 나왔다. 판정은 **수요기관 기준**(조달청 · 지방조달청은 대행일 뿐)이고, 대학 · 22개 시군 ·
혁신도시 기관 목록은 여기 하나에만 둔다. 점수(전략 가산) · 실무순 광주 · 전남 예외 · 브리핑 「광주 · 전남 발주」가 같은 함수를 쓴다.
"""

from __future__ import annotations

import re
from typing import Final

#: 옛 전라남도 22개 시군(「신안산대」는 경기 안산이라 뺀다 · 「순천향」은 충남).
_CITIES: Final[tuple[str, ...]] = (
    "목포", "여수", "순천(?!향)", "나주", "광양", "담양", "곡성", "구례", "고흥", "보성", "화순", "장흥", "강진", "해남", "영암",
    "무안", "함평", "영광", "장성", "완도", "진도", "신안(?!산)",
)

#: 광주 · 전남 대학(이름에 지명이 없는 곳).
_UNIVERSITIES: Final[tuple[str, ...]] = (
    "조선대", "조선이공대", "남부대", "호남대", "동신대", "송원대", "세한대", "초당대", "동강대", "서영대", "청암대", "한영대",
    "기독간호대", "광주과학기술원", "GIST", "한국에너지공과대", "한국에너지공대", "KENTECH",
)

#: 빛가람 혁신도시(나주) · 광주 국가기관 · 공공기관.
_INSTITUTIONS: Final[tuple[str, ...]] = (
    "한국전력공사", "한전KDN", "한전KPS", "한국인터넷진흥원", "한국농어촌공사", "한국콘텐츠진흥원", "한국전력거래소",
    "한국농수산식품유통공사", "한국방송통신전파진흥원", "국립전파연구원", "우정사업정보센터", "사립학교교직원연금공단",
    "한국문화예술위원회", "농식품공무원교육원", "국립아시아문화전당", "아시아문화원", "인공지능산업융합사업단",
)

_HOME_RE: Final[re.Pattern[str]] = re.compile(
    "|".join(["광주", "전남", "전라남도", *_CITIES, *(re.escape(u) for u in _UNIVERSITIES), *(re.escape(i) for i in _INSTITUTIONS)])
)
#: 「경기도 광주시」 · 「경기 광주」는 우리 광주가 아니다.
_GYEONGGI_GWANGJU_RE: Final[re.Pattern[str]] = re.compile(r"경기\S*\s*광주")
#: 조달청 · 지방조달청 — 대행이라 지역 근거가 아니다(수요기관을 본다).
PROCUREMENT_OFFICE_RE: Final[re.Pattern[str]] = re.compile(r"^\s*조달청")


def is_home(name: str | None) -> bool:
    """광주 · 전남 기관 이름인가."""
    text = (name or "").strip()
    if not text or _GYEONGGI_GWANGJU_RE.search(text):
        return False
    return bool(_HOME_RE.search(text))


def deciding_agency(agency: str | None, demand: str | None) -> str | None:
    """지역을 정하는 기관 — 수요기관이 있으면 수요기관(조달청이 대행해도), 없으면 공고기관."""
    demand_text = (demand or "").strip()
    return demand_text or (agency or "").strip() or None


def display_agency(agency: str, demand: str | None) -> str:
    """화면 · 브리핑의 기관 칸 — 조달청 대행이면 「국토교통인재개발원(조달청 대행)」(43차 BRIEF-03)."""
    demand_text = (demand or "").strip()
    if demand_text and demand_text != agency.strip() and PROCUREMENT_OFFICE_RE.search(agency or ""):
        return f"{demand_text}(조달청 대행)"
    return agency
