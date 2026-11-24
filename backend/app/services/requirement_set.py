"""요구사항 집합의 신원 — 안정 ID · 집합 해시 · 두 집합의 차이.

## 왜 필요한가

추출 규칙을 고치면 같은 공고에서 요구사항이 32건 → 56건이 된다. 그런데 식별자가
`REQ-001` 부터의 **문서 등장 순서 일련번호** 하나뿐이라(`rfp_extractor.py:842`),
문서 중간에 항목이 하나 끼면 뒤 번호가 전부 한 칸씩 밀린다.

실측(g2b-R26BK01707959-000, 2026-09-11): 저장된 제안서 19문장 중 5문장이 다른
요구사항을 가리키고 있었다. PS-15 는 「자료 목적 외 사용 금지」를 쓴 문장인데
REQ-017 을 가리키고, 지금 REQ-017 은 「이수자 관리 추가 제안」이다. Auditor 는 이미
대응된 요구사항을 「미반영」으로, 대응 없는 요구사항을 「반영됨」으로 본다.
**건수가 늘어난 문제가 아니라 조용한 오답이다.**

## 어떻게 푸는가

세 겹으로 나눈다.

- `requirement_id` (REQ-nnn) — **바꾸지 않는다.** 스키마가 `^REQ-\\d{3}$` 로 형식을
  고정했고 제안서·근거·조건·행동·감사·자격·정정이 전부 이 짧은 문자열을 외래키로 쓴다.
  여기를 건드리면 저장된 모든 것이 끊긴다.
- `display_code` (TSK-nnn) — 화면 표시용. 이미 있다(`item_classifier.display_code`).
- `stable_id` (SR-<16hex>) — **이 모듈이 새로 만든다.** 내용에서 결정론적으로 나오므로
  번호가 밀려도 같은 요구사항이면 같은 값이다. 제안서·감사가 「어느 요구사항에
  대응했는가」를 기록할 때 이것을 쓴다.

## 안정 ID 를 무엇으로 만드는가

쓸 수 있는 재료가 제한돼 있다. 저장되는 18개 필드 중

- `page` — HWP 는 문단 40개 묶음의 **근사값**이다(`document_extractor.PARAGRAPHS_PER_PAGE`).
  추출 규칙이 바뀌면 문단 수와 함께 통째로 밀린다. 앵커로 못 쓴다.
- `category` — 직전 절 제목에서 정규식으로 «추론»한 값이다. 절 제목 인식 규칙을
  고치면 바뀐다. 실제로 지난 작업에서 6건이 「일정」 → 「보안」으로 옮겨갔다.
- `source_text` — 원문 줄 그대로다. **문서가 바뀌지 않는 한 바뀌지 않는다.**

그래서 `(procurement_id, 정규화한 source_text, 같은 원문의 몇 번째인가)` 를 쓴다.
마지막 항이 필요한 이유는 같은 문장이 문서에 두 번 나올 수 있어서다 — 그때
둘을 같은 것으로 뭉뚱그리면 한쪽이 영영 미탐이 된다.

`document`(첨부 파일명)는 **재료에서 뺐다.** 실측(2026-09-14, g2b-R26BK01707959-000):

    v001.json  document='1_2. 제안요청서(피지컬 AI).hwp'  n=56  첫 항목 SR-ecfae8c008ec37b3
    v002.json  document='2. 제안요청서(피지컬 AI).hwp'    n=55  첫 항목 SR-53862f24afcdbeed

같은 첨부를 다시 내려받으면서 파일명 앞의 `1_` 하나가 사라졌다. 그것만으로 같은
문장의 안정 ID 가 전부 갈렸고, 저장된 제안서 19문장의 `stable_requirement_id` 가
지금 요구사항과 **0/19** 매치가 됐다. 파일명은 «전달 방식»이지 «신원»이 아니다 —
신원은 「이 공고의 이 문장」이다.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Iterable, Literal

# ---------------------------------------------------------------------------
# 정규화
# ---------------------------------------------------------------------------

#: 글머리표·번호 매김. 원문 줄 앞에 붙는 것들로, 추출 규칙이 바뀌면 붙었다 떨어졌다 한다.
#: 같은 문장이 「○ 교육 운영」과 「교육 운영」으로 오가도 같은 항목이어야 한다.
_LEADING_MARKER_RE = re.compile(
    r"^\s*(?:"
    r"[○◦●◇◆□■▪▫·∙⦁•\-–—*]"
    r"|\(?\d{1,2}[.)]"
    r"|[가-힣][.)]"
    r"|[ⓐ-ⓩ①-⑳]"
    r"|[IVXivx]{1,4}[.)]"
    r")\s*"
)

#: 눈에 보이지 않는 글자. HWP 추출물에 섞여 들어오고 판본마다 다르다.
_INVISIBLE_RE = re.compile(r"[​-‏‪-‮﻿\xa0]")


def normalize_source(text: str) -> str:
    """안정 ID 를 뽑기 전에 원문을 다듬는다.

    지우는 것은 «표기 흔들림»뿐이다 — 글머리표, 보이지 않는 글자, 공백 차이,
    전각/반각 차이. **낱말도 숫자도 지우지 않는다.** 지우면 다른 요구사항이
    같은 ID 를 받는다.
    """
    if not text:
        return ""
    # 전각 영숫자·괄호를 반각으로. HWP 는 같은 글자를 판본마다 다르게 내보낸다.
    cleaned = unicodedata.normalize("NFKC", text)
    cleaned = _INVISIBLE_RE.sub("", cleaned)
    # 여러 줄로 이어 붙인 원문은 줄바꿈 자리가 규칙에 따라 달라진다 — 공백 하나로 본다.
    cleaned = re.sub(r"\s+", " ", cleaned)
    # 줄 앞 글머리표는 반복해서 붙을 수 있다 (「○ 가. 교육 운영」).
    for _ in range(3):
        stripped = _LEADING_MARKER_RE.sub("", cleaned, count=1)
        if stripped == cleaned:
            break
        cleaned = stripped
    return cleaned.strip()


def _digest(*parts: str) -> str:
    joined = "␟".join(parts)  # 실제 본문에 나올 수 없는 구분자
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def source_text_hash(source_text: str) -> str:
    """정규화한 원문의 해시 16자. 같은 원문 ⇒ 같은 값."""
    return _digest(normalize_source(source_text))[:16]


# ---------------------------------------------------------------------------
# 안정 ID
# ---------------------------------------------------------------------------


def stable_requirement_id(
    *,
    procurement_id: str,
    document: str = "",
    source_text: str,
    ordinal: int = 0,
) -> str:
    """요구사항의 영구 식별자. `SR-` + 16자.

    `ordinal` 은 «같은 원문이 이 공고에서 몇 번째로 나왔는가»다(0부터).
    같은 문장이 두 번 나오는 문서가 실제로 있어서 필요하다 — 뭉뚱그리면
    둘 중 하나가 영영 대응을 못 받는다.

    `document` 는 **받지만 해시에 쓰지 않는다**(2026-09-14). 첨부 파일명은
    같은 파일을 다시 내려받는 것만으로 바뀐다 — 실측으로 `1_2. 제안요청서…hwp`
    → `2. 제안요청서…hwp` 가 되면서 56건 전체의 안정 ID 가 갈렸고, 저장된 제안서
    19문장이 전부 미아가 됐다(0/19). 인자를 지우지 않는 것은 호출부가 여럿이고
    저장 payload 에 `document` 가 남아 있어서다. 새 호출부는 넘기지 않아도 된다.
    """
    del document  # 신원의 재료가 아니다. 위 docstring 의 실측 사고를 참고할 것.
    return "SR-" + _digest(procurement_id, normalize_source(source_text), str(ordinal))[:16]


def source_locator(page: int | None, ordinal: int) -> str:
    """원문 위치 표기. 안정 ID 의 재료가 **아니다** — 사람이 찾아가라고 적는 값이다.

    HWP 의 page 는 근사값이라 앵커로 쓸 수 없다(모듈 docstring 참고).
    """
    return f"p{page}#{ordinal}" if page else f"p?#{ordinal}"


def assign_identity(
    requirements: list[dict[str, Any]],
    *,
    procurement_id: str,
    document: str = "",
    recompute: bool = False,
) -> int:
    """요구사항 목록에 stable_id · source_text_hash · source_locator 를 채운다.

    이미 `stable_id` 가 있는 항목은 건드리지 않는다 — 한 번 정해진 신원은 바뀌지 않는다.
    바꾼 항목 수를 돌려준다.

    `recompute=True` 는 **이미 찍힌 stable_id 도 지금 규칙으로 다시 계산한다.**
    마이그레이션 전용이다. 안정 ID 는 내용에서 결정론적으로 나오는 «파생값»이라
    규칙이 바뀌면 다시 계산하는 것이 추측이 아니라 정정이다. 다만 다시 계산하면
    이 값을 가리키던 제안서가 끊기므로, 부르는 쪽이 옛 값 → 새 값 대응표를 만들어
    함께 옮겨야 한다(scripts/migrate_requirement_sets.py 가 그렇게 한다).
    """
    seen: dict[str, int] = {}
    changed = 0
    for req in requirements:
        source = str(req.get("source_text") or req.get("content") or "")
        key = source_text_hash(source)
        ordinal = seen.get(key, 0)
        seen[key] = ordinal + 1
        fresh = stable_requirement_id(
            procurement_id=procurement_id, document=document, source_text=source, ordinal=ordinal
        )
        if not req.get("stable_id"):
            req["stable_id"] = fresh
            changed += 1
        elif recompute and req["stable_id"] != fresh:
            req["stable_id"] = fresh
            changed += 1
        if not req.get("source_text_hash") or (recompute and req["source_text_hash"] != key):
            req["source_text_hash"] = key
            changed += 1
        if not req.get("source_locator"):
            page = req.get("page")
            req["source_locator"] = source_locator(page if isinstance(page, int) else None, ordinal)
            changed += 1
    return changed


# ---------------------------------------------------------------------------
# 집합 해시
# ---------------------------------------------------------------------------


def _identity_row(req: dict[str, Any]) -> str:
    """집합 해시에 들어가는 한 줄.

    **번호도 정렬 순서도 넣지 않는다.** 내용이 같고 순서만 바뀐 집합은 같은 집합이다.
    대신 대응 방식을 바꾸는 값(필수/선택, 항목 유형)은 넣는다 — 그것이 바뀌면
    제안서가 다시 검토돼야 한다.

    첨부 파일명은 여기에도 들어가지 않는다. `stable_id` 를 통해 간접적으로 섞여
    들어가고 있었는데(그 재료에 document 가 있었다), 2026-09-14 에 그것을 뺐다.
    이제 집합 해시는 첨부 파일명이 바뀌어도 흔들리지 않는다.
    """
    return "␞".join(
        [
            str(req.get("stable_id") or req.get("source_text_hash") or ""),
            str(req.get("requirement_type") or "mandatory"),
            str(req.get("item_type") or "REQUIREMENT"),
            str(req.get("response_scope") or ""),
        ]
    )


def set_hash(requirements: Iterable[dict[str, Any]]) -> str:
    """요구사항 집합의 해시 16자.

    정렬해서 넣으므로 **추출 순서가 바뀌어도 내용이 같으면 같은 값**이다.
    """
    rows = sorted(_identity_row(req) for req in requirements)
    return _digest(*rows)[:16]


def set_id(procurement_id: str, requirement_set_hash: str) -> str:
    """집합 식별자. 같은 공고에서 같은 내용이면 같은 id 다 — 마이그레이션을 여러 번
    돌려도 새 id 가 생기지 않는다(멱등)."""
    return f"rs-{procurement_id}-{requirement_set_hash[:8]}"


def document_hash(pages: Iterable[Any]) -> str:
    """원문 문서의 해시. 「제안서를 만든 뒤 공고 첨부가 바뀌었는가」를 보기 위한 값."""
    chunks: list[str] = []
    for page in pages:
        if isinstance(page, dict):
            chunks.append(str(page.get("char_count") or ""))
            chunks.append(str(page.get("page") or ""))
        else:
            chunks.append(str(getattr(page, "char_count", "")))
            chunks.append(str(getattr(page, "page", "")))
    return _digest(*chunks)[:16]


# ---------------------------------------------------------------------------
# 집합 메타
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SetMeta:
    """한 요구사항 집합의 신원과 규모."""

    requirement_set_id: str
    requirement_set_hash: str
    requirement_set_version: int
    generated_at: str | None
    procurement_id: str
    source_document_hash: str | None
    requirement_count: int
    mandatory_count: int
    optional_or_conditional_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement_set_id": self.requirement_set_id,
            "requirement_set_hash": self.requirement_set_hash,
            "requirement_set_version": self.requirement_set_version,
            "generated_at": self.generated_at,
            "procurement_id": self.procurement_id,
            "source_document_hash": self.source_document_hash,
            "requirement_count": self.requirement_count,
            "mandatory_count": self.mandatory_count,
            "optional_or_conditional_count": self.optional_or_conditional_count,
        }


def describe(payload: dict[str, Any], *, previous: dict[str, Any] | None = None) -> SetMeta:
    """저장 payload 에서 집합 메타를 계산한다.

    `previous` 를 주면 버전을 이어 센다 — 내용이 같으면 버전을 올리지 않는다.
    (마이그레이션을 두 번 돌려도 버전이 2씩 오르지 않게 하려는 것이다.)
    """
    requirements = payload.get("requirements") or []
    procurement_id = str(payload.get("procurement_id") or "")
    digest = set_hash(requirements)

    version = 1
    prev_hash = str((previous or {}).get("requirement_set_hash") or "")
    if prev_hash:
        prev_version = int((previous or {}).get("requirement_set_version") or 0) or 1
        # 내용이 같으면 판을 올리지 않는다 — 마이그레이션을 여러 번 돌려도 1씩 오르지 않게.
        version = prev_version if prev_hash == digest else prev_version + 1
    # 이전 판에 해시가 아예 없으면 «처음 찍는 것»이지 «바뀐 것»이 아니다. 1로 시작한다.

    mandatory = sum(1 for r in requirements if str(r.get("requirement_type")) == "mandatory")
    return SetMeta(
        requirement_set_id=set_id(procurement_id, digest),
        requirement_set_hash=digest,
        requirement_set_version=version,
        generated_at=str(payload.get("generated_at")) if payload.get("generated_at") else None,
        procurement_id=procurement_id,
        source_document_hash=document_hash(payload.get("pages") or []),
        requirement_count=len(requirements),
        mandatory_count=mandatory,
        optional_or_conditional_count=len(requirements) - mandatory,
    )


# ---------------------------------------------------------------------------
# 두 집합의 차이
# ---------------------------------------------------------------------------

ChangeKind = Literal[
    "added",  # 새로 발견됨
    "removed",  # 이번 집합에 없음
    "content_changed",  # 같은 자리인데 문장이 달라짐
    "category_changed",  # 항목 유형(과업/제출/자격…)이 달라짐
    "obligation_changed",  # 필수 ↔ 선택
    "unchanged",  # 그대로
    "uncertain",  # 자동으로 잇기에 확신이 부족함 — 사람이 본다
]

#: 자동 연결을 확정하는 문장 유사도. reparse 스크립트가 쓰는 값과 같게 맞춘다.
CONFIDENT_MATCH = 0.85
#: 이 아래면 아예 다른 항목으로 본다. 사이 구간이 「사람이 확인」이다.
CANDIDATE_MATCH = 0.60


@dataclass
class ChangeEntry:
    kind: ChangeKind
    previous_requirement_id: str | None
    requirement_id: str | None
    stable_id: str | None
    item_type: str
    title: str
    similarity: float | None = None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "previous_requirement_id": self.previous_requirement_id,
            "requirement_id": self.requirement_id,
            "stable_id": self.stable_id,
            "item_type": self.item_type,
            "title": self.title,
            "similarity": self.similarity,
            "detail": self.detail,
        }


@dataclass
class SetDiff:
    entries: list[ChangeEntry] = field(default_factory=list)

    def by_kind(self, kind: ChangeKind) -> list[ChangeEntry]:
        return [e for e in self.entries if e.kind == kind]

    @property
    def counts(self) -> dict[str, int]:
        out = {k: 0 for k in ("added", "removed", "content_changed", "category_changed", "obligation_changed", "unchanged", "uncertain")}
        for entry in self.entries:
            out[entry.kind] = out.get(entry.kind, 0) + 1
        return out

    def to_dict(self) -> dict[str, Any]:
        return {"counts": self.counts, "entries": [e.to_dict() for e in self.entries]}


def _norm_for_compare(req: dict[str, Any]) -> str:
    return normalize_source(str(req.get("content") or req.get("source_text") or ""))


def diff(previous: list[dict[str, Any]], current: list[dict[str, Any]]) -> SetDiff:
    """이전 집합과 현재 집합을 견준다.

    순서가 세 단계다 — 지시서의 마이그레이션 순서와 같다.

    1. 같은 `stable_id`
    2. 같은 `source_text_hash`
    3. 정규화 문장 유사도 (0.85 이상 확정 / 0.60~0.85 는 「사람이 확인」)

    **불확실한 대응을 자동으로 확정하지 않는다.** `uncertain` 으로 남겨 사람에게 넘긴다.
    """
    out = SetDiff()
    remaining = list(current)

    def _take(pred) -> dict[str, Any] | None:
        for i, item in enumerate(remaining):
            if pred(item):
                return remaining.pop(i)
        return None

    for prev in previous:
        prev_sid = prev.get("stable_id")
        prev_hash = prev.get("source_text_hash") or source_text_hash(str(prev.get("source_text") or prev.get("content") or ""))

        match = None
        similarity: float | None = None
        if prev_sid:
            match = _take(lambda r: r.get("stable_id") == prev_sid)
        if match is None:
            match = _take(lambda r: (r.get("source_text_hash") or source_text_hash(str(r.get("source_text") or ""))) == prev_hash)
        if match is not None:
            similarity = 1.0
        else:
            # 3) 문장 유사도 — 가장 닮은 것을 찾되 확신 구간을 나눈다.
            prev_text = _norm_for_compare(prev)
            best, best_ratio = None, 0.0
            for cand in remaining:
                ratio = SequenceMatcher(None, prev_text, _norm_for_compare(cand)).ratio()
                if ratio > best_ratio:
                    best, best_ratio = cand, ratio
            if best is not None and best_ratio >= CANDIDATE_MATCH:
                match = best
                remaining.remove(best)
                similarity = round(best_ratio, 3)

        if match is None:
            out.entries.append(
                ChangeEntry(
                    kind="removed",
                    previous_requirement_id=str(prev.get("requirement_id") or ""),
                    requirement_id=None,
                    stable_id=prev_sid,
                    item_type=str(prev.get("item_type") or "REQUIREMENT"),
                    title=str(prev.get("title") or prev.get("content") or "")[:120],
                    detail="이번 요구사항 집합에는 없습니다. 이전 제안서 문장은 지우지 않고 이전 버전에 남습니다.",
                )
            )
            continue

        kind: ChangeKind
        detail = ""
        if similarity is not None and similarity < CONFIDENT_MATCH:
            kind = "uncertain"
            detail = f"문장이 {int((similarity or 0) * 100)}% 만 일치합니다. 같은 요구사항인지 사람이 확인해야 합니다."
        elif str(prev.get("requirement_type")) != str(match.get("requirement_type")):
            kind = "obligation_changed"
            detail = f"{prev.get('requirement_type')} → {match.get('requirement_type')}"
        elif str(prev.get("item_type") or "") != str(match.get("item_type") or ""):
            kind = "category_changed"
            detail = f"{prev.get('item_type')} → {match.get('item_type')}"
        elif _norm_for_compare(prev) != _norm_for_compare(match):
            kind = "content_changed"
            detail = "원문 문장이 달라졌습니다."
        else:
            kind = "unchanged"

        out.entries.append(
            ChangeEntry(
                kind=kind,
                previous_requirement_id=str(prev.get("requirement_id") or ""),
                requirement_id=str(match.get("requirement_id") or ""),
                stable_id=match.get("stable_id"),
                item_type=str(match.get("item_type") or "REQUIREMENT"),
                title=str(match.get("title") or match.get("content") or "")[:120],
                similarity=similarity,
                detail=detail,
            )
        )

    for leftover in remaining:
        out.entries.append(
            ChangeEntry(
                kind="added",
                previous_requirement_id=None,
                requirement_id=str(leftover.get("requirement_id") or ""),
                stable_id=leftover.get("stable_id"),
                item_type=str(leftover.get("item_type") or "REQUIREMENT"),
                title=str(leftover.get("title") or leftover.get("content") or "")[:120],
                detail="새로 발견된 요구사항입니다.",
            )
        )
    return out


# ---------------------------------------------------------------------------
# 제안서가 어느 집합 기준인가
# ---------------------------------------------------------------------------

ProposalBasis = Literal[
    "no_proposal",          # 초안이 아직 없다
    "current",              # 최신 요구사항 집합 기준
    "stale_requirements",   # 이전 집합 기준 — 최신 결과처럼 보여주면 안 된다
    "unknown_basis",        # 옛 저장본이라 기준 기록이 없다. 단정하지 않는다
]


def proposal_basis(
    *,
    proposal_set_hash: str | None,
    proposal_mandatory_total: int | None,
    current_set_hash: str | None,
    current_mandatory_count: int | None,
    has_proposal: bool = True,
) -> ProposalBasis:
    """초안이 최신 요구사항 집합 기준인지 판정한다.

    해시가 있으면 해시로 본다. 옛 저장본에는 해시가 없으므로 «필수 건수»를 2차
    신호로 쓴다 — 32건 기준 초안을 55건 집합과 견주는 것을 그냥 지나치면 안 된다.
    건수까지 같으면 **단정하지 않고** `unknown_basis` 로 둔다. 「최신이다」라고
    말하려면 근거가 있어야 하고, 없는 근거를 만들지 않는다(CLAUDE.md 11).
    """
    if not has_proposal:
        return "no_proposal"
    if proposal_set_hash and current_set_hash:
        return "current" if proposal_set_hash == current_set_hash else "stale_requirements"
    if proposal_mandatory_total and current_mandatory_count:
        if proposal_mandatory_total != current_mandatory_count:
            return "stale_requirements"
    return "unknown_basis"


#: 화면에 그대로 쓸 수 있는 설명. 숫자는 호출자가 채운다.
BASIS_MESSAGE: dict[str, str] = {
    "no_proposal": "아직 제안서 초안이 없습니다.",
    "current": "현재 제안서는 최신 요구사항 기준입니다.",
    "stale_requirements": "필수 요구사항이 {before}건에서 {after}건으로 변경되었습니다. 현재 제안서는 이전 필수 요구사항 기준입니다.",
    #: 건수는 그대로인데 «구성»이 바뀐 경우. 항목 하나가 다른 것으로 갈리면 이렇게 된다.
    "stale_requirements_same_count": "필수 요구사항 수는 {after}건 그대로지만 구성이 달라졌습니다. 현재 제안서는 이전 요구사항 기준입니다.",
    "unknown_basis": "이 제안서가 어느 요구사항 집합을 기준으로 만들어졌는지 기록이 없습니다. 최신 여부를 단정할 수 없습니다.",
}


def basis_message(basis: str, *, before: int | None = None, after: int | None = None) -> str:
    """화면에 그대로 쓰는 문장.

    2026-09-14 — 「필수 요구사항이 57건에서 57건으로 변경되었습니다」가 실제로 떴다.
    숫자를 그대로 끼워 넣기만 해서, 건수가 같은데 구성만 달라진 경우에 «같은 수로 변경»이라는
    말이 됐다. 담당자는 이 문장을 읽고 무엇이 바뀐 건지 알 수 없다.
    """
    if basis == "stale_requirements" and before is not None and before == after:
        return BASIS_MESSAGE["stale_requirements_same_count"].format(after=after)
    template = BASIS_MESSAGE.get(basis, "")
    if basis == "stale_requirements":
        return template.format(before=before if before is not None else "?", after=after if after is not None else "?")
    return template


# ---------------------------------------------------------------------------
# 차이를 사람이 읽는 말로
# ---------------------------------------------------------------------------

#: 항목 유형 → 「무엇이 새로 나왔는가」로 읽히는 이름.
_ADDED_LABEL: dict[str, str] = {
    "TASK": "새로 발견된 수행과업",
    "EVALUATION": "새로 발견된 평가기준",
    "SUBMISSION": "새로 발견된 제출조건",
    "ELIGIBILITY": "새로 발견된 참가자격",
    "SPECIAL_CONDITION": "새로 발견된 계약·보안조건",
    "SCHEDULE": "새로 발견된 일정 조건",
    "REQUIREMENT": "새로 발견된 요구사항",
    "REFERENCE": "새로 발견된 참고 항목",
}


def added_summary(
    diff_result: SetDiff,
    *,
    covered_stable_ids: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """새로 발견된 항목을 유형별로 묶고, 기존 초안이 이미 대응하는지 나눈다.

    「24건 증가」한 줄로 끝내면 담당자가 할 일을 알 수 없다. 무엇이 늘었고
    그중 새 문장이 필요한 것이 몇 건인지까지 적는다.
    """
    covered = set(covered_stable_ids)
    buckets: dict[str, dict[str, Any]] = {}
    for entry in diff_result.by_kind("added"):
        label = _ADDED_LABEL.get(entry.item_type, "새로 발견된 요구사항")
        bucket = buckets.setdefault(
            entry.item_type,
            {"item_type": entry.item_type, "label": label, "total": 0, "already_covered": 0, "needs_sentence": 0, "examples": []},
        )
        bucket["total"] += 1
        if entry.stable_id and entry.stable_id in covered:
            bucket["already_covered"] += 1
        else:
            bucket["needs_sentence"] += 1
        if len(bucket["examples"]) < 3:
            bucket["examples"].append({"requirement_id": entry.requirement_id, "title": entry.title})
    return sorted(buckets.values(), key=lambda b: -b["total"])
