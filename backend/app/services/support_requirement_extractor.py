"""기업마당 **공고문에서 조항을 뽑는다** (0924.md §4-A-3 · ISSUE-096).

## 무엇을 뽑는가

검수자가 공고문 26건을 직접 읽고 판정에 쓴 조건들이다
(`docs/reports/2026-09-24_bizinfo_candidates.md`). 요약문·해시태그에는 하나도 없다.

    소재       「디지털 제품(서비스)를 보유한 광주광역시 본사소재 기업」
    조직 형태  「(예비)사회적기업, (예비)마을기업, 사회적협동조합, 자활기업(법인)」
    인원       「고용보험 피보험자 수 10인 이상 기업」 + 「10인 미만 기업도 참여 가능」
    연차       「모집공고일 기준 창업 7년 이내인 창업기업」
    매출       「지식서비스산업 : 10억 이상」
    선행·보유  「스마트제조혁신R&D 최종평가 결과 완료판정(60점 이상)」
    역할       「공급기업 및 수요기업 형태의 컨소시엄 참여 필수」
    돈         「기업당 10~20백만원 차등 지원」 · 「정부지원금 80%」 · 「(무료)」
    제외       「교육·훈련을 주 사업으로 하는 훈련기관 … 제외」
    마감       「2026-09-23 18:00」 · 「이메일 접수」

## 규율

- **원문 그대로 인용한다** (0924 §3-14). 문장을 만들어 넣지 않는다. 못 뽑았으면 그 조항이
  없는 것이고, 판정은 「확인 필요」로 간다 — 「없으니 가능」이 아니다.
- **LLM 을 쓰지 않는다.** 정규식과 절 제목으로만 찾는다(CLAUDE.md §4-D: 구조화 가능한 것은
  규칙으로). 규칙이 못 잡는 문장은 사람이 원문에서 읽는다.
- 찾은 자리(쪽·절 제목)를 함께 남긴다. 「신청자격」 절에서 나온 소재 요건과 「참고」에
  스쳐 지나간 지역 이름은 무게가 다르다 — 판정 규칙이 그 차이를 본다.

## 완벽한 파서가 아니다

공고문 서식은 기관마다 다르다. 놓치는 모양이 나오면 여기에 규칙을 더한다. 놓친 것을
「없음」으로 단정하지 않는 것이 이 파일의 가장 중요한 성질이다.
"""

from __future__ import annotations

import re
from typing import Final, Iterable

from app.schemas.business_opportunity import SupportClause, SupportRequirements
from app.services import bizinfo_document_store, wording

# --------------------------------------------------------------------------
# 절 제목
# --------------------------------------------------------------------------

#: 절 이름 → 그 절에서 찾은 조항의 «무게». 자격 절에서 나온 것만 「불가」의 근거가 된다.
SECTION_ELIGIBILITY: Final[str] = "자격"
SECTION_SUPPORT: Final[str] = "지원내용"
SECTION_BURDEN: Final[str] = "부담"
SECTION_DOCUMENTS: Final[str] = "제출서류"
SECTION_EXCLUSION: Final[str] = "제외"
SECTION_SCHEDULE: Final[str] = "일정"

_SECTION_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        SECTION_ELIGIBILITY,
        ("지원대상", "신청자격", "참여자격", "모집대상", "지원자격", "신청대상", "참가자격",
         "응모자격", "지원 대상", "신청 자격", "참여대상", "신청 대상", "기본요건", "자격요건",
         "지원조건", "선정기준", "공모대상",
         # 「4. 참여기업 자격 및 역할」·「기업 자격」 — 자격 요건이 여기 표로 들어 있었다.
         "참여기업 자격", "기업 자격", "자격 및",
         # 띄어쓰기가 다른 표기와 「사업대상」. 같은 뜻인데 한 글자 차이로 놓치고 있었다.
         "사업대상", "사업 대상", "참여 대상", "모집 대상", "지원 자격", "참여 자격"),
    ),
    (SECTION_EXCLUSION, ("지원제외", "참여제한", "신청제외", "제외대상", "지원 제외")),
    (SECTION_SUPPORT, ("지원내용", "지원규모", "지원금액", "지원사항", "지원예산", "지원항목")),
    (SECTION_BURDEN, ("자부담", "기업부담", "민간부담", "기관부담", "부담금")),
    (SECTION_DOCUMENTS, ("제출서류", "구비서류", "신청방법", "접수방법", "신청 방법", "접수 방법")),
    (SECTION_SCHEDULE, ("신청기간", "접수기간", "모집기간", "공고기간", "추진일정", "신청 기간")),
)

#: 자격 판정의 근거가 될 수 있는 절. 그 밖의 절에서 나온 조항은 근거로 쓰되 「불가」는 못 만든다.
#:
#: **제외 절은 여기 없다** (0925 §4-C-1 · ISSUE-098). 「< 지원 제외 대상 >」 아래의
#: 「…적용을 받지 않는 사업(비영리사회적기업, 어린이집, 장기요양센터 등)」에서
#: 「사회적기업」을 뽑아 **요건**으로 읽었고, 그래서 장애인 창업 컨설팅이 「가능」이 됐다.
#: 제외 절의 문장은 `exclusion` 갈래로만 담는다 — 요건이 아니라 «막는 말»이다.
ELIGIBILITY_SECTIONS: Final[frozenset[str]] = frozenset({SECTION_ELIGIBILITY})

#: **자격 요건을 읽을 좁은 창.** 제목 바로 아래 목록만 본다.
#:
#: 「신청자격」 절이 열 쪽을 덮으면, 그 안의 평가표·밋업 안내·서식까지 자격 요건이 된다
#: (실측: 「밋업 : 발표평가 대상자와 공공기관과…」 줄이 「공공기관만 신청 가능」으로 읽혔다).
#: 소재·조직 형태·인원·연차·매출은 대개 제목 바로 다음 몇 줄에 적힌다.
ELIGIBILITY_WINDOW_LINES: Final[int] = 6

#: **요건이 아니라 «막는 말»**인 줄. 여기서 조직 형태·소재를 읽으면 뜻이 뒤집힌다 —
#: 「공공기관의 지원사업 … 참여 제한」을 「공공기관만 신청 가능」으로 읽는다.
_NEGATIVE_RE = re.compile(r"제외|제한|불가|해당하지\s*않|아닌\s*경우|없는\s*기업|취소|환수|반납")

#: **자격이 아니라 «평가·운영·인력» 문장**임을 가리키는 말 (ISSUE-115 · prompt_02 §4-C).
#:
#: 자격 갈래 가운데 역할(role)과 선행·보유 요건(prerequisite)은 「문서 어디에 있어도 뜻이
#: 같다」고 보아 절을 가리지 않고 뽑는다. 대개는 맞다 — 「컨소시엄 참여 필수」는 어느 절에
#: 있든 요건이다. 그런데 126482 에서 그 관대함이 이렇게 샜다(12차 보고 §4-(4) · 재검증 10 §3-5):
#:
#:   「밋업(Meet-Up) : 발표평가 대상자와 공공기관과 온·오프라인」        → 평가 진행 안내
#:   「⑨ 2026년 동 사업 주관기관의 전담조직의 장, 전담/겸직인력으로 …」  → 운영 인력 안내
#:
#: 둘 다 「공공기관」·「주관기관」이라는 낱말 때문에 역할 조항으로 잡혔다. 사업계획서 초안의
#: 「신청 자격 충족 설명」에 이 문장들이 인용되면 담당자가 자격 요건으로 읽는다.
#:
#: 절을 좁히는 대신 **이 말이 든 줄만** 뺀다. 절로 막으면 기준 답안 26행의 역할 조항
#: (「공급기업 및 수요기업 형태의 컨소시엄 참여 필수」 등)까지 함께 사라진다.
_NOT_ELIGIBILITY_RE = re.compile(
    r"밋업|Meet-?Up|발표\s*평가|선정\s*평가|평가\s*일정|평가\s*위원|심사\s*위원"
    r"|전담\s*조직|전담\s*인력|겸직\s*인력|참여\s*중\s*또는\s*참여|참여\s*예정"
    r"|간담회|설명회|워크숍|워크샵|안내\s*예정",
    re.IGNORECASE,
)

#: **절차 서술** — 「누가 무엇을 한다」이지 「신청자가 무엇이어야 한다」가 아니다
#: (ISSUE-119 · prompt_03 §4-D-3).
#:
#: 126482 245행이 이렇게 샜다:
#:
#:   「※ 신청기업의 요건 및 사업계획서 유사‧중복성 검토는 전문기관 및 주관기관에서 상시 진행하며,」
#:
#: 「주관기관」이라는 낱말 때문에 **역할 조항**(`role: 주관기관`)으로 잡혔다. 그런데 이 줄이
#: 말하는 것은 심사하는 쪽의 일하는 방식이지 신청자의 자격이 아니다. 사업계획서 초안의
#: 「신청 자격 충족 설명」에 이것이 인용되면 담당자가 자격 요건으로 읽는다.
#:
#: **좁게 잡는다.** 「검토/심사/평가/점검」 + 「는/은」 + … + 「진행/실시/수행」이 한 줄에
#: 모두 있을 때만이다. 진짜 요건은 이 모양이 아니라서 그대로 남는다 —
#: 「… 에 한하여 신청 가능」·「… 완료판정 과제」·「컨소시엄 참여 필수」.
_PROCEDURE_RE = re.compile(
    r"(?:검토|심사|평가|점검)\s*(?:는|은)\s*[^\n]*?(?:진행|실시|수행)"
)

#: 절 제목이 다스리는 줄 수.
#:
#: 제목이 문서 끝까지 이어진다고 보면 안 된다. 스무 쪽짜리 공고문에서 「신청자격」 한 줄
#: 뒤에 오는 붙임·표·서식이 전부 「자격 절」이 되어, 별첨의 아무 숫자나 자격 요건으로
#: 읽혔다(실측: 별첨 표의 「10인 이상」·「5억원 이상」이 참여 요건으로 잡혔다).
#: 제목은 **바로 아래 목록**을 다스린다.
SECTION_WINDOW_LINES: Final[int] = 20

#: 줄 자체가 자격 문장임을 가리키는 낱말. 절 제목을 못 잡았을 때의 두 번째 근거다.
_SELF_ELIGIBILITY = ("지원대상", "신청자격", "참여자격", "모집대상", "지원자격", "신청대상", "기본요건")
#: 문장 가운데서 그 낱말을 **말하는** 줄 — 「…소상공인정책자금 지원대상에 포함.」(121182 붙임 용어 풀이)은 자격 절을 열지 않는다(35차 R34S-03).
_ELIGIBILITY_MENTION_RE = re.compile(r"(?:지원|신청|모집)\s*대상\s*(?:에|에서)\s*(?:포함|제외|해당)")
#: 형태 낱말을 대상 요건으로 읽으면 안 되는 문단의 머리 — 「(비영리법인 중 예외적으로 중소기업 인정)」 · 「…을 의미함」 같은 용어 풀이.
#: 참여제한 · 제외 머리 아래(`exclusion_run`)도 같다(121182 · 35차 R34S-03).
_ORG_SKIP_HEADING_RE = re.compile(
    r"예외적으로|용어\s*(?:의\s*)?(?:정의|풀이|설명)|이란[,，]"
    # 「※ 「광주 소재」는 본점 소재지를 의미함」 같은 한 줄 풀이는 아래 줄을 다스리지 않는다(35차 마지막 검토)
    r"|(?:다음|아래|각\s*호)[^\n]{0,40}?(?:을|를)\s*의미함"
)
#: 건너뛰기 구간을 끝내는 윗단 글머리 — 새 항목이다(「○ 광주광역시 소재 사회적기업」 · 35차 마지막 검토).
_TOP_BULLET_RE = re.compile(r"^\s*[□○❍■▣]")
#: 목록 항목 글머리 — 제외 · 서류 목록 안의 줄이라 절 제목처럼 보여도 구간을 끝내지 않는다.
#: 「1. 사업개요 · 가. 지원대상」은 절 제목이고 「1) · 가)」가 항목이다.
_LIST_ITEM_RE = re.compile(r"^\s*(?:[-–·ㆍ*※▸]|[①-⑳]|\d{1,2}\s*\)|[가-힣]\s*\))")


def _bullet_rank(line: str) -> int | None:
    """글머리 단계 — 「1. · 가.」 머리 0 · □ 1 · ○ 2 · 그 밖 목록 글머리(- · ① · ※ · 1)) 3 · 글머리 없음 None.

    제외 · 서류 건너뛰기는 그 구간을 연 줄보다 **윗단** 글머리가 나오면 끝난다(36차 R35-RULE-01 — 「※ 확인방법 : …」 아래
    「○ 기업부설연구소를 보유한 기업」이 서류 줄로 삼켜졌다). 같은 단계는 끝내지 않는다 — 「○ 제외 대상」 아래 ○ 항목이 이어지는 공고가 있다.
    """
    if re.match(r"^\s*(?:\d{1,2}\s*\.(?!\d)|[가-하]\s*\.)\s*\S", line):
        return 0
    if re.match(r"^\s*[□■▣◆◇]", line):
        return 1
    if re.match(r"^\s*[○❍◦●◎]", line):
        return 2
    if _LIST_ITEM_RE.match(line):
        return 3
    return None


def _ends_run(rank: int | None, opened: int) -> bool:
    """구간을 연 줄(`opened`)보다 윗단 글머리인가 — **같은 글머리 체계 안에서만**(□ · ○ · - 끼리 · 「1. · 가.」 끼리).
    「□ 제출서류」 아래 「1. 사업신청서 1부」는 □ 보다 윗단이 아니라 그 목록의 항목이다(36차 마지막 검토 R36-02 —
    서류 구간이 첫 항목에서 끝나 「3. 기업부설연구소 인정서(보유기업에 한함)」가 연구소 요건으로 읽혀 거짓 「불가」)."""
    return rank is not None and rank < opened and (rank == 0) == (opened == 0)


