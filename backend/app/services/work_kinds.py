"""일의 종류 — 「무슨 일을 시키는가」의 **단일 출처**.

상세 분석(`capability_service`)과 목록 조회(`procurement_service`·`opportunity_service`)가
같은 규칙표 하나를 본다. 여기 없는 두 번째 규칙표를 만들지 않는다 — 목록이 「개발」이라 부른 것을
상세가 「감리」라 부르면 화면이 스스로 모순된다.

`opportunity_filter` 의 `matched_work`/`matched_dev` 는 이 축을 재지 않는다. 그쪽은
«AI 후보인가»를 판정하려고 모은 **근거 키워드 목록**이고, 여기는 «무슨 일을 시키는가»다.
실측(2026-09-10, demo-snapshot 152건): 두 축의 답이 high 20건 중 5건에서 갈렸고,
`matched_work` 로 「교육」을 뽑으면 캐시 87건 중 82건이 나오는데 그중 74건이
「○○교육청 발주 급식실 증축 설계용역」류였다. 같은 87건을 이 규칙으로 나누면 교육은 6건이다.
"""

from __future__ import annotations

import re
from typing import Final, Sequence

from app.schemas.capability import WorkKind, WorkTrack
from app.schemas.procurement import ProcurementNotice


# ---------------------------------------------------------------------------
# 일의 종류 — 「무슨 일을 시키는가」
# ---------------------------------------------------------------------------
# 순서가 중요하다. 감리·구매·연구는 개발 낱말과 함께 등장하는 일이 많고
# (「AI 실습 기능 **개발** 위탁**감리**」), 그때 우리가 할 일은 개발이 아니라 감리다.
WORK_KIND_RULES: Final[tuple[tuple[WorkKind, re.Pattern[str]], ...]] = (
    (
        "supervision",
        re.compile(r"위탁\s*감리|감리\s*용역|감리\s*사업|정보시스템\s*감리|감리원|사업\s*관리\s*위탁"),
    ),
    (
        "procurement",
        re.compile(
            # 「사용권 구매」 — 교수학습 플랫폼 사용권을 사는 공고가 교육(A1)으로 잡혔다(37차 기획서 1-10 · 아이모두 1767120)
            r"구독권|기념품|라이선스\s*(?:구매|구입|공급)|사용권\s*(?:구매|구입|공급)|물품\s*(?:구매|구입|납품)"
            r"|장비\s*(?:구매|구입|납품|임차)|기자재\s*(?:구매|납품)|도입\s*사업|제품\s*도입"
            r"|공급\s*및\s*설치|단순\s*납품"
        ),
    ),
    (
        "research",
        re.compile(
            r"로드맵\s*수립|정책\s*연구|기초\s*연구|학술\s*연구|연구\s*용역|방안\s*연구"
            r"|실태\s*조사|동향\s*조사|타당성\s*조사|수요\s*조사|기술\s*조사|현황\s*분석\s*연구"
        ),
    ),
    (
        "construction",
        re.compile(
            r"신축|증축|개축|리모델링|착공|지하안전|내진|구조\s*설계|실시설계|기본\s*설계"
            r"|설계\s*용역|설계용역|토목|건축\s*공사|전기\s*공사|소방\s*공사|시설물"
        ),
    ),
    (
        "education",
        # 2026-09-20 실측으로 넓혔다 (ISSUE-073). 「AI 교육 지원센터 프로그램 위탁 운영」
        # (2.27억)·「제4기 AI ADVANCED 과정 운영」·「AI취업캠프 프로그램 위탁」처럼 **교육을
        # 운영하는 일인데 「교육」이라는 낱말이 그 자리에 없는** 공고가 통째로 빠져 있었다.
        #
        # 더한 말: 과정 운영 · 프로그램 운영 · 프로그램 위탁 · 위탁 운영 · 캠프 ·
        #          교육 지원센터 · 스터디 랩 · 인력/인재 양성.
        # 「부트캠프」·「송캠프」·「취업캠프」는 `캠프` 하나로 들어온다 —
        # 같은 것을 두 번 적지 않는다.
        re.compile(
            r"교육\s*과정|교육과정|교육\s*운영|교육운영|교육\s*기획|교육\s*프로그램|커리큘럼"
            r"|교안|강사|캠프|아카데미|리터러시|역량\s*강화|역량강화|연수|실무\s*교육"
            r"|직무\s*교육|이러닝|교육생|수강생|교재"
            # 「양성」은 **사람을 기르는 말일 때만** 인정한다. 낱말만 보면
            # 「하이퍼링커 양성 플랫폼 구축」처럼 «양성 프로그램에 쓸 물건을 만드는» 사업까지
            # 교육으로 끌려온다 — 실측에서 2건이 그랬다.
            r"|인력\s*양성|인재\s*양성|양성\s*(?:과정|교육|사업|프로그램)"
            r"|과정\s*운영|프로그램\s*운영|프로그램\s*위탁|위탁\s*운영"
            r"|교육\s*지원\s*센터|교육지원센터|스터디\s*랩",
            re.IGNORECASE,
        ),
    ),
    ("consulting", re.compile(r"컨설팅|자문|진단\s*용역|전략\s*수립")),
    (
        "development",
        re.compile(
            r"개발|구축|고도화|구현|제작|솔루션|소프트웨어|자동화|플랫폼|시스템"
            r"|웹서비스|홈페이지|대시보드|API|앱\s*개발"
        ),
    ),
)

