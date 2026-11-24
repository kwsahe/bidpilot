"""화면 · 내보낸 파일이 함께 쓰는 말 (32차 §3-E).

1. **요구사항 · 조항 번호 풀이** — 「REQ-014」 → 「14번 요구사항」 · 「RFP-QC-20」 → 「20번 조항」. 프론트
   `clauseRefText`(frontend/src/lib/cosmos/format.ts)와 같은 규칙이다. 저장 값(id)은 그대로 두고 글자만 바꾼다.
2. **저장된 결과의 옛 글** — 글을 고쳐도 이미 저장된 제안서 · 점검 · 사업계획서 초안 · 공고문 메모는 옛 말
   그대로였다(검수 2026-10-21 · 구조적인 빈틈 ①). 저장 파일은 기록이라 고치지 않는다 — **읽어서 화면에 내보낼 때와
   파일로 내보낼 때** 알려진 옛 꼴만 새 말로 바꾼다. 검사 · 해시 · 비교에 쓰는 읽기 경로에는 쓰지 않는다.
"""

from __future__ import annotations

import re
from typing import Any, Final, TypeVar

from pydantic import BaseModel

_REQ_RE: Final = re.compile(r"^REQ-0*(\d+)$")
_QC_RE: Final = re.compile(r"QC-0*(\d+)$")


def requirement_label(requirement_id: str | None) -> str:
    """「REQ-014」 → 「14번 요구사항」 · 「QC-03」 · 「RFP-QC-03」 → 「3번 조항」 · 그 밖은 그대로."""
    if not requirement_id:
        return "요구사항"
    match = _REQ_RE.match(requirement_id)
    if match:
        return f"{match.group(1)}번 요구사항"
    match = _QC_RE.search(requirement_id)
    if match:
        return f"{match.group(1)}번 조항"
    return requirement_id


def rfp_ref(page: int | None, requirement_id: str | None) -> str:
    """「제안요청서 17쪽 · 14번 요구사항」 — 쪽을 모르면 「제안요청서 14번 요구사항」."""
    label = requirement_label(requirement_id)
    return f"제안요청서 {page}쪽 · {label}" if page else f"제안요청서 {label}"


# ---------------------------------------------------------------------------
# 저장된 결과의 옛 글 → 새 말. 앞에서부터 차례로 적용한다(앞 규칙의 결과를 뒤 규칙이 다시 보지 않게 겹치지 않는 꼴만).
# ---------------------------------------------------------------------------

def _req_sub(match: re.Match[str]) -> str:
    return rfp_ref(int(match.group(1)), f"REQ-{match.group(2)}")


_LEGACY_PATTERNS: Final[tuple[tuple[re.Pattern[str], Any], ...]] = (
    # 점검 권고 「RFP p.9 REQ-015 요구사항 '…'」 · 「RFP p.9 REQ-015 조건은」 · 새 판 「제안요청서 17쪽 (REQ-014) 요구사항」
    (re.compile(r"RFP p\.(\d+) REQ-0*(\d+)(?: 요구사항| 조건)?"), _req_sub),
    (re.compile(r"제안요청서 (\d+)쪽 \(REQ-0*(\d+)\)(?: 요구사항| 조건)?"), _req_sub),
    (re.compile(r"제안요청서 \(REQ-0*(\d+)\)(?: 요구사항| 조건)?"), lambda m: f"제안요청서 {m.group(1)}번 요구사항"),
    # 「… 조건은 원문만으로 충족을 확정할 수 없어 CHECK 상태입니다」(영문 판정값)
    (re.compile(r"CHECK 상태입니다"), "「확인 필요」로 남아 있습니다"),
    # 제안서 문장 꼬리 「(RFP p.3 요구사항 준수)」 — 쪽 번호는 「p.3」 꼴 그대로 둔다: 「3쪽」은 점검의 숫자 검사가 근거 없는
    # 숫자로 읽는다(proposal_service._rfp_sentence 와 같은 이유 · 31차 §3-D). 「RFP」만 화면 말로.
    (re.compile(r"\(RFP( p\.\d+)? 요구사항 준수\)"), r"(제안요청서\1 요구사항 준수)"),
    # 후보 근거의 0~1 소수 「, 유사도 0.42 — 미채택)」
    (re.compile(r", 유사도 \d?\.\d+(?= — 미채택\))"), ""),
    # 「(합성)」 → 「(가상 예시)」(31차 이름 결정 · R31-16) — **문서 이름 자리(닫는 낫표 앞)만**(33차 R32W-1).
    # 「회사소개서(합성)」 같은 우리 문서 이름이 그 자리다. 문장 속 다른 「(합성)」은 남의 글일 수 있어 그대로 둔다.
    (re.compile(r"\(합성\)(?=」)"), "(가상 예시)"),  # 화면 문장 아님 — 저장된 옛 글을 찾는 꼴
)