#: 자격 낱말 — 「신청자격 및 제외대상」 · 「지원대상(참여제한 기업 제외)」 · 「지원대상 및 지원제외 대상」 머리는 제외 구간을 열지 않는다
#: (36차 R35-RULE-01 — 그 바로 아래 □ 줄의 형태 · 매출 · 연구소 요건이 제외 목록으로 삼켜져 거짓 「가능」이었다).
_ELIGIBILITY_WORD_RE = re.compile(r"신청\s*자격|지원\s*대상|참여\s*자격|모집\s*대상|지원\s*자격|신청\s*대상")
#: 대상을 꾸미는 꼴 — 「…를 추진하는 국내 중소 · 중견기업」 · 「으뜸기업 6기로 선정된 기업은」 · 「…에 소재한」. 이 꼴이 없는 줄
#: (「(지원방식) 참여청년, 기업 등에 보조금 지급」 · 「청년이 기업에서 …」)은 대상 요건이 아니다.
_TARGET_NOUN_RE = re.compile(
    # 꾸밈말 끝(인 · 한 · 된 · 는) 뒤에 띄어쓰기 — 「개인정보 보유기업」의 「인」은 꾸밈말이 아니다(123682 전략산업 표)
    r"[인한된는]\s+(?:[가-힣A-Za-z·ㆍ]{1,10}\s*){0,2}(?:기업|업체|사업자|기관|법인|단체|조합|소상공인|창업자|사업장|자)(?![가-힣])"
    r"|소재\s*(?:한|하는|하고|해야)|에\s*한(?:함|하여|정)"
)
#: 「전담부서 인정서만 보유한 기업은 미포함」 · 「연구개발전담부서는 불인정」 · 「인정하지 않으므로」 — 기업부설연구소만 받는 공고(36차 R35-DV-02 · 125370 · 127116 · 126756).
_DEPT_EXCLUDED_RE = re.compile(r"전담\s*부서[^\n]{0,30}?(?:미포함|불인정|인정하지\s*않|인정\s*안\s*됨|인정되지\s*않)")
#: 「기업부설연구소 **또는 연구개발전담부서**」 — 전담부서도 받는 조항(37차 R36-RV-06).
_DEPT_ALLOWED_RE = re.compile(r"또는\s*(?:연구\s*개발\s*)?전담\s*부서")
#: 「전담부서 미포함」을 찾는 범위 — 같은 절 안 앞뒤 몇 줄(37차 R36-RV-06).
DEPT_EXCLUDED_LOOKAROUND_LINES: Final[int] = 6
#: 가점 · 평가 문맥 — 「전담부서 보유 기업은 가점 불인정」은 대상 요건이 아니다(36차 R36-10).
_BONUS_CONTEXT_RE = re.compile(r"가점|가산|우대|배점|평가")
#: 공고에 주관기관 말고 다른 자리(공동 · 참여)가 있다 — 주관기관 자리에만 걸린 요건은 「불가」로 닫지 않는다(36차 R35-DV-03).
_OTHER_ROLE_RE = re.compile(r"공동\s*연구\s*개발\s*기관|공동\s*연구\s*기관|공동\s*기관|참여\s*기관")
#: 「< 주관연구개발기관 자격 조건 >」 — 이 아래 줄은 주관기관 자리의 요건이다(127025).
_LEAD_ROLE_HEADING_RE = re.compile(r"[<〈【\[]\s*주관\s*연구\s*개발\s*기관[^>〉】\]]{0,12}(?:자격|요건|조건)")
#: 주관기관을 주어로 한 줄 — 「주관연구개발기관이 기업인 경우는 …」(126756). 같은 줄에 「공동」이 있으면 두 자리 모두다(125370).
#: 「주관연구개발기관」만 본다 — 운영기관 「주관기관 : 경북테크노파크」 · 「주관기관(재단)이 정한 기준」은 신청 자리가 아니다(36차 R36-08).
_LEAD_ROLE_RE = re.compile(r"주관\s*연구\s*개발\s*기관")
#: 「ㅇ 주관연구개발기관 : 해당 시·도내 기업(법인)」 — 그 아래 「*」 줄들도 주관기관 자리의 요건이다(127025 RFP 첨부).
_LEAD_ROLE_LABEL_RE = re.compile(r"^\s*[ㅇ○◦❍·\-]?\s*주관\s*연구\s*개발\s*기관\s*[:：]")
#: 주관기관 자격 머리가 다스리는 줄 수.
LEAD_ROLE_RUN_LINES: Final[int] = 10
#: 과제 이름의 지역 표시 — 「- (경북) 산불화재시 …」(127025 지정공모 과제).
_TASK_REGION_RE = re.compile(r"^\s*[-·•▪○◦]?\s*\((서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)\)\s*\S")
#: 「해당 연구과제별 시·도에 소재해야 함」 — 과제 이름의 지역이 소재 요건이다(36차 R35-DV-01 · 127025).
_TASK_SITE_RE = re.compile(r"과제\s*별\s*(?:해당\s*)?시\s*[·ㆍ․]?\s*도[^\n]{0,6}?(?:에|내)\s*소재")
#: 「기업부설연구소를 보유한 중소·중견기업」 — 연구소 문장 안의 중소기업도 확인서 조항이다(36차 R35-DV-01 · 125778).
_LAB_SME_RE = re.compile(r"(?:기업부설\s*연구소|연구개발\s*전담\s*부서)[^\n]{0,40}?보유(?:한|하고\s*있는)\s*(?:국내\s*)?중소\s*[·ㆍ‧]?\s*(?:중견)?\s*기업")
#: 절차 머리 — 이 아래의 「(신청 대상) …」은 회사 자격이 아니다(121107 「이의신청 절차 — (신청 대상) … 오류가 있는 기업」).
_PROCEDURE_HEADING_RE = re.compile(r"이의|절차|방법|일정|문의|선정|평가|변경|정산|결과|유의|기타|붙임|참고|서식|협약|사후")
#: 대상 요건이 아닌 대상 절 줄 — 머리 문장(「다음 요건을 모두 충족하는 기업」) · 우대 · 가점 · 평가 · 절차.
_NOT_TARGET_RE = re.compile(
    r"(?:다음|아래)[^\n]{0,20}?(?:요건|조건|자격|각\s*호|중\s*하나|어느)|우대|가점|우선\s*(?:선정|지원|선발|검토)|배점|평가|심사|선정\s*(?:기준|절차)"
    r"|신청\s*(?:방법|기간|서류)|문의|참고|붙임|별첨|서식|여부|이의|심의|안내|지급|보조금"
    # 「…미리 확인하고 싶은 기업」 — 추천 문구지 자격이 아니다(125426)
    r"|(?:싶은|원하는)\s*(?:기업|업체|자)"
)
#: 그 머리가 다스리는 줄 수.
ORG_SKIP_RUN_LINES: Final[int] = 8


# --------------------------------------------------------------------------
# 지역
# --------------------------------------------------------------------------

#: 광역 이름 → 대표 이름. `bizinfo_service.REGION_ALIASES` 와 같은 축이다.
#: 통합 이후 광주·전남은 한 이름 「전남광주」다.
_WIDE_REGIONS: tuple[tuple[str, str], ...] = (
    ("전남광주통합특별시", "전남광주"),
    ("광주광역시", "전남광주"),
    ("전라남도", "전남광주"),
    ("서울특별시", "서울"), ("부산광역시", "부산"), ("대구광역시", "대구"),
    ("인천광역시", "인천"), ("대전광역시", "대전"), ("울산광역시", "울산"),
    ("세종특별자치시", "세종"), ("경기도", "경기"), ("강원특별자치도", "강원"),
    ("충청북도", "충북"), ("충청남도", "충남"), ("전북특별자치도", "전북"),
    ("전라북도", "전북"), ("경상북도", "경북"), ("경상남도", "경남"),
    ("제주특별자치도", "제주"),
)

#: 소재 요건임을 가리키는 낱말. 이것이 없으면 그냥 지역 이름이 스친 것이다.
_SITE_WORDS = ("본사", "소재", "사업장", "공장", "연구소", "주소지", "소재지", "위치", "등록지")

#: **광역시 줄임말** 「광주시 · 울산시 … 소재」 — 시 · 군이 아니라 광역이다(37차 recheck29 R36-RV-05).
#: 「광주시」는 경기도 광주시와 겹친다 — 조항에 `ambiguous` 를 달고 판정이 소관 · 수행기관 지역으로 가린다(못 가리면 확인 필요).
METRO_SHORT: Final[dict[str, str]] = {
    "서울시": "서울", "부산시": "부산", "대구시": "대구", "인천시": "인천",
    "광주시": "전남광주", "대전시": "대전", "울산시": "울산", "세종시": "세종",
}
#: 뒤에 조사 · 소재 낱말만 온다 — 「광주시청」 · 「서울시립」은 아니다.
_METRO_SHORT_RE = re.compile(r"(?<![가-힣])(서울|부산|대구|인천|광주|대전|울산|세종)시(?=$|[^가-힣]|에|내|와|과|및|소재|본사|사업장|지역)")

#: 시·군 이름. 광역보다 좁은 요건(「광양시 소재 제조 공장」)을 놓치지 않으려는 것이다.
_CITY_RE = re.compile(r"(?<![가-힣])([가-힣]{2,3}(?:시|군))\s*(?:내)?\s*(?:에)?\s*(?:소재|본사|사업장|공장|위치)")
#: 시·군으로 읽으면 안 되는 꼬리. 「광주광역시」는 광역이지 시·군이 아니다.
_NOT_A_CITY = ("광역시", "특별시", "자치시")


# --------------------------------------------------------------------------
# 조직 형태
# --------------------------------------------------------------------------

def word_at(line: str, needle: str) -> bool:
    """`needle` 이 **낱말로** 들어 있는가 (0925 §4-C-1 · ISSUE-098).

    한국어에는 띄어쓰기 경계가 없어 부분 문자열이 그대로 맞는다 —
    「비영리**사회적기업**」에서 「사회적기업」이 맞으면 제외 대상이 요건이 된다.
    그래서 **앞 글자가 한글이면 다른 낱말의 꼬리**로 보고 세지 않는다.
    「(예비)사회적기업」·「인증 사회적기업」처럼 괄호·공백 뒤는 그대로 맞는다.

    뒤는 보지 않는다 — 「사회적기업이」·「사회적기업은」의 조사가 한글이기 때문이다.
    """
    start = 0
    while True:
        at = line.find(needle, start)
        if at < 0:
            return False
        before = line[at - 1] if at > 0 else ""
        if not ("가" <= before <= "힣"):
            return True
        start = at + 1


#: 조직 «형태» 요건. 「중소기업」처럼 거의 모든 공고에 있는 말은 여기 두지 않는다 —
#: 변별력이 없으면서 모든 공고에 조항을 하나씩 만들어 낸다.
_ORG_TYPES: tuple[tuple[str, str], ...] = (
    ("예비사회적기업", "예비사회적기업"),
    ("사회적기업", "사회적기업"),
    ("사회적협동조합", "사회적협동조합"),
    ("마을기업", "마을기업"),
    ("자활기업", "자활기업"),
    ("사회연대경제", "사회연대경제기업"),
    ("비영리법인", "비영리법인·단체"),
    ("비영리단체", "비영리법인·단체"),
    ("유치기업", "유치기업"),
    ("협동조합", "협동조합"),
    ("소상공인", "소상공인"),
    ("1인창조기업", "1인창조기업"),
    ("대학", "대학"),
    ("연구기관", "연구기관"),
    ("공공기관", "공공기관"),
    ("지방공기업", "지방공기업"),
)


# --------------------------------------------------------------------------
# 인원 · 연차 · 매출
# --------------------------------------------------------------------------

#: 고용을 가리키는 낱말이 **반드시** 있어야 한다. 없이 「10인 이상」만 보면 표·흐름도의
#: 아무 숫자나 고용 요건이 된다 (실측: 신청 흐름도의 「➊…➋」 줄이 걸렸다).
_HEADCOUNT_RE = re.compile(
    r"(?:피보험자\s*수?|상시\s*근로자\s*수?|고용\s*인원|상시고용|고용|근로자\s*수?|종업원\s*수?)"
    r"[^\n]{0,10}?(\d{1,4})\s*(?:인|명)\s*(이상|미만|이하)"
)
#: 「20인 이상 사업장」처럼 주어가 뒤에 오는 모양.
_HEADCOUNT_SITE_RE = re.compile(r"(\d{1,4})\s*(?:인|명)\s*(이상|미만|이하)\s*(?:사업장|기업|업체)")
#: 인원 요건을 푸는 예외 문장.
_WAIVER_WORDS = ("예외", "인정 요건 충족", "미만 기업도", "미만도 참여", "미만도 가능", "예외가능", "예외 가능")
#: 「다만, 고용보험 피보험자수 10인 미만의 기업이라도 다음의 기업은 참여 가능 ①벤처 … ③사회적기업」(122145) — 줄이 꺾여
#: 「…미만의 기업」에서 끊겨도 예외다. 이 줄을 「10인 미만」 요건으로 읽으면 안 된다(34차 R33-D4).
_WAIVER_RE = re.compile(
    r"다만[^\n]{0,60}?\d{1,4}\s*(?:인|명)\s*미만"
    # 「벤처기업, 이노비즈, 사회적기업 등 일부 기업은 10인 미만 사업장도 지원 가능」(116832 · 35차 R34-DATA-03)
    r"|\d{1,4}\s*(?:인|명)\s*미만\s*(?:의\s*)?(?:사업장|기업|업체|사업체)?\s*(?:이라도|도)\s*[^\n]{0,8}?(?:지원|참여|신청|참가)\s*가능"
)


def _is_headcount_waiver(line: str) -> bool:
    """인원 요건을 푸는 예외 문장인가 — 이 줄의 형태 낱말(「벤처기업, 이노비즈, 사회적기업 등」)은 대상 요건이 아니다."""
    return bool((any(word in line for word in _WAIVER_WORDS) and re.search(r"\d\s*(?:인|명)", line)) or _WAIVER_RE.search(line))

