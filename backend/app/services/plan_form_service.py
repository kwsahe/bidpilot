"""사업계획서 양식 뽑기 — 공고가 준 「사업계획서」 양식과 「평가지표」를 뼈대로 (25차 · prompt_15 §4-B).

## 왜 양식인가

지금까지 초안은 우리가 정한 절 여섯(사업 개요 · 신청 자격 · 수행 역량 · 추진 계획 · 예산 · 기대 효과)에
공고문 인용을 모은 것이었다. 공고는 이미 **양식**을 준다 — 대항목 · 소항목 · 표 · 작성 규칙
(「양식의 목차, 표는 변경 또는 삭제 불가」) · 평가지표. 담당자가 옮겨 쓸 수 있는 초안은 그 양식 순서다.

## 무엇을 뽑는가

목차(□ 대항목 · 소항목 · 선택 칸) · 표(이름 · 열) · 소항목 안내 문구 · 작성 규칙(쪽수 · 글자 크기 ·
목차·표 변경 불가) · 사업비 상한(공고문 money 조항 `cap` — 없으면 양식 안내 문구) · 허용 비목(참고 쪽 — 목차에는
넣지 않는다) · 평가지표(항목 · 세부 내용 · 가점 · 탈락 점수) · 협약 기간 · 과제 표 · **양식 예시 값**(000 · 0000.00.00 ·
예시 금액 · 예시 날짜 — 이 값이 초안에 나오면 근거가 아니다).

## 어떻게 읽는가 — PDF 텍스트는 표가 뒤섞여 있다

2단 표(「평가 항목 | 세부 내용」 · 「비목 | 비목 정의」)가 한 줄로 섞이고, 병합 셀(기관명)은 행 사이 줄로
떨어진다. 줄 모양만으로는 소항목 이름과 안내 문구를 가를 수 없어 **자주 쓰는 양식 어휘**(소항목 · 평가 항목 ·
비목 · 칸 이름)를 공백 없이 맞춰 찾고, 어휘에 없는 소항목은 「안내 문구 뒤의 짧은 줄」로 찾는다(`recognized_by`).
과제 표는 병합 셀을 줄 위치로 되살린다(기관이 두 행 사이에 있으면 두 행 다).

양식 절을 못 찾으면 **표준 양식**(문제 인식 · 실현 가능성 · 성장 전략 · 팀 구성 — 창업 지원사업 공통 틀)을 쓰고
그 사유를 적는다 — 「공고문 텍스트 없음」과 「양식 절 없음」을 가른다.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.core import org_storage, storage
from app.schemas.organization import AnalysisContext
from app.services import bizinfo_document_store, support_requirement_extractor

FILE_NAME = "plan_form.json"
FORM_VERSION = 1

#: 사람만 채우는 칸 · 빈칸 표시 (§2 · §4-C)
HUMAN_INPUT = "(담당자 입력)"
TASK_PENDING = "(담당자 선택)"
#: 빈칸 표시와 변형 꼴 한 규칙(2.8.0 B3) — 「(담당자 입력)」 · 「[담당자 입력]」 · 「(담당자입력)」 · 「(담당자 기재 · 작성)」 ·
#: 「(담당자 입력 — 예: …)」. 품질 게이트 · 제출 전 채울 칸 수 · 한글 빈칸 글자 모양 · 입찰 거르기(`bid_filter`)가 함께 쓴다.
#: 「(담당자 확인)」도 — 괄호가 바로 닫힐 때만(2.10.0 T3 · 손 수정본이 미확인 값을 이 꼴로 25곳 남겼는데 0 으로 셌다 ·
#: 「(담당자 확인 후 발주기관 승인)」은 계획 문장).
HUMAN_INPUT_RE = re.compile(r"[(\[（]\s*담당자\s*(?:(?:입력|기재|작성)[^)\]）\n]{0,80}|확인\s*)[)\]）]")
#: 그 밖의 미작성 꼴(2.8.0 B3) — TBD · TODO 낱말 · 「추후 기입 · 기재」 · 「(미정)」 · 「(확인 필요)」. 「장소 미정입니다」 · 「김미정」은 아니다
#: (공고 원문에 사람 이름 · 정상 값으로 나온다 — 괄호 꼴이나 칸 전체만 본다).
#: 맨 「확인 필요」도 — AI 가 채운 표 칸은 본문 거르기(`bid_filter`)를 지나지 않는다(대표 11-03 「제출용에 확인 필요 없음」 · 2.8.0 검토).
#: 본문 거르기(`bid_proposal_service._HEDGE_RE`)와 같은 선 — 「필요」 바로 뒤가 한글이면(「확인이 필요한 수료생」 · 「확인 필요성」 ·
#: 「확인 필요여부」) 꾸밈꼴이라 세지 않고, 「확인 필요 시」 · 「확인 필요 사항」도 아니다(2.8.0 검토 — 두 규칙이 어긋나면 거르기가 남긴
#: 정상 문장이 차단이 된다).
_UNWRITTEN_RE = re.compile(r"(?<![A-Za-z])(?:TBD|TODO)(?![A-Za-z])|추후\s*(?:기입|기재)|[(（]\s*(?:미정|확인\s*필요)\s*[)）]"
                           r"|확인\s*(?:이\s*)?필요(?:합니다|함)?(?![가-힣])(?!\s*(?:시|사항))")
#: 칸 · 문단 전체가 미정 꼴이면 1 — 「미정」 · 「추후 확정」 · 「협의 필요」 · 「검토 필요」(문장 속 「장소 미정입니다」 · 「김미정」은 아니다).
_UNWRITTEN_WHOLE_RE = re.compile(r"미정|추후\s*(?:확정|결정|확인|협의)(?:\s*예정)?|(?:협의|검토)\s*(?:가\s*)?필요(?:합니다|함)?")


def unwritten_count(text: str) -> int:
    """글 한 덩어리(문단 · 표 칸)에 남은 미작성 표시 수 — 빈칸 표시 · 변형 꼴 · 미작성 꼴, 덩어리 전체가 미정 꼴이면 1."""
    text = str(text or "")
    if _UNWRITTEN_WHOLE_RE.fullmatch(text.strip(" .·-")):
        return 1
    marks = len(HUMAN_INPUT_RE.findall(text))
    return marks + len(_UNWRITTEN_RE.findall(HUMAN_INPUT_RE.sub(" ", text) if marks else text))  # 「(담당자 입력 — TBD)」는 한 칸

REASON_NO_TEXT = "공고문 텍스트 없음"
REASON_NO_FORM = "양식 절 없음"

# ---------------------------------------------------------------------------
# 줄 다듬기
# ---------------------------------------------------------------------------

_PAGE_MARK_RE = re.compile(r"\f?\[쪽 \d+\]")
_PAGE_FOOTER_RE = re.compile(r"^-\s*\d+\s*-$")
#: 양식 머리 — 「붙임 1 사업계획서」 · 「[붙임 1] 사업계획서」. 본문 속 참조(「사업계획서[붙임 1]」 ·
#: 「[붙임 1] 양식으로」)는 줄 머리가 아니거나 「사업계획서」로 끝나지 않아 걸리지 않는다.
_FORM_HEAD_RE = re.compile(
    r"^\[?\s*붙임\s*(\d+)\s*\]?\s*[.:)]?\s*(?:창업기업\s*)?사업\s*계획서\s*(?:\(\s*양식\s*\)|양식)?\s*$"
)
#: 다음 붙임 · 별첨 머리 — 양식 절이 끝나는 자리.
_NEXT_ANNEX_RE = re.compile(r"^\[?\s*(?:붙임|별첨)\s*\d+\s*\]?\s*\S")
_REFERENCE_RE = re.compile(r"^참고\s+\S")
_MAJOR_RE = re.compile(r"^□\s*(.+)$")
_GUIDE_RE = re.compile(r"※\s*\(\s*표는\s*삭제\s*후\s*제출\s*\)")
#: 안내 문구 속 각주(「산출물 및 * 개발단계 : …」) — 이름 조각을 되살리려고 떼어 낸다.
_FOOTNOTE_TAIL_RE = re.compile(r"\s\*\s.*$")


def _lines(text: str) -> list[str]:
    """쪽 표식을 떼고 줄로 나눈다. 쪽 바닥줄(「- 16 -」)과 빈 줄은 **빈 문자열**로 남긴다 — 표가 끝나는 표시다."""
    out: list[str] = []
    for raw in text.split("\n"):
        line = _PAGE_MARK_RE.sub("", raw).replace("\f", "").strip()
        out.append("" if _PAGE_FOOTER_RE.match(line) else line)
    return out


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _find_vocab(compact: str, vocab: tuple[tuple[str, str], ...]) -> list[tuple[int, str]]:
    """공백 없는 글에서 어휘를 찾는다 — 긴 것부터, 겹치지 않게. (위치, 표시 이름) 목록을 위치 순으로."""
    taken: list[tuple[int, int]] = []
    found: list[tuple[int, str]] = []
    for key, name in sorted(vocab, key=lambda kv: -len(kv[0])):
        start = compact.find(key)
        while start >= 0:
            end = start + len(key)
            if not any(start < b and a < end for a, b in taken):
                taken.append((start, end))
                found.append((start, name))
                break
            start = compact.find(key, start + 1)
    return sorted(found)


# ---------------------------------------------------------------------------
# 어휘 — 정부지원 사업계획서 양식에 자주 나오는 이름
# ---------------------------------------------------------------------------

#: 소항목 (공백 없는 열쇠, 표시 이름). 선택 칸은 `_OPTIONAL_ITEMS`.
ITEM_VOCAB: tuple[tuple[str, str], ...] = (
    ("공공데이터활용계획", "공공데이터 활용 계획"),
    ("과제해결방안", "과제 해결방안"),
    ("기술등경쟁력", "기술 등 경쟁력"),
    ("산출물및개발단계", "산출물 및 개발단계"),
    ("사업화방안", "사업화 방안"),
    ("기업(팀)역량", "기업(팀) 역량"),
    ("추진계획", "추진 계획"),
    ("집행계획", "집행 계획"),
    ("이미지", "이미지"),
    # 표준 창업 사업계획서(PSST) 계열
    ("창업아이템개요", "창업 아이템 개요"),
    ("개발동기", "개발 동기"),
    ("목표시장분석", "목표 시장 분석"),
    ("개발방안", "개발 방안"),
    ("차별화방안", "차별화 방안"),
    ("사업화전략", "사업화 전략"),
    ("자금소요및조달계획", "자금 소요 및 조달 계획"),
    ("대표자및팀원의보유역량", "대표자 및 팀원의 보유 역량"),
)
_OPTIONAL_ITEMS = frozenset({"이미지"})

#: 평가 항목 (공백 없는 열쇠, 표시 이름)
EVAL_VOCAB: tuple[tuple[str, str], ...] = (
    ("협업과제이해도", "협업 과제 이해도"),
    ("팀(기업)구성", "팀(기업) 구성"),
    ("실현가능성및구체성", "실현 가능성 및 구체성"),
    ("지속가능성", "지속 가능성"),
    ("문제인식", "문제 인식"),
    ("실현가능성", "실현 가능성"),
    ("성장전략", "성장 전략"),
    ("팀구성", "팀 구성"),
    ("기술성", "기술성"),
    ("사업성", "사업성"),
    ("시장성", "시장성"),
    ("혁신성", "혁신성"),
)

#: 사업비 비목 (공백 없는 열쇠, 표시 이름)
BUDGET_ITEM_VOCAB: tuple[tuple[str, str], ...] = (
    ("재료비", "재료비"),
    ("외주용역비", "외주용역비"),
    ("기계장치", "기계장치"),
    ("특허권등무형자산취득비", "특허권 등 무형자산 취득비"),
    ("인건비", "인건비"),
    ("지급수수료", "지급수수료"),
    ("여비", "여비"),
    ("교육훈련비", "교육훈련비"),
    ("광고선전비", "광고선전비"),
    ("창업활동비", "창업활동비"),
    ("기자재임차비", "기자재 임차비"),
)

#: 일반 현황 · 기업 현황 칸 (공백 없는 열쇠, 표시 이름, 사람만 채우는가)
FIELD_VOCAB: tuple[tuple[str, str, bool], ...] = (
    ("과제명", "과제명", False),
    ("기업명", "기업명", False),
    ("대표자유형", "대표자 유형", True),
    ("대표자", "대표자", True),
    ("생년월일", "생년월일", True),
    ("연락처", "연락처", True),
    ("이메일", "이메일", True),
    ("개업연월일", "개업연월일", True),
    ("창업일", "창업일", True),
    ("사업장소재지", "사업장 소재지", True),
    ("사업자등록번호", "사업자등록번호", True),
    ("법인등록번호", "법인등록번호", True),
    ("사업장주소", "사업장 주소", True),
    ("사업분야", "사업분야(주요 생산품)", False),
    ("기업및제품서비스", "기업 및 제품·서비스 특징", False),
    ("제품및서비스사진", "제품 및 서비스 사진", True),
    ("사업수행실적", "사업수행 실적", False),
    ("사업수행성과", "사업수행 성과", False),
    ("기타성과", "기타 성과", False),
)

#: 표준 양식(공고 양식이 없을 때)의 일반 현황 칸 — (표시 이름, 사람만 채우는가) (29차 §3-B)
STANDARD_GENERAL_FIELDS: tuple[tuple[str, bool], ...] = (
    ("기업명", False), ("대표자", True), ("개업연월일", True), ("사업장 소재지", True), ("사업자등록번호", True),
    ("연락처", True), ("업태/종목", True), ("사업분야(주요 생산품)", False),
)

#: 양식 표 — 열은 고정이다(구조화 출력 스키마 · 검증이 열 이름에 기댄다). 사람만 채우는 표는 AI 가 채우지 않는다.
TABLE_SPECS: tuple[dict[str, Any], ...] = (
    {"key": "staff", "title": "인력 구성", "detect": re.compile(r"인력\s*구성"),
     "columns": ["연번", "성명", "직위", "담당업무", "보유 역량(경력 및 학력 등)", "구성 상태"], "human_only": True},
    {"key": "awards", "title": "수상 이력", "detect": re.compile(r"<\s*수상\s*이력"),
     "columns": ["대회명", "주최", "입상여부"], "human_only": True},
    {"key": "schedule", "title": "사업 추진일정", "detect": re.compile(r"<\s*사업\s*추진\s*일정\s*>"),
     "columns": ["추진 내용", "추진 기간", "세부 내용"], "human_only": False},
    {"key": "budget", "title": "사업비 집행계획", "detect": re.compile(r"<[^>]*집행\s*계획[^>]*>"),
     "columns": ["비목", "산출근거", "금액(원)"], "human_only": False},
    {"key": "performance", "title": "정량적 성과", "detect": re.compile(r"정량적\s*성과"),
     "columns": ["구분", "2023년", "2024년", "2025년"], "human_only": True},
)

_AGENCY_SUFFIX_RE = re.compile(r"(청|처|부|원|공사|공단|회|센터|재단|기관|위원회|대학교|병원|시|도|구|군)$")
_REGION_PREFIX_RE = re.compile(
    r"^(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충청|전라|경상|전북|제주)\S*(특별시|광역시|특별자치시|특별자치도|도)$"
)

# ---------------------------------------------------------------------------
# 절 찾기
# ---------------------------------------------------------------------------


def _form_bounds(lines: list[str]) -> tuple[int, int] | None:
    start = next((i for i, line in enumerate(lines) if _FORM_HEAD_RE.match(line)), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(lines)) if _NEXT_ANNEX_RE.match(lines[i]) and not _FORM_HEAD_RE.match(lines[i])), len(lines))
    return start, end


def _item_blocks(section_lines: list[str]) -> tuple[list[str], list[list[str]]]:
    """대항목 안을 「※ (표는 삭제 후 제출)」 안내 상자마다 나눈다 — (머리 조각, 상자들)."""
    head: list[str] = []
    blocks: list[list[str]] = []
    for line in section_lines:
        if _GUIDE_RE.search(line):
            blocks.append([line])
        elif blocks:
            blocks[-1].append(line)
        else:
            head.append(line)
    return head, blocks


#: 작성 규칙 상자(「본문 7page 내외, 11포인트 … 양식의 목차, 표는 변경 또는 삭제 불가」) — 소항목이 아니다.
_RULES_BOX_RE = re.compile(r"본문\s*\d+\s*(?:page|페이지|쪽)|포인트로\s*작성|변경\s*또는\s*삭제\s*불가")


def _block_names(block: list[str]) -> list[tuple[str, str]]:
    """상자 하나에서 소항목 이름(들)과 알아낸 방법. 어휘가 먼저, 없으면 안내 문구 뒤의 짧은 줄.

    작성 규칙 상자는 소항목이 아니다. 선택 칸(「이미지」)은 안내 문구 속 「사진(이미지)」가 아니라
    **그 이름으로 시작하는 줄**이 있을 때만 칸이다.
    """
    if block and _RULES_BOX_RE.search(" ".join(block[:3])):
        return []
    cleaned = [_FOOTNOTE_TAIL_RE.sub("", line) for line in block if line and not line.startswith("*")]
    vocab = tuple((key, name) for key, name in ITEM_VOCAB if name not in _OPTIONAL_ITEMS)
    found = [(pos, name) for pos, name in _find_vocab(_compact("".join(cleaned)), vocab)]
    for position, line in enumerate(cleaned):
        for name in _OPTIONAL_ITEMS:
            if line.startswith(name) and position > 0:
                found.append((10**6 + position, name))
    if found:
        return [(name, "dictionary") for _, name in sorted(found)]
    # 어휘에 없다 — 안내(※ · - · < · 각주) 뒤에 오는 짧은 줄을 이름으로 본다.
    candidates = [
        line for line in cleaned[1:]
        if 1 < len(_compact(line)) <= 12 and not re.match(r"^[※\-<•◦⁞.·(0-9]", line) and not line.endswith("등")
    ]
    return [(" ".join(candidates[-2:]), "heuristic")] if candidates else []


def _guide_text(block: list[str]) -> str:
    """상자 안의 안내 문구(※ 줄 · - 줄과 그 이어진 줄 · 각주) — 소항목이 무엇을 쓰라는지. 초안 작성 지시에 쓴다.

    PDF 가 안내를 두 줄로 나누면 둘째 줄은 ※·- 없이 온다(「… 최종 산출물(형태, 수량 등) 및」 + 「현재 개발단계 등」).
    「등 · 기재 · 있음」으로 끝나는 줄은 이어진 안내로 붙이고, 이름 줄에 붙은 각주(「산출물 및 * 개발단계 : …」)는
    각주만 붙인다. 표 제목(「<」)에서 멈춘다 — 그 뒤는 표의 예시 행(「- 자재구입 … 3,448,000」)이다.
    """
    parts: list[str] = []
    for line in block:
        if line.startswith("<"):
            break
        text = _GUIDE_RE.sub("", line).strip()
        if line.startswith("※") or line.startswith("-"):
            parts.append(text.lstrip("-※ ").strip())
        elif parts:
            footnote = _FOOTNOTE_TAIL_RE.search(line)
            if footnote:
                parts.append(footnote.group(0).strip().lstrip("*").strip())
            elif re.search(r"(?:등|기재|있음)$", text):
                parts.append(text)
    return " ".join(p for p in parts if p)[:300]


def _clean_title(raw: str) -> tuple[str, str | None]:
    match = re.match(r"^(.*?)\s*\(([^)]*)\)\s*$", raw)
    if match and match.group(1):
        return match.group(1).strip(), match.group(2).strip()
    return raw.strip(), None


def _fields(lines: list[str]) -> list[dict[str, Any]]:
    compact = _compact("".join(lines))
    vocab = tuple((key, name) for key, name, _ in FIELD_VOCAB)
    human = {name: flag for _, name, flag in FIELD_VOCAB}
    return [{"label": name, "human_only": human[name]} for _, name in _find_vocab(compact, vocab)]


def _tables(form_lines: list[str], owner: list[tuple[str | None, str | None]]) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    for spec in TABLE_SPECS:
        index = next((i for i, line in enumerate(form_lines) if spec["detect"].search(line)), None)
        if index is None:
            continue
        columns = list(spec["columns"])
        row_labels: list[str] = []
        if spec["key"] == "performance":
            window = " ".join(form_lines[index : index + 4])
            years = re.findall(r"(\d{4})\s*년", window)
            if years:
                columns = ["구분", *[f"{y}년" for y in dict.fromkeys(years)]]
            row_labels = re.findall(r"(매출액\s*\([^)]*\)|고용\s*인원\s*\([^)]*\))", window)
        section_key, item_key = owner[index]
        # 공고 양식의 표 제목(「< 정부지원사업비 집행계획 세부내역 >」)을 그대로 — 공고가 「표는 변경 불가」라 적는다(27차 검수 D7).
        named = re.search(r"<\s*([^<>]{2,40}?)\s*>", form_lines[index])
        tables.append(
            {
                "key": spec["key"],
                "title": named.group(1) if named else spec["title"],
                "columns": columns,
                "row_labels": row_labels,
                "section": section_key,
                "item": item_key,
                "human_only": spec["human_only"],
            }
        )
    return tables


def _rules(form_text: str) -> dict[str, Any]:
    pages = re.search(r"본문\s*(\d+)\s*(?:page|페이지|쪽)", form_text)
    font = re.search(r"(\d+)\s*포인트", form_text)
    locked = re.search(r"(?:목차\s*,?\s*표는|양식은)\s*변경\s*또는\s*삭제\s*불가", form_text)
    return {
        "pages": int(pages.group(1)) if pages else None,
        "font_pt": int(font.group(1)) if font else None,
        "no_structure_change": bool(locked),
    }


def _examples(form_lines: list[str]) -> dict[str, Any]:
    """양식 안의 **예시 값** — 초안에 나오면 근거가 아니다(§4-C-3). 상한 문구(최대 … 이내)는 예시가 아니다."""
    numbers: list[int] = []
    dates: list[str] = []
    raw: list[str] = []
    for line in form_lines:
        if re.search(r"최대|한도|이내|이하", line):
            continue
        for match in re.finditer(r"\d{1,3}(?:,\d{3})+", line):
            value = int(match.group(0).replace(",", ""))
            if value not in numbers:
                numbers.append(value)
                raw.append(match.group(0))
        for match in re.finditer(r"[’'‘](\d{2})\.\s*(\d{1,2})\.\s*(\d{1,2})", line):
            iso = f"20{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
            if iso not in dates:
                dates.append(iso)
                raw.append(match.group(0))
        for match in re.finditer(r"0000\.00\.00\.?|00\.00\.00\.?~00\.00\.00\.?|0000년 00월 00일|000-0000-0000|\b0{3,4}\b|\(\d?0년\)|\(‘?00\.0\)", line):
            if match.group(0) not in raw:
                raw.append(match.group(0))
    return {"numbers": numbers, "dates": dates, "raw": raw}


def _budget(text: str, form_lines: list[str], reference_lines: list[str]) -> dict[str, Any]:
    cap: int | None = None
    source: str | None = None
    try:
        requirements = support_requirement_extractor.extract_from_text("form", text)
        caps = [c for c in requirements.of("money") if (c.detail or {}).get("kind") == "cap"]
    except Exception:  # 조항 뽑기가 실패해도 양식은 읽는다
        caps = []
    if caps:
        cap = int(caps[0].detail["krw"])
        source = f"공고문 조항: {caps[0].source_text}"
    else:
        for line in form_lines:
            match = re.search(r"최대\s*([\d,.]+)\s*(억|천만|백만|만)\s*원", line)
            if match:
                amount = float(match.group(1).replace(",", ""))
                cap = support_requirement_extractor._krw(amount, match.group(2))
                source = f"양식 안내 문구: {line.strip()}"
                break
    allowed = _names_at_fragment_starts(reference_lines, BUDGET_ITEM_VOCAB)
    # 비목 정의 원문 — 모델이 이름만 보고 「태블릿 = 재료비」처럼 고르지 않게 집행 계획 절에 함께 보낸다(공고문 발췌).
    reference = " ".join(line.strip() for line in reference_lines if line.strip())[:1500] or None
    return {"cap_krw": cap, "cap_source": source, "allowed_items": allowed, "item_reference": reference}


def _names_at_fragment_starts(lines: list[str], vocab: tuple[tuple[str, str], ...]) -> list[str]:
    """2단 표(「이름 | 정의」)에서 **이름 칸**만 — 줄 머리(또는 • 앞)에서 시작하는 어휘만 센다.

    정의 칸의 낱말(「… 멘토링비, 기자재 임차비, …」)은 줄 가운데라 걸리지 않는다. 이름이 두 줄로
    나뉜 것(「특허권 등 •…」 + 「무형자산 취득비 …」)은 이어 붙인 글에서 첫 조각 머리로 찾는다.
    """
    compact = ""
    starts: list[int] = []
    for line in lines:
        fragment = line.split("•")[0] if "•" in line else line
        if not fragment.strip():
            continue
        starts.append(len(compact))
        compact += _compact(fragment)
    ordered = sorted(vocab, key=lambda kv: -len(kv[0]))
    names: list[str] = []
    for start in starts:
        for key, name in ordered:
            if compact.startswith(key, start) and name not in names:
                names.append(name)
                break
    return names


def _evaluation(lines: list[str]) -> dict[str, Any]:
    start = next((i for i, line in enumerate(lines) if re.match(r"^□\s*평가\s*(지표|기준|항목)", line)), None)
    if start is None:
        return {"items": [], "bonus": [], "cutoff": None}
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("□")), len(lines))
    section = lines[start + 1 : end]
    header = next((i for i, line in enumerate(section) if re.search(r"평가\s*항목", line) and re.search(r"세부|내용|배점", line)), -1)
    body = section[header + 1 :] if header >= 0 else section
    names = [line.split("•")[0] for line in body if line and not line.startswith(("*", "※", "◦"))]
    items = [name for _, name in _find_vocab(_compact("".join(names)), EVAL_VOCAB)]
    bullets = _eval_bullets(body, items)
    joined = " ".join(section)
    bonus_match = re.search(r"가점\s*(\d+)\s*점", joined)
    bonus: list[dict[str, Any]] = []
    if bonus_match:
        detail = bullets[len(items)] if len(bullets) > len(items) else None
        bonus.append({
            "name": ("비수도권 " if detail and "비수도권" in detail else "") + f"가점 {bonus_match.group(1)}점",
            "points": int(bonus_match.group(1)),
            "detail": detail,
            "non_capital_region": bool(detail and "비수도권" in detail),
        })
    cutoff = re.search(r"(\d+)\s*점\s*미만", joined)
    return {
        "items": [{"name": name, "detail": bullets[i] if i < len(bullets) else None} for i, name in enumerate(items)],
        "bonus": bonus,
        "cutoff": int(cutoff.group(1)) if cutoff else None,
    }


def _eval_bullets(body: list[str], names: list[str]) -> list[str]:
    """평가 기준 세부 내용 — • 줄과 그 이어진 줄. 첫 줄에서 자르면 「… 활용 방안 및 요구」로 끝난다(9-28 시험 실행).

    이어진 줄이 항목 이름 줄(「협업 과제 이해도」)이면 건너뛰고, 이름의 꼬리로 시작하면(「및 구체성 차별성 등」)
    그 꼬리를 떼고 붙인다.
    """
    compact_names = [_compact(n) for n in names]
    bullets: list[str] = []
    for line in body:
        if "•" in line:
            bullets.append(line.split("•", 1)[1].strip())
            continue
        if not bullets or not line.strip() or line.startswith(("*", "※", "◦")) or _compact(line) in compact_names:
            continue
        words = line.split()
        for cut in range(len(words) - 1, 0, -1):
            head = _compact("".join(words[:cut]))
            if any(n.endswith(head) and n != head for n in compact_names):
                words = words[cut:]
                break
        bullets[-1] = f"{bullets[-1]} {' '.join(words)}".strip()
    return bullets


#: 「지원기간 · 사업기간 · 수행기간 · 협약기간 : 2026. 11. 1. ~ 2027. 3. 31.」(44차 S10 — 협약 기간 줄이 없는 공고는 일정표 기간 칸이 모두 빈칸이었다 · 123852)
_PERIOD_LINE = re.compile(r"(?:지원|사업|수행|협약)\s*기간\s*[:：]?\s*([^\n]{4,80})")
_PERIOD_START = re.compile(r"(20\d\d)\s*[.\-/년]\s*(\d{1,2})")
_PERIOD_END = re.compile(r"[～~∼]\s*(?:(20\d\d)|[’'‘](\d{2}))\s*[.\-/년]\s*(\d{1,2})")
#: 끝에 연도가 없는 꼴 「2026. 9. 1. ~ 12. 10.」 — 끝의 첫 숫자는 월이고 연도는 시작에서(월이 작아지면 다음 해 · 44차 마지막 검토)
_PERIOD_END_NO_YEAR = re.compile(r"[～~∼]\s*(\d{1,2})\s*[.\-/월]\s*\d{1,2}")


def _agreement_period(text: str) -> dict[str, Any] | None:
    match = re.search(r"협약\s*일?\s*[～~∼]\s*[’'‘]?(\d{2})\s*\.\s*(\d{1,2})\s*월(?:\s*\((\d+)\s*개월\))?", text)
    if match:
        return {
            "text": match.group(0),
            "end": f"20{match.group(1)}-{int(match.group(2)):02d}",
            "months": int(match.group(3)) if match.group(3) else None,
        }
    # 협약 기간 줄이 없으면 공고의 「지원기간 · 사업기간 · 수행기간」 줄 — 끝 연월이 있을 때만(지어내지 않는다)
    for line in _PERIOD_LINE.finditer(text):
        tail = line.group(1)
        end = _PERIOD_END.search(tail)
        if end:
            year, month = int(end.group(1) or f"20{end.group(2)}"), int(end.group(3))
        else:
            end = _PERIOD_END_NO_YEAR.search(tail)
            first = _PERIOD_START.search(tail[: end.start()]) if end else None
            if not end or not first:
                continue
            year, month = int(first.group(1)), int(end.group(1))
            year += 1 if month < int(first.group(2)) else 0
        if not 1 <= month <= 12:
            continue
        start = _PERIOD_START.search(tail[: end.start()])
        months = None
        if start and 1 <= int(start.group(2)) <= 12:
            months = (year * 12 + month) - (int(start.group(1)) * 12 + int(start.group(2))) + 1
            months = months if 0 < months <= 60 else None
        return {"text": line.group(0).strip()[:90], "end": f"{year}-{month:02d}", "months": months}
    return None


def _reception_period(lines: list[str]) -> str | None:
    for line in lines:
        match = re.match(r"^□\s*(?:접수|모집|신청)\s*기간\s*:\s*(.+)$", line)
        if match:
            return match.group(1).strip()
    return None


def _tasks(lines: list[str]) -> list[dict[str, Any]]:
    """과제 표(「연번 공공기관 협업 과제」). 병합 셀 기관명을 줄 위치로 되살린다."""
    header = next((i for i, line in enumerate(lines) if re.match(r"^연번\s+\S*\s*(?:기관|공공기관)\s+.*과제", line)), None)
    if header is None:
        return []
    rows: list[dict[str, Any]] = []
    fragments: list[tuple[int, str]] = []  # (줄 위치, 기관 조각)
    for index in range(header + 1, len(lines)):
        line = lines[index]
        if not line or line.startswith("□"):
            if rows:
                break
            continue
        number = re.match(r"^(\d{1,2})(?:\s+(.*))?$", line)
        if "▪" in line:
            before, title = line.split("▪", 1)
            no = None
            agency = before.strip()
            head = re.match(r"^(\d{1,2})\s*(.*)$", agency)
            if head:
                no, agency = int(head.group(1)), head.group(2).strip()
            rows.append({"no": no, "agency": agency or None, "title": title.strip(), "line": index, "inline": bool(agency)})
        elif number:
            rest = (number.group(2) or "").strip()
            pending = next((r for r in reversed(rows) if r["no"] is None), None)
            if pending is not None:
                pending["no"] = int(number.group(1))
                if rest and not pending["agency"]:
                    pending["agency"], pending["inline"] = rest, True
            else:
                rows.append({"no": int(number.group(1)), "agency": rest or None, "title": "", "line": index, "inline": bool(rest)})
        elif _AGENCY_SUFFIX_RE.search(line) and " " not in line.strip():
            fragments.append((index, line.strip()))
        elif rows:
            rows[-1]["title"] = f"{rows[-1]['title']} {line}".strip()

    # 1) 두 줄 기관명 — 지역 머리(「서울특별시」)와 뒤 조각이 한 행을 사이에 둔다.
    used: set[int] = set()
    for pos, (p_line, prefix) in enumerate(fragments):
        if not _REGION_PREFIX_RE.match(prefix) or pos + 1 >= len(fragments):
            continue
        f_line, tail = fragments[pos + 1]
        between = [r for r in rows if p_line < r["line"] < f_line]
        if len(between) == 1 and not between[0]["agency"]:
            between[0]["agency"] = f"{prefix} {tail}"
            used.update({pos, pos + 1})
    # 2) 남은 조각 — 앞뒤 행 사이에 있으면 병합 셀: 빈 쪽 모두.
    for pos, (f_line, name) in enumerate(fragments):
        if pos in used:
            continue
        before = next((r for r in reversed(rows) if r["line"] < f_line), None)
        after = next((r for r in rows if r["line"] > f_line), None)
        for row in (before, after):
            if row is not None and not row["agency"]:
                row["agency"] = name
    # 3) 아직 빈 행 — 다음 행의 기관명이 번호보다 먼저 나온 줄(병합 셀)이면 물려받는다.
    for i, row in enumerate(rows):
        if not row["agency"] and i + 1 < len(rows) and rows[i + 1]["inline"]:
            row["agency"] = rows[i + 1]["agency"]
    tasks = [{"no": r["no"], "agency": r["agency"], "title": r["title"]} for r in rows if r["no"] is not None]
    return sorted(tasks, key=lambda t: t["no"])


# ---------------------------------------------------------------------------
# 표준 양식 (공고 양식을 못 찾았을 때)
# ---------------------------------------------------------------------------


def standard_form(program_id: str, reason: str) -> dict[str, Any]:
    """창업 지원사업 공통 틀(일반 현황 · 문제 인식 · 실현 가능성 · 성장 전략 · 팀 구성). 사유를 맨 위에 적는다.

    일반 현황 칸은 공고 양식과 같은 이름이라 회사자료 자동 채움(`plan_fill_service.FIELD_MAP`)이 같은 표로 채운다 (29차 §3-B).
    """
    sections = [
        {"key": "S0", "title": "일반 현황", "note": None, "items": [], "fields": [
            {"label": label, "human_only": human} for label, human in STANDARD_GENERAL_FIELDS]},
        {"key": "S1", "title": "문제 인식", "note": None, "fields": [], "items": [
            {"key": "S1-1", "title": "창업 아이템 개요", "guide": "", "optional": False, "recognized_by": "standard"},
            {"key": "S1-2", "title": "목표 시장 분석", "guide": "", "optional": False, "recognized_by": "standard"}]},
        {"key": "S2", "title": "실현 가능성", "note": None, "fields": [], "items": [
            {"key": "S2-1", "title": "개발 방안", "guide": "", "optional": False, "recognized_by": "standard"},
            {"key": "S2-2", "title": "차별화 방안", "guide": "", "optional": False, "recognized_by": "standard"}]},
        {"key": "S3", "title": "성장 전략", "note": None, "fields": [], "items": [
            {"key": "S3-1", "title": "사업화 전략", "guide": "", "optional": False, "recognized_by": "standard"},
            {"key": "S3-2", "title": "추진 계획", "guide": "", "optional": False, "recognized_by": "standard"},
            {"key": "S3-3", "title": "집행 계획", "guide": "", "optional": False, "recognized_by": "standard"}]},
        {"key": "S4", "title": "팀 구성", "note": None, "fields": [], "items": [
            {"key": "S4-1", "title": "대표자 및 팀원의 보유 역량", "guide": "", "optional": False, "recognized_by": "standard"}]},
    ]
    tables = [
        {"key": "schedule", "title": "사업 추진일정", "columns": ["추진 내용", "추진 기간", "세부 내용"], "row_labels": [], "section": "S3", "item": "S3-2", "human_only": False},
        {"key": "budget", "title": "사업비 집행계획", "columns": ["비목", "산출근거", "금액(원)"], "row_labels": [], "section": "S3", "item": "S3-3", "human_only": False},
        {"key": "staff", "title": "인력 구성", "columns": ["연번", "성명", "직위", "담당업무", "보유 역량(경력 및 학력 등)", "구성 상태"], "row_labels": [], "section": "S4", "item": "S4-1", "human_only": True},
    ]
    return {
        "version": FORM_VERSION,
        "program_id": program_id,
        "source": "standard",
        "reason": reason,
        # 외부 점검 T4 — 초안을 만들기 전에도 뜨므로 현재형 · 창업 공통 목차라 이 사업 양식과 다를 수 있음을 함께(쉬운 보기 · /plan · 전체 보기가 이 글 하나)
        "notice": f"공고문에서 사업계획서 양식을 찾지 못해({reason}) 표준 양식(창업 지원사업 공통 목차)으로 씁니다 — 이 사업의 신청서 양식과 다를 수 있으니 공고 원문의 신청서 양식을 먼저 확인하세요",
        "heading": None,
        "title": None,
        "sections": sections,
        "tables": tables,
        "rules": {"pages": None, "font_pt": None, "no_structure_change": False},
        "budget": {"cap_krw": None, "cap_source": None, "allowed_items": [], "item_reference": None},
        "evaluation": {"items": [], "bonus": [], "cutoff": None},
        "agreement_period": None,
        "reception_period": None,
        "tasks": [],
        "form_examples": {"numbers": [], "dates": [], "raw": []},
    }


# ---------------------------------------------------------------------------
# 본체
# ---------------------------------------------------------------------------


def extract_form(program_id: str, text: str | None) -> dict[str, Any]:
    """공고문 텍스트 → 양식. 텍스트가 없거나 양식 절이 없으면 표준 양식(사유 포함)."""
    plain_id = program_id.removeprefix("bizinfo-")
    if not text:
        return standard_form(plain_id, REASON_NO_TEXT)
    lines = _lines(text)
    bounds = _form_bounds(lines)
    if bounds is None:
        return standard_form(plain_id, REASON_NO_FORM)
    start, end = bounds
    region = lines[start + 1 : end]
    reference_at = next((i for i, line in enumerate(region) if _REFERENCE_RE.match(line) and re.search(r"비목|집행", line)), len(region))
    form_lines = region[:reference_at]
    reference_lines = region[reference_at:]

    title_parts: list[str] = []
    for line in form_lines:
        if not line or line.startswith(("※", "□")):
            break
        title_parts.append(line)

    sections: list[dict[str, Any]] = []
    owner: list[tuple[str | None, str | None]] = [(None, None)] * len(form_lines)
    majors = [i for i, line in enumerate(form_lines) if _MAJOR_RE.match(line)]
    for n, index in enumerate(majors):
        stop = majors[n + 1] if n + 1 < len(majors) else len(form_lines)
        section_key = f"S{n + 1}"
        title, note = _clean_title(_MAJOR_RE.match(form_lines[index]).group(1))
        body = form_lines[index + 1 : stop]
        head, blocks = _item_blocks(body)
        items: list[dict[str, Any]] = []
        offset = index + 1 + len(head)
        for block in blocks:
            names = _block_names(block)
            block_items = []
            for name, how in names:
                if any(existing["title"] == name for existing in items):
                    continue
                item = {
                    "key": f"{section_key}-{len(items) + 1}",
                    "title": name,
                    "guide": _guide_text(block) if name not in _OPTIONAL_ITEMS else "",
                    "optional": name in _OPTIONAL_ITEMS,
                    "recognized_by": how,
                }
                items.append(item)
                block_items.append(item)
            main = next((it for it in block_items if not it["optional"]), None)
            for k in range(len(block)):
                owner[offset + k] = (section_key, main["key"] if main else None)
            offset += len(block)
        for k in range(index, index + 1 + len(head)):
            owner[k] = (section_key, None)
        sections.append({
            "key": section_key,
            "title": title,
            "note": note,
            "fields": _fields(head) if not items or head else [],
            "items": items,
        })
    # 소항목이 없는 대항목(일반 현황 · 기업 현황)은 칸 이름을 절 전체에서 찾는다.
    for n, index in enumerate(majors):
        stop = majors[n + 1] if n + 1 < len(majors) else len(form_lines)
        if not sections[n]["items"]:
            sections[n]["fields"] = _fields(form_lines[index + 1 : stop])
    for k in range(0, majors[0] if majors else 0):
        owner[k] = (None, None)

    if not sections:
        return standard_form(plain_id, REASON_NO_FORM)

    form_text = "\n".join(form_lines)
    return {
        "version": FORM_VERSION,
        "program_id": plain_id,
        "source": "notice",
        "reason": None,
        "notice": None,
        "heading": lines[start],
        "title": " ".join(title_parts) or None,
        "sections": sections,
        "tables": _tables(form_lines, owner),
        "rules": _rules(form_text),
        "budget": _budget(text, form_lines, reference_lines),
        "evaluation": _evaluation(lines),
        "agreement_period": _agreement_period(text),
        "reception_period": _reception_period(lines),
        "tasks": _tasks(lines),
        "form_examples": _examples(form_lines),
    }


def build_form(program_id: str) -> dict[str, Any]:
    """받아 둔 공고문에서 양식을 뽑는다(id 에 `bizinfo-` 가 붙어 있어도 된다)."""
    plain_id = program_id.removeprefix("bizinfo-")
    text = bizinfo_document_store.load_text(plain_id)
    return in_kind_form(extract_form(plain_id, text), support_requirement_extractor.load(plain_id), text)


#: 받는 돈이 있다는 조항 — 하나라도 있으면 무료(현물) 지원만의 공고가 아니다.
_PAID_MONEY_KINDS = frozenset({"cap", "range", "monthly", "government_share", "self_share"})
#: 공고가 **첨부 신청서식**을 쓰라고 하는가 — 그러면 본문에 사업계획서 양식이 없는 것이 맞다.
_ATTACHED_FORM_RE = re.compile(r"첨부\s*서식|신청\s*서식|공고\s*게시문\s*내")
IN_KIND_NOTE = "공고가 무료(현물) 지원이라 사업비 표와 집행 계획을 뺍니다"
ATTACHED_FORM_NOTE = "공고가 첨부 신청서식을 쓰라고 합니다 — 이 표준 양식 초안은 참고용입니다"


def in_kind_form(form: dict[str, Any], requirements: Any, text: str | None = None) -> dict[str, Any]:
    """표준 양식을 공고에 맞춘다 (27차 §3-C-8 검수 D1 · D3).

    123852(광주 SW 품질 컨설팅 · 테스팅 **무료** 지원)에 창업 표준 양식을 씌우자 AI 가 사업비 표에 인건비 · 외주용역비를
    채우고 집행 계획에 사업비 편성 문장을 썼다 — 공고에 현금 사업비 · 한도 · 자부담이 없는데. 돈 조항이 「무료」뿐이면
    사업비 표와 집행 계획(S3-3)을 빼고 `budget.mode = "in_kind"` 로 둔다(검증이 사업비 문장을 표시한다).
    첨부 신청서식을 쓰라는 공고면 안내 글에 한 줄 더한다. 공고 양식(source=notice)은 공고가 정한 것이라 건드리지 않는다.
    """
    if form.get("source") != "standard":
        return form
    notes = [form.get("notice") or ""]
    if text and form.get("reason") == REASON_NO_FORM and _ATTACHED_FORM_RE.search(text):
        notes.append(ATTACHED_FORM_NOTE)
    money = list(requirements.of("money")) if requirements is not None and getattr(requirements, "document_read", False) else []
    free = any(c.detail.get("kind") == "free" for c in money) and not any(c.detail.get("kind") in _PAID_MONEY_KINDS for c in money)
    if free:
        notes.append(IN_KIND_NOTE)
        form = {
            **form,
            "sections": [{**section, "items": [item for item in section["items"] if item["key"] != "S3-3"]} for section in form["sections"]],
            "tables": [table for table in form["tables"] if table["key"] != "budget"],
            "budget": {**form["budget"], "mode": "in_kind"},
        }
    return {**form, "notice": " · ".join(n for n in notes if n)}


# ---------------------------------------------------------------------------
# 과제 고르기 · 저장
# ---------------------------------------------------------------------------


def rank_tasks(tasks: list[dict[str, Any]], company_words: list[str]) -> list[dict[str, Any]]:
    """회사 사업영역 · 역량과 낱말이 겹치는 과제를 위로 (규칙). **고르는 것은 사람이다.**"""
    words = {w for text in company_words for w in re.findall(r"[가-힣A-Za-z]{2,}", text)}
    ranked = []
    for task in tasks:
        text = f"{task.get('title') or ''} {task.get('agency') or ''}"
        hits = sorted({w for w in words if w in text})
        ranked.append({**task, "match_words": hits})
    return sorted(ranked, key=lambda t: (-len(t["match_words"]), t["no"]))


def _form_path(context: AnalysisContext, program_id: str) -> Path:
    return org_storage.storage_for(context.organization_id).analysis_dir(program_id) / FILE_NAME


def load_saved(context: AnalysisContext, program_id: str) -> dict[str, Any]:
    path = _form_path(context, program_id)
    if not path.exists():
        return {}
    data = storage.read_json(path)
    return data if isinstance(data, dict) else {}


def form_for(context: AnalysisContext, program_id: str, *, task_no: int | None = None) -> dict[str, Any]:
    """양식 + 고른 과제. `task_no` 를 주면 그 과제를 고른 것으로 저장한다(없는 번호면 ValueError)."""
    form = build_form(program_id)
    saved = load_saved(context, program_id)
    selected = saved.get("selected_task")
    if task_no is not None:
        selected = next((t for t in form["tasks"] if t["no"] == task_no), None)
        if selected is None:
            raise ValueError(f"과제 번호 {task_no} 가 이 공고의 과제 표에 없습니다")
    form["selected_task"] = selected
    return form


def save_form(context: AnalysisContext, program_id: str, form: dict[str, Any]) -> Path:
    path = _form_path(context, program_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    storage.write_json_atomic(path, form)
    return path


def remember_kept(context: AnalysisContext, program_id: str, reason: str) -> None:
    """옛 AI 초안을 유지한 사유를 남긴다 — 다시 열어도(GET) 「새 AI 초안 없음: 사유」 한 줄이 남게 (27차 R26-15).

    고른 과제는 건드리지 않는다. 새 초안이 저장되면 `save_form` 이 새 양식으로 덮어 사유도 사라진다.
    """
    saved = load_saved(context, program_id)
    saved["kept_reason"] = reason
    save_form(context, program_id, saved)


def kept_reason(context: AnalysisContext, program_id: str) -> str | None:
    value = load_saved(context, program_id).get("kept_reason")
    return str(value) if value else None


#: 과제소개서 발췌 상한(글자) — 126482 실측: 과제 22개 1,161~10,800자 · 17번만 6,000자를 넘는다(30차 §3-A).
ANNEX_LIMIT = 6000
#: 과제 머리 줄 — 「과제4 서울특별시 강동송파교육지원청 과제소개서」 · 「과제 17 공무원연금공단 과제소개서」(띄어쓰기 섞임).
#: 목차 줄(「4. … 과제소개서 ····· 14」)은 「과제」로 시작하지 않고 쪽 번호로 끝나 걸리지 않는다.
#: 같은 기관 과제가 둘이면 「과제소개서(1)」 · 「(2)」 꼬리가 붙는다(126482 실측 5~12번).
_ANNEX_HEAD_RE = re.compile(r"^\s*과제\s*(\d{1,2})\s+\S.*과제\s*소개서\s*(?:\(\s*\d\s*\))?\s*$")
#: 과제 절의 덩어리 머리 — 「□ …」 · 「< … >」 · 「◦ (…)」. 과제마다 덩어리 이름이 다르다(17번은 「(데이터 파이프라인)」 꼴).
_ANNEX_SPLIT_RE = re.compile(r"^\s*(?:□|<|◦\s*\()")
#: 6,000자가 넘으면 이 이름의 덩어리를 먼저 담는다 — 개요 · 문제점 · 공공데이터 · 협업 요구사항 · 기준요건 · 협업 계획 · 협업 지원.
_ANNEX_PRIORITY_RE = re.compile(r"개\s*요|문제점|공공\s*데이터|협업\s*요구|기준\s*요건|협업\s*및\s*활용|협업\s*지원|과제\s*제안")
#: 기준요건 덩어리 머리.
_ANNEX_REQUIREMENT_HEAD_RE = re.compile(r"^\s*<\s*협업\s*창업기업\s*기준\s*요건")
#: 기준요건 덩어리의 한 줄 — 「▪ …」.
_ANNEX_BULLET_RE = re.compile(r"^\s*[▪■▸]\s*(.+)$")


def _annex_text(program_id: str) -> str | None:
    """받아 둔 과제소개서 텍스트(쪽 구분 · 쪽 번호 줄 없이). **텍스트 파일만** 읽는다 — 없으면 None.

    원본(PDF · HWP)을 여기서 다시 읽지 않는다(32차 R31-32): 텍스트는 받기(`fetch_annex`)가 스레드에서 뽑아 둔다. 첫 받기가
    끝나기 전에 /plan 을 열면 원본을 이 자리(이벤트 루프)에서 읽어 서버가 약 17초 멈췄다 · 실패한 파일도 매번 다시 읽었다(R30-20).
    """
    plain_id = program_id.removeprefix("bizinfo-")
    text_file = bizinfo_document_store.DOCS_DIR / f"{plain_id}.{bizinfo_document_store.ANNEX_TAG}.txt"
    try:
        if not text_file.exists():
            return None
        text = text_file.read_text(encoding="utf-8")
    except OSError:  # 못 읽으면 없는 것처럼(지어내지 않음)
        return None
    lines = [ln for ln in _PAGE_MARK_RE.sub("\n", text).splitlines() if not _PAGE_FOOTER_RE.match(ln.strip())]
    return "\n".join(lines)


#: 다른 과제가 시작되는 줄 — 「과제 5 …」로 시작하면(머리 꼴이 아니어도) 앞 과제 절은 거기서 끝난다(31차 R30-21).
#: 「과제 2. 농업기술 …」처럼 번호 뒤에 마침표가 오면 절 안의 목록 번호라 끝으로 보지 않는다(126482 과제 13 실측).
_ANNEX_OTHER_TASK_RE = re.compile(r"^\s*과제\s*(\d{1,2})(?![\d.])\s")
#: 머리 줄의 기관 이름 — 「과제17 공무원연금공단 과제소개서」의 가운데. 이것이 없으면 과제 머리가 아니다.
_ANNEX_AGENCY_RE = re.compile(r"^\s*과제\s*\d{1,2}\s+(.*?)\s*과제\s*소개서")


def annex_sections(text: str) -> dict[int, str]:
    """과제소개서 텍스트 → {과제 번호: 그 과제 절} (31차 R30-21 — 다른 과제소개서에서 잘림 · 섞임 · 목차 조각이 났다).

    - 절은 머리 줄부터 **다음 「과제N」으로 시작하는 줄** 앞까지(머리 꼴이 아니어도 다른 과제가 시작되면 끝).
    - 같은 번호 머리가 잇달아 나오면(쪽마다 되풀이되는 머리) 이어 붙인다.
    - 같은 번호가 떨어진 곳에 또 나오면(목차 · 개요 목록) **가장 긴 덩어리**를 쓴다.
    - 머리에 기관 이름이 없거나(2글자 미만) 본문이 없는 덩어리는 과제 절이 아니다 — 그 번호는 없다(None · 지어내지 않음).
    """
    lines = text.splitlines()
    blocks: list[tuple[int, int, int]] = []  # (번호, 시작 줄, 끝 줄)
    for i, line in enumerate(lines):
        head = _ANNEX_HEAD_RE.match(line)
        if not head:
            continue
        agency = _ANNEX_AGENCY_RE.match(line)
        if not agency or len(re.sub(r"[^가-힣A-Za-z]", "", agency.group(1))) < 2:
            continue
        no = int(head.group(1))
        end = next((j for j in range(i + 1, len(lines)) if (m := _ANNEX_OTHER_TASK_RE.match(lines[j])) and int(m.group(1)) != no), len(lines))
        if blocks and blocks[-1][0] == no and blocks[-1][2] >= i:
            continue  # 앞 덩어리 안에서 되풀이된 같은 번호 머리 — 이미 담았다
        if blocks and blocks[-1][0] == no and all(not lines[k].strip() for k in range(blocks[-1][2], i)):
            blocks[-1] = (no, blocks[-1][1], end)  # 잇달아 나온 같은 번호 — 이어 붙인다
        else:
            blocks.append((no, i, end))
    out: dict[int, str] = {}
    for no, start, end in blocks:
        section = "\n".join(lines[start:end]).strip()
        if len(section.splitlines()) < 2:
            continue  # 머리만 있는 조각(목차 줄 등)
        if len(section) > len(out.get(no, "")):
            out[no] = section
    return out


def _annex_shrink(section: str, limit: int) -> str:
    """긴 과제 절 — 머리 줄 + 덩어리를 상한 안에. 중요한 이름의 덩어리(개요 · 문제점 · 공공데이터 · 협업 요구사항 ·
    기준요건 · 협업 계획)를 먼저 고르고 남는 자리에 나머지를 고른 뒤 **원래 차례로** 잇는다. 고른 것이 하나도 안 들어가면 줄 경계에서 자른다."""
    lines = section.splitlines()
    head, body = lines[0].strip(), lines[1:]
    starts = [i for i, line in enumerate(body) if _ANNEX_SPLIT_RE.match(line)]
    if not starts or starts[0] != 0:
        starts = [0, *starts]
    blocks = ["\n".join(body[s : (starts[k + 1] if k + 1 < len(starts) else len(body))]).strip() for k, s in enumerate(starts)]
    order = [i for i, b in enumerate(blocks) if _ANNEX_PRIORITY_RE.search(b.splitlines()[0] if b else "")]
    order += [i for i in range(len(blocks)) if i not in order]
    chosen: set[int] = set()
    used = len(head)
    for i in order:
        if blocks[i] and used + len(blocks[i]) + 1 <= limit:
            chosen.add(i)
            used += len(blocks[i]) + 1
    if not chosen:
        cut = section[:limit]
        return cut[: cut.rfind("\n")] if "\n" in cut else cut
    return "\n".join([head, *(blocks[i] for i in sorted(chosen))])


def annex_excerpt(program_id: str, task: dict[str, Any] | None, *, limit: int = ANNEX_LIMIT) -> str | None:
    """과제소개서([별첨 1])가 받아져 있으면 **고른 과제 번호의 절만** 발췌한다 (30차 §3-A). 없거나 못 찾으면 None.

    예전에는 과제 제목 앞 12자 자리부터 2,000자를 잘라 과제 머리를 놓치고 긴 과제는 앞만 남았다(검수 recheck22 §4).
    """
    if not task or task.get("no") is None:
        return None
    text = _annex_text(program_id)
    section = annex_sections(text).get(int(task["no"])) if text else None
    if not section:
        return None
    return section if len(section) <= limit else _annex_shrink(section, limit)


def annex_task_requirements(program_id: str) -> dict[int, list[str]]:
    """과제마다 「협업 창업기업 기준요건 및 요구사항」의 ▪ 줄(있는 그대로 · 점수 · 판정 없음) — 과제 고르기 돕기(30차 §3-A)."""
    text = _annex_text(program_id)
    if not text:
        return {}
    out: dict[int, list[str]] = {}
    for no, section in annex_sections(text).items():
        rows: list[str] = []
        inside = False
        for line in section.splitlines():
            if _ANNEX_REQUIREMENT_HEAD_RE.match(line):
                inside = True
                continue
            if inside and re.match(r"^\s*[□<]", line):
                break  # 다음 덩어리(「< 역할 및 추진 로드맵」 · 「□ 협업 및 활용 계획」)에서 끝
            bullet = _ANNEX_BULLET_RE.match(line) if inside else None
            if bullet:
                rows.append(bullet.group(1).strip())
            elif inside and rows and line.strip() and not re.match(r"^\s*[<◦□※]", line):
                rows[-1] = f"{rows[-1]} {line.strip()}"  # 줄이 넘어간 ▪ 항목을 잇는다
        if rows:
            out[no] = rows[:12]
    return out