# 우리가 수행사로 들어갈 수 없는(또는 개발이 아닌) 일의 종류.
# 이게 잡히면 개발 역량이 아무리 맞아도 그 사업의 «수행자»가 아니다.
NOT_OUR_ROLE: Final[dict[str, str]] = {
    "supervision": "감리는 남이 만든 것을 감독하는 일이라 개발 수행과 역할이 다릅니다 (감리원 자격이 따로 필요합니다).",
    "procurement": "물품·구독권을 사서 납품하는 사업이라 개발 수행 사업이 아닙니다.",
    "research": "조사·연구 보고서를 내는 사업이라 개발 수행 사업이 아닙니다.",
    "construction": "공사·시설 설계 사업이라 소프트웨어 개발과 분야가 다릅니다.",
}


#: 교육 낱말이 있어도 **교육을 운영하는 일이 아닌** 것 (ISSUE-073, 정밀도 우선).
#:
#: 실측에서 「2026 AI·빅데이터 기반 학교 리더십 전략과정 직무연수 3기 **연수시설 임차**」가
#: 교육으로 잡혔다. 발주 대상은 강의가 아니라 **건물을 빌리는 것**이다. 같은 이유로
#: 「교육관 개관식 행사」도 교육 운영이 아니다.
#:
#: 「교육자료 콘텐츠 개발」은 여기 없어도 된다 — 그 말에는 교육 어휘가 걸리지 않아
#: 이미 개발로 간다.
EDUCATION_EXCLUSION_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:연수|교육)\s*(?:시설|장)\s*(?:임차|임대|대관|사용)"
    r"|개관식"
)


def detect_work_kinds(text: str) -> list[WorkKind]:
    """공고가 요구하는 일의 종류. 걸리는 것을 **전부**, 규칙 순서대로 돌려준다.

    교육 어휘가 걸려도 「시설 임차」·「개관식」이면 교육에서 뺀다 — 넓힌 어휘가 데려온
    오탐을 여기서 막는다. 정밀도가 먼저다.
    """
    kinds = [kind for kind, pattern in WORK_KIND_RULES if pattern.search(text)]
    if "education" in kinds and EDUCATION_EXCLUSION_RE.search(text):
        kinds = [kind for kind in kinds if kind != "education"]
    return kinds


def work_tracks(kinds: Sequence[WorkKind]) -> list[WorkTrack]:
    """일의 종류 → 화면 갈래. **새 규칙이 아니라 투영이다** — 낱말을 하나도 보지 않는다.

    감리·연구·구매·공사가 하나라도 섞이면 「그 밖」이다. 「AI 실습 기능 **개발** 위탁**감리**」처럼
    개발 낱말과 함께 오는 일이 흔한데, 그때 우리가 할 일은 개발이 아니라 감리다.
    이 판정은 `capability_service` 의 `is_development` 와 **같은 규칙**을 쓴다.
    """
    if any(kind in NOT_OUR_ROLE for kind in kinds):
        return ["other"]
    tracks: list[WorkTrack] = []
    if "education" in kinds or "consulting" in kinds:
        tracks.append("education")
    if "development" in kinds:
        tracks.append("development")
    # 빈 목록은 「해당 없음」이 아니라 「가리지 못했다」다. 억지로 교육·개발에 밀어 넣지 않는다.
    return tracks or ["unclassified"]