_FOUNDING_RE = re.compile(r"(?:창업|업력|설립)\s*(\d{1,2})\s*년\s*(이내|미만)")
_REVENUE_RE = re.compile(r"매출(?:액)?[^\n]{0,30}?([\d,]+(?:\.\d+)?)\s*(억|천만|백만)\s*원?\s*(이상|이하|미만)")
#: 「지식서비스산업 : 10억 이상」처럼 「매출」이 앞 줄에 있는 모양.
_AMOUNT_ONLY_RE = re.compile(r"([\d,]+(?:\.\d+)?)\s*(억|천만|백만)\s*원?\s*(이상|이하|미만)")
#: 매출 하한이 **신청 대상 문장**인 꼴 — 「…이상인 기업」 · 「…이상이어야」. 그 밖(「…이상인 경우」 제외 목록 · 배점표 · 「아래 기준 중
#: 1개 이상」 갈래)은 불가의 근거가 아니다(119754 팁스 · 126473 배점 · 126497 갈래 · 35차 R34-DATA-02).
_REVENUE_TARGET_RE = re.compile(
    r"이상\s*(?:인|의)?\s*(?:중소|중견|창업)?\s*(?:기업|업체|자|사업자|법인|소상공인)|이상\s*이어야|이상\s*일\s*것"
    r"|이상\s*(?:을|를)?\s*(?:달성|기록|보유)|이상인\s*경우에\s*한"
)
#: 「매출액 10억원 이상인 기업 또는 고용 10인 이상인 기업」 — 매출은 갈래 하나다. 못 미쳐도 불가가 아니다(35차 마지막 검토).
_REVENUE_ALT_RE = re.compile(r"또는|이거나|혹은|중\s*(?:하나|\d+\s*개)")


# --------------------------------------------------------------------------
# 선행 · 보유 요건
# --------------------------------------------------------------------------

_PREREQUISITES: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"기업부설연구소|연구개발전담부서"), "research_department", "기업부설연구소·연구개발전담부서 보유"),
    (re.compile(r"완료판정|최종평가\s*결과\s*완료"), "completed_program", "선행 과제 완료 판정"),
    # 「선정」은 뺐다 — 「당해연도 … 공급기업으로 **선정된** 기업(은 신청 불가)」이
    # 「공급기업 등록이 필요하다」로 읽혔다. 요건은 「등록」·「풀」 쪽이다.
    (re.compile(r"공급기업\s*(?:으로)?\s*(?:등록|풀)"), "supplier_registration", "공급기업 등록"),
    (re.compile(r"디지털\s*제품\(?서비스\)?를?\s*보유"), "digital_product", "디지털 제품(서비스) 보유"),
    # 주어가 «기업»일 때만 요건이다. 「'공공데이터 활용 지원'」 같은 사업 이름이 아니라
    # 「데이터를 생산‧유통‧활용하는 중소기업」이 요건이다.
    (re.compile(r"데이터[^\n]{0,12}(?:생산|유통|활용|보유)(?:하는|한|하고)[^\n]{0,24}(?:기업|사업자|중소|중견)"),
     "data_product", "데이터 생산·유통·활용"),
    (re.compile(r"수출\s*실적|해외\s*법인|해외\s*MOU"), "export_record", "수출·해외 실적"),
    # 「자가진단 결과가 50점 이상(…)인 경우에 한하여 … 신청」(120566 · 문장이 줄을 넘는다) — 신청 전에 넘어야 할 점수. 뒤가 선정 · 지급이면 심사 기준이다.
    (re.compile(r"(?:점수|결과|등급)[^\n]{0,30}?이상[^\n]{0,40}?(?:경우에\s*한하여|에\s*한하여|경우에\s*한해)(?!\s*(?:선정|지급|최종|인증서))"),
     "score_threshold", "신청 전 점수 · 평가 기준"),
    # 「강진군 밀키트 사업 **선정업소로** (식육)즉석판매제조가공업 영업 신고 … 되어 있는 업소」
    # — 다른 사업에 이미 뽑힌 곳만 신청할 수 있다는 말이다 (0925 §4-A-7).
    (re.compile(r"(?:선정|선발|지정)\s*(?:된\s*)?(?:업소|업체|기업|기관)\s*(?:로|으로|만|에\s*한)"),
     "prior_selection", "다른 사업의 선정 업소·기업"),
)

#: 연구소 · 전담부서를 **가져야 한다**는 대상 문장 — 「…를 보유한 기업」 · 「보유하고 있는 자」 · 「인정서 보유기업」 · 「인정받은 기업」.
#: 줄이 꺾여 동사가 다음 줄에 오기도 한다(127025 「…기업부설연구소 또는 / 연구개발전담부서 인정서를 보유해야 함」).
_RESEARCH_HOLD_RE = re.compile(r"(?:기업부설\s*연구소|연구개발\s*전담\s*부서)[^\n]{0,60}?(?:보유|인정\s*받은\s*(?:기업|업체|자|중소))")
#: 연구소 낱말이 있어도 요건이 아닌 줄 — 예시(「ex) 기업부설연구소 12명」) · 작성요령 · 배점 · 가점 · 서류 이름 · 근로자 수에서 빼는
#: 연구전담요원 · 연구소를 세우게 돕는 사업 이름(35차 R34-DATA-01 — 연구소 「없음」이면 22건이 거짓 불가였다).
_RESEARCH_NOT_REQ_RE = re.compile(
    r"ex\)|예\s*\)|예시|작성|기재|배점|점수|가점|우대|우선\s*(?:선정|지원|선발)|연구\s*전담\s*요원|인정서\s*(?:\d\s*부|각)"
)
#: 서류 · 설립 사업 낱말 — **괄호 밖에서만** 본다. 「…를 보유한 기업 (증빙: 인정서 사본 제출)」은 요건이다(35차 마지막 검토).
_RESEARCH_DOC_RE = re.compile(r"설립(?!\s*(?:후|이후))|사본|제출(?!\s*일)|증빙|구비|첨부|확인\s*서류")
#: 제출 · 증빙 서류 목록의 머리 — 그 아래 표의 「연구소 인정서 보유기업」은 서류 이름이다(117992 · 125778 서류 표).
_DOC_LIST_HEADING_RE = re.compile(r"(?:제출|구비|증빙|첨부|필수|추가)\s*서류|확인\s*방법|서류\s*목록")
#: 서류 목록 머리가 다스리는 줄 수.
DOC_LIST_RUN_LINES: Final[int] = 12


def _not_research_requirement(line: str) -> bool:
    return bool(_RESEARCH_NOT_REQ_RE.search(line) or _RESEARCH_DOC_RE.search(_PAREN_RE.sub(" ", line)))


def _research_requirement(line: str, following: str, in_doc_list: bool) -> str | None:
    """연구소 보유 요건이면 인용할 글(동사가 다음 줄이면 두 줄)을, 아니면 None."""
    if in_doc_list or _not_research_requirement(line):
        return None
    if _RESEARCH_HOLD_RE.search(line):
        return line
    joined = f"{line} {following}".strip()
    if following and not _not_research_requirement(following) and _RESEARCH_HOLD_RE.search(joined):
        return joined
    return None


#: **자격 절에서만** 읽는 보유 요건. 그 밖의 절에서 나오면 요건이 아니라 설명이다.
_ELIGIBILITY_ONLY_PREREQUISITES: Final[frozenset[str]] = frozenset({"prior_selection"})
#: 「완료판정 전인 · 완료 전」 — 아직 끝나지 않은 것을 말한다. 끝난 과제를 요구하는 말이 아니다(34차 · 126672 p9
#: 「출원중인 특허, 발급전인 인증, 완료판정 전인 기술개발제품 등」이 요건으로 읽혀 거짓 불가였다). 자격 절 밖의 진짜 요건
#: (125978 「최종평가 결과 완료판정(60점 이상) 과제에 한하여 신청 가능」)은 그대로 읽는다.
_NOT_COMPLETED_RE = re.compile(r"완료\s*판정\s*전|완료\s*전인")
#: 선정 **뒤** 절차 낱말 — 「선정기업에 한하여 … 개별 통보」(122147) · 「최종 선정된 기관에 한하여 제출」(126384)은
#: 다른 사업에 먼저 뽑혀야 한다는 요건이 아니다(32차 R31-01 — 열린 공고 둘이 거짓 「불가」로 숨었다).
#: 33차 R32-04 — 「에 한하여 … 통보 · 제출」 꼴로만 좁힌다. 낱말 하나(「협약」)만 보면 「…협약이 체결된 선정기업에 한하여」 같은
#: 진짜 선행 선정 요건까지 버릴 수 있었다.
#: 34차 R33-02 — 「에 한하여」로만 좁혔더니 「선정기업만 협약 … 지급」이 요건으로 읽혀 거짓 불가였다. 넓은 낱말로 되돌린다.
_SELECTION_PROCEDURE_RE = re.compile(r"통보|제출|협약|안내|지급|발표|공지")
#: 그래도 자격 꼴이면 요건 — 「선정업소로 … 신고가 되어 있는 업소」 · 「선정된 기업으로서」 · 「선정기업에 한하여 신청 가능」.
_PRIOR_SELECTION_QUALIFY_RE = re.compile(
    r"되어\s*있는|으로서|신청|참여|참가"
    # 「(종료 · 완료 · 체결)(된 · 한) (선정)기업 · 기관 · 자」 · 「받은 기업」 — **바로 뒤에 신청자 낱말**이 올 때만 자격 꼴이다.
    # 뒤 낱말 없이 「완료된」을 넣었더니 「평가가 완료된 후 선정기업에 한하여 통보」가 요건이 됐다(34차 R33-01).
    r"|(?:종료|완료|체결)(?:된|한)\s*(?:선정\s*)?(?:기업|기관|업체|업소|자)|받은\s*(?:선정\s*)?(?:기업|기관|업체|업소|자)"
)
#: 괄호 한 겹 — 절차 낱말은 괄호 밖에서만 본다(「…신청할 수 있음(최종 선정 결과는 개별 통보)」).
_PAREN_RE = re.compile(r"\([^()]*\)")


# --------------------------------------------------------------------------
# 지역 전략산업
#
# 「지역 전략산업 영위기업 우선 선정」이라고 적고, 몇 줄 뒤에 시·도별 업종 표를 붙이는
# 공고가 있다(ICT 정보보호 지원). 그 표에 「광주 ICT」가 있으면 회사가 바로 그 대상이다 —
# 요약문에는 없고 공고문에만 있는 사실이다.
# --------------------------------------------------------------------------

_STRATEGIC_RE = re.compile(r"전략산업|특화산업|주력산업|중점산업|전략\s*분야")
#: 전략산업 머리글이 다스리는 줄 수. 표가 바로 뒤에 온다.
STRATEGIC_RUN_LINES: Final[int] = 6


def _extract_strategic(clauses, line, page, section, *, in_run: bool) -> None:
    if not (in_run or _STRATEGIC_RE.search(line)):
        return
    hit = next((alias for alias, _ in _WIDE_REGIONS if alias in line), None)
    short = next((short for short in ("광주", "전남", "호남") if short in line), None)
    if hit is None and short is None:
        return
    _add(clauses, "strategic_industry", "지역 전략산업", line, page, section,
         {"region_text": hit or short})


# --------------------------------------------------------------------------
# 역할
# --------------------------------------------------------------------------

_ROLES: tuple[tuple[str, str, str], ...] = (
    ("주관연구개발기관", "lead_rnd", "주관연구개발기관"),
    ("공동연구개발기관", "joint_rnd", "공동연구개발기관"),
    ("실증공급기업", "pilot_supplier", "실증공급기업"),
    ("공급기업", "supplier", "공급기업"),
    ("수요기업", "demand", "수요기업"),
    ("도입기업", "adopter", "도입기업"),
    ("기술기업", "tech_partner", "기술기업"),
    ("주관기관", "lead_org", "주관기관"),
    ("운영기관", "operator", "운영기관"),
    ("협약기업", "partner", "협약기업"),
    ("참여기업", "participant", "참여기업"),
    ("컨소시엄", "consortium", "컨소시엄"),
)


# --------------------------------------------------------------------------
# 돈
# --------------------------------------------------------------------------

#: **받는 것을 말하는 문장인가** (0925 §4-C-2 · ISSUE-099).
#:
#: 「지원·지급·감면·부담」이 없는 문장의 숫자는 받는 것이 아니다 — 신청수수료·보증한도·
#: 매출 기준·평가 배점이 그렇게 「최대 10억원」으로 읽혔다.
_MONEY_VERB_RE = re.compile(r"지원|지급|감면|부담|보조|출연|제공|바우처|혜택")

#: **받는 것이 아닌 문장.** 여기 걸리면 숫자가 있어도 담지 않는다.
#:
#: 실측(120566 지식재산 경영인증): 「신청수수료 : 33만원」 · 「지점장 전결 보증한도
#: 10억원~30억원 확대」 · 「재신청 시 1회에 한해 수수료 무료」 — 셋 다 받는 것이 아닌데
#: 「무료 · 최대 10억원」으로 읽혀 그 공고를 5위로 올렸다.
_MONEY_NOT_RE = re.compile(
    r"보증|수수료|매출|가점|배점|평가\s*점수|점수|환수|위약|과태료|벌점|이자|융자\s*한도|담보"
    # 다른 사업의 대출 한도 · 이차보전 — 「최대 3억원 대출에 대한 이차보전금 지급」(121107 · 35차 R34-DATA-08)
    r"|대출|이차\s*보전|활용\s*사업"
)

#: 돈 조항을 읽어도 되는 절.
_MONEY_SECTIONS: Final[frozenset[str]] = frozenset({SECTION_SUPPORT, SECTION_BURDEN})

