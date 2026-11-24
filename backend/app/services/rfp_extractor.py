"""실제 나라장터 제안요청서(HWP/HWPX/PDF)에서 요구사항을 규칙으로 추출한다.

`rfp_parser.py`는 합성 fixture의 `[수치]` 같은 명시 태그에 의존한다.
실제 제안요청서에는 그런 태그가 없으므로 별도의 규칙 세트를 쓴다.

추출 경로는 두 가지다.

1. **요구사항 정의서 표** — 정보화 사업 제안요청서에서 흔한
   ``요구사항 고유번호 / SFR-001 / 요구사항 명칭 / ... / 정의 / ...`` 블록.
   문서 자체가 요구사항이라고 선언한 항목이므로 최우선으로 잡는다.
2. **의무 문장** — ``하여야 한다 / 해야 함 / 제출한다 / 준수한다 / 할 것 /
   반드시 / 금지`` 등 의무 표현이 있는 문장. 목차·표 셀·페이지 번호 같은
   비문장 줄은 걸러낸다.

원칙 (CLAUDE.md 11, 25)
    - LLM·네트워크를 쓰지 않는다. 같은 입력이면 항상 같은 출력이다.
    - `page`는 원문 DocumentPage.page 그대로, `source_text`는 원문 줄 그대로 둔다.
    - 근거를 아직 연결하지 않았으므로 기본 status는 "unmatched"이고,
      사람이 판단해야 하는 유사·경력·동등 조건은 "check"로 남긴다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas.requirement import (
    Requirement,
    RequirementStatus,
    RequirementType,
)
from app.services import item_classifier
from app.services.document_extractor import ExtractedDocument

# --------------------------------------------------------------------------
# 튜닝 상수 (실제 제안요청서 6건을 보고 정했다)
# --------------------------------------------------------------------------

# 표가 통째로 한 줄로 붙어 나오는 경우가 있어 지나치게 긴 줄은 문장으로 보지 않는다.
MAX_LINE_CHARS = 400
# 표 셀·목차 조각처럼 짧은 줄은 요구사항 문장이 아니다.
MIN_CONTENT_CHARS = 12
# 줄바꿈으로 끊긴 문장을 이어 붙일 때의 최대 줄 수·길이.
MAX_JOIN_LINES = 3
MAX_JOINED_CHARS = 500
# 요구사항 정의서 표는 "정의 + 세부 내용"을 합쳐 담되 지나치게 길어지지 않게 자른다.
MAX_TABLE_CONTENT_CHARS = 1000
# 응답이 무한정 커지지 않도록 한 문서당 상한을 둔다 (기자재 규격서는 의무문이 매우 많다).
#
# 120 → 250 → 400. 추출 규칙을 넓히고 나니 실제 문서 12건 중 4건이 250에 잘렸고,
# 그 뒤에도 1건(324 후보)이 남았다. 잘림은 조용한 재현율 손실이고, 문서 뒤쪽이
# 잘리므로 보통 제출서류·서식 목록 — 놓치면 입찰 자체가 안 되는 것들 — 이 먼저 사라진다.
# 실측: 보관된 12건을 상한 없이 뽑으면 최대 324건 261 KB 다. 400 이면 전부 담기고,
# 상한을 없애지 않는 이유는 규격서류 한 건이 응답을 수 MB 로 만들 수 있어서다.
# 잘렸다는 사실은 truncated 로 계속 화면에 알린다.
MAX_REQUIREMENTS = 400
# 포함관계 중복 판정을 적용할 최소 길이 (정규화 후). 짧은 문장은 우연히 겹친다.
MIN_CONTAINMENT_CHARS = 20
# 포함하는 쪽이 이 배수보다 길면 같은 문장의 변형이 아니라 다른 덩어리(서식 본문 등)가
# 문장을 삼킨 것으로 본다. 실제로 위임장 서식(232자)이 요구사항 1건(21자)을 삼킨 사례가 있었다.
MAX_CONTAINMENT_RATIO = 2.0
TITLE_MAX_CHARS = 40

# --------------------------------------------------------------------------
# 정규식
# --------------------------------------------------------------------------

# 글머리표 / 번호 매기기
_MARKER_RE = re.compile(
    r"^(?:"
    r"[○◦❍ㅇ□■▪▫▸▹‣※·•▶▷◇◆☞∙⦁◈☐√✓＊*․]+"
    r"|[oO](?=\s)"  # 한글 문서에서 글머리표로 자주 쓰이는 영문 o
    # 번호 뒤에 공백이나 줄 끝을 요구한다.
    # 요구하지 않으면 「2.45억원 이상」의 앞 두 글자를 글머리표로 보고 떼어내
    # 「45억원 이상」이라는 **원문에 없는 금액**을 만든다. 그 값이 Auditor 로 흘러가
    # 「RFP는 45억원을 요구하는데 초안은 2.45억원」이라는 없는 불일치를 지적했다.
    # CLAUDE.md 11 「원문에 없는 숫자 생성 금지」에 걸린다.
    r"|\(?\d{1,2}[.)](?=\s|$)"
    r"|\(?[가-힣][.)]"
    r"|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+[.)]?"
    r"|[①-⑳㉠-㉯]"
    r"|[-–—]"
    r")\s*"
)

# 페이지 번호 / 머리말·꼬리말
_PAGE_NUMBER_RE = re.compile(r"^[-–—<(\[]?\s*(?:Page\s*)?\d{1,4}\s*[-–—>)\]]?$", re.IGNORECASE)
# 목차의 점선 리더 ("사업개요 ······ 3")
_TOC_LEADER_RE = re.compile(r"[.·․…‥]{3,}\s*\d{1,4}\s*$")
# 목차 나열 줄 ("Ⅰ. 사업 개요 ... Ⅱ. 과업 내용 ...")
_TOC_MULTI_RE = re.compile(r"(?:[ⅠⅡⅢⅣⅤⅥ]\s*\.?\s*\S+){3,}")
# 서식 목록 ("[서식 1] 입찰 참가 신청서")
_FORM_INDEX_RE = re.compile(r"^[\[<]\s*서식\s*[\d-]+\s*[\]>]")

# 의무(필수) 표현
_MANDATORY_RE = re.compile(
    r"[가-힣]야\s*(?:한다|합니다|하며|하고|하는|함|할|됨|된다)"  # 하여야/해야/되어야/있어야 한다
    r"|하여야|해야\s|해야함|해야$"
    r"|할\s*것"
    r"|반드시|필수(?:적|사항|이며|임|으로)?|의무적"
    r"|준수(?:한다|하여야|해야|할|하여|사항)"
    r"|금지|불가함|불가하다|할\s*수\s*없|해서는\s*안|하여서는\s*안|아니한다|아니\s*된다"
    r"|[가-힣]도록\s*(?:한다|하여야|해야|함|할)"
    r"|(?:제출|납품|이행|보장|구비|확보|배치|유지|지급|부담|제공|작성|운영|수행|설치"
    r"|포함|명시|적용|보고|완료|처리|관리|협의|기재|첨부)(?:한다|하여야|해야|해야함)"
    r"|(?:요망|필요함|요함)$"
)

# 권장·선택 표현.
# "가점"은 "평가점수"·"추가점수" 안에도 들어가므로 낱말 시작에서만 인정한다.
_OPTIONAL_RE = re.compile(r"권장|바람직|가급적|가능하면|선택사항|우대|(?<![가-힣])가점|참고사항")

# 의무 표현은 있지만 **제안서가 대응할 요구사항이 아닌** 문장.
# 실제 제안요청서 5건에서 관찰한 계약 일반조건·권리포기 조항·과업범위 제외 문구다.
# 이런 줄이 요구사항으로 들어가면 Auditor가 "미반영(high)"으로 띄워 진짜 누락을 덮는다.
# 표(요구사항 정의서)에서 온 항목에는 적용하지 않는다 — 문서가 요구사항이라 선언한 것이므로.
_NON_REQUIREMENT_RE = re.compile(
    # 이의제기·소송 포기 조항
    r"이의를?\s*제기할\s*수\s*없"
    r"|이의를?\s*제기하지\s*(?:못|않)"
    r"|일체의?\s*이의"
    # 손해배상 청구 포기 / 계약 자동해지
    r"|손해배상을?\s*청구할\s*수\s*없"
    r"|계약은\s*자동\s*해지"
    # 발주기관 해석·결정 우선 조항
    r"|발주(?:처|기관)의\s*해석에\s*따르"
    r"|발주(?:처|기관)의\s*결정에\s*따"
    r"|통상적\s*관례"
    # 과업 범위에서 제외한다고 못박은 문구
    r"|과업\s*범위에는?\s*포함되지\s*않"
    r"|과업\s*범위에서\s*제외"
    r"|과업\s*범위가?\s*아님"
    # 서식 하단의 단독 확인 문구. 주체·행동·기준이 없어 요구사항이나 평가기준이 아니다.
    # 마침표가 붙은 꼴 · 「위의 사실과 틀림없음을 확인합니다」 꼴도 같다(실측 1692535 · 1704406).
    r"|^위의?\s*사실(?:을\s*증명함|과\s*틀림없음을\s*확인(?:함|합니다))\.?$"
)

# --------------------------------------------------------------------------
# 과업(제안요청) 절 — 개조식 요구사항
# --------------------------------------------------------------------------
# 교육·운영 용역 제안요청서는 과업 내용을 "~ 운영", "~ 기획"처럼 **명사형 개조식**으로만
# 적고 "하여야 한다"를 쓰지 않는 경우가 많다 (실측: 가천대 생성형 AI 교육 용역).
# 의무 표현만 찾으면 계약조건·자격요건만 남고 정작 과업이 통째로 빠진다.
# 그래서 과업 절 안에서는 종결어미가 없어도 개조식 항목을 요구사항으로 인정한다.
_TASK_SECTION_RE = re.compile(
    r"제안\s*요청\s*내용|주요\s*사업\s*내용|상세\s*요구사항|세부\s*수행\s*내용|세부수행"
    r"|과업\s*내용|과업\s*범위|수행\s*내용|사업\s*내용|산출물"
)
# 배경·목표·기대효과는 같은 개조식이어도 요구사항이 아니다. 여기서는 다시 끈다.
_NON_TASK_SECTION_RE = re.compile(
    r"추진\s*배경|필요성|과업\s*목표|사업\s*목표|기대\s*효과|과업\s*개요|사업\s*개요"
    r"|목\s*차|입찰\s*참가|참가\s*자격|평가\s*항목|배점|선정\s*방법|주의사항"
)

# --------------------------------------------------------------------------
# 조건 절 — 과업 절과 같은 이유로, 여기서도 개조식 항목이 진짜 요구사항이다.
#
# 실측(가천대 생성형 AI 교육 용역, gold 83건): 놓친 59건 가운데 25건이
# 「~한 자」·「~ 제시」·「매수: 20page 내외」처럼 의무 표현이 없는 개조식 조건이었다.
# 이런 문장은 과업 절 밖(참가자격 각 호·제안서 작성지침·평가 배점표·산출물·서식)에 있어서
# 과업 절 구제 경로가 닫혀 있었고, 전역 의무 표현 규칙만으로는 걸리지 않았다.
#
# 전역 `_MANDATORY_RE` 를 넓히지 않는 이유:
#   그러면 「설명문은 추출하지 않는다」는 기존 계약이 무너진다. 절을 알고 있을 때만 넓힌다.
# --------------------------------------------------------------------------
_CONDITION_SECTION_RE = re.compile(
    r"입찰\s*참가|참가\s*자격|자격\s*요건|자격\s*조건|제안서\s*작성|작성\s*지침|제안서\s*목차"
    r"|평가\s*항목|평가\s*기준|배점|심사\s*기준|산출물|제출\s*서류|구비\s*서류|제출\s*방법"
    # 과업지시서 계열의 절 이름. 실측(마운트 DB 구축 과업지시서)에서 p.2 의 조건이
    # 통째로 빠졌는데, 절 이름이 「검수」·「자격조건」·「계약해지」라 위 목록에 없었다.
    r"|검수|결과물|책임\s*및\s*의무|계약\s*해지|계약\s*조건"
)

#: 조건 절 가운데 «평가·배점» 절. 여기서만 「~성·~도·~력」 같은 명사화 어미를 인정한다.
#:
#: 실측(가천대 제안요청서, gold 83건): 놓친 항목의 절반이 배점표의 평가 항목이었다 —
#: 「제안내용의 적절성·전문성·차별성」·「과업 및 발주기관에 대한 이해도」·「전주기적
#: 지원방안의 적정성」. 평가 항목은 «성질을 명사로 세운 말»로 적히는 것이 규칙에 가깝다.
#: CLAUDE.md 2장 4번이 요구사항 정리 대상에 「평가항목」을 명시하므로 빼면 안 되는 항목이다.
#:
#: 절을 가리지 않고 이 어미를 허용하면 문서 이력표의 「…공개 가능」 같은 줄까지 딸려 온다
#: (합성 RFP 에서 실제로 그랬다). 그래서 평가 절 안으로 한정한다.
_EVALUATION_SECTION_RE = re.compile(
    r"평가\s*항목|평가\s*기준|배점|심사\s*기준|정량\s*평가|정성\s*평가|평가\s*방법"
)
#: 평가 절 항목의 명사화 어미. 앞에 한 글자라도 있어야 한다(「성」 한 글자짜리 셀 제외).
_QUALITY_TAIL_RE = re.compile(r"(?:[가-힣]성|[가-힣]도|[가-힣]력)$")

# --------------------------------------------------------------------------
# 평가표의 칸 (0919.md §4-B-5)
# --------------------------------------------------------------------------
#
# 정답셋 미탐의 상당수가 배점표·서식 목록이다. 어미가 없는 명사구라 어떤 어미 규칙에도
# 걸리지 않는다 — 「최근 3년 이내 유사 사업 수행 실적」·「참여인력의 수행 역량」.
#
# 표가 어떻게 내려오는지는 원본 형식마다 다르다. HWP 는 칸마다 줄을 바꿔 주고, PDF 는 한 줄에
# 탭이나 여러 칸 공백으로 붙여 내려준다. 둘을 같은 경로로 다루려면 먼저 칸으로 나눠야 한다.
#
# **평가 절 안에서만 켠다.** 절을 가리지 않고 명사구를 인정하면 문서 어디에나 있는 명사구가
# 전부 요구사항이 되어 정밀도가 무너진다 — 이 파일이 이미 같은 이유로 `_QUALITY_TAIL_RE` 를
# 평가 절로 한정하고 있다.

#: 표의 칸 구분자. 탭 · 두 칸 이상의 공백 · 세로줄.
_TABLE_CELL_SPLIT_RE = re.compile(r"\t+| {2,}|\s*[|｜]\s*")

#: 평가표에서 요구사항이 아닌 칸 — 머리글·합계.
_EVALUATION_HEADER_RE = re.compile(
    r"^(?:평가\s*항목|평가\s*요소|평가\s*내용|배점|구분|총\s*계|소\s*계|합\s*계|비고|점수|가중치|순번|연번)$"
)

#: 평가표 칸의 최소 길이와 한글 수. 「배점」·「5건 이상」 같은 칸을 걸러낸다.
MIN_EVALUATION_CELL_CHARS = 6
MIN_EVALUATION_CELL_HANGUL = 4


#: 조건 절 개조식 항목의 최소 길이. 표의 분류 셀·머리글을 걸러낸다.
MIN_CONDITION_ITEM_CHARS = 8
#: 그중 한글이 이만큼은 있어야 한다 (숫자·기호만 있는 배점 셀 제외).
MIN_CONDITION_HANGUL = 4

#: 조건 절 항목의 끝맺음. 명사형·「~한 자」·「~ 인정」까지 인정한다.
_CONDITION_TAIL_RE = re.compile(
    r"(?:운영|기획|제공|지원|관리|진행|구성|개발|제작|실시|수행|구축|점검|평가|발표|작성"
    r"|납품|등록|모집|선발|인증|제출|배포|설계|분석|보고|교육|보유|가능|필수|제시|첨부"
    r"|인정|포함|명시|준수|확보|기준|방식|방법|이상|이내|이하|미만|초과|자|것|함|음|임"
    # 「업체」만 더했다 — 「…입찰등록을 필한 업체」(1순위 조건)가 이 어미 때문에 빠졌다.
    # 「실적·증명서·서류」도 재 봤지만 새로 잡은 4줄 중 2줄만 gold 라(자체 정확도 0.5)
    # 정밀도를 0.800 아래로 끌어내렸다. 넣지 않는다.
    # 검수 항목·제출 목록의 어미. 「⑤ DB 양식 적합성」·「② 시험 대상품 확보 여부」처럼
    # 명사로 끝나는 점검 항목이 조건 절에 늘어선다 (과업지시서에서 흔하다).
    r"|업체|여부|결과|적합성|보고서|도면|계획서"
    # 제안서 작성 지시의 어미. 「서식 1,2호 양식을 활용하여 … 기술」·「제안 내용의 특징 및
    # 장점을 요약하여 기술」처럼 «무엇을 적으라»는 지시가 제안요청서에는 통째로 들어 있다.
    r"|기술"
    # 열거로 끝나는 제출물·산출물 목록. 「등」 하나만 넣으면 본문 서술까지 딸려 와 정밀도가
    # 떨어졌다(실측 P 0.727 → 0.709). 목록임이 분명한 앞말이 붙은 것만 인정한다.
    r"|명단\s*등|서류\s*등|자료\s*등"
    # 계약해지 사유는 「~하였을 때」·「~어려울 때」로 끝난다. 조건 절에서만 인정하므로
    # 본문의 평범한 「~할 때」가 딸려 오지는 않는다.
    r"|때)$"
)
# 과업 항목의 명사형 끝맺음. 이 말로 끝나야 과업 항목으로 본다 (배경 서술문 제외).
_TASK_TAIL_RE = re.compile(
    r"(?:운영|기획|제공|지원|관리|배정|발급|진행|구성|개발|제작|실시|수행|편성|구축"
    r"|점검|평가|발표|작성|납품|등록|모집|선발|인증|제출|배포|설계|분석|보고|교육"
    # 실측으로 더한 어미. 「활용·구현」도 후보를 늘리지만 새로 잡은 4줄 중 2줄만
    # gold 라 자체 정확도가 0.5 였다 — 정밀도를 깎아서 넣지 않는다.
    # 「정리·제안」은 새로 잡은 2줄이 모두 gold 였다.
    r"|정리|제안)$"
)
# 절 판정에 쓸 제목 줄의 최대 길이.
SECTION_LINE_MAX_CHARS = 30
# 과업 절 개조식 항목의 최소 길이. 표의 '구분' 열 값("교육과정 기획")을 걸러낸다.
MIN_TASK_ITEM_CHARS = 10

# 사람이 판단해야 하는 모호한 자격·실적 표현
_AMBIGUOUS_RE = re.compile(r"유사|경력|동등|상당|준하는|이에\s*준|해당하는\s*자")
# 모호 판정을 적용할 자격·실적 맥락
_QUALIFICATION_CONTEXT_RE = re.compile(r"자격|실적|경력|면허|등록|인력|업종|기술자|참가")

# 요구사항 정의서 표 라벨
_REQ_TABLE_START_RE = re.compile(r"^요구사항\s*고유\s*번호$")
_REQ_CODE_RE = re.compile(r"^[A-Z]{2,4}\s*-\s*\d{2,4}$")
_REQ_TABLE_LABELS = {
    "요구사항명칭": "name",
    "요구사항분류": "kind",
    "요구사항상세설명": "detail",
    "정의": "definition",
    "세부내용": "detail_items",
}

# 문장이 끝난 것으로 볼 종결 표현 (끊긴 줄 이어붙이기 판단용)
_SENTENCE_END_RE = re.compile(
    r"(?:[.。!?:;]|다|함|음|임|것|요망|바람|가능|불가|없음|있음|참조|해당|이상|이하|이내|까지)$"
)

# --------------------------------------------------------------------------
# 카테고리
# --------------------------------------------------------------------------

# 앞에 있는 항목이 우선한다 (예: "제안서 평가"는 평가로 본다).
_CATEGORY_RULES: list[tuple[re.Pattern[str], str]] = [
    # 참석 여부가 입찰 가능성을 가르는 현장설명은 단순 제출서류가 아니라 참가자격이다.
    (re.compile(r"현장\s*설명|입찰\s*설명회|제안\s*요청\s*설명회"), "입찰참가자격"),
    (re.compile(r"참가\s*자격|입찰\s*참가|자격\s*요건|응찰\s*자격"), "입찰참가자격"),
    (re.compile(r"평가|배점|심사|낙찰자|채점"), "평가"),
    (re.compile(r"제출\s*서류|구비\s*서류|제안서\s*작성|제안서\s*제출|서식|제안설명회"), "제출서류"),
    # 보안 절 다음에 이어지는 계약 해지·정산 조항을 보안 요구사항으로 오인하지 않는다.
    (re.compile(r"계약(?:을|의)?\s*해지|계약\s*해제|정산하여야"), "기타"),
    (re.compile(r"보안|비밀|개인정보|보안각서"), "보안"),
    (re.compile(r"인력|조직|투입|참여\s*인력|기술자"), "인력"),
    (re.compile(r"일정|기간|추진\s*계획|추진일정"), "일정"),
    (re.compile(r"과업|요구사항|제안\s*요청|사업\s*내용|규격|과업지침|납품|하자"), "과업내용"),
    (re.compile(r"개요|목적|배경|기대효과|추진\s*방향"), "사업개요"),
]

# 요구사항 정의서 표의 분류값 -> 카테고리
_TABLE_KIND_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"보안"), "보안"),
    (re.compile(r"품질"), "품질"),
    (re.compile(r"제약"), "제약사항"),
    (re.compile(r"프로젝트\s*관리|관리"), "프로젝트관리"),
    (re.compile(r"프로젝트\s*지원|지원"), "프로젝트지원"),
    (re.compile(r"인터페이스|데이터|시스템|기능|성능"), "과업내용"),
]

DEFAULT_CATEGORY = "기타"

# 대분류 제목 (Ⅰ. / 1. / 제1장). 여기서 카테고리를 못 찾으면 이전 절의 값을 물려주지 않고 초기화한다.
_MAJOR_HEADING_RE = re.compile(r"^(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+|\d{1,2}|제?\s*\d{1,2}\s*장)[.)]?\s*\S")
# 별지·서식 묶음은 제출서류로 본다.
_FORM_HEADING_RE = re.compile(r"^[【\[<(]?\s*(?:별지|서식|붙임)")


def _category_of(text: str, rules: list[tuple[re.Pattern[str], str]]) -> str | None:
    for pattern, category in rules:
        if pattern.search(text):
            return category
    return None


# --------------------------------------------------------------------------
# 줄 단위 전처리
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Line:
    page: int
    raw: str

    @property
    def body(self) -> str:
        """글머리표·번호를 떼어낸 본문."""
        return _MARKER_RE.sub("", self.raw).strip()


def _sanitize(text: str) -> str:
    """HWP 본문에서 넘어오는 짝 없는 서로게이트·제어문자를 제거한다.

    document_extractor는 HWP 특수문자를 그대로 chr()로 옮기기 때문에 JSON 직렬화가
    불가능한 코드포인트가 섞일 수 있다. 원문 글자는 바꾸지 않고 그것만 걷어낸다.
    """
    cleaned = text.encode("utf-8", "ignore").decode("utf-8", "ignore")
    return "".join(ch for ch in cleaned if ch >= " " or ch == "\t")


def _is_noise(line: str) -> bool:
    """목차·페이지번호·표 셀 조각 등 요구사항 문장이 될 수 없는 줄."""
    if not line:
        return True
    if len(line) > MAX_LINE_CHARS:
        return True
    if _PAGE_NUMBER_RE.match(line):
        return True
    if _TOC_LEADER_RE.search(line):
        return True
    if _TOC_MULTI_RE.search(line):
        return True
    if _FORM_INDEX_RE.match(line):
        return True
    # 한글이 거의 없는 줄(수치만 있는 표 셀, 깨진 글리프)은 버린다.
    hangul = sum(1 for ch in line if "가" <= ch <= "힣")
    return hangul < 3


def _iter_lines(doc: ExtractedDocument) -> list[_Line]:
    lines: list[_Line] = []
    for page in doc.pages:
        for raw in page.text.splitlines():
            text = _sanitize(raw).strip()
            if not text:
                continue
            lines.append(_Line(page=page.page, raw=text))
    return lines


# --------------------------------------------------------------------------
# 문장 판정
# --------------------------------------------------------------------------


#: 절 제목에 쓰이는 번호 표기. **글머리표(○ ◦ - •)는 여기 없다.**
#:
#: 예전에는 글머리표만 있어도 제목으로 보고 버렸다. 그래서 「○ 사업 착수계(착수 보고서 등)」,
#: 「- 2주차: RAG 심화 기술의 이해 및 활용」 같은 **진짜 요구사항 24건**이 제목으로 오인돼
#: 통째로 사라졌다(실측). 절 제목은 번호를 쓰고, 항목은 글머리표를 쓴다.
_SECTION_NUMBER_RE = re.compile(
    r"^(?:"
    r"[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+[.)]?"
    r"|\(?\d{1,2}[.)]"
    r"|\(?[가-힣][.)]"          # 가. 나. 다.
    r"|제?\s*\d{1,2}\s*장"
    r")\s*\S"
)


def _is_heading(line: _Line) -> bool:
    """절 제목 줄인지. 제목은 요구사항이 아니고 카테고리 단서로만 쓴다.

    **글머리표가 붙은 짧은 줄은 제목이 아니다.** 그건 항목이다.
    이 구분이 없으면 산출물 목록·주차별 커리큘럼이 전부 제목으로 오인돼 사라진다.
    """
    if len(line.raw) > 40:
        return False
    body = line.body
    if not body or len(body) < 2:
        return False
    if _MANDATORY_RE.search(body) or _OPTIONAL_RE.search(body):
        return False
    if not _SECTION_NUMBER_RE.match(line.raw.strip()):
        return False
    # 번호가 붙은 짧은 줄이고 아는 카테고리면 제목이다.
    # (「가. 보안 및 책임」은 '책임'의 '임' 때문에 종결어미 검사에 걸려 제목이 되지 못했고,
    #  그 바람에 앞 절의 「일정」 카테고리가 보안·계약·하자 블록까지 그대로 흘러들었다.)
    if _category_of(body, _CATEGORY_RULES) is not None:
        return True
    return not body.endswith((".", "다", "함", "음", "임"))


def _section_mode(line: _Line) -> str | None:
    """제목 줄이 어느 절을 여는지.

    "task"      — 과업 절. 개조식 과업 항목을 인정한다.
    "condition" — 자격·작성지침·평가·산출물·제출서류 절. 개조식 조건을 인정한다.
    "other"     — 배경·목표 등. 개조식은 요구사항이 아니다.
    """
    if len(line.raw) > SECTION_LINE_MAX_CHARS:
        return None
    body = line.body
    if not body:
        return None
    # 조건 절을 «먼저» 본다. 「입찰 참가자격」·「평가 항목」은 _NON_TASK_SECTION_RE 에도
    # 걸리는데, 그건 「과업 절이 아니다」라는 뜻이지 「요구사항이 없다」는 뜻이 아니었다.
    if _CONDITION_SECTION_RE.search(body):
        return "condition"
    # 배경·목표 절이 그다음이다 ("과업 개요"가 "과업 내용"보다 우선 판정되게).
    if _NON_TASK_SECTION_RE.search(body):
        # 번호가 붙어야 «제목»이다. 번호 없이 이 낱말만 있는 짧은 줄은 표의 칸 이름이거나
        # 본문 중간의 언급이지 절이 바뀌는 자리가 아니다. 그것으로 절을 닫아 버리면 뒤에
        # 이어지는 진짜 항목들이 통째로 「절 밖」이 되어 사라진다 (실측: 가천대 제안요청서에서
        # 이 한 가지로 Recall 0.566 → 0.675).
        return "other" if _SECTION_NUMBER_RE.match(line.raw.strip()) else None
    if _TASK_SECTION_RE.search(body):
        return "task"
    return None


def _hangul_count(text: str) -> int:
    return sum(1 for ch in text if "가" <= ch <= "힣")


#: 끝에 붙은 괄호 주석. 전각 괄호도 본다 (HWP 문서에 흔하다).
_TRAILING_PAREN_RE = re.compile(r"\s*[(（][^()（）]*[)）]\s*$")
#: 끝의 구두점·닫는 기호.
_TRAILING_PUNCT_RE = re.compile(r"[\s.,;:)\]】」』·]+$")


def _tail_candidates(body: str) -> list[str]:
    """어미를 볼 후보 문자열. 괄호 주석을 «떼기 전»과 «뗀 뒤»를 모두 본다.

    구두점 정리를 먼저 하면 닫는 괄호가 함께 지워져 「괄호로 끝난다」는 사실 자체를 잃는다.
    실제로 그래서 「◦ 매수: 20page 내외로 작성(별지 제외)」이 「작성」으로 복원되지 못하고
    빠졌다. 그래서 원문에서 곧바로 괄호를 뗀 갈래를 따로 만든다.

    괄호 주석은 어미가 아니라 «보충 설명»이다 — 「… 학습 지원(메인 교육과정과 병행 운영)」의
    끝맺음은 「운영」이 아니라 「지원」이다.
    """
    out: list[str] = []
    for text in (body, _TRAILING_PAREN_RE.sub("", body)):
        cleaned = _TRAILING_PUNCT_RE.sub("", text).rstrip(" .,;:")
        if cleaned and cleaned not in out:
            out.append(cleaned)
    return out


def _evaluation_cells(line: _Line) -> list[str]:
    """평가·배점 절의 표 한 줄에서 «요구사항이 되는 칸»만 꺼낸다.

    띄어쓰기를 요구하는 것이 이 판정의 핵심이다. 평가표에는 두 종류의 칸이 섞여 있다 —
    분류 칸(「사업수행역량」·「경영상태」)과 평가요소 칸(「과업 및 발주기관에 대한 이해도」).
    앞엣것은 한 낱말로 붙여 쓰고 뒤엣것은 구(句)라 띄어쓰기가 있다. 분류 칸은 요구사항이
    아니라 요구사항을 묶는 이름이므로 표에 올리면 안 된다.
    """
    cells: list[str] = []
    for raw in _TABLE_CELL_SPLIT_RE.split(line.body):
        cell = re.sub(r"\s+", " ", raw).strip(" .,;:·")
        if len(cell) < MIN_EVALUATION_CELL_CHARS:
            continue
        if _hangul_count(cell) < MIN_EVALUATION_CELL_HANGUL:
            continue
        if _EVALUATION_HEADER_RE.match(cell):
            continue
        if _NON_REQUIREMENT_RE.search(cell):
            continue
        if " " not in cell:
            continue
        cells.append(cell)
    return cells


def _is_condition_item(line: _Line, *, evaluation: bool = False) -> bool:
    """조건 절 안의 개조식 항목인지.

    끝의 괄호·구두점을 떼고 어미를 본다 — 「…(단, 2.5천만원 이상의 건만 인정)」처럼
    괄호로 끝나는 조건이 많기 때문이다.

    `evaluation=True` 는 지금이 평가·배점 절이라는 뜻이다. 그 안에서만 「~성·~도·~력」
    같은 명사화 어미를 함께 인정한다 (`_EVALUATION_SECTION_RE` 주석 참고).
    """
    body = line.body
    if len(body) < MIN_CONDITION_ITEM_CHARS:
        return False
    if _hangul_count(body) < MIN_CONDITION_HANGUL:
        return False
    if _NON_REQUIREMENT_RE.search(body):
        return False
    for tail in _tail_candidates(body):
        if _CONDITION_TAIL_RE.search(tail):
            return True
        if evaluation and _QUALITY_TAIL_RE.search(tail):
            return True
    return False


#: 과업 절 평서형 문장의 최소 길이. 표 셀·머리글을 걸러낸다.
MIN_TASK_SENTENCE_CHARS = 14


def _is_task_sentence(line: _Line) -> bool:
    """과업 절 안의 평서형 과업 문장인지 — 「~한다」·「~된다」로 끝나는 것.

    배경·목적 서술도 같은 어미를 쓰므로, 그런 절에서는 애초에 이 함수를 부르지 않는다
    (`_NON_TASK_SECTION_RE` 가 과업 절을 닫는다).
    """
    body = line.body
    if len(body) < MIN_TASK_SENTENCE_CHARS:
        return False
    if _NON_REQUIREMENT_RE.search(body):
        return False
    tail = body.rstrip(" .")
    return bool(_TASK_SENTENCE_TAIL_RE.search(tail))


#: 과업 문장의 평서형 끝맺음.
#: 「~있음」·「~함」 같은 상태 서술은 넣지 않는다 — 배경 설명이 대부분이다.
_TASK_SENTENCE_TAIL_RE = re.compile(r"(?:한다|된다|짓는다|세운다|만든다|삼는다)$")


def _is_task_item(line: _Line) -> bool:
    """과업 절 안의 개조식·표 항목인지.

    의무 표현이 없어도 "~ 운영", "~ 배정"처럼 명사형으로 끝나는 과업 항목을 인정한다.
    표의 '구분' 열 값처럼 짧은 조각은 길이로 걸러낸다.
    """
    body = line.body
    if len(body) < MIN_TASK_ITEM_CHARS:
        return False
    if _NON_REQUIREMENT_RE.search(body):
        return False
    return any(_TASK_TAIL_RE.search(tail) for tail in _tail_candidates(body))


def _requirement_type(text: str) -> RequirementType | None:
    """의무면 mandatory, 권장이면 optional, 요구사항이 아니면 None."""
    mandatory = bool(_MANDATORY_RE.search(text))
    optional = bool(_OPTIONAL_RE.search(text))
    if optional and not mandatory:
        return "optional"
    if mandatory:
        return "mandatory"
    return None


def _status_for(category: str, text: str) -> RequirementStatus:
    """근거 매핑 전이므로 기본 unmatched. 모호한 자격·실적 조건만 check."""
    if not _AMBIGUOUS_RE.search(text):
        return "unmatched"
    if category in ("입찰참가자격", "인력") or _QUALIFICATION_CONTEXT_RE.search(text):
        return "check"
    return "unmatched"


def _title_of(content: str) -> str:
    """본문 앞부분을 제목으로 쓴다. 원문에 없는 말은 만들지 않는다."""
    text = content.strip()
    if len(text) <= TITLE_MAX_CHARS:
        return text
    cut = text[:TITLE_MAX_CHARS]
    space = cut.rfind(" ")
    if space >= TITLE_MAX_CHARS // 2:
        cut = cut[:space]
    return cut.rstrip(" ,·") + "…"


def _normalize(text: str) -> str:
    """중복 판정용 정규화 (공백·구두점 제거)."""
    return re.sub(r"[\s.,·:;()\[\]<>\"'“”‘’]", "", text)


def _drop_contained(drafts: list[_Draft]) -> list[_Draft]:
    """다른 요구사항 안에 통째로 들어가는 항목을 버린다.

    같은 문장이 글머리표만 바꿔 두 번 실리거나, 한 줄이 이어붙기 여부에 따라
    긴 판·짧은 판으로 두 번 잡히는 경우가 실제 제안요청서에 있다
    (예: "천재지변으로 ... 청구할 수 없음"이 뒤 문장을 포함한 채 한 번 더).
    같은 내용을 두 건으로 세면 Coverage 분모가 부풀고 Auditor가 같은 지적을 두 번 한다.
    짧은 쪽을 버리고 정보가 더 많은 긴 쪽을 남긴다.
    """
    keys = [_normalize(d.content) for d in drafts]
    kept: list[_Draft] = []
    for i, (draft, key) in enumerate(zip(drafts, keys, strict=True)):
        # 짧은 문장은 우연히 다른 문장에 포함될 수 있어 포함관계 판정에서 뺀다.
        # 포함하는 쪽이 지나치게 길면 중복이 아니라 서식 본문이 문장을 삼킨 것이다.
        if len(key) >= MIN_CONTAINMENT_CHARS and any(
            i != j
            and key != other
            and key in other
            and len(other) <= len(key) * MAX_CONTAINMENT_RATIO
            for j, other in enumerate(keys)
        ):
            continue
        kept.append(draft)
    return kept


# --------------------------------------------------------------------------
# 1) 요구사항 정의서 표 블록
# --------------------------------------------------------------------------


@dataclass
class _Draft:
    page: int
    category: str
    requirement_type: RequirementType
    title: str
    content: str
    source_lines: list[str]
    status: RequirementStatus


def _label_of(text: str) -> str | None:
    return _REQ_TABLE_LABELS.get(re.sub(r"\s+", "", text))


def _parse_requirement_table(lines: list[_Line], start: int) -> tuple[_Draft | None, int]:
    """`요구사항 고유번호` 블록 1건을 읽는다. (draft, 다음 인덱스)를 반환."""
    index = start + 1
    if index >= len(lines):
        return None, start + 1

    code = re.sub(r"\s+", "", lines[index].raw)
    if not _REQ_CODE_RE.match(code):
        return None, start + 1

    source: list[str] = [lines[start].raw, lines[index].raw]
    fields: dict[str, list[str]] = {}
    current: str | None = None
    index += 1

    while index < len(lines):
        line = lines[index]
        if _REQ_TABLE_START_RE.match(re.sub(r"\s+", " ", line.raw).strip()):
            break
        label = _label_of(line.raw)
        if label is not None:
            current = label
            source.append(line.raw)
            index += 1
            continue
        if current is None:
            break
        fields.setdefault(current, []).append(line.raw)
        source.append(line.raw)
        index += 1

    name = " ".join(fields.get("name", [])).strip()
    definition = " ".join(fields.get("definition", [])).strip()
    # "요구사항 상세설명"과 "세부 내용"은 라벨만 다를 뿐 둘 다 요구사항 본문이다.
    detail_lines = [d.strip() for d in [*fields.get("detail", []), *fields.get("detail_items", [])]]
    kind = " ".join(fields.get("kind", [])).strip()

    head = definition or name
    if not head or len(head) < 2:
        return None, index

    # 정의·명칭만으로는 "하자보수", "(공통) 로그인"처럼 제목 수준이라 요구사항 구실을
    # 못 한다. 상세설명/세부내용을 이어 붙여야 대조할 본문이 생긴다.
    body_parts = [
        stripped
        for d in detail_lines
        if (stripped := _MARKER_RE.sub("", d).strip())
    ]
    content = f"{head} / {' / '.join(body_parts)}" if body_parts else head
    content = re.sub(r"\s+", " ", content).strip()[:MAX_TABLE_CONTENT_CHARS]

    category = _category_of(kind or name, _TABLE_KIND_RULES) or "과업내용"
    title = f"{code} {name}".strip() if name else code
    body_for_status = " ".join([name, definition, *detail_lines])

    return (
        _Draft(
            page=lines[start].page,
            category=category,
            # 요구사항 정의서에 실린 항목은 문서가 요구사항으로 선언한 것이므로 필수로 본다.
            requirement_type="mandatory",
            title=_title_of(title),
            content=content,
            source_lines=source,
            status=_status_for(category, body_for_status),
        ),
        index,
    )


# --------------------------------------------------------------------------
# 2) 의무 문장
# --------------------------------------------------------------------------


#: 이어 붙이기를 시작할 수 있는 최소 길이.
#:
#: HWP 표는 셀 하나가 문단 하나로 평탄화되어 나온다. 그래서 「교육과정 운영」 같은
#: 짧은 분류 셀이 종결어미가 없다는 이유로 뒤 셀 두 개를 끌어와 한 덩어리로 붙였고,
#: 합쳐진 문장에 의무 표현이 없어 통째로 탈락했다 — 실측으로 gold 10건이 이렇게 사라졌다.
#: 진짜 줄바꿈으로 끊긴 문장은 대개 이보다 길다.
MIN_JOIN_HEAD_CHARS = 30

#: 이 어미로 끝나면 문장이 이어진다는 신호다(짧아도 이어 붙인다).
_CONTINUING_TAIL_RE = re.compile(r"(?:하여|하고|되어|되며|이며|으로|로서|및|또는|따라|위해|통해|경우)\s*$")


def _join_wrapped(lines: list[_Line], start: int) -> tuple[list[str], int]:
    """줄바꿈으로 끊긴 문장을 이어 붙인다. (원문 줄 목록, 다음 인덱스).

    표 셀을 잘못 삼키지 않도록, **앞줄이 충분히 길거나 연결형 어미로 끝날 때만** 이어 붙인다.
    """
    collected = [lines[start].raw]
    head = lines[start].raw.strip()
    joinable = len(head) >= MIN_JOIN_HEAD_CHARS or bool(_CONTINUING_TAIL_RE.search(head))
    index = start + 1
    while (
        joinable
        and len(collected) < MAX_JOIN_LINES
        and index < len(lines)
        and lines[index].page - lines[start].page <= 1
        and not _SENTENCE_END_RE.search(collected[-1])
        and not _MARKER_RE.match(lines[index].raw)
        and not _is_heading(lines[index])
        # 잡음 줄(쪽번호·목차 점선·표 셀 조각)은 이어 붙이지 않는다. 붙이면 원문에 없는
        # 문장이 만들어진다 — 실측으로 '6', '경영', 'AXR-010' 이 요구사항 뒤에 붙었다.
        and not _is_noise(lines[index].raw)
        and len(" ".join(collected)) + len(lines[index].raw) <= MAX_JOINED_CHARS
    ):
        collected.append(lines[index].raw)
        index += 1
    return collected, index


#: 입찰 제안서를 평가하는 조항의 낱말. 과업 절로 잘못 열린 자리에 끼어든 「제4조 (제안서 평가)」 ·
#: 「협상적격자」 조항은 평가 그대로 둔다(실측 1704406 — 끄면 앞 절의 「제출서류」로 새어 6건이 제출 항목이 됐다).
_BID_EVALUATION_RE = re.compile(
    r"제안서\s*평가|평가\s*점수|배점|낙찰|협상|기술\s*능력|가격\s*평가|평가\s*위원|심사\s*위원"
)


def _task_line_category(content: str) -> str | None:
    """과업 절 줄의 분류. 교육생 · 과제 「평가」는 버리고 절 분류(과업내용)를 따르게 한다.

    과업 절의 「평가 체계 운영」 · 「수강생 단계별 교육 평가 진행」은 교육생 · 과제를 평가하는
    «할 일»이다 — 입찰 제안서 평가기준이 아니다. 줄 낱말 규칙은 「평가」를 과업보다 먼저 보므로
    여기서 끄지 않으면 참고 · 평가로 빠져 필수 셈에서 사라진다.
    """
    found = _category_of(content, _CATEGORY_RULES)
    if found == "평가" and not _BID_EVALUATION_RE.search(content):
        return None
    return found


#: 표의 「제출 시기」 칸만 따로 떨어진 줄 — 「만료일로부터 14일 이내」.
_TIMING_ONLY_RE = re.compile(r"^\S*\s*\d+\s*(?:일|주|개월)\s*(?:이내|이전|전|후|까지)$")
#: 그 칸이 속한 행의 첫 칸(「○ 최종산출물(종합보고서 등)」)을 알아보는 글머리표.
_ROW_HEAD_MARKERS = ("○", "◦", "-", "•", "ㅇ", "□")
#: 행의 첫 칸을 찾아 거슬러 올라가는 줄 수.
ROW_HEAD_LOOKBACK = 3


def _timing_row(lines: list[_Line], index: int) -> list[str] | None:
    """시기 칸 조각이 속한 행의 원문 줄들(첫 칸 ~ 이 줄). 첫 칸을 못 찾으면 None.

    HWP 산출물 표는 칸마다 한 줄씩 내려온다(「결과보고 / ○ 최종산출물(종합보고서 등) / 계약기간 /
    만료일로부터 14일 이내」). 시기 칸만 항목이 되면 «무엇을» 내는지 빠진 조각이 요구사항이 된다.
    """
    line = lines[index]
    for j in range(index - 1, max(index - 1 - ROW_HEAD_LOOKBACK, -1), -1):
        if lines[j].page == line.page and lines[j].raw.startswith(_ROW_HEAD_MARKERS):
            return [item.raw for item in lines[j : index + 1]]
    return None


def _after_bare_number(lines: list[_Line], index: int) -> bool:
    """HWP 표 제목 칸은 번호(「2」)를 따로 줄로 내려준다 — 바로 뒤 짧은 줄은 번호 붙은 제목이다."""
    if index <= 0:
        return False
    prev, line = lines[index - 1], lines[index]
    return (
        prev.page == line.page
        and re.fullmatch(r"\d{1,2}", prev.raw.strip()) is not None
        and len(line.raw) <= SECTION_LINE_MAX_CHARS
        and not _MARKER_RE.match(line.raw)
    )


def _build_drafts(lines: list[_Line]) -> list[_Draft]:
    drafts: list[_Draft] = []
    category = DEFAULT_CATEGORY
    # 과업(제안요청) 절 안인지. 이 안에서는 개조식 항목도 요구사항으로 인정한다.
    in_task_section = False
    # 조건 절(자격·작성지침·평가·산출물·제출서류) 안인지.
    in_condition_section = False
    # 그중에서도 «평가·배점» 절인지. 명사화 어미(「~성·~도」)는 여기서만 인정한다.
    in_evaluation_section = False
    index = 0

    while index < len(lines):
        line = lines[index]

        # (1) 요구사항 정의서 표
        if _REQ_TABLE_START_RE.match(re.sub(r"\s+", " ", line.raw).strip()):
            draft, index = _parse_requirement_table(lines, index)
            if draft is not None:
                drafts.append(draft)
            continue

        # (1-1) 서식(별지) 본문이 시작되면 평가 절을 닫는다 (0919 §4-B-5).
        #
        # 「【서식 1】」 아래는 담당자가 채워 넣을 «빈 양식»이다. 칸 이름(「회사 설립 년도」·
        # 「사업자 등록번호」)은 요구사항이 아니라 서식의 항목이다. 이 줄들은 절 이름 규칙에
        # 걸리지 않아 평가 절이 문서 끝까지 열린 채로 남았고, 표의 칸을 항목화하기 시작하자
        # 양식 칸 14개가 통째로 요구사항으로 올라와 정밀도가 0.80 → 0.68 로 내려갔다.
        #
        # 잡음 판정보다 **먼저** 본다. 「【서식 1】」은 한글이 두 자뿐이라 잡음으로 걸러져
        # 여기까지 오지도 못한다 — 절을 닫을 기회를 그 줄에서 잃는다.
        #
        # 목록 줄(「◦ 서식 1 : 제안업체 일반현황 및 연혁」)은 닫지 않는다 — 그건 «무엇을
        # 제출해야 하는가»라서 요구사항이 맞다. 그래서 글머리표를 뗀 본문이 아니라 원문 줄로
        # 본다: 서식 «본문»의 제목만 【 】·[ ] 로 시작한다.
        if in_evaluation_section and _FORM_HEADING_RE.match(line.raw.strip()):
            in_evaluation_section = False

        # (2) 목차 조각·페이지 번호 등
        if _is_noise(line.raw):
            index += 1
            continue

        # (2-1) 절 전환 판정 — 어느 절 안인지에 따라 개조식 인정 범위가 달라진다.
        mode = _section_mode(line)
        if mode is not None:
            in_task_section = mode == "task"
            in_condition_section = mode == "condition"
            in_evaluation_section = in_condition_section and bool(_EVALUATION_SECTION_RE.search(line.body))
        elif in_evaluation_section and _is_heading(line) and _MAJOR_HEADING_RE.match(line.raw):
            # 아는 이름이 아닌 **대분류**가 나오면 평가 절을 닫는다 (0919 §4-B-5).
            #
            # 「Ⅶ. 기자재 상세 규격」은 절 이름 규칙에 없어서 `_section_mode` 가 None 을 준다.
            # 그러면 앞의 「Ⅴ. 평가방법 및 세부평가 배점」이 문서 끝까지 열린 채로 남는다.
            #
            # 다른 절 판정은 건드리지 않는다. 여기서 닫는 것은 평가 절뿐이고, 이 절만이
            # 「어미 없는 명사구도 항목으로 본다」는 넓은 규칙을 켠다.
            #
            # `_is_heading` 을 함께 보는 이유: `_MAJOR_HEADING_RE` 는 「10」·「100」 같은
            # 배점 칸에도 걸린다(`\d{1,2}` 뒤의 구두점이 선택이라 「1」+「0」으로 읽힌다).
            # 그것만 보고 닫으면 배점표 한가운데서 절이 끊긴다 — 실측으로 재현율이
            # 0.843 에서 0.711 로 떨어졌다.
            in_evaluation_section = False

        # (2-2) 조건 절의 개조식 항목 — 「~한 자」·「매수: 20page 내외」 같은 것들.
        # 의무 표현이 없어 전역 규칙으로는 걸리지 않지만, 이 절에서는 진짜 조건이다.
        # 의무 표현이 없으므로 status 는 「확인 필요」로 둔다 — 사람이 보고 확정한다.
        # 조건 절 안에서는 **항목이 제목을 이긴다.**
        #
        # 조건은 「가. …」·「나. …」로 번호를 달고 나열되는데, 그건 절 제목과 같은 모양이다.
        # 제목 판정을 먼저 하면 조건이 통째로 제목으로 오인돼 버려진다 —
        # 실측: 계약해지 사유 3건(「가. “을”이 계약사항을 이행하지 않거나 … 때」, 36자)이
        # 전부 이렇게 사라졌다. 절 제목은 이미 (2-1)에서 읽었으므로 여기서는 항목을 우선한다.
        #
        # 다만 «방금 절을 연 줄» 자체는 제목이다. 그 줄은 절 이름 정규식에 걸려서 여기까지 온
        # 것이므로(「Ⅲ. 입찰 참가자격 및 사업자 선정 방법」·「3. 유사사업 수행실적 평가기준」),
        # 항목으로도 내보내면 목차가 요구사항 표에 섞인다. 조건이 제목으로 오인되는 앞의 문제는
        # 절을 «열지 않은» 줄에서 생기므로 이 예외와 부딪히지 않는다.
        #
        # HWP 가 절 번호(「2」)를 따로 한 줄로 내려 주면 바로 뒤 「사업자 선정 방법」은 번호 없는
        # 짧은 줄이 되어 절을 닫지 못하고 「방법」 어미로 항목이 된다. 절 이름 낱말이면 제목으로 본다.
        if (
            mode is None
            and in_condition_section
            and not (_after_bare_number(lines, index) and _NON_TASK_SECTION_RE.search(line.body))
            and _is_condition_item(line, evaluation=in_evaluation_section)
        ):
            content = re.sub(r"\s+", " ", line.body).strip()
            row_lines = [line.raw]
            if _TIMING_ONLY_RE.match(content):
                row = _timing_row(lines, index)
                if row is None:
                    # 무엇을 내는지 모르는 시기 조각은 버린다.
                    index += 1
                    continue
                row_lines = row
                content = re.sub(
                    r"\s+", " ", " ".join(_Line(page=line.page, raw=r).body for r in row_lines)
                ).strip()
            line_category = _category_of(content, _CATEGORY_RULES)
            resolved = line_category or (category if category != DEFAULT_CATEGORY else DEFAULT_CATEGORY)
            drafts.append(
                _Draft(
                    page=line.page,
                    category=resolved,
                    requirement_type=_requirement_type(content) or "mandatory",
                    title=_title_of(content),
                    content=content,
                    source_lines=row_lines,
                    status="check",
                )
            )
            index += 1
            continue

        # (2-2b) 평가·배점 표의 칸 (0919 §4-B-5)
        #
        # 배점표의 평가요소는 어미가 없는 명사구라 어떤 어미 규칙에도 걸리지 않는다 —
        # 「최근 3년 이내 유사 사업 수행 실적」·「참여인력의 수행 역량」. 정답셋이 요구사항으로
        # 보고 있고(CLAUDE.md 2장 4번이 평가항목을 정리 대상으로 명시한다) 실제로도 제안서에
        # 그대로 답해야 하는 항목이다.
        #
        # 평가 절 **안에서만** 켠다. 절을 가리지 않고 명사구를 인정하면 문서 어디에나 있는
        # 명사구가 전부 요구사항이 되어 정밀도가 무너진다.
        #
        # 의무·권장 표현이 있는 줄은 **건드리지 않는다.** 아래 (4) 전역 규칙이 그 줄을
        # «문장 그대로» 담는데, 여기서 먼저 칸으로 쪼개면 끝의 마침표까지 떨어져 나가
        # 원문과 달라진다(실측: 「…첨부하여야 한다.」가 「…첨부하여야 한다」가 됐다).
        if (
            mode is None
            and in_evaluation_section
            and not _is_heading(line)
            and _requirement_type(line.body) is None
        ):
            cells = _evaluation_cells(line)
            for cell in cells:
                line_category = _category_of(cell, _CATEGORY_RULES)
                drafts.append(
                    _Draft(
                        page=line.page,
                        category=line_category or "평가",
                        # 배점 항목은 «의무»가 아니라 «채점 기준»이다. 사람이 보고 확정한다.
                        requirement_type=_requirement_type(cell) or "mandatory",
                        title=_title_of(cell),
                        content=cell,
                        source_lines=[line.raw],
                        status="check",
                    )
                )
            if cells:
                index += 1
                continue

        # (2-3) 과업 절의 평서형 문장 — 「~한다」로 끝나는 것.
        #
        # 과업지시서는 과업을 「분석한다」·「도출한다」·「수립한다」처럼 평서형으로 적는다.
        # 전역 의무 규칙은 「하여야 한다」계열만 보므로 이런 문장이 통째로 빠졌다.
        # 실측(마운트 DB 구축 과업지시서, gold 39건): 이 한 가지로 25건 중 다수를 놓쳤다.
        #
        # 전역 규칙을 넓히지 않는 이유는 늘 같다 — 그러면 배경 서술문까지 딸려 온다.
        # 「여기는 과업 절이다」를 아는 지금만 인정한다.
        if in_task_section and not _is_heading(line) and _is_task_sentence(line):
            content = re.sub(r"\s+", " ", line.body).strip()
            line_category = _task_line_category(content)
            resolved = line_category or ("과업내용" if category == DEFAULT_CATEGORY else category)
            drafts.append(
                _Draft(
                    page=line.page,
                    category=resolved,
                    requirement_type="mandatory",
                    title=_title_of(content),
                    content=content,
                    source_lines=[line.raw],
                    status=_status_for(resolved, content),
                )
            )
            index += 1
            continue

        # (2-4) 과업 절의 개조식·표 항목 (의무 표현이 없어도 요구사항이다)
        if in_task_section and _is_task_item(line):
            content = re.sub(r"\s+", " ", line.body).strip()
            line_category = _task_line_category(content)
            resolved = line_category or ("과업내용" if category == DEFAULT_CATEGORY else category)
            drafts.append(
                _Draft(
                    page=line.page,
                    category=resolved,
                    requirement_type=_requirement_type(content) or "mandatory",
                    title=_title_of(content),
                    content=content,
                    source_lines=[line.raw],
                    status=_status_for(resolved, content),
                )
            )
            index += 1
            continue

        # (3) 절 제목 -> 카테고리 갱신
        if _is_heading(line):
            found = _category_of(line.body, _CATEGORY_RULES)
            if found is not None:
                category = found
            elif _MAJOR_HEADING_RE.match(line.raw):
                # 대분류가 바뀌었는데 아는 카테고리가 아니면 이전 절 값을 계속 쓰지 않는다.
                category = DEFAULT_CATEGORY
            index += 1
            continue

        # (3-1) 별지·서식 묶음
        if _FORM_HEADING_RE.match(line.raw):
            category = "제출서류"

        # (4) 의무 문장
        raw_lines, next_index = _join_wrapped(lines, index)
        content = " ".join(_Line(page=line.page, raw=r).body for r in raw_lines).strip()
        content = re.sub(r"\s+", " ", content)
        req_type = _requirement_type(content)
        if req_type is None or len(content) < MIN_CONTENT_CHARS:
            index = next_index
            continue
        # 계약 일반조건·권리포기 조항은 의무 표현이 있어도 제안서가 대응할 항목이 아니다.
        if _NON_REQUIREMENT_RE.search(content):
            index = next_index
            continue

        line_category = _category_of(content, _CATEGORY_RULES)
        # 문장 자체에 명확한 분류 단서가 있으면 이전 절 제목보다 우선한다.
        # 그렇지 않으면 「보안」 절 뒤의 계약해지·하자보완 문장까지 보안으로 새어 간다.
        resolved = line_category or (category if category != DEFAULT_CATEGORY else DEFAULT_CATEGORY)
        drafts.append(
            _Draft(
                page=line.page,
                category=resolved,
                requirement_type=req_type,
                title=_title_of(content),
                content=content,
                source_lines=raw_lines,
                status=_status_for(resolved, content),
            )
        )
        index = next_index

    return drafts


# --------------------------------------------------------------------------
# 공개 API
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ExtractionResult:
    """추출 결과 + 상한 적용 정보.

    candidate_count는 MAX_REQUIREMENTS를 적용하기 **전**의 (중복 제거된) 후보 수다.
    truncated가 True면 문서 뒤쪽 요구사항이 응답에서 빠졌다는 뜻이고,
    그 상태의 Coverage는 검사한 범위 안에서만 유효하다. 조용히 버리지 않고 드러낸다.
    """

    requirements: list[Requirement]
    candidate_count: int

    @property
    def truncated(self) -> bool:
        return self.candidate_count > len(self.requirements)


def extract_with_stats(procurement_id: str, doc: ExtractedDocument) -> ExtractionResult:
    """요구사항을 추출하고 상한에 잘린 건수까지 함께 돌려준다."""
    drafts = _drop_contained(_build_drafts(_iter_lines(doc)))

    unique: list[_Draft] = []
    seen: set[str] = set()
    for draft in drafts:
        key = _normalize(draft.content)
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(draft)

    # 항목 유형(과업·참가자격·제출·일정·평가·특이사항)과 중대성을 함께 채운다.
    #
    # 합성 fixture 경로(rfp_parser.extract_requirements)는 이것을 하는데 실제 공고 경로는
    # 하지 않았다. Requirement 의 기본값이 item_type="REQUIREMENT" 라 실공고 12건이 전부
    # 한 유형으로 저장됐고, 읽기 시 보정(item_classifier.enrich_payload)은 «값이 비어 있을
    # 때만» 채우므로 기본값이 이미 들어간 파일은 영영 고쳐지지 않았다.
    #
    # 그 바람에 화면에서 유형 탭이 모두 0건이고, 「행동 필요」 배지가 절대 뜨지 않으며,
    # BLOCKER 강조와 「지금 할 일」이 실데이터에서 늘 비어 있었다.
    requirements = []
    for seq, draft in enumerate(unique[:MAX_REQUIREMENTS], start=1):
        requirement_id = f"REQ-{seq:03d}"
        source_text = "\n".join(draft.source_lines)
        requirements.append(
            Requirement(
                id=f"{procurement_id}:{requirement_id}",
                procurement_id=procurement_id,
                requirement_id=requirement_id,
                category=draft.category,
                requirement_type=draft.requirement_type,
                title=draft.title,
                content=draft.content,
                page=draft.page,
                source_text=source_text,
                status=draft.status,
                extraction_method="RULE",
                **item_classifier.classify_fields(
                    category=draft.category,
                    requirement_type=draft.requirement_type,
                    content=draft.content,
                    source_text=source_text,
                    requirement_id=requirement_id,
                ),
            )
        )
    return ExtractionResult(requirements=requirements, candidate_count=len(unique))


def extract_requirements_from_document(
    procurement_id: str, doc: ExtractedDocument
) -> list[Requirement]:
    """실제 제안요청서 텍스트에서 요구사항을 추출한다.

    page는 원문 페이지(HWP/HWPX는 문단 묶음 근사값), source_text는 원문 줄 그대로다.
    근거를 아직 연결하지 않았으므로 status는 unmatched(모호 조건은 check)로 둔다.
    상한에 잘렸는지까지 알아야 하면 extract_with_stats를 쓴다.
    """
    return extract_with_stats(procurement_id, doc).requirements