def notice_work_text(notice: ProcurementNotice) -> str:
    """갈래 판정에 넣을 텍스트.

    **발주기관명을 넣지 않는다.** 넣으면 기관 이름이 일의 종류를 뒤집는다 — 실측 5건:
    「지방자치인재**개발**원」·「노인인력**개발**원」이 개발로, 「한국**교육**과정평가원」이 교육으로
    잡혔다. `capability_service.evaluate()` 가 이미 지키는 규칙과 같다.
    """
    return " ".join(filter(None, [notice.title, notice.description or ""]))


#: 조달 분류명(`pubPrcrmntClsfcNm`)이 갈래를 **직접** 말해 주는 경우 (0921 §4-C-1).
#:
#: 공고명만 보면 「AI 활용 역량 강화」가 교육인지 개발인지 흐린데, 조달청이 붙인 분류는
#: 그것을 이미 정해 두었다. 실측(2026-09-17 캐시 191건)에서 정보시스템개발서비스 40건 ·
#: 정보화교육서비스 6건 · 기타교육서비스 7건처럼 값이 분명하다.
#: **낱말 규칙을 덮어쓰지 않고 «더한다»** — 분류가 개발이라고 해서 교육 과업이 없는 것은 아니다.
CLASSIFICATION_KINDS: tuple[tuple[str, WorkKind], ...] = (
    ("교육", "education"),
    ("개발", "development"),
    ("구축", "development"),
    ("감리", "audit"),
    ("연구조사", "research"),
)


def classification_kinds(procurement_class: str | None) -> list[WorkKind]:
    """조달 분류명에서 읽히는 일의 종류. 없으면 빈 목록."""
    text = (procurement_class or "").strip()
    if not text:
        return []
    return [kind for token, kind in CLASSIFICATION_KINDS if token in text]


#: 제목 유형(근사) → 일의 종류(43차 결정 4 — 사업영역 점수도 제목 먼저 · 유형 근사와 같은 원칙).
_TITLE_TYPE_KINDS: dict[str, tuple[WorkKind, ...]] = {
    "A1": ("education",), "A2": ("education",), "B1": ("consulting",), "C": ("development",),
}


def of_notice(notice: ProcurementNotice) -> dict[str, object]:
    """공고 하나의 갈래 판정 결과 (API 응답에 그대로 실린다).

    43차 결정 4 — **제목이 갈래를 말하면 제목 먼저**(A1 · A2 · B1 · C). 조달 분류명(「연구조사 · 학술연구」) · 요약의 「연구」가 교육 ·
    컨설팅 공고를 「그 밖」(사업영역 0.2)으로 묶었다(본업 덩어리 A1 · A2 · B1 중 0.2 가 34행 · 그중 19행이 기준 답안 본업). 제목에 갈래가
    없거나 B2 · D 면 예전대로 제목 · 요약 · 조달 분류를 모두 본다.
    """
    from app.services import practical_priority  # 늦게 — practical_priority 가 이 모듈을 부른다

    titled = practical_priority._title_type(notice.title or "")
    if titled is not None and titled[0] in _TITLE_TYPE_KINDS:
        title_kinds = [k for k in detect_work_kinds(notice.title or "") if k not in NOT_OUR_ROLE]
        wanted = set(_TITLE_TYPE_KINDS[titled[0]]) | set(title_kinds)
        kinds = [kind for kind, _ in WORK_KIND_RULES if kind in wanted]
        return {"kinds": kinds, "tracks": work_tracks(kinds), "basis": "공고명·요약", "method": "RULE"}
    kinds = detect_work_kinds(notice_work_text(notice))
    # 조달 분류명이 말해 주는 것을 **더한다** (0921 §4-C-1). 순서는 규칙표 순서를 지킨다.
    raw = notice.raw_data if isinstance(notice.raw_data, dict) else {}
    extra = classification_kinds(raw.get("procurement_class"))
    if extra:
        merged = [kind for kind, _ in WORK_KIND_RULES if kind in kinds or kind in extra]
        kinds = merged or kinds
    return {
        "kinds": kinds,
        "tracks": work_tracks(kinds),
        # 무엇을 보고 판정했는지 — 상세 분석이 과업 원문까지 읽는 것과 구분된다.
        "basis": "공고명·요약",
        "method": "RULE",
    }