#: 「무료」로 볼 표기. 「수수료 무료」·「무료 상담 안내」처럼 받는 것이 아닌 것과 가른다.
#: 43차 Q9 · BIZ-03 — 참여자(청년) 인건비 · 수당의 「전액 지원」은 회사가 받는 무료가 아니다(같은 미래내일 일경험 세 운영기관 중 한 곳만
#: 이 낱말로 무료 가산 · 규모 만점을 받아 9점 위에 섰다).
_FREE_RE = re.compile(
    r"\(\s*무\s*료\s*\)|무료\s*(?:지원|제공|이용|참가|수강)"
    r"|(?<!\(수당\) )(?<!\(수당\))(?<!수당 )(?<!인건비 )(?<!인건비)(?<!임금 )(?<!급여 )전액\s*(?:지원|지급|무료)"
)

#: 「자부담 없음」은 **그렇게 적힌 문장이 있을 때만**이다 — 지어내지 않는다.
_NO_BURDEN_RE = re.compile(r"(?:자부담|기업\s*부담|민간\s*부담|자기?\s*부담)(?:금|비)?\s*(?:의무)?\s*(?:는|은|이)?\s*없")

_MONEY_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (_FREE_RE, "free"),
    (re.compile(r"(?:최대|한도|까지)\s*([\d,]+(?:\.\d+)?)\s*(억|천만|백만|만)\s*원"), "cap"),
    (re.compile(r"([\d,]+)\s*~\s*([\d,]+)\s*(백만원|만원|억원|백만|만|억)"), "range"),
    (re.compile(r"정부\s*지원(?:금|비율)?\s*(?:은|:|는)?\s*([\d.]+)\s*%"), "government_share"),
    # 「가치평가비용의 50%(최대 1,500만원) … 지원」 · 「정부가 구축 비용의 30% 이내 지원」 · 「지원 규모 및 비용 : 총 비용의 75%(중소)」
    # (10-10 · 120083 은 이 줄이 괄호 속 「VAT 제외」 때문에 제외 조항으로 잘못 잡혀 인용에만 우연히 실려 있었다). 같은 줄에 「지원」이 있고
    # 현금 · 현물 · 부담 말이 없을 때만 — 「현금 900,000원(컨설팅 비용의 25%)」(122147 기업부담 표) · 「기술 도입에 소요된 비용의 50% 이내」
    # (127025 비목 한도)는 지원 비율이 아니다(10-10 검토).
    (re.compile(r"^(?=[^\n]*지원)(?![^\n]*(?:현금|현물|부담))[^\n]*?비용\s*의\s*([\d.]+)\s*%"), "government_share"),
    # 창이 좁아 놓치던 자리 — 「과제별 총 연구개발비 중 기관부담연구개발비(민간부담금 등)
    # 매칭비율은 … 중소기업·초기중견기업은25% 이상」에서 부담과 비율이 70자쯤 떨어져 있다.
    (re.compile(r"(?:민간|기업|기관|자기?)\s*부담(?:금|연구개발비)?[^\n]{0,80}?([\d.]+)\s*%\s*(이상|이내)?"), "self_share"),
    # 「(지원조건) 소요비용 50%(최대 15백만원) 내 지원」 — 「부담」이라는 말 없이 비율만 적는다.
    (re.compile(r"(?:소요비용|총\s*사업비|사업비)\s*(?:의)?\s*([\d.]+)\s*%"), "self_share"),
    (re.compile(r"자부담\s*(?:은|:|는)?\s*([\d.]+)\s*%"), "self_share"),
    (re.compile(r"월\s*([\d,]+)\s*만\s*원"), "monthly"),
)


# --------------------------------------------------------------------------
# 제외
# --------------------------------------------------------------------------

_EXCLUSION_RE = re.compile(r"제외|참여\s*제한|신청\s*불가|지원\s*불가|지원할\s*수\s*없")

#: 계산 꼴 「제외 시 · 제외하고 · 제외한 나머지」 — 「제외한다」는 제외 조항이다(10-10 검토).
_EXCLUSION_CALC_RE = re.compile(r"제외\s*(?:시|하고|하면|한(?!다))")
#: 괄호 안은 메모다 — 「(… 점수 제외 시 45점)」 · 「(VAT 제외)」 · 「(대기업 제외)」 · 「(OEM제품 제외)」. 다만 「(지원제외)」 · 「(중복지원 불가)」 ·
#: 「(참여제한)」 같은 **제외 이름표**는 남긴다(괄호를 통째로 지우면 진짜 제외 조항을 잃었다 · 10-10 검토).
_EXCLUSION_LABEL_PAREN_RE = re.compile(
    r"\(\s*(?:(?:지원|신청|참여|참가|모집|중복\s*지원|중복\s*신청)\s*)?(?:제외|불가|제한)\s*(?:대상|사항)?\s*\)"
    # 주어가 있는 괄호 속 제외 문장 — 「(교육 · 훈련을 주 사업으로 하는 훈련기관은 제외)」 · 「(간이과세자 지원 불가)」(35차 R34S-05)
    r"|\([^()]*(?:(?:은|는)\s*제외|지원\s*불가|신청\s*불가|참여\s*(?:제한|불가))[^()]*\)"
)


def _strip_note_parens(line: str) -> str:
    """제외 이름표 괄호만 남기고 괄호 메모와 계산 꼴을 지운 줄 — 제외 · 부정 낱말을 볼 때 쓴다."""
    kept = _PAREN_RE.sub(lambda m: m.group(0) if _EXCLUSION_LABEL_PAREN_RE.fullmatch(m.group(0)) else " ", line)
    return _EXCLUSION_CALC_RE.sub(" ", kept)

#: 목차 줄. 「8. 사전 지원 제외 대상·········」은 조항이 아니라 쪽 안내다.
_TOC_RE = re.compile(r"[·．.]{6,}|…{2,}")

#: **제외 목록의 머리글.** 그 아래 붙는 항목에는 「제외」라는 말이 없다 —
#: 「2. 아래 지원 제외 항목에 해당하지 않는 기업」 다음에 「- 교육·훈련을 주 사업으로 하는
#: 훈련기관 …」 이 온다. 머리글만 보면 회사를 막는 바로 그 조항을 놓친다.
_EXCLUSION_HEADING_RE = re.compile(r"제외\s*(?:항목|대상|사유|기준|조건)|지원\s*제외|참여\s*제한|^\W*제한\s*사항\W*$")
#: 「참여 · 신청 제외」는 **머리 꼴**일 때만 제외 머리다(36차 R35-RULE-01 · 마지막 검토 R36-01 — 「○ 대기업 및 계열사는 참여 제외」
#: 한 줄이 제외 구간 10줄을 열어 아래 「○ 직전년도 매출액 10억원 이상인 기업」이 제외 조항이 되어 거짓 「가능」이었다).
_ROLE_EXCLUSION_RE = re.compile(r"(?:참여|신청)\s*제외")
_EXCLUSION_SENTENCE_RE = re.compile(r"[은는]\s*(?:참여|신청)\s*제외")
#: 머리 꼴로 볼 글 길이(글머리 · 괄호 · 쌍점 빼고).
ROLE_EXCLUSION_HEADING_CHARS: Final[int] = 20


def _exclusion_heading(line: str) -> bool:
    """제외 목록의 머리글인가."""
    if _EXCLUSION_HEADING_RE.search(line):
        return True
    if not _ROLE_EXCLUSION_RE.search(line) or _EXCLUSION_SENTENCE_RE.search(line):
        return False
    return len(re.sub(r"[\s□○◦❍■▪•·\-–<>〈〉【】\[\]():：]", "", line)) <= ROLE_EXCLUSION_HEADING_CHARS


def _opens_exclusion(line: str) -> bool:
    """이 줄이 제외 구간을 여는가 — 자격 낱말이 머리에 함께 있으면(「신청자격 및 제외대상」 · 「지원대상(참여제한 기업 제외)」)
    열지 않는다. 괄호 속 · 「※」 뒤 풀이의 자격 낱말은 세지 않는다 — 「지원 제외 대상(지원대상에서 제외되는 기업)」 ·
    「< 신청 제외 대상 > ※ 신청자격을 갖추었더라도 …」는 순수한 제외 머리다(36차 R36-03)."""
    if not _exclusion_heading(line):
        return False
    core = re.sub(r"※.*$", "", _PAREN_RE.sub(" ", line))
    return not _ELIGIBILITY_WORD_RE.search(core)

#: 제외 머리글이 다스리는 줄 수.
EXCLUSION_RUN_LINES: Final[int] = 10

#: 목록 항목의 머리 기호.
_BULLET_RE = re.compile(r"^\s*[-–—○❍□◦▪•·∙※o]\s*\S")


# --------------------------------------------------------------------------
# 마감 · 접수
# --------------------------------------------------------------------------

_TIME_RE = re.compile(r"(\d{1,2})\s*:\s*(\d{2})")
_METHOD_WORDS = ("이메일", "온라인", "방문", "우편", "등기", "누리집", "홈페이지", "IRIS", "이메일접수")


# --------------------------------------------------------------------------
# 본체
# --------------------------------------------------------------------------

#: 한 갈래에서 남길 조항 수 상한. 같은 말이 스무 번 반복되는 공고문이 있다.
MAX_PER_KIND: Final[int] = 6

#: 조항 한 줄의 길이 상한. 표가 뭉개져 한 줄이 수천 자인 경우가 있어 근거가 못 읽힌다.
MAX_SOURCE_CHARS: Final[int] = 300

#: 예외 — **전략산업 표는 한 줄에 열일곱 시·도가 다 들어 있다.**
#: 「호남권광주ICT, 모빌리티 …」가 그 줄의 중간에 있어 300자에서 잘리면 근거를 잃는다.
#: 길게 담되, 화면에 적는 인용은 판정 규칙이 **회사 몫만 잘라** 짧게 만든다.
LONG_SOURCE_KINDS: Final[dict[str, int]] = {"strategic_industry": 2000}

#: 이보다 짧은 줄은 조각이다 (표 셀 하나·쪽 번호).
MIN_SOURCE_CHARS: Final[int] = 6

#: 지원대상 절의 첫 문장으로 담을 최소 길이. 「지원대상」·「신청자격」 네 글자짜리
#: 제목 줄만 거르면 된다 — 「전국 소재 중소기업」(9자) 같은 짧은 요건은 담아야 한다.
TARGET_SENTENCE_MIN_CHARS: Final[int] = 8

#: **공고문 제목 줄.** 요건이 아니라 문서 이름이다.
_DOC_TITLE_RE = re.compile(r"(?:공고문?|모집\s*공고|안내문?|계획)\s*$|제\s*\d{2,4}\s*[-–]\s*\d+\s*호")

#: 「값이 같으면 한 줄」인 갈래. 제외·마감·예외는 **문장 자체가 값**이라 여기 없다.
_VALUE_KINDS: Final[frozenset[str]] = frozenset(
    {"location", "org_type", "headcount", "founding_years", "revenue", "prerequisite", "role", "money"}
)


#: 제목으로 볼 줄의 길이 상한. 제목은 짧다.
MAX_HEADING_CHARS: Final[int] = 45
#: 「○ 지원대상 : …」처럼 제목 낱말이 줄 앞머리에 오는 경우의 허용 위치.
MAX_HEADING_OFFSET: Final[int] = 20


def _section_of(line: str) -> str | None:
    """이 줄이 절 제목을 담고 있으면 그 절 이름. 아니면 None.

    **제목은 짧거나 앞머리에 온다.** 이 조건이 없으면 본문 한가운데의 「… 지원조건 …」
    한 마디가 그 뒤 여덟 줄을 「자격 절」로 만든다 — 실측에서 평가 안내·밋업 일정이
    신청 자격으로 읽혔다.
    """
    for name, words in _SECTION_WORDS:
        for word in words:
            at = line.find(word)
            if at < 0:
                continue
            if len(line) <= MAX_HEADING_CHARS or at <= MAX_HEADING_OFFSET:
                return name
    return None


def _clean(line: str, *, limit: int = MAX_SOURCE_CHARS) -> str:
    """근거로 실을 한 줄. 앞뒤 기호를 털고 길이를 자른다 — **글자는 바꾸지 않는다.**"""
    text = line.strip().strip("○❍□◦▪•※-–—·⇒>＊*\t ")
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text[:limit]


def _number(text: str) -> float | None:
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def _krw(amount: float, unit: str) -> int:
    scale = {"억": 100_000_000, "천만": 10_000_000, "백만": 1_000_000, "만": 10_000,
             "억원": 100_000_000, "백만원": 1_000_000, "만원": 10_000}
    return int(amount * scale.get(unit, 1))


#: 한국어 금액 한 덩어리의 조각 — 숫자 + (천 · 백 · 십)? + (억 · 만)?. 「3천」 · 「5백만」 · 「1억」 · 「2,000만」.
_KRW_TOKEN_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*([천백십]?[억만]?)")
_KRW_SMALL = {"천": 1_000, "백": 100, "십": 10}
_KRW_BIG = {"억": 100_000_000, "만": 10_000}


def _krw_phrase(phrase: str) -> int:
    """한국어 금액 한 덩어리 → 원 (27차 R26-10 · 금액 해석은 여기 한 곳).

    「3천5백만원」 = 35,000,000 · 「1억 3천4백만원」 = 134,000,000 · 「100,000천원」 = 100,000,000 ·
    「1억 5천만원」 = 150,000,000. 억 뒤에 남은 천 · 백은 **원이 붙지 않았을 때만** 만 단위다 —
    「1억 5천」은 1억 5천만(쓰는 사람의 뜻), 「1억 5천원」은 100,005,000원(적힌 그대로).
    """
    total = 0.0
    section = 0.0
    last_big = ""
    for number, unit in _KRW_TOKEN_RE.findall(phrase):
        value = float(number.replace(",", ""))
        small = unit[:1] if unit[:1] in _KRW_SMALL else ""
        big = unit[-1:] if unit[-1:] in _KRW_BIG else ""
        section += value * _KRW_SMALL.get(small, 1)
        if big:
            total += section * _KRW_BIG[big]
            section = 0.0
            last_big = big
    if section:
        if last_big == "억" and not phrase.rstrip().endswith("원"):
            section *= _KRW_BIG["만"]
        total += section
    return int(round(total))


