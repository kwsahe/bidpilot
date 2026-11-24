"""기업마당 지원사업이 «어떤 성격의 사업인가» — 한 곳에서만 정한다.

나라장터 공고에는 「무슨 일을 시키는가」라는 축이 있어 work_kinds.py 가 그것을 정한다.
기업마당은 축이 다르다 — 우리가 **신청하는** 사업이고, 무엇을 지원해 주는가가 축이다.
그래서 work_kinds 를 재사용하지 않고 따로 둔다.

왜 필요한가:
  회사 프로필에서 뽑은 토큰이 25개나 되다 보니(AI·교육·컨설팅·개발·로봇·제조·대학·비전 …)
  거의 모든 공고가 2~3개는 스쳤고, 그것만으로 사업영역 만점이 나왔다.
  실측(2026-09-10, org-sample, 100건): 「디지털혁신기술국제공동연구」와
  「시설농업 AI로봇 실증기반 구축」이 각각 81점으로 상위 1·2위였다.
  둘 다 SampleEdu 이 신청해서 얻을 것이 거의 없는 사업이다.

  키워드가 스친 것과 「우리가 할 수 있는 종류의 사업인가」는 다른 질문이다.
  이 모듈은 뒤의 질문에 답한다.

원칙:
  - 판정 근거를 함께 돌려준다. 점수만 바뀌고 이유를 모르면 담당자가 신뢰할 수 없다.
  - 모르면 「판정 보류」다. 억지로 한 갈래에 넣지 않는다.
  - 이 판정은 **선정확률이 아니다.** 회사와 사업의 성격이 얼마나 겹치는지일 뿐이다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

SupportKind = Literal[
    "ai_education",       # AI 교육
    "ai_consulting",      # AI·AX 컨설팅
    "ai_development",     # AI 소프트웨어 개발
    "physical_ai",        # Physical AI·로봇
    "academic_public",    # 대학·공공기관 협력
    "rnd",                # R&D 지원
    "commercialization",  # 사업화·수출·전시
    "manufacturing",      # 제조 지원
    "low_relevance",      # SampleEdu 직접 관련 낮음
    "unclassified",       # 판정 보류
]

SUPPORT_KIND_LABELS: dict[SupportKind, str] = {
    "ai_education": "AI 교육",
    "ai_consulting": "AI·AX 컨설팅",
    "ai_development": "AI 소프트웨어 개발",
    "physical_ai": "Physical AI·로봇",
    "academic_public": "대학·공공기관 협력",
    "rnd": "R&D 지원",
    "commercialization": "사업화·수출·전시",
    "manufacturing": "제조 지원",
    "low_relevance": "직접 관련 낮음",
    "unclassified": "판정 보류",
}

# 갈래별 판정 규칙. 위에서부터 본다 — 앞선 갈래가 더 구체적이다.
#
# 「AI」 한 낱말만으로는 어느 갈래도 되지 않는다. 무엇을 지원해 주는 사업인지를 말하는
# 두 번째 낱말이 함께 있어야 한다. 그것이 이 모듈을 만든 이유다.
_RULES: list[tuple[SupportKind, str, str]] = [
    # --- 우리가 주체가 될 수 있는 갈래 (먼저 본다. 규칙이 좁다) ---
    (
        "ai_education",
        r"(?:AI|인공지능|생성형|디지털|SW|소프트웨어)[^.\n]{0,14}?(?:교육|연수|아카데미|인력\s*양성|역량\s*강화|훈련)"
        r"|(?:교육|연수|아카데미|훈련)\s*(?:과정|프로그램|운영)[^.\n]{0,14}?(?:AI|인공지능|생성형)",
        "AI·디지털 분야의 교육·인력양성 사업",
    ),
    (
        "ai_consulting",
        # 「진단」을 홀로 두면 의료 진단까지 잡는다 — 실제로 「AI 헬스케어 빅데이터 모바일진단」이
        # 컨설팅 사업으로 분류돼 상위 1위에 올랐다. 도입·전환·사전 같은 말이 붙어야 업무 진단이다.
        # 「AX클리닉」처럼 지자체가 여는 진단 창구는 이름 자체가 컨설팅이다 — 클리닉을 함께 본다.
        r"(?:AI|인공지능|생성형|디지털|DX|AX)[^.\n]{0,14}?(?:컨설팅|자문|클리닉|전환\s*지원|도입\s*지원|업무\s*자동화)"
        # 「사전진단」도 홀로 두면 수출 준비 진단까지 잡는다(실측: 수출상담회가 2·3위로 올라왔다).
        # 무엇에 대한 진단인지 — AI·디지털이 함께 있어야 우리 일이다.
        r"|(?:AI|인공지능|디지털|DX|AX)[^.\n]{0,10}?(?:도입|전환|사전|경영|업무)?\s*진단"
        r"|(?:컨설팅|자문)[^.\n]{0,14}?(?:AI|인공지능|디지털\s*전환)",
        "AI·디지털 전환 컨설팅 사업",
    ),
    (
        "ai_development",
        # 「구축」만으로는 안 된다 — 「AI로봇 실증기반 구축」 같은 설비 사업이 걸린다.
        # 소프트웨어를 가리키는 말이 함께 있어야 한다.
        r"(?:AI|인공지능|생성형|LLM)[^.\n]{0,14}?(?:솔루션|플랫폼|소프트웨어|SW|서비스\s*개발|앱|웹|시스템\s*개발)"
        r"|(?:소프트웨어|SW|SaaS)[^.\n]{0,10}?개발",
        "AI·소프트웨어 개발 사업",
    ),
    (
        "academic_public",
        # 「대학」이 스치기만 해도 걸리면 안 된다(신청 자격에 흔히 적힌다).
        # 대학·공공기관과 «함께 하는» 사업임이 드러나야 한다.
        r"산학협력|산학연\s*협력|위탁\s*교육|대학[^.\n]{0,10}?(?:연계|협력|위탁|공동)"
        r"|(?:공공기관|지자체|교육청)[^.\n]{0,10}?(?:연계|협력|위탁|공동)",
        "대학·공공기관과 함께하는 사업",
    ),
    # --- 성격상 회사가 신청 주체가 되기 어려운 갈래 ---
    (
        "physical_ai",
        r"로봇|자율주행|드론|스마트\s*팜|시설농업|비전\s*검사|머신\s*비전",
        "로봇·자율주행 등 물리 AI 사업",
    ),
    (
        "rnd",
        r"R&D|연구개발|기술개발|국제공동연구|과제\s*공고|실증(?:사업|기반)|기초연구|신규지원\s*대상과제",
        "연구개발 과제 지원 사업",
    ),
    (
        "commercialization",
        r"사업화|수출|전시회|박람회|판로|마케팅\s*지원|바이어|해외\s*진출|투자\s*유치|한국관",
        "사업화·수출·전시 지원 사업",
    ),
    (
        "manufacturing",
        r"제조|공장|생산\s*설비|뿌리기술|자동화\s*설비|스마트\s*공장",
        "제조·생산 현장 지원 사업",
    ),
]

_COMPILED = [(kind, re.compile(pattern, re.IGNORECASE), why) for kind, pattern, why in _RULES]

# SampleEdu 이 «신청해서 직접 수행할» 수 있는 갈래.
# 나머지는 무관하다는 뜻이 아니라, 회사가 주체가 되기 어렵다는 뜻이다.
OUR_KINDS: frozenset[SupportKind] = frozenset(
    {"ai_education", "ai_consulting", "ai_development", "academic_public"}
)

#: 사업의 «대상»을 정하는 갈래. 이것이 걸리면 그 사업은 근본적으로 그 분야의 사업이다.
SUBJECT_KINDS: frozenset[SupportKind] = frozenset({"physical_ai", "manufacturing"})

#: 대상 갈래가 함께 걸렸을 때 «우리 것»으로 인정하지 않는 서비스 갈래.
#:
#: 회사는 로봇·제조를 **가르치고 자문**하지, 로봇을 만들거나 공장을 짓지 않는다.
#: 그래서 교육·컨설팅은 대상이 로봇이어도 우리 일이지만, 개발은 아니다.
#: 실제로 「시설농업 AI로봇 실증기반 구축」이 요약문의 「SW 등을 개발」 한 구절 때문에
#: 소프트웨어 개발 사업으로 분류돼 상위에 올라왔다.
DEMOTED_BY_SUBJECT: frozenset[SupportKind] = frozenset({"ai_development"})


@dataclass(frozen=True)
class SupportKindResult:
    kinds: list[SupportKind]
    """맞은 갈래 전부. 하나도 없으면 ["unclassified"]."""

    basis: str
    """무엇을 보고 판정했는지 — 담당자에게 그대로 보여줄 수 있는 문장."""

    words: tuple[str, ...] = ()
    """갈래마다 맞은 공고 낱말(「컨설팅 AI」 · 「로봇」) — 점수 이유가 괄호 세 겹 없이 낱말만 보여 줄 때 쓴다(32차)."""

    declared: bool = True
    """사업이 **스스로 밝힌 목적**(제목·분류)에서 걸렸는가.

    False 면 요약문에만 걸린 것이다. 요약문에는 부수 설명이 섞여 있어서
    「디지털 역량강화」 한 구절 때문에 방화벽 도입 사업이 AI 교육이 되는 일이 있었다.
    """

    @property
    def primary(self) -> SupportKind:
        """가장 구체적인 갈래 하나. 규칙 순서가 곧 구체성 순서다.

        단, 사업의 «대상»이 로봇·제조인데 서비스 갈래가 「개발」뿐이라면 대상 쪽이 이긴다.
        요약문에 「SW 등을 개발」 같은 구절이 스쳤다고 로봇 실증 사업이
        소프트웨어 개발 사업이 되지는 않기 때문이다.
        """
        head = self.kinds[0]
        if head in DEMOTED_BY_SUBJECT and any(k in SUBJECT_KINDS for k in self.kinds):
            return next(k for k in self.kinds if k in SUBJECT_KINDS)
        return head

    @property
    def is_ours(self) -> bool:
        """회사가 주체가 되어 신청·수행할 수 있는 성격인가.

        **가장 구체적인 갈래 하나**로 판정한다. 「아무 갈래나 하나 걸리면 우리 것」으로 보면
        로봇 실증 사업에 「AI」가 들어 있다는 이유로 통과한다 — 실제로 그렇게 새어 나갔다.
        규칙 순서가 곧 구체성 순서이고, 우리 갈래는 목록 앞쪽에 좁게 적혀 있다.

        그리고 그 갈래가 **사업이 스스로 밝힌 목적**에서 나와야 한다.
        요약문 한 구절만으로 우리 일이 되지는 않는다.
        """
        return self.declared and self.primary in OUR_KINDS


#: 기관 이름. 갈래 판정에서 지운다.
#:
#: 「기관명은 넣지 않는다」고 적어 두었지만 요약문·해시태그로 그대로 흘러들었다. 실측:
#:   「전북대학교산학협력단」 → 「대학교산학협력」이 걸려 «대학·공공기관 협력» 사업이 됐다
#:   「한국관광공사」 → 앞 세 글자 「한국관」이 걸려 «사업화·수출·전시»가 됐다
#: 사업의 성격은 무엇을 지원하는가로 정해지지, 누가 주관하는가로 정해지지 않는다.
_ORG_NAME_RE = re.compile(
    r"[가-힣]{2,10}(?:대학교|대학)\s*(?:산학협력단|산학협력본부|기술지주)?"
    r"|[가-힣]{2,10}(?:공사|공단|진흥원|테크노파크|테크노밸리|연구원|재단|협회|조합|센터)"
    r"|한국[가-힣]{2,6}(?:공사|공단|원|회)"
)


def program_text(program, *, include_summary: bool = True) -> str:
    """판정에 쓰는 글. 기관명은 지운다 — 기관 이름 때문에 갈래가 바뀌면 안 된다.

    `include_summary=False` 면 «사업이 스스로 밝힌 목적»만 본다(제목·분류).
    요약문에는 부수 설명이 섞여 있어서, 거기만 걸린 것은 목적이 아닐 때가 많다 —
    실측: 수리조선 지원사업의 요약에 들어 있던 「디지털 역량강화」 한 구절 때문에
    그 사업이 «AI 교육»으로 분류됐다(원문 맥락은 방화벽·백신 도입이었다).
    """
    parts = [program.title or "", program.category or "", program.subcategory or ""]
    if include_summary:
        parts.extend([program.summary or "", " ".join(program.hashtags or [])])
    return _ORG_NAME_RE.sub(" ", " ".join(p for p in parts if p))


def detect(text: str) -> SupportKindResult:
    """글에서 갈래를 찾는다. 못 찾으면 판정 보류다 — 억지로 넣지 않는다."""
    kinds: list[SupportKind] = []
    why: list[str] = []
    words: list[str] = []
    for kind, pattern, reason in _COMPILED:
        match = pattern.search(text)
        if match:
            kinds.append(kind)
            words.append(match.group(0).strip()[:24])
            why.append(f"{SUPPORT_KIND_LABELS[kind]}(「{words[-1]}」)")

    if not kinds:
        return SupportKindResult(kinds=["unclassified"], basis="공고 낱말로는 어떤 사업인지 알 수 없습니다 — 원문을 확인하세요")

    # 가장 구체적인 갈래가 우리 것이 아니면 「직접 관련 낮음」을 함께 표시한다.
    # 갈래 자체를 지우지는 않는다 — 무엇인지는 알려 줘야 담당자가 판단할 수 있다.
    result = SupportKindResult(kinds=kinds, basis=" · ".join(why[:3]), words=tuple(dict.fromkeys(words)))
    if result.primary not in OUR_KINDS:
        return SupportKindResult(kinds=[*kinds, "low_relevance"], basis=result.basis, words=result.words)
    return result


def of_program(program) -> SupportKindResult:
    """사업의 갈래.

    「우리가 주체가 될 수 있는가」는 **사업이 스스로 밝힌 목적**(제목·분류)으로만 판정한다.
    요약문에만 걸린 것은 갈래로는 기록하되 is_ours 로 인정하지 않는다 —
    부수 설명 한 구절 때문에 무관한 사업이 상위로 올라오는 것을 막기 위해서다.
    """
    full = detect(program_text(program))
    if not full.is_ours:
        return full

    declared = detect(program_text(program, include_summary=False))
    if declared.is_ours:
        return full

    # 목적에는 우리 갈래가 없다. 갈래는 그대로 두고 「목적에서 걸린 것이 아니다」를 표시한다.
    return SupportKindResult(
        kinds=full.kinds,
        basis=full.basis + " — 사업 목적(제목·분류)에는 없고 기업마당 요약에만 나옵니다",
        words=full.words,
        declared=False,
    )


# ---------------------------------------------------------------------------
# 관련성 — 「이 사업이 우리와 상관이 있는가」 (0922.md §4-C-2 · ISSUE-085)
# ---------------------------------------------------------------------------
#
# 갈래 판정(`of_program`)은 「무엇을 지원해 주는 사업인가」를 본다. 그런데 기업마당을
# 전부 받으면 1,605건이고, 그중 603건이 「확인 필요」로 남아 마감 순으로 아무거나
# 올라온다 — 「SEOUL FOOD 페어링」·「무기체계 부품국산화」·「모두의 창업」이 담당자의
# 아침 화면을 채웠다(ISSUE-084).
#
# 검수자가 손으로 한 일은 단순했다: **포함 어휘 하나 이상 + 제외 어휘 없음**.
# 1,604건 → 207건 → 16건. 같은 규칙을 코드로 옮긴다.
#
# 이것은 「지우는 규칙」이 아니라 「접는 규칙」이다. 「관련 낮음」도 목록에 남고,
# 담당자가 펼치면 보인다 — 규칙이 틀렸을 때 찾을 수 있어야 한다.
#
# ## 어디를 보느냐가 정밀도를 가른다
#
# 제외 어휘를 **요약문까지** 뒤지면 검수자가 고른 사업이 잘못 접힌다. 실측 4건:
# 「AX실증밸리조성(R&D)」이 요약의 「에너지 AX 분야」 때문에, 「전남국방벤처센터 협약기업」이
# 「전시회 참가 지원」 때문에, 「전남 창업BuS」가 「바이오·에너지 분야 스타트업」 때문에,
# 「K-Global 해외진출」이 「전시회」 때문에 접혔다. 넷 다 검수자가 **골라 둔** 사업이다.
#
# 그래서 축을 나눈다 — **제외 어휘는 사업이 스스로 밝힌 목적(제목·분야·해시태그)에서만**
# 보고, 포함 어휘는 요약·대상까지 본다. `of_program` 이 갈래를 판정할 때 쓰는 원칙과 같다.

#: **회사 분야를 직접 가리키는 낱말.** 이것이 목적에 있으면 제외 어휘가 스쳐도 우리 사업이다.
#:
#: 검수자의 판단을 그대로 옮긴 것이다 — 「AX실증밸리조성(R&D)」은 해시태그에 「에너지」가
#: 붙어 있어도 골랐고(제목이 AX·R&D), 「전남 창업BuS」는 「바이오·에너지」가 붙어 있어도
#: 골랐다(AI 스타트업 대상). 반면 「모두의 창업」은 같은 창업 사업인데 뺐다 — 그 공고에는
#: 우리 분야를 가리키는 낱말이 없다.
CORE_WORDS: tuple[str, ...] = (
    "AI", "인공지능", "생성형", "데이터", "소프트웨어", "SW", "디지털", "DX", "AX",
    "클라우드", "SaaS", "에이전트", "지능정보", "정보통신", "ICT", "스마트공장", "바우처",
)

#: 하나라도 있어야 「관련」이다.
RELEVANT_WORDS: tuple[str, ...] = (
    "AI", "인공지능", "데이터", "소프트웨어", "SW", "디지털", "DX", "AX", "바우처",
    "스마트공장", "클라우드", "플랫폼", "로봇", "비전", "ICT", "에이전트", "생성형",
    "기술개발", "R&D", "사회적기업", "훈련", "공급기업", "콘텐츠", "SaaS", "스타트업",
    "사업화", "정보통신", "지능정보", "테크노파크",
)

#: 사업이 **스스로 밝힌 목적**에 하나라도 있으면 「관련 낮음」이다.
#:
#: 「FOOD·푸드」는 검수자가 뺀 「SEOUL FOOD 페어링 위크」 때문에 더했다 — 그 공고는 제목이
#: 영문이라 「식품」으로는 걸리지 않는다. 「무기체계·부품국산화」도 같은 자리에서 나왔다 —
#: 「기술개발」이라는 낱말은 걸리지만 3인 소프트웨어 팀이 할 수 있는 일이 아니다
#: (검수자의 제외 목록에 있는 반도체·조선·해양·원전과 같은 갈래, 하드웨어 제조다).
EXCLUDED_WORDS: tuple[str, ...] = (
    "융자", "이차보전", "보증", "대출", "소상공인", "전통시장", "농업", "어업", "축산",
    "관광", "음식", "공예", "서점", "이차전지", "바이오", "의료기기", "임상", "섬유",
    "뷰티", "화장품", "식품", "FOOD", "푸드", "반도체", "조선", "해양", "에너지", "원전",
    "건설", "부동산", "게임", "반려동물", "포상", "경진대회", "박람회", "전시회",
    "투자설명회", "시장개척단", "무기체계", "부품국산화",
)


@dataclass(frozen=True)
class Relevance:
    """「관련 있는가」와 그 근거."""

    related: bool
    reason: str
    #: 걸린 포함 어휘 / 제외 어휘. 화면이 그대로 적는다.
    matched: tuple[str, ...] = ()
    excluded: tuple[str, ...] = ()


def _word_present(word: str, text: str) -> bool:
    """낱말이 글에 있는가.

    **영문 낱말은 낱말 경계로 본다.** 그냥 부분 문자열로 찾으면 「AI」가 `chain`·`detail`·
    `Thailand` 안에서 걸린다 — 실측에서 무기체계 부품국산화 공고가 그 때문에 「관련」이
    됐다. 한글은 붙여 쓰는 말이 많아 부분 문자열이 맞다.
    """
    if word.isascii():
        return re.search(rf"\b{re.escape(word)}\b", text, re.IGNORECASE) is not None
    return word in text


def relevance_of_text(text: str, *, declared: str | None = None) -> Relevance:
    """포함 어휘 + 제외 어휘로 관련성을 판정한다. **근거 낱말을 함께 돌려준다.**

    `declared` 는 사업이 **스스로 밝힌 목적**(제목·분야·해시태그)이다. 제외 어휘는 거기서만
    본다 — 요약문 한 구절에 스친 「에너지」·「전시회」 때문에 우리 사업이 접히지 않게.
    주지 않으면 글 전체를 목적으로 본다(글 한 덩어리만 아는 호출자를 위한 기본값).
    """
    subject = declared if declared is not None else text
    excluded = tuple(word for word in EXCLUDED_WORDS if _word_present(word, subject))
    matched = tuple(word for word in RELEVANT_WORDS if _word_present(word, text))
    core = tuple(word for word in CORE_WORDS if _word_present(word, subject))
    if excluded and core:
        # 제외 어휘가 스쳤지만 **목적에 우리 분야가 적혀 있다.** 그때는 우리 사업으로 본다.
        return Relevance(
            related=True,
            reason=f"관련 낱말: {', '.join(core[:3])} (「{', '.join(excluded[:2])}」은 곁 분야)",
            matched=matched,
            excluded=excluded,
        )
    if excluded:
        return Relevance(
            related=False,
            reason=f"우리 사업과 거리가 먼 낱말: {', '.join(excluded[:3])}",
            matched=matched,
            excluded=excluded,
        )
    if not matched:
        return Relevance(related=False, reason="회사와 이어지는 낱말이 없습니다", matched=(), excluded=())
    return Relevance(related=True, reason=f"관련 낱말: {', '.join(matched[:3])}", matched=matched, excluded=())


def relevance_of(program) -> Relevance:
    """사업 하나의 관련성.

    **제외 어휘는 제목·분류·해시태그(목적)에서만**, 포함 어휘는 요약·대상까지 본다.
    """
    declared = " ".join(
        filter(
            None,
            [
                program.title or "",
                program.category or "",
                program.subcategory or "",
                " ".join(program.hashtags or []),
            ],
        )
    )
    text = " ".join(filter(None, [declared, program.summary or "", program.target or ""]))
    return relevance_of_text(text, declared=declared)