#: 글 전체가 정확히 이 꼴인 옛 문장(사업계획서 초안 경고 · 공고문 메모).
_LEGACY_EXACT: Final[dict[str, str]] = {
    "공고 인용 밖 내용 — AI 제안": "공고에 없는 내용입니다 — AI가 덧붙였으니 확인하세요",
    "회사 근거 밖 내용 — AI 제안": "회사 근거에 없는 내용입니다 — AI가 덧붙였으니 확인하세요",
    "공고 근거 확인 필요 — 인용한 공고 문장을 찾지 못했다": "인용한 공고 문장을 공고에서 찾지 못했습니다 — 확인하세요",
    "공고 근거 확인 필요 — 인용이 너무 짧아 공고 문장과 대조할 수 없다": "공고 인용이 너무 짧아 공고와 맞춰 보지 못했습니다 — 확인하세요",
    "근거 확인 필요 — AI가 가리킨 근거가 없습니다": "회사 근거가 없습니다 — AI가 덧붙였으니 확인하세요",
    "근거 확인 필요 — 자체 기재 역량을 검증 · 인증된 것처럼 썼다": "회사가 스스로 적은 역량을 「검증된」 것처럼 썼습니다 — 고치세요",
    "무료(현물) 지원 공고 — 사업비 · 자부담 편성 문장은 공고와 맞지 않는다": "무료 지원 공고인데 사업비 · 자부담 이야기가 있습니다 — 빼세요",
    "공고문이 이미지입니다 — 요약문으로 판정합니다": "공고문이 그림 파일이라 글을 읽지 못해, 기업마당 요약만 보고 판정했습니다",
    "원문 읽기 실패 · 요약문 기준 — 이미지 문서로 보입니다(텍스트 없음)": "공고문 파일에 글이 없어(그림 문서) 기업마당 요약만 보고 판정했습니다",
}

def download_failure_line(label: str, status: int | None) -> str:
    """기업마당 파일 서버가 원본을 주지 않았을 때 메모 한 줄(10-31 최종 점검 — httpx 영어 예외 글 · 바깥 주소가 화면에 그대로 나왔다).

    새 메모(`bizinfo_client._download_file`)와 저장된 옛 메모(아래 `_LEGACY_PREFIX`)가 같은 말을 쓴다.
    """
    if status == 403:
        return f"기업마당이 {label} 내려받기를 막았습니다(403) — 공고 원문에서 직접 받으세요"
    if status:
        return f"기업마당 파일 서버가 {label} 내려받기에 오류로 답했습니다({status}) — 공고 원문에서 직접 받으세요"
    return f"기업마당 파일 서버에 연결하지 못해 {label} 내려받기가 안 됐습니다 — 공고 원문에서 직접 받으세요"


def _http_status_of(text: str) -> int | None:
    match = re.search(r"error '(\d{3})", text)
    return int(match.group(1)) if match else None


#: 머리말 꼴 옛 경고 — 뒤에 값이 붙는다(「공고 근거 확인 필요 — 3억원」).
_LEGACY_PREFIX: Final[tuple[tuple[re.Pattern[str], Any], ...]] = (
    # 옛 내려받기 실패 메모 「공고문 내려받기 실패: Client error '403 Forbidden' for url 'https://…' For more information …」
    (re.compile(r"^(공고문|첨부) 내려받기 실패: (.*)$", re.S),
     lambda m: download_failure_line(m.group(1), _http_status_of(m.group(2)))),
    (re.compile(r"^공고 근거 확인 필요 — (.+)$"), lambda m: f"공고에 없는 값이 있습니다: {m.group(1)} — 확인하세요"),
    (re.compile(r"^근거 확인 필요 — (.+)$"), lambda m: f"회사 근거에 없는 말이 있습니다: {m.group(1)} — 확인하세요"),
    (re.compile(r"^일정표와 단계 수가 다르다 — 본문 (\d+)단계 · 일정표 (\d+)행$"),
     lambda m: f"본문은 {m.group(1)}단계인데 일정표는 {m.group(2)}줄입니다 — 맞추세요"),
    (re.compile(r"^금칙어 — (.+)$"), lambda m: f"쓰면 안 되는 말: {m.group(1)}"),
    (re.compile(r"^공고 문장 복사 — (.+)$"), lambda m: f"공고 문장과 거의 같습니다 — 우리 말로 바꾸세요({m.group(1)})"),
)


def modernize_text(text: str) -> str:
    """옛 글 한 줄 → 새 말. 모르는 글은 그대로."""
    exact = _LEGACY_EXACT.get(text)
    if exact is not None:
        return exact
    for pattern, repl in _LEGACY_PREFIX:
        match = pattern.match(text)
        if match:
            return repl(match)
    for pattern, repl in _LEGACY_PATTERNS:
        text = pattern.sub(repl, text)
    return text


#: 옛 글을 바꾸는 칸 — 우리가 만든 문장이 들어가는 자리(점검 권고 · 제안서 · 초안 문장 · 경고 · 메모 · 공고문 판 메모).
#: 그 밖의 칸(`source_text` · `source` · `quotes` · 문서 이름 …)은 공고 · 회사 **원문 인용**이라 그대로 둔다(33차 R32W-1 —
#: 모든 글 값에 걸어 원문 인용의 「(합성)」까지 바꿨다).
#: `proposal_text` 는 점검이 옮겨 적은 **우리 제안서 문장**이라 바꾼다(33차 마지막 검토 — 빼니 점검 화면에 「(합성)」이 다시 보였다).
TEXT_KEYS: Final[frozenset[str]] = frozenset({"recommendation", "text", "flags", "note", "notice_version", "proposal_text"})


def modernize(value: Any, _key: str | None = None) -> Any:
    """dict · list 안의 **바꿀 칸(`TEXT_KEYS`) 글 값**만 바꾼 새 사본(키는 그대로). 저장 파일은 건드리지 않는다."""
    if isinstance(value, str):
        return modernize_text(value) if _key in TEXT_KEYS else value
    if isinstance(value, dict):
        return {key: modernize(item, key) for key, item in value.items()}
    if isinstance(value, list):
        return [modernize(item, _key) for item in value]
    return value


ModelT = TypeVar("ModelT", bound=BaseModel)


def modernize_model(model: ModelT) -> ModelT:
    """pydantic 모델의 글 값만 바꾼 새 사본."""
    return type(model).model_validate(modernize(model.model_dump(mode="python")))