def _lines_with_pages(text: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for page, body in bizinfo_document_store.split_pages(text):
        for line in body.splitlines():
            stripped = line.strip()
            if stripped:
                out.append((page, stripped))
    return out


def _without_role(detail: dict) -> dict:
    """주관기관 한정 표시(`role_limited` · `role`)는 줄을 읽은 **뒤에** 붙는다 — 같은 값 견주기에서 빼야 둘째 줄
    (「※ 기업부설연구소 보유여부 확인 : …」)이 한정 없는 별도 조항으로 남지 않는다(36차 R36-04 · 125966 · 126384 · 126450)."""
    return {k: v for k, v in detail.items() if k not in ("role_limited", "role")}


def _add(
    clauses: list[SupportClause],
    kind: str,
    label: str,
    line: str,
    page: int,
    section: str | None,
    detail: dict,
) -> None:
    """같은 갈래·같은 값이면 한 번만 남긴다. 상한을 넘으면 버린다."""
    same = [c for c in clauses if c.kind == kind]
    if len(same) >= MAX_PER_KIND:
        return
    source = _clean(line, limit=LONG_SOURCE_KINDS.get(kind, MAX_SOURCE_CHARS))
    if len(source) < MIN_SOURCE_CHARS:
        return
    #: 값으로 같음을 가리는 갈래. 제외·마감처럼 «문장 자체가 값»인 것은 여기 없다 —
    #: 그것들을 값으로 접으면 제외 목록의 둘째 항목부터 사라진다(실측: 훈련기관 제외 조항).
    for existing in same:
        if existing.label == label and existing.source_text == source:
            return
        # 같은 값이 다른 줄에서 또 나오면 **먼저 나온 것**을 남긴다 — 대개 그쪽이 자격 절이다.
        if kind in _VALUE_KINDS and existing.label == label and _without_role(existing.detail) == _without_role(detail):
            return
    clauses.append(
        SupportClause(kind=kind, label=label, source_text=source, page=page, section=section, detail=detail)  # type: ignore[arg-type]
    )


#: 「경북 소재 제조기업과 **전국소재** … 지원 기업의 컨소시엄」(120334) — 역할마다 소재가 다르다(34차 §3-A-3).
_NATIONWIDE_PART_RE = re.compile(r"전국\s*(?:소재|대상|의)")
#: 지역 이전을 조건으로 하는 줄 — 「이전을 희망 · 이전 예정 · 이전 주소 · 이전 확약」(34차 · 127034 대전 웰컴 스테이).
_RELOCATION_RE = re.compile(r"이전\s*(?:을\s*)?(?:희망|예정|완료|주소|확약|계획)|(?:으로|로)\s*이전|이전\s*할\s*예정|이전하려|이전하고자")
#: 소재 줄 다음 몇 줄(「② … 창원특례시로 / 이전할 예정인 …」)까지 이어 이전 갈래를 찾는다(36차 R35-DV-04 · 126963).
RELOCATION_LOOKAHEAD_LINES: Final[int] = 8
#: 사후관리 벌칙 문맥 — 「본사를 도외로 이전하는 경우 환수」는 이전 기업도 받는다는 뜻이 아니다(36차 R36-07).
_PENALTY_RE = re.compile(r"환수|취소|반환|위약|제재|지원\s*중단|불이익")
#: 「전남 소재」 짧은 이름 — 통합 이후 해석이 갈려 「전라남도 소재」와 같게 본다(34차 §3-A-6).
_JEONNAM_SHORT_RE = re.compile(r"(?<![가-힣])전남\s*(?:지역\s*)?(?:내\s*)?(?:소재|본사|사업장)")
_GWANGJU_SHORT_RE = re.compile(r"(?<![가-힣])광주")
_GYEONGGI_GWANGJU_RE = re.compile(r"경기(?:도)?\s*광주")


def names_gwangju(line: str) -> bool:
    """줄에 광주가 함께 있는가 — 「광주·전남 지역 내 본사」(126823)는 전남만이 아니다. 「경기도 광주시」는 아니다(34차 마지막 검토)."""
    return bool(_GWANGJU_SHORT_RE.search(line)) and not _GYEONGGI_GWANGJU_RE.search(line)


#: 「전남광주통합특별시 내 **옛 전라남도** 지역」 · 「(구)광주광역시」 · 「광주 제외」 — 통합 전 지역을 말한다(126999 · 126229 · 35차 R34S-04).
_OLD_REGION_RE = re.compile(
    r"(?:옛|\(\s*구\s*\)|(?<![가-힣])구(?=\s))\s*(전라남도|전남|광주광역시|광주)(?=$|[^가-힣]|지역|권)"
    r"|(?<![·ㆍ,/])(광주|전남)\s*(?:광역시)?\s*(?:지역)?\s*(?:은|는)?\s*제외"
)
#: 「(광주·전남 제외)」 — 두 곳을 다 뺀 말이라 옛 지역 한쪽을 가리키지 않는다.
_BOTH_REGIONS_OUT_RE = re.compile(r"(?:광주|전남)\s*(?:[·ㆍ,/]|및)\s*(?:광주|전남)[^\n]{0,8}?제외")


def _old_region(line: str) -> str | None:
    """통합 전 지역(「광주」 · 「전남」) — 「광주 제외」는 전남이다."""
    if _BOTH_REGIONS_OUT_RE.search(line):
        return None
    match = _OLD_REGION_RE.search(line)
    if match is None:
        return None
    if match.group(1):
        return "광주" if match.group(1).startswith("광주") else "전남"
    return "전남" if match.group(2) == "광주" else "광주"


def _location_flags(line: str, alias: str) -> dict:
    """소재 줄의 단서 — 우대(요건 아님 · 122910) · 전국 소재 갈래(120334) · 통합 전 지역(126999)."""
    flags: dict = {}
    old = _old_region(line) if alias in ("전남광주통합특별시", "광주광역시", "전라남도", "전남", "광주·전남") else None
    if old:
        flags["old_region"] = old
    if re.search(re.escape(alias) + r"[^()\n]{0,40}(?:우대|가점)", line):
        flags["preferred"] = True
    if _NATIONWIDE_PART_RE.search(line):
        flags["mixed"] = True
    if _RELOCATION_RE.search(line):
        # 「대전광역시로 … 이전을 희망하거나 이전을 완료한 기업」 · 서식의 「이전 주소」(127034) — 그 지역으로 옮기는 기업도 대상이다
        flags["relocation"] = True
    return flags


def _extract_location(clauses, line, page, section) -> None:
    if not any(word in line for word in _SITE_WORDS):
        return
    found = False
    for alias, canonical in _WIDE_REGIONS:
        if alias not in line:
            continue
        site = next((w for w in ("본사", "공장", "사업장", "연구소") if w in line), "소재")
        _add(clauses, "location", f"소재: {alias}({site})", line, page, section,
             {"region": canonical, "alias": alias, "site": site, **_location_flags(line, alias)})
        found = True
        break
    if not found and _JEONNAM_SHORT_RE.search(line):
        # 「광주·전남」이면 광주도 대상 — 「전남」 별칭(통합 해석 확인)으로 두지 않는다(34차 마지막 검토 · 126823)
        alias = "광주·전남" if names_gwangju(line) else "전남"
        _add(clauses, "location", f"소재: {alias}(소재)", line, page, section,
             {"region": "전남광주", "alias": alias, "site": "소재", **_location_flags(line, "전남")})
    # 광역시 줄임말(「광주시 · 울산시 소재」) — 광역으로 읽는다. 「경기도 광주시」는 경기의 시라 시 · 군으로 둔다(37차 R36-RV-05).
    gyeonggi_gwangju = bool(_GYEONGGI_GWANGJU_RE.search(line))
    metros: list[str] = []
    for match in _METRO_SHORT_RE.finditer(line):
        name = f"{match.group(1)}시"
        if name in metros or (name == "광주시" and gyeonggi_gwangju):
            continue
        metros.append(name)
        if found:
            continue  # 이 줄의 광역 정식 이름을 이미 담았다 — 같은 줄의 줄임말은 같은 요건의 다른 표기다
        detail = {"region": METRO_SHORT[name], "alias": name, "site": "소재", "metro_short": True, **_location_flags(line, name)}
        if name == "광주시":
            detail["ambiguous"] = "경기 광주시"
        _add(clauses, "location", f"소재: {name}(광역시 줄임말)", line, page, section, detail)
    city = _CITY_RE.search(line)
    if city and not any(tail in city.group(1) for tail in _NOT_A_CITY) and city.group(1) not in metros:
        _add(clauses, "location", f"소재: {city.group(1)}", line, page, section,
             {"city": city.group(1), "site": "소재"})


#: 조직 형태를 읽으면 안 되는 줄 — 신청«자»가 아니라 **과정·강의·서류**를 말한다.
#:
#: 실측(118350): 「온라인 창업교육 시스템(창업-NET) 강의(기초, 역량강화, 창업자 재기,
#: 협동조합 등 택1) 수강 후 수료증 제출 필수」에서 「협동조합」을 조직 형태 요건으로 읽었다.
_NOT_APPLICANT_RE = re.compile(r"강의|강좌|수강|교육\s*과정|커리큘럼|과목|수료|제출\s*서류|증명서|서식|서약서|신청서|동의서|양식")
#: 대상이 아니라 **조건을 붙이는** 줄 — 「→ 사회적기업이면서 참여대상에 해당하는 기업은 … 경우에 한하여 참여 가능」(126473 · 35차 R34S-03).
_ORG_CONDITION_RE = re.compile(r"이면서[^\n]{0,30}?대상에\s*해당|경우에\s*한하여\s*(?:참여|신청|지원)\s*가능")
_SOCIAL_ECONOMY_RELATED_RE = re.compile(r"사회연대경제\s*관련\s*(?:비영리|단체|법인|기관)")
#: 법적 정의의 법인격 나열 — 「상법상 회사, 개인사업자 또는 협동조합(사회적협동조합 … 포함)」(여성기업지원법 시행령 제2조 꼴).
#: 주식회사도 드는 목록이라 그 안의 협동조합은 대상 제한이 아니다(118204 여성기업 육성사업 · 10-31 「사회적협동조합만 대상 → 불가」).
#: 「상법상 회사가 아닌 …」처럼 나열이 아니면 그대로 읽는다.
_LEGAL_FORM_LIST_RE = re.compile(r"상법\s*상\s*(?:회사|법인)\s*(?:[,，·ㆍ]|또는|및)")


def _extract_org_types(clauses, line, page, section) -> None:
    """조직 형태. **낱말로 맞을 때만**, 신청자를 말하는 줄에서만 담는다 (0925 §4-C-1)."""
    if _NOT_APPLICANT_RE.search(line) or _is_headcount_waiver(line) or _LEGAL_FORM_LIST_RE.search(line):
        return
    # 조건을 붙이는 줄의 형태는 대상이 아니라 「그 경우에만」 열리는 길이다 — 표시해 두고 판정이 확인 필요로 쓴다(126473 기준 답안)
    conditional = bool(_ORG_CONDITION_RE.search(line))
    for needle, label in _ORG_TYPES:
        if label == "사회연대경제기업" and _SOCIAL_ECONOMY_RELATED_RE.search(line):
            continue  # 「사회연대경제 관련 비영리법인 · 단체」는 사회연대경제기업이 아니다(126473 · 35차 R34S-03)
        if word_at(line, needle):
            detail = {"org_type": label, **({"conditional": True} if conditional else {})}
            _add(clauses, "org_type", f"조직 형태: {label}", line, page, section, detail)


def _extract_headcount(clauses, line, page, section) -> None:
    if _is_headcount_waiver(line):
        _add(clauses, "headcount_waiver", "인원 요건 예외", line, page, section, {})
        return
    # 4 · 「근로자 5인 미만 기업(70%), 5인 이상 기업(30%)」 — 같은 숫자의 미만 · 이상에 비율이 붙으면 선정 몫을 나눈 배정 비율이지
    # 인원 요건이 아니다(125345 · 35차 R34-DATA-04)
    if "%" in line:
        sides: dict[int, set[str]] = {}
        for pattern in (_HEADCOUNT_SITE_RE, _HEADCOUNT_RE):
            for match in pattern.finditer(line):
                sides.setdefault(int(match.group(1)), set()).add(match.group(2))
        if any({"미만", "이상"} <= found for found in sides.values()):
            return
    # **한 줄에 둘이 함께 오는 표가 있다** — 「근로자 5인 미만 기업(70%), 5인 이상 기업(30%)」.
    # 앞의 것만 읽으면 「5인 이상」 기준이 통째로 사라진다.
    seen: set[tuple[int, str]] = set()
    for pattern in (_HEADCOUNT_SITE_RE, _HEADCOUNT_RE):
        for match in pattern.finditer(line):
            count, comparator = int(match.group(1)), match.group(2)
            if count > 1000:  # 「1,000명 이상 관람객」류는 고용 요건이 아니다
                continue
            if (count, comparator) in seen:
                continue
            seen.add((count, comparator))
            _add(clauses, "headcount", f"고용 인원: {count}인 {comparator}", line, page, section,
                 {"count": count, "comparator": comparator})


def _extract_founding(clauses, line, page, section) -> None:
    match = _FOUNDING_RE.search(line)
    if match:
        years = int(match.group(1))
        _add(clauses, "founding_years", f"창업 {years}년 {match.group(2)}", line, page, section,
             {"years": years, "comparator": match.group(2)})


def _extract_revenue(clauses, line, page, section, revenue_context: bool, *, in_exclusion: bool = False) -> None:
    if in_exclusion:
        return  # 「신청 제외 · 참여제한」 머리 아래 목록의 금액 · 매출은 매출 요건이 아니다(119754 팁스 — 두 단 PDF)
    match = _REVENUE_RE.search(line)
    if match is None and revenue_context:
        match = _AMOUNT_ONLY_RE.search(line)
    if match is None:
        return
    amount = _number(match.group(1))
    if amount is None:
        return
    krw = _krw(amount, match.group(2))
    _add(clauses, "revenue", f"매출 {match.group(1)}{match.group(2)} {match.group(3)}", line, page, section,
         {"krw": krw, "comparator": match.group(3),
          "target": bool(_REVENUE_TARGET_RE.search(line)) and not _REVENUE_ALT_RE.search(line, match.start())})


#: 여러 갈래 중 하나인 줄 — 표의 연번 줄(「1 국가연구개발사업 완료판정 과제의 기술이 적용된 제품」 · 126672 대상 제품 13종) ·
#: 트랙(119692 「[트랙 1] … [트랙 2] … 선정기업」) · 「중 하나 · 택1」. 그 한 줄을 전체 필수로 읽으면 거짓 불가다(34차 §3-A-2).
_OPTION_ROW_RE = re.compile(
    r"^\s*\d{1,2}\s+(?=[가-힣])|트랙|택\s*1|중\s*(?:어느\s*)?하나|하나\s*이상|다음\s*요건\s*중"
    # 「기업부설연구소, 연구개발전담부서, 기업부설창작연구소, 기업창작전담부서 중 1개 이상 보유」(122045 · 35차)
    r"|중\s*\d+\s*개\s*이상"
)
#: 다음 줄이 「중 1개 이상 · 중 하나」로 시작하면 이 줄은 갈래 목록이다(35차 마지막 검토).
_OPTION_FOLLOW_RE = re.compile(r"\s*중\s*(?:\d+\s*개|어느\s*하나|하나)")


#: 「중소기업」 신청 요건 — **분명한 꼴만** 읽는다(10-10). 「SW관련 중소기업」 · 「전남 소재 중소기업」처럼 말만 스친 줄은 아직 안 읽는다
#: (거의 모든 공고에 있는 말이라 변별력이 없다 · `_ORG_TYPES` 주석).
_SME_LAW_RE = re.compile(
    r"중소\s*기업\s*기본법\s*[」｣』\"'”]?\s*(?:제\s*2\s*조|시행령\s*제\s*3\s*조)[^\n]{0,30}?(?:따른|의한|정한|해당하는)\s*중소\s*기업(?:자)?"
)
_SME_CERT_RE = re.compile(r"중소\s*기업\s*확인\s*서\W{0,2}\s*(?:를|을)\s*(?:발급\s*받은|보유한|소지한|보유하고)")
#: 「신청 제외 대상에 해당되지 않는 … 중소기업」(119692) — 두 번 부정은 요건이다. 부정 낱말 검사 전에 지운다.
_SME_DOUBLE_NEG_RE = re.compile(r"(?:신청\s*)?제외\s*대상에\s*해당(?:되|하)지\s*않는|업종\s*제한\s*없음")
#: 줄 앞 글머리 — 「o」 · 「ㅇ」 · 「가.」 · 「1)」 · 「①」 · 「(공통)」. 남은 조건으로 인용하면 「「o」」가 사유에 실렸다(35차 R34S-07).
_SME_BULLET_RE = re.compile(r"^\s*(?:(?:[oOㅇ○◦●•▪■□◇◆※*\-–·]|[가-하]\.|\d{1,2}[.)]|[①-⑳]|\(\s*공통\s*\))\s*)+")
_SME_LABEL_RE = re.compile(r"^[^가-힣A-Za-z]*(?:[(\[]?\s*(?:모집|신청|지원|참가|참여)\s*(?:대상|자격)\s*[)\]]?\s*[:：]?)?")
#: 줄에서 법 이름 · 조항 · 「따른」 · 서류 이름을 지운 뒤 남는 것을 본다 — 남는 게 없으면 「중소기업」 하나만 요구하는 줄이다.
_SME_LAW_NAME_RE = re.compile(
    r"[「｢『\"']?중소\s*기업\s*기본법[」｣』\"'”]?\s*(?:제\s*\d+\s*조(?:\s*제?\s*\d+\s*항)?(?:\s*의\s*규정)?)?"
    r"(?:\s*(?:및|과)\s*(?:같은\s*법|동법)?\s*시행령\s*(?:제\s*\d+\s*조)?)?"
    r"\s*(?:에\s*)?(?:따른|의한|정한|해당하는|의거한?)?"
)
#: 대상을 넓히는 말 — 「중소기업 및 「중견기업 성장촉진 및 경쟁력 강화에 관한 특별법」에 따른 중견기업」(122147 · 10-10 검토).
_SME_WIDER_RE = re.compile(
    r"(?:및|또는|이나|·|ㆍ|,)\s*[「｢『]?중견\s*기업(?:\s*성장\s*촉진\s*및\s*경쟁력\s*강화에\s*관한\s*특별법[」｣』]?"
    r"(?:\s*제\s*\d+\s*조(?:\s*제?\s*\d+\s*항)?)?\s*(?:에\s*)?(?:따른|의한)?\s*(?:중견\s*기업)?)?"
)


#: 중소기업 앞뒤의 관계 · 희망 조건 — 확인서로 가릴 수 없다(126412 「KCA와 거래·협력중인 중소기업 중 … 희망하는 기업」).
_SME_QUALIFIED_RE = re.compile(
    r"(?:거래\s*[·ㆍ]?\s*협력|협력\s*중인|거래\s*중인)[^\n]{0,20}?중소\s*기업|중소\s*기업[^\n]{0,40}?(?:희망하는|거래\s*[·ㆍ]?\s*협력|협력\s*중인)"
)
#: 「지역정보보호지원센터가 속한 지역기업을 지원」(123800 인천센터) — 수행기관 지역 기업이 대상이다. 표 각주에 있어 문서 어디서나 본다.
_OPERATOR_REGION_RE = re.compile(r"(?:센터|테크노파크|진흥원|기관)\s*(?:가|이)?\s*(?:속한|소재한|위치한)\s*지역\s*(?:의\s*)?기업")


def _extract_sme(clauses, line, page, section) -> None:
    """「중소기업기본법 제2조에 따른 중소기업」 · 「중소기업 확인서를 보유한」 — `detail.clean` 은 그 줄이 중소기업 하나만 요구하는가."""
    probe = _SME_DOUBLE_NEG_RE.sub(" ", line)
    if _NEGATIVE_RE.search(_PAREN_RE.sub(" ", probe)):
        return  # 「중소기업에 해당하지 않는 경우」는 제외 조항이다
    qualified = _SME_QUALIFIED_RE.search(probe)
    if qualified and not (_SME_LAW_RE.search(probe) or _SME_CERT_RE.search(probe)):
        # 법 이름이 없어도 「OO와 거래 · 협력 중인 중소기업」은 규칙이 못 읽는 대상 조건이다 — 확인서가 있어도 가능으로 닫지 않는다
        _add(clauses, "sme", "중소기업(못 읽은 조건)", line, page, section,
             {"clean": False, "qualified": True, "rest": qualified.group(0)[:60]})
        return
    if _LAB_SME_RE.search(probe) and not (_SME_LAW_RE.search(probe) or _SME_CERT_RE.search(probe)):
        # 연구소 · 국내 소재는 다른 조항이 본다 — 여기서는 중소(중견)기업 하나만 요구한다
        _add(clauses, "sme", "중소기업", line, page, section, {"clean": True, "rest": None, "lab_sentence": True})
        return
    if not (_SME_LAW_RE.search(probe) or _SME_CERT_RE.search(probe)):
        return
    rest = _SME_LABEL_RE.sub("", _SME_BULLET_RE.sub("", probe, count=1), count=1)
    rest = _SME_CERT_RE.sub(" ", _SME_LAW_NAME_RE.sub(" ", rest))
    # 「(본사)」 · 「(개인사업자 포함)」처럼 대상을 넓히는 괄호는 조건이 아니다(10-10 검토 — 122147)
    rest = re.sub(r"중소\s*기업(?:자)?|\(\s*본사\s*\)|\([^()]*포함\s*\)", " ", rest)
    rest = _SME_WIDER_RE.sub(" ", rest)
    # 사유에 그대로 인용하므로 띄어쓰기를 남긴다(글자만 붙여 「중지역전략산업…」으로 보였다 · 10-10 검토)
    rest = re.sub(r"\s+", " ", rest).strip(" ,·ㆍ-:：")
    clean = not re.search(r"[가-힣A-Za-z0-9]", rest)
    # 「으로 전남광주 … 소재」처럼 조사로 시작하지 않게(「…중소기업의」는 조사만 남아도 clean 이 아니다 — 126482)
    shown = re.sub(r"^(?:으로서|로서|으로|로|이며|이고|인|의)\s+", "", rest) or rest
    detail = {"clean": clean, "rest": None if clean else shown[:60]}
    if qualified:
        detail["qualified"] = True
    _add(clauses, "sme", "중소기업", line, page, section, detail)


def _extract_prerequisites(
    clauses, line, page, section, *, following: str = "", in_doc_list: bool = False, in_exclusion: bool = False
) -> None:
    # 「선정제외대상」 · 「제한사항」 머리 아래 줄(그 줄엔 제외 낱말이 없음)은 보유 요건이 아니다 — 「공급기업으로 등록된 기업」을
    # 「공급기업으로 등록하면 가능」으로 거꾸로 읽었다(43차 M20 · COMPANY-04 · 인천 블록체인 바우처 수요기업)
    negative = in_exclusion or bool(_NEGATIVE_RE.search(line))
    for pattern, key, label in _PREREQUISITES:
        # 「… 공급기업으로 선정된 기업은 신청 불가」를 「공급기업 등록 필요」로 읽지 않는다. 점수 문턱만 괄호 밖에서 본다(괄호 안 「제외 시」)
        if key == "score_threshold":
            if _NEGATIVE_RE.search(_strip_note_parens(line)):
                continue
        elif negative:
            continue
        if key in _ELIGIBILITY_ONLY_PREREQUISITES and section != SECTION_ELIGIBILITY:
            continue
        # 괄호 안 절차 낱말(「(최종 선정 결과는 개별 통보)」)은 보지 않는다 · 「신청 · 참여 · 참가」가 있으면 자격 꼴이다(32차 마지막 검토)
        if (
            key == "prior_selection"
            and _SELECTION_PROCEDURE_RE.search(_PAREN_RE.sub(" ", line))
            and not _PRIOR_SELECTION_QUALIFY_RE.search(line)
        ):
            continue
        if key == "completed_program" and _NOT_COMPLETED_RE.search(line):
            continue
        if not pattern.search(line):
            continue
        quote = line
        if key == "research_department":
            quote = _research_requirement(line, following, in_doc_list)
            if quote is None:
                continue
        detail: dict = {"requirement": key}
        if _OPTION_ROW_RE.search(quote) or _OPTION_FOLLOW_RE.match(following):
            detail["option"] = True
        _add(clauses, "prerequisite", label, quote, page, section, detail)


#: 「누가 이 사업을 **운영하는가**」를 말하는 자리. 신청자가 들어갈 자리가 아니다.
_OPERATING_ROLE_KEYS: frozenset[str] = frozenset({"lead_org", "operator"})

#: 신청자를 말하는 동사. 운영기관 이름 옆에 이것이 없으면 **기관 나열**일 뿐이다
#: (ISSUE-119 마지막 자리 · prompt_05 §4-F).
#:
#: 126482 에서 이렇게 샜다 — 넷 다 `role: 주관기관` 으로 잡혔다:
#:
#:   247행 「* (전문기관) 창업진흥원 (주관기관) 서울창조경제혁신센터」   ← 운영기관 나열
#:   286행 「주관기관 또는 전문기관에서 별도 현장실사를 진행할 수 있음」  ← 심사하는 쪽의 일
#:   312행 「… ▶ K-Startup 누리집 ▶ 전문기관, 주관기관, 협력기관」       ← 안내 흐름도
#:   419행 「◦ 전문기관과 주관기관은 선정된 창업기업의 사업비 횡령 …」    ← 선정 뒤 관리
#:
#: 넷 다 사업계획서 초안의 「신청 자격 충족 설명」에 인용될 수 있고, 담당자는 그것을 자격
#: 요건으로 읽는다. 「검토는 … 진행하며」(`_PROCEDURE_RE`)와 같은 부류인데 그쪽 모양에
#: 안 맞아 남아 있었다.
#:
#: **좁게 잡는다.** 운영 쪽 자리(`_OPERATING_ROLE_KEYS`)에만 걸고, 그 줄에 신청·모집·참여가
#: 하나라도 있으면 그대로 둔다 — 「주관기관 모집 공고」·「참여기업이 주관기관과 협약을
#: 맺어 신청」 같은 진짜 요건은 이 그물을 지나간다. 신청자 쪽 자리(공급기업·수요기업·
#: 도입기업·기술기업·컨소시엄 …)는 아예 건드리지 않는다.
_APPLICANT_VERB_RE = re.compile(r"신청|모집|참여")


#: 컨소시엄을 **구성해야** 신청하는 꼴 — 「…과 컨소시엄을 구성하고」 · 「컨소시엄 참여 필수」 · 「컨소시엄으로 신청」(37차 recheck29 R36-RV-03)
#: · 괄호 낀 「국제 컨소시엄(일본 필수 포함)을 구성」(127116) · 조사 없는 「컨소시엄 구성하여 … 필수」 · 「컨소시엄을 구성한 기업만」(38차 RULES-01 · 03).
CONSORTIUM_REQUIRED_RE = re.compile(
    r"컨소시엄\s*(?:\([^)\n]{0,30}\)\s*)?(?:을|를)\s*(?:구성|이루)(?:하여|해서|해야|하고|하여야|한\s*후|\s*$|\s*[)\]」.·,])"
    r"|컨소시엄\s*(?:참여|구성)?\s*필수|컨소시엄\s*(?:으로|형태로)\s*(?:신청|참여|지원)"
    r"|컨소시엄\s*구성하여[^\n]{0,40}?필수"
    r"|컨소시엄\s*(?:\([^)\n]{0,30}\)\s*)?(?:을|를)?\s*구성한\s*(?:기업|기관|자)\s*(?:만|에\s*한)"
)
#: 선택 · 조건 꼴 — 「컨소시엄 구성 가능」 · 「구성이 가능하며」 · 「컨소시엄연구개발과제의 경우 … 별 적용」(127152 · 127025 · 127081 — 37차 원문 대조).
CONSORTIUM_OPTIONAL_RE = re.compile(r"컨소시엄[^\n]{0,14}?(?:(?<!불)가능|할\s*수\s*있|의\s*경우|경우에)|구성하는\s*각")
#: 선택 꼴 낱말이 있어도 필수인 줄 — 「필수」 · 「…기업만 신청 가능」 · 「…에 한하여」(38차 RULES-03 — 「가능」이 선택으로 읽혔다).
_CONSORTIUM_STRICT_RE = re.compile(r"필수|(?:기업|기관|자)\s*만\s|(?:기업|기관|자)에\s*한(?:하여|함|정)")


def consortium_required(line: str) -> bool:
    """컨소시엄을 구성해야만 신청하는 줄인가 — 필수 꼴이고, 선택 꼴이 아니거나 「필수 · …만 · 한하여」가 함께 있다."""
    if not CONSORTIUM_REQUIRED_RE.search(line):
        return False
    return bool(_CONSORTIUM_STRICT_RE.search(line)) or not CONSORTIUM_OPTIONAL_RE.search(line)


def _extract_roles(clauses, line, page, section) -> None:
    """한 줄에 나오는 자리를 **전부** 남긴다.

    「도입기업이 기술기업과 컨소시엄을 구성하여 신청」은 한 줄에 두 자리가 있고, 그 둘이
    함께 있다는 것이 곧 «두 축 구조»다 — 도입기업이 신청하고 기술기업이 수행한다.
    앞의 하나만 읽으면 회사가 들어갈 자리(기술기업)가 사라진다.

    **운영기관 이름만 늘어놓은 줄은 자리가 아니다** (바로 위 주석 · prompt_05 §4-F).
    """
    applicant = _APPLICANT_VERB_RE.search(line) is not None
    for needle, key, label in _ROLES:
        if needle not in line:
            continue
        if key in _OPERATING_ROLE_KEYS and not applicant:
            continue
        detail: dict = {"role": key}
        if key == "consortium" and consortium_required(line):
            # 필수 줄은 앞서 나온 선택 · 설명 줄과 값이 달라 따로 남는다(38차 RULES-03 — 처음 나온 「컨소시엄」 한 줄만 남았다).
            detail["required"] = True
        _add(clauses, "role", f"역할: {label}", line, page, section, detail)


def _extract_money(clauses, line, page, section) -> None:
    """한 줄에 있는 돈 조각을 **전부** 담는다.

    「소요비용 50%(최대 15백만원) 내 지원」 한 줄에 비율과 한도가 함께 있다. 앞의 하나만
    읽으면 담당자가 「얼마를 내야 하는가」와 「얼마까지 받는가」 중 하나를 잃는다.
    """
    # **받는 것을 말하는 문장만 본다** (0925 §4-C-2).
    if _MONEY_NOT_RE.search(line):
        return
    if section not in _MONEY_SECTIONS and not _MONEY_VERB_RE.search(line):
        return
    # 「자부담 없음」은 그렇게 적힌 문장이 있을 때만 담는다.
    if _NO_BURDEN_RE.search(line):
        _add(clauses, "money", "자부담 없음", line, page, section, {"kind": "no_self_burden"})
    for pattern, key in _MONEY_PATTERNS:
        match = pattern.search(line)
        if match is None:
            continue
        if key == "free":
            _add(clauses, "money", "무료", line, page, section, {"kind": "free"})
            continue
        elif key == "cap":
            amount = _number(match.group(1))
            if amount is None:
                continue
            _add(clauses, "money", f"최대 {match.group(1)}{match.group(2)}원", line, page, section,
                 {"kind": "cap", "krw": _krw(amount, match.group(2))})
            continue
        elif key == "range":
            low, high = _number(match.group(1)), _number(match.group(2))
            if low is None or high is None:
                continue
            unit = match.group(3)
            _add(clauses, "money", f"{match.group(1)}~{match.group(2)}{unit}", line, page, section,
                 {"kind": "range", "low_krw": _krw(low, unit), "high_krw": _krw(high, unit)})
            continue
        elif key == "monthly":
            amount = _number(match.group(1))
            if amount is None:
                continue
            _add(clauses, "money", f"월 {match.group(1)}만원", line, page, section,
                 {"kind": "monthly", "krw": _krw(amount, "만")})
            continue
        else:
            share = _number(match.group(1))
            if share is None or share > 100:
                continue
            label = "정부지원 비율" if key == "government_share" else "자부담 비율"
            _add(clauses, "money", f"{label} {match.group(1)}%", line, page, section,
                 {"kind": key, "percent": share})


def _extract_exclusions(clauses, line, page, section, *, in_list: bool = False) -> None:
    if _TOC_RE.search(line):
        return  # 「8. 사전 지원 제외 대상·········12」는 쪽 안내이지 조항이 아니다
    # 괄호 안 「(… 점수 제외 시 45점)」 · 「(정부지원금 제외)」와 계산 꼴 「제외 시 · 제외한 나머지」는 제외 조항이 아니다(「(중복지원 불가)」 · 「제외한다」는 제외 조항) — 120566 의 신청 문턱
    # 「자가진단 결과가 50점 이상(… 제외 시 45점)인 경우에 한하여」가 제외 조항으로 숨었다(10-10 중소기업 확인서 감사)
    if _EXCLUSION_RE.search(_strip_note_parens(line)):
        _add(clauses, "exclusion", "제외 조항", line, page, section, {})
        return
    # 제외 목록 안의 항목. 「제외」라는 말이 없어도 그 목록에 있으면 제외 대상이다.
    if in_list and _BULLET_RE.match(line):
        _add(clauses, "exclusion", "제외 조항", line, page, section, {"from_list": True})


def _extract_deadline(clauses, line, page, section) -> None:
    time = _TIME_RE.search(line)
    if time and any(word in line for word in ("까지", "마감", "접수", "제출")):
        _add(clauses, "deadline_detail", f"마감 시각 {time.group(1)}:{time.group(2)}", line, page, section,
             {"hour": int(time.group(1)), "minute": int(time.group(2))})
        return
    method = next((w for w in _METHOD_WORDS if w in line), None)
    if method and any(word in line for word in ("접수", "제출", "신청")):
        _add(clauses, "deadline_detail", f"접수 방법: {method}", line, page, section, {"method": method})


_OUTSIDE_OK_RE = re.compile(r"도외\s*기업|도내\s*[/·ㆍ]\s*외|도내외|관외\s*기업")


#: 못 읽은 대상 줄은 몇 줄까지 남기나(사유에는 첫 줄을 인용한다).
MAX_UNHANDLED_TARGETS: Final[int] = 5


def _target_line(line: str) -> bool:
    """대상 요건을 말하는 줄인가 — 주어(기업 · 기관 · 소재 …)가 있고 머리 문장 · 우대 · 절차가 아니다."""
    cleaned = _clean(line)
    if len(cleaned) < 8 or _NOT_TARGET_RE.search(cleaned) or not _TARGET_NOUN_RE.search(cleaned):
        return False
    # 「지원대상 :」 · 「□ 신청자격」처럼 머리 낱말뿐인 줄은 아니다
    return len(_ELIGIBILITY_WORD_RE.sub("", re.sub(r"[\s:：()（）]", "", cleaned))) >= 6


def _line_handled(line: str, page: int, here: str | None, following: str, revenue_context: bool = False) -> bool:
    """규칙이 이 줄에서 조항 하나라도 뽑는가 — 새 목록에 그 줄만 뽑아 본다(같은 값 중복 줄도 「읽었다」).
    매출 문맥(「○ 직전년도 매출액 기준」 아래 「- 10억원 이상인 기업」)도 반복문과 같게 준다(36차 R36-09)."""
    probe: list[SupportClause] = []
    _extract_location(probe, line, page, here)
    _extract_org_types(probe, line, page, here)
    _extract_headcount(probe, line, page, here)
    _extract_founding(probe, line, page, here)
    _extract_revenue(probe, line, page, here, revenue_context)
    _extract_sme(probe, line, page, here)
    _extract_prerequisites(probe, line, page, here, following=following)
    _extract_roles(probe, line, page, here)
    _extract_exclusions(probe, line, page, here)
    _extract_strategic(probe, line, page, here, in_run=False)
    # 「해당 연구과제별 시·도에 소재」는 과제 지역 소재 조항으로 읽는다(반복문 안 · 127025)
    return bool(probe) or bool(_TASK_SITE_RE.search(line))


def extract_from_text(program_id: str, text: str, *, pages: int = 0) -> SupportRequirements:
    """공고문 텍스트에서 조항을 뽑는다. 못 찾은 갈래는 **비워 둔다**."""
    clauses: list[SupportClause] = []
    #: 지원대상 절의 **첫 문장** (0925 §4-A-1). 판정이 「확인 필요」일 때 사유가 인용한다.
    target_sentence: str | None = None
    section: str | None = None
    since_heading = 0
    exclusion_run = 0
    strategic_run = 0
    revenue_context = 0
    doc_run = 0
    org_skip_run = 0
    exclusion_rank = 0
    doc_rank = 0
    unhandled: list[str] = []
    #: 지금 머리가 절차 머리인가 — 그 아래에서는 대상 줄을 모으지 않는다(머리 줄이 바뀔 때까지)
    procedure_context = False
    lead_run = 0
    previous = ""
    other_roles = bool(_OTHER_ROLE_RE.search(text))
    task_regions = sorted({m.group(1) for m in (_TASK_REGION_RE.match(raw) for _, raw in _lines_with_pages(text)) if m})
    rows = list(_lines_with_pages(text))
    for index, (page, line) in enumerate(rows):
        following = rows[index + 1][1] if index + 1 < len(rows) else ""
        # **공고문 제목 줄은 절을 열지 않는다** (0925 §4-A-1).
        #
        # 「2026년「장애인 창업 컨설팅」지원 대상자 모집공고」에 「지원 대상」이 들어 있어
        # 그 아래 여섯 줄(사업 취지 문단)이 통째로 자격 절이 됐다.
        # 「…지원대상에 포함.」처럼 문장 가운데서 말한 줄은 절 제목이 아니다(121182 붙임 용어 풀이 · 35차 R34S-03)
        heading = None if _DOC_TITLE_RE.search(line) or _ELIGIBILITY_MENTION_RE.search(line) else _section_of(line)
        if heading is not None:
            section, since_heading = heading, 0
        else:
            since_heading += 1
        # 제목이 다스리는 창을 벗어나면 「절을 모른다」로 돌아간다.
        here = section if since_heading <= SECTION_WINDOW_LINES else None
        if (
            any(word in line for word in _SELF_ELIGIBILITY)
            and not _DOC_TITLE_RE.search(line)
            and not _ELIGIBILITY_MENTION_RE.search(line)
        ):
            # 이 줄 자체가 자격 문장이다. 창도 여기서 다시 연다 — 바로 아래 목록이 요건이다.
            here, section, since_heading = SECTION_ELIGIBILITY, SECTION_ELIGIBILITY, 0
        if _LEAD_ROLE_HEADING_RE.search(line):
            # 「< 주관연구개발기관 자격 조건 >」도 자격 절이다 — 그 아래 소재 · 형태 요건을 읽는다(127025)
            here, section, since_heading = SECTION_ELIGIBILITY, SECTION_ELIGIBILITY, 0
        # 제외 · 서류 · 형태 건너뛰기 구간은 **새 절 제목**에서 끝난다(목록 항목 글머리 줄 · 제외 머리 자체는 빼고).
        # 끝나지 않으면 「□ 지원대상 및 지원 제외 대상 / ○ 지원대상: 광주 소재 사회적기업」의 형태 요건이 사라져
        # 인증 없는 회사가 거짓 「가능」이었다(35차 마지막 검토).
        new_item = (heading is not None or bool(_TOP_BULLET_RE.match(line))) and not _LIST_ITEM_RE.match(line)
        if heading is not None and new_item and not _exclusion_heading(line) and not _NEGATIVE_RE.search(line):
            exclusion_run = 0
            if not _DOC_LIST_HEADING_RE.search(_PAREN_RE.sub(" ", line)):
                doc_run = 0
        if new_item and not _ORG_SKIP_HEADING_RE.search(line) and not _is_headcount_waiver(line):
            org_skip_run = 0
        # 구간을 연 줄보다 윗단 글머리의 새 항목에서도 끝난다(36차 R35-RULE-01 · `_bullet_rank`)
        rank = _bullet_rank(line)
        before = len(clauses)
        if _LEAD_ROLE_HEADING_RE.search(line):
            lead_run = LEAD_ROLE_RUN_LINES
        elif _LEAD_ROLE_LABEL_RE.match(line):
            lead_run = max(lead_run, 4)
        elif rank in (0, 1) or re.match(r"^\s*[【\[<〈《]", line):
            lead_run = 0
        # 절차 머리는 구조 머리(「1.」 · □ · 【】 · < >)에서만 바뀐다 — 「○ (신청 대상) …」 줄이 이의신청 절차를 다시 자격 절로 덮지 않게
        if rank in (0, 1) or re.match(r"^\s*[【\[<〈《]", line):
            procedure_context = bool(_PROCEDURE_HEADING_RE.search(line)) and not _ELIGIBILITY_WORD_RE.search(line)
        if exclusion_run and _ends_run(rank, exclusion_rank) and not _exclusion_heading(line):
            exclusion_run = 0
        if doc_run and _ends_run(rank, doc_rank) and not _DOC_LIST_HEADING_RE.search(_PAREN_RE.sub(" ", line)):
            doc_run = 0
        # 지원대상 절의 **첫 문장**을 한 번만 담아 둔다 (0925 §4-A-1).
        #
        # 공고문 제목(「2026년「장애인 창업 컨설팅」지원 대상자 모집공고」)에도 「지원 대상」이
        # 들어 있어 그것이 먼저 잡혔다. 제목은 요건이 아니다 — 건너뛰고 실제 목록을 담는다.
        if target_sentence is None and here == SECTION_ELIGIBILITY:
            candidate = _clean(line)
            if (
                len(candidate) >= TARGET_SENTENCE_MIN_CHARS
                and not _NEGATIVE_RE.search(candidate)
                and not _DOC_TITLE_RE.search(candidate)
            ):
                target_sentence = candidate
        # **자격 문맥에서만 자격 조항을 뽑는다.**
        #
        # 소재·조직 형태·인원·연차·매출은 「누가 신청할 수 있는가」를 정하는 말이다. 그
        # 말이 붙임 표나 안내문에서 스쳐 지나갔다고 요건으로 읽으면, 판정이 근거 없이
        # 「불가」로 간다 — 그것이 가장 나쁜 고장이다(공고를 아예 못 보게 된다).
        # 대신 못 찾았으면 「없음」이 아니라 **「확인 필요」**다 — 규칙이 그렇게 읽는다.
        eligible_here = (
            here in ELIGIBILITY_SECTIONS
            and since_heading <= ELIGIBILITY_WINDOW_LINES
            and not _NEGATIVE_RE.search(line)
            # 자격 절 안이어도 «평가·운영 안내» 줄은 요건이 아니다 (ISSUE-115).
            # 126482 의 「밋업 : 발표평가 대상자와 공공기관과 …」이 「공공기관」 때문에
            # 조직 형태 요건으로 잡혔다.
            and not _NOT_ELIGIBILITY_RE.search(line)
            # 「검토는 … 진행하며」 같은 **절차 서술**도 요건이 아니다 (ISSUE-119 · §4-D-3).
            and not _PROCEDURE_RE.search(line)
        )
        # 「중소기업」 요건은 두 번 부정(「제외 대상에 해당되지 않는 … 중소기업」)도 읽으므로 부정 낱말 검사를 자기가 한다(10-10)
        if (
            here in ELIGIBILITY_SECTIONS
            and since_heading <= ELIGIBILITY_WINDOW_LINES
            and not _NOT_ELIGIBILITY_RE.search(line)
            and not _PROCEDURE_RE.search(line)
        ):
            _extract_sme(clauses, line, page, here)
        if eligible_here:
            _extract_location(clauses, line, page, here)
            # 줄바꿈으로 갈린 「…시·도에 / 소재」도 읽되, 문구가 **이 줄에서 시작**할 때만 붙인다 — 앞 줄(「○ 공동연구개발기관: …」)에
            # 붙으면 주관기관 한정이 빠져 거짓 「불가」였다(36차 R36-05)
            site = _TASK_SITE_RE.search(f"{line} {following}")
            if len(task_regions) == 1 and site and site.start() < len(line):
                region = task_regions[0]
                canon = "전남광주" if region in ("광주", "전남") else region
                _add(clauses, "location", f"소재: {region}(과제 지역)", line, page, here,
                     {"region": canon, "alias": region, "site": "소재", "task_region": True})
            if exclusion_run == 0 and org_skip_run == 0:
                _extract_org_types(clauses, line, page, here)
            _extract_headcount(clauses, line, page, here)
            _extract_founding(clauses, line, page, here)
            _extract_revenue(clauses, line, page, here, revenue_context > 0, in_exclusion=exclusion_run > 0)
            # 규칙이 하나도 읽지 못한 대상 줄을 모은다 — 남으면 「가능」 대신 확인 필요(36차 R35-DV-01).
            # 그 줄만 새 목록에 다시 뽑아 본다 — 같은 값이 앞서 있어 한 번만 남는 경우에도 「읽었다」로 센다.
            # 지역 전략산업 표(우선 선정 가산 · 자격 아님 — 123682)도 대상 줄이 아니다
            if exclusion_run == 0 and doc_run == 0 and org_skip_run == 0 and strategic_run == 0 and not procedure_context and _target_line(line):
                cleaned = _clean(line)
                if cleaned not in unhandled and len(clauses) == before and not _line_handled(line, page, here, following, revenue_context > 0):
                    unhandled.append(cleaned)
        # 아래 다섯은 문서 어디에 있어도 뜻이 같다 — 받는 돈·역할·제외·마감·보유 요건.
        # 단, 역할·선행 요건은 «평가·운영·인력» 문장에서 뽑지 않는다 (ISSUE-115).
        # 절차 서술(「검토는 전문기관에서 상시 진행하며」)은 역할·선행 요건이 아니다
        # — 심사하는 쪽의 일하는 방식이지 신청자의 자격이 아니다 (ISSUE-119 · §4-D-3).
        role_ok = not _NOT_ELIGIBILITY_RE.search(line) and not _PROCEDURE_RE.search(line)
        if role_ok:
            _extract_prerequisites(clauses, line, page, here, following=following, in_doc_list=doc_run > 0, in_exclusion=exclusion_run > 0)
            _extract_roles(clauses, line, page, here)
        _extract_money(clauses, line, page, here)
        if _OPERATOR_REGION_RE.search(line) and not any(c.kind == "operator_region" for c in clauses):
            _add(clauses, "operator_region", "수행기관 지역 기업 대상", line, page, here, {})
        _extract_exclusions(clauses, line, page, here, in_list=exclusion_run > 0)
        _extract_deadline(clauses, line, page, here)
        _extract_strategic(clauses, line, page, here, in_run=strategic_run > 0)
        strategic_run = (
            STRATEGIC_RUN_LINES if _STRATEGIC_RE.search(line) else max(0, strategic_run - 1)
        )
        # 제외 목록은 머리글 아래 몇 줄을 다스린다.
        if _opens_exclusion(line):
            exclusion_run, exclusion_rank = EXCLUSION_RUN_LINES, (rank if rank is not None else 0)
        else:
            exclusion_run = max(0, exclusion_run - 1)
        if _DOC_LIST_HEADING_RE.search(_PAREN_RE.sub(" ", line)):
            doc_run, doc_rank = DOC_LIST_RUN_LINES, (rank if rank is not None else 0)
        else:
            doc_run = max(0, doc_run - 1)
        org_skip_run = (
            # 인원 예외 문장 아래 목록(「① 벤처기업 … ③ 사회적기업」)도 대상 요건이 아니다(35차 R34-DATA-03)
            ORG_SKIP_RUN_LINES if _ORG_SKIP_HEADING_RE.search(line) or _is_headcount_waiver(line)
            else 0 if heading is not None else max(0, org_skip_run - 1)
        )
        line_lead = lead_run > 0 or (bool(_LEAD_ROLE_RE.search(f"{previous} {line}")) and "공동" not in line)
        if other_roles and line_lead and len(clauses) > before:
            clauses[before:] = [
                c.model_copy(update={"detail": {**c.detail, "role_limited": True, "role": "주관연구개발기관"}})
                if c.kind == "location" or (c.kind == "prerequisite" and c.detail.get("requirement") == "research_department")
                else c
                for c in clauses[before:]
            ]
        lead_run = max(0, lead_run - 1)
        previous = line
        # 「매출액」이 제목 줄에 있고 숫자가 **몇 줄 뒤** 표에 오는 공고가 있다 (명품강소기업).
        revenue_context = 4 if "매출" in line else max(0, revenue_context - 1)
    # 표 칸이 줄로 떨어져 나오면(119692 트랙 2 칸) 같은 글이 갈래 표시 없이 한 번 더 잡힌다 — 갈래 줄 안에 든 글이면 갈래다.
    options = [re.sub(r"\s+", "", c.source_text) for c in clauses if c.kind == "prerequisite" and c.detail.get("option")]
    if options:
        clauses = [
            c.model_copy(update={"detail": {**c.detail, "option": True}})
            if c.kind == "prerequisite" and not c.detail.get("option")
            and any(re.sub(r"\s+", "", c.source_text) in row for row in options)
            else c
            for c in clauses
        ]
    # 소재 줄 아래 ② · ③ 갈래 줄이 줄바꿈으로 갈린 이전 단서(36차 R35-DV-04) — 그 소재 조항에 이전 단서를 단다
    cleaned_rows = [_clean(raw) for _, raw in rows]
    def _relocation_after(source: str) -> bool:
        at = next((i for i, row in enumerate(cleaned_rows) if row and (row == source or source.startswith(row[:30]))), None)
        if at is None:
            return False
        window: list[str] = []
        for k in range(at, min(at + RELOCATION_LOOKAHEAD_LINES, len(rows))):
            raw = rows[k][1]
            if k > at and _bullet_rank(raw) in (0, 1, 2):
                break  # 다음 ○ · □ 항목(「□ 사후관리」 · 「○ 협약기간 중 …」)은 이 소재 줄의 갈래가 아니다(36차 R36-07)
            if not _PENALTY_RE.search(raw):
                window.append(raw)
        return bool(_RELOCATION_RE.search(re.sub(r"\s+", " ", " ".join(window))))
    clauses = [
        c.model_copy(update={"detail": {**c.detail, "relocation": True}})
        if c.kind == "location" and not c.detail.get("relocation") and _relocation_after(c.source_text)
        else c
        for c in clauses
    ]
    def _dept_excluded_near(source: str) -> bool:
        """「전담부서 … 미포함 · 불인정」이 **같은 절 · 앞뒤 몇 줄 안**에 있는가(37차 R36-RV-06 — 예전에는 문서 전체에서 찾아
        전담부서를 받는 다른 대상 줄에도 「기업부설연구소만」이 붙었다). 윗단 글머리(1. · □)를 넘으면 다른 절이다."""
        # 같은 줄이 개요 상자에도 있으면 처음 것만 보면 창이 개요 쪽으로 간다 — 나오는 곳마다 본다(38차 RULES-02).
        spots = [i for i, row in enumerate(cleaned_rows) if row and (row == source or source.startswith(row[:30]))]

        def hit(raw: str) -> bool:
            return bool(_DEPT_EXCLUDED_RE.search(raw)) and not _BONUS_CONTEXT_RE.search(raw)

        def near(at: int) -> bool:
            if hit(rows[at][1]):
                return True
            for step in (1, -1):
                k = at + step
                while 0 <= k < len(rows) and abs(k - at) <= DEPT_EXCLUDED_LOOKAROUND_LINES:
                    raw = rows[k][1]
                    if _bullet_rank(raw) in (0, 1):
                        break
                    if hit(raw):
                        return True
                    k += step
            return False

        return any(near(at) for at in spots)

    clauses = [
        c.model_copy(update={"detail": {**c.detail, "lab_only": (
            # 조항이 「또는 연구개발전담부서」를 받으면 붙이지 않는다(37차 R36-RV-06)
            not _DEPT_ALLOWED_RE.search(c.source_text)
            and (_dept_excluded_near(c.source_text) or not re.search(r"전담\s*부서", c.source_text))
        )}})
        if c.kind == "prerequisite" and c.detail.get("requirement") == "research_department"
        else c
        for c in clauses
    ]
    if _OUTSIDE_OK_RE.search(text):
        # 「도내/외 기업」 · 「도외기업」 — 소재 요건이 프로그램마다 다르다(34차 §3-A-3 · 126827). 소재 줄 모두에 단서를 단다.
        clauses = [
            c.model_copy(update={"detail": {**c.detail, "outside_ok": True}}) if c.kind == "location" else c
            for c in clauses
        ]
    return SupportRequirements(
        program_id=program_id,
        document_read=True,
        pages=pages or max((p for p, _ in _lines_with_pages(text)), default=0),
        target_sentence=target_sentence,
        clauses=clauses,
        unhandled_targets=unhandled[:MAX_UNHANDLED_TARGETS],
    )


def load(program_id: str) -> SupportRequirements:
    """받아 둔 공고문에서 조항을 뽑는다. 없으면 「못 읽음」 상태로 돌려준다."""
    plain_id = program_id.removeprefix("bizinfo-")
    text = bizinfo_document_store.load_text(plain_id)
    if text:
        record = bizinfo_document_store.load_index().records.get(plain_id)
        return extract_from_text(plain_id, text, pages=record.pages if record else 0)
    record = bizinfo_document_store.load_index().records.get(plain_id)
    if record is None:
        return SupportRequirements(
            program_id=plain_id,
            document_read=False,
            document_note="공고문 파일은 아직 안 받아, 기업마당 요약만 보고 판정했습니다",
        )
    return SupportRequirements(
        program_id=plain_id,
        document_read=False,
        # 저장된 옛 메모는 내보낼 때만 새 말로(33차 R32-13 — 색인 파일은 그대로)
        document_note=wording.modernize_text(record.note) if record.note else "공고문 파일을 읽지 못해, 기업마당 요약만 보고 판정했습니다",
    )


def free_of(requirements) -> bool:
    """공고문이 **무료·전액 지원**이라고 적었는가."""
    return any(c.detail.get("kind") == "free" for c in requirements.of("money"))


def no_self_burden_of(requirements) -> bool:
    """공고문이 **자부담이 없다**고 적었는가. 없으면 모르는 것이지 「없다」가 아니다."""
    return any(c.detail.get("kind") == "no_self_burden" for c in requirements.of("money"))


def coverage(requirements: Iterable[SupportRequirements]) -> dict[str, int]:
    """조항 갈래별로 **몇 건에서 찾았는가**. 보고서가 이 값을 그대로 적는다."""
    kinds = ("location", "org_type", "sme", "headcount", "founding_years", "revenue",
             "prerequisite", "role", "money", "exclusion", "deadline_detail",
             "strategic_industry")
    out = {kind: 0 for kind in kinds}
    out["total"] = 0
    out["read"] = 0
    for item in requirements:
        out["total"] += 1
        if not item.document_read:
            continue
        out["read"] += 1
        for kind in kinds:
            if item.of(kind):
                out[kind] += 1
    return out
