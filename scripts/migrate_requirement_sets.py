"""요구사항 집합 신원 마이그레이션 — 안정 ID · 대응 범위 · 집합 해시 · 제안서 연결 복구.

무엇을 고치는가
--------------

식별자가 `REQ-001` 부터의 문서 등장 순서 일련번호뿐이라, 추출 규칙을 고쳐 요구사항이
32건 → 56건이 되자 뒤 번호가 전부 밀렸다. 그 결과 저장된 제안서가 **다른 요구사항을
가리키게** 됐다.

실측(g2b-R26BK01707959-000): 19문장 중 5문장이 어긋났다.

    PS-15 → REQ-017 이라고 적혀 있지만 실제로는 REQ-019 (자료 목적 외 사용 금지)
    PS-19 → REQ-029 라고 적혀 있지만 실제로는 REQ-039 (제안서 허위 작성 금지)

이 스크립트는 네 가지를 한다.

1. 요구사항 파일에 **안정 ID**(내용에서 나오는 영구 식별자)와 **대응 범위**,
   그리고 **집합 해시**를 찍는다.
2. 이미 찍힌 안정 ID 를 **지금 규칙으로 다시 계산한다**(2026-09-14 추가, 아래).
3. 제안서 문장이 실제로 인용한 원문으로 올바른 요구사항을 찾아 `stable_requirement_id`
   를 붙이고, 확신이 설 때만 `requirement_id` 를 바로잡는다.
4. 고치기 전 판을 버전 폴더에 보존한다.

2026-09-14 — 첨부 파일명이 안정 ID 를 갈아엎었다
------------------------------------------------

    v001.json  document='1_2. 제안요청서(피지컬 AI).hwp'  n=56  첫 항목 SR-ecfae8c008ec37b3
    v002.json  document='2. 제안요청서(피지컬 AI).hwp'    n=55  첫 항목 SR-53862f24afcdbeed

같은 첨부를 다시 받으면서 파일명 앞의 `1_` 이 사라진 것 **하나만으로** 같은 문장의
안정 ID 가 전부 바뀌었다. 저장된 제안서 19문장의 `stable_requirement_id` 는 지금
요구사항과 **0/19** 매치가 됐다. `requirement_set.stable_requirement_id()` 에서
document 를 재료에서 뺐고, 이 스크립트가 저장본을 새 규칙으로 옮긴다.

옮기는 방법은 «추측»이 아니다. 안정 ID 는 (공고 id, 정규화한 원문, 같은 원문의 몇
번째인가)에서 결정론적으로 나오므로, 저장된 각 판에서 «옛 id → 새 id» 대응표를
그대로 계산할 수 있다. 제안서 문장은 이 대응표로만 옮긴다 — 대응표에 없으면
예전처럼 인용문 유사도(0.85)로 찾고, 그래도 확신이 없으면 **손대지 않고 보고만** 한다.

지키는 것
---------

- **아무것도 지우지 않는다.** 이전 판은 `*.versions/vNNN.json` 으로 남는다.
- **멱등이다.** 여러 번 돌려도 판이 겹쳐 쌓이지 않고 번호가 오르지 않는다.
- **불확실한 대응을 자동 확정하지 않는다.** 유사도 0.85 미만은 손대지 않고 보고만 한다.

사용법
------

    python scripts/migrate_requirement_sets.py --dry-run     # 미리보기
    python scripts/migrate_requirement_sets.py               # 반영
    python scripts/migrate_requirement_sets.py g2b-R26BK01707959-000
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core import storage  # noqa: E402
from app.services import item_classifier, proposal_service, requirement_set, rfp_parser  # noqa: E402

GENERATED_DIR = ROOT / "data" / "public" / "sample_rfp" / "generated"
PROPOSALS_DIR = ROOT / "data" / "public" / "proposals"
PRIVATE_ORGS = ROOT / "data" / "private" / "organizations"

#: 제안서 문장이 요구사항을 그대로 인용한 머리말 — 「[원문…] "원문…" — …」
_QUOTE_RE = re.compile(r"^\[(?P<quoted>.+?)\]")
#: 문장 끝의 출처 표기. 대조할 때 걸리적거린다.
_CITATION_RE = proposal_service.TRAILING_NOTE_RE  # 32차 R31-23 — 새 꼴 「(제안요청서 p.17 요구사항)」도 걷는다

#: 이 아래면 손대지 않는다. reparse 스크립트와 같은 기준.
CONFIDENT = 0.85


@dataclass
class Report:
    procurement_id: str
    requirements_stamped: int = 0
    #: 이미 있던 안정 ID 를 새 규칙으로 다시 계산한 건수.
    requirements_recomputed: int = 0
    requirement_set_id: str | None = None
    requirement_set_version: int | None = None
    archived_requirements: str | None = None
    proposals_touched: list[str] = field(default_factory=list)
    #: 옛 안정 ID → 새 안정 ID 로 «정확히» 옮긴 문장. 원문이 같다는 것이 계산으로 증명된다.
    identity_remapped: list[dict[str, str]] = field(default_factory=list)
    #: 옮길 곳을 못 찾은 문장. 손대지 않았다.
    identity_orphaned: list[dict[str, str]] = field(default_factory=list)
    citations_fixed: list[dict[str, str]] = field(default_factory=list)
    citations_uncertain: list[dict[str, str]] = field(default_factory=list)
    #: 초안이 적어 둔 집합 해시가 «옛 규칙으로 계산된 같은 구성»임이 증명되어 새 표기로 옮긴 것.
    basis_hash_rewritten: list[dict[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 1) 요구사항 파일
# ---------------------------------------------------------------------------


def _content_signature(requirements: list[dict[str, Any]]) -> tuple[str, ...]:
    """요구사항 «구성»의 지문. 안정 ID 는 넣지 않는다.

    판 번호를 함부로 올리지 않기 위한 값이다. 이번 마이그레이션은 id 규칙만 바꾸는데,
    그것으로 집합 해시가 달라진다고 판 번호를 올리면 「요구사항이 또 바뀌었다」는
    거짓 신호가 된다 — 실제로 늘거나 준 것이 하나도 없는데도.
    """
    rows = [
        "␞".join(
            [
                requirement_set.source_text_hash(str(r.get("source_text") or r.get("content") or "")),
                str(r.get("requirement_type") or "mandatory"),
                str(r.get("item_type") or ""),
                str(r.get("response_scope") or ""),
            ]
        )
        for r in requirements
        if isinstance(r, dict)
    ]
    return tuple(sorted(rows))


def _remap_of(payload: dict[str, Any]) -> dict[str, str | None]:
    """이 판에서 «옛 안정 ID → 새 안정 ID» 대응을 계산한다.

    저장된 id 를 새 규칙으로 다시 계산할 뿐이라 추측이 없다. 값이 None 이면
    «같은 옛 id 가 서로 다른 새 id 로 갈린다»는 뜻이고, 그런 것은 쓰지 않는다.
    """
    procurement_id = str(payload.get("procurement_id") or "")
    out: dict[str, str | None] = {}
    seen: dict[str, int] = {}
    for req in payload.get("requirements", []) or []:
        if not isinstance(req, dict):
            continue
        source = str(req.get("source_text") or req.get("content") or "")
        key = requirement_set.source_text_hash(source)
        ordinal = seen.get(key, 0)
        seen[key] = ordinal + 1
        old = str(req.get("stable_id") or "")
        if not old:
            continue
        fresh = requirement_set.stable_requirement_id(
            procurement_id=procurement_id, source_text=source, ordinal=ordinal
        )
        if old in out and out[old] != fresh:
            out[old] = None  # 갈렸다 — 자동으로 고르지 않는다
        else:
            out[old] = fresh
    return out


def identity_remap(procurement_id: str) -> dict[str, str]:
    """지금 저장본과 **보존된 모든 이전 판**에서 모은 옛 id → 새 id 대응표.

    제안서가 가리키는 옛 id 는 지금 파일이 아니라 «그때 그 판»의 것일 수 있다.
    실측: g2b-R26BK01707959-000 제안서의 19개 id 는 전부 v001(첨부명 `1_2. …`) 것이었다.
    그래서 보존된 판까지 훑는다. 보존 파일 자체는 **고치지 않는다** — 그때의 기록이다.
    """
    merged: dict[str, str | None] = {}
    payloads: list[dict[str, Any]] = []
    current = storage.read_json(GENERATED_DIR / f"{procurement_id}.requirements.json")
    if isinstance(current, dict):
        payloads.append(current)
    payloads.extend(rfp_parser.list_versions(procurement_id))
    for payload in payloads:
        for old, fresh in _remap_of(payload).items():
            if old in merged and merged[old] != fresh:
                merged[old] = None
            else:
                merged[old] = fresh
    return {old: fresh for old, fresh in merged.items() if fresh}


def legacy_set_hash(payload: dict[str, Any]) -> str | None:
    """이 payload 를 **옛 규칙**(안정 ID 재료에 첨부 파일명이 들어가던)으로 해시하면 얼마인가.

    제안서에는 만들 당시의 집합 해시가 적혀 있다. 그런데 안정 ID 규칙이 바뀌면서
    같은 구성인데도 집합 해시가 갈렸다 — 실측: g2b-R26BK01718694-000 은 요구사항이
    한 건도 바뀌지 않았는데(전체 60 · 필수 57 그대로) 제안서가 「이전 기준」으로 밀리고
    화면이 「필수 요구사항이 57건에서 57건으로 변경되었습니다」라고 말했으며,
    제출 전 점검은 409 로 막혔다.

    여기서 옛 해시를 **다시 계산**해 제안서가 적어 둔 값과 대조한다. 같으면 «구성은
    그대로이고 규칙만 바뀐 것»이 계산으로 증명되므로 새 해시로 옮겨도 된다. 다르면
    진짜로 다른 집합을 본 것이니 손대지 않는다.
    """
    requirements = [r for r in payload.get("requirements") or [] if isinstance(r, dict)]
    if not requirements:
        return None
    procurement_id = str(payload.get("procurement_id") or "")
    document = str(payload.get("document") or "")
    seen: dict[str, int] = {}
    rows: list[str] = []
    for req in requirements:
        source = str(req.get("source_text") or req.get("content") or "")
        key = requirement_set.source_text_hash(source)
        ordinal = seen.get(key, 0)
        seen[key] = ordinal + 1
        legacy_id = "SR-" + requirement_set._digest(  # noqa: SLF001 — 옛 규칙을 그대로 재현해야 한다
            procurement_id, document, requirement_set.normalize_source(source), str(ordinal)
        )[:16]
        rows.append(
            "␞".join(
                [
                    legacy_id,
                    str(req.get("requirement_type") or "mandatory"),
                    str(req.get("item_type") or "REQUIREMENT"),
                    str(req.get("response_scope") or ""),
                ]
            )
        )
    return requirement_set._digest(*sorted(rows))[:16]  # noqa: SLF001


def migrate_requirements(path: Path, *, dry_run: bool) -> tuple[Report, dict[str, Any]]:
    payload = storage.read_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"읽을 수 없는 파일: {path}")
    report = Report(procurement_id=str(payload.get("procurement_id") or path.stem))

    already = sum(1 for r in payload.get("requirements", []) if isinstance(r, dict) and r.get("stable_id"))
    total = len(payload.get("requirements", []))

    # 고치기 전 판을 보존한다 (이미 보존돼 있으면 다시 쓰지 않는다).
    if not dry_run:
        archived = rfp_parser.archive_previous(report.procurement_id)
        report.archived_requirements = str(archived.relative_to(ROOT)) if archived else None

    # 항목 유형 필드 + 안정 ID + 집합 신원. enrich 는 «비어 있을 때만» 채운다.
    approx = bool(payload.get("page_is_approximate", False))
    requirements = [r for r in payload.get("requirements", []) if isinstance(r, dict)]
    for req in requirements:
        item_classifier.enrich_payload(req, page_is_approximate=approx)

    signature_before = _content_signature(requirements)
    version_before = payload.get("requirement_set_version")

    # 안정 ID 를 지금 규칙으로 다시 계산한다. 파생값을 다시 계산하는 것이라 추측이 아니다.
    # 옛 값은 위 identity_remap() 이 이미 읽어 두므로 제안서는 함께 옮길 수 있다.
    before_ids = [str(r.get("stable_id") or "") for r in requirements]
    requirement_set.assign_identity(requirements, procurement_id=report.procurement_id, recompute=True)
    report.requirements_recomputed = sum(
        1 for old, r in zip(before_ids, requirements) if old and old != r.get("stable_id")
    )

    rfp_parser.stamp_identity(payload, previous=payload)
    # 구성이 그대로면 판 번호를 되돌린다 — id 규칙이 바뀐 것을 «요구사항이 또 바뀌었다»로
    # 읽히게 두면 화면이 있지도 않은 변경을 보고하게 된다.
    if _content_signature(requirements) == signature_before and version_before:
        payload["requirement_set_version"] = int(version_before)
    payload["item_counts"] = item_classifier.item_counts(payload.get("requirements", []))
    payload["schema_version"] = rfp_parser.REQUIREMENT_SCHEMA_VERSION

    report.requirements_stamped = total - already
    report.requirement_set_id = payload.get("requirement_set_id")
    report.requirement_set_version = payload.get("requirement_set_version")

    if not dry_run:
        storage.write_json_atomic(path, payload)
    return report, payload


# ---------------------------------------------------------------------------
# 2) 제안서 연결 복구
# ---------------------------------------------------------------------------


def _probe_text(sentence: dict[str, Any]) -> str:
    """문장에서 «요구사항 원문에 해당하는 부분»을 꺼낸다.

    두 가지 형태가 있다.
      - 「[원문 요약] "원문" — 설명」  → 대괄호 안이 요구사항 원문이다.
      - 「원문을 어투만 바꾼 문장 (RFP p.3 요구사항 준수)」 → 문장 자체가 원문에 가깝다.
    """
    text = str(sentence.get("text") or "")
    match = _QUOTE_RE.match(text)
    if match:
        return match.group("quoted")
    return _CITATION_RE.sub("", text).strip()


def _best_requirement(probe: str, requirements: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, float]:
    target = requirement_set.normalize_source(probe)
    if not target:
        return None, 0.0
    best, best_ratio = None, 0.0
    for req in requirements:
        candidate = requirement_set.normalize_source(str(req.get("content") or ""))
        # 제안서 문장은 어미가 바뀌어 있다. 앞부분이 겹치는지를 먼저 본다.
        ratio = SequenceMatcher(None, target[:120], candidate[:120]).ratio()
        if ratio > best_ratio:
            best, best_ratio = req, ratio
    return best, best_ratio


def migrate_proposal(
    path: Path,
    requirements: list[dict[str, Any]],
    report: Report,
    *,
    procurement_id: str,
    dry_run: bool,
    remap: dict[str, str] | None = None,
    legacy_hash: str | None = None,
    current_hash: str | None = None,
) -> None:
    payload = storage.read_json(path)
    if not isinstance(payload, dict):
        return
    sentences = payload.get("sentences")
    if not isinstance(sentences, list):
        return

    by_req = {str(r.get("requirement_id")): r for r in requirements}
    by_stable = {str(r.get("stable_id")): r for r in requirements if r.get("stable_id")}
    remap = remap or {}
    covered: set[str] = set()

    for sentence in sentences:
        if not isinstance(sentence, dict):
            continue
        claimed = str(sentence.get("requirement_id") or "")
        old_stable = str(sentence.get("stable_requirement_id") or "")

        # (0) 지금 집합에 그대로 있는 안정 ID — 이미 맞다. 건드릴 이유가 없다.
        target = by_stable.get(old_stable) if old_stable else None

        # (1) 옛 규칙(첨부 파일명이 섞여 있던)으로 찍힌 값이면 같은 원문의 새 id 로 옮긴다.
        #     대응표는 저장된 원문에서 다시 계산한 값이므로 «원문이 같다»가 계산으로
        #     증명된다 — 유사도 추정보다 강한 근거다.
        if target is None and old_stable:
            moved = remap.get(old_stable)
            target = by_stable.get(moved) if moved else None
            if target is not None:
                sentence["stable_requirement_id"] = target["stable_id"]
                report.identity_remapped.append(
                    {
                        "sentence": str(sentence.get("id") or ""),
                        "from": old_stable,
                        "to": str(target["stable_id"]),
                        "requirement_id": str(target.get("requirement_id") or ""),
                    }
                )

        if target is not None:
            covered.add(str(target["stable_id"]))
            actual = str(target.get("requirement_id") or "")
            if actual and actual != claimed:
                # 같은 원문을 가리키는 항목의 번호가 밀렸을 뿐이다. 옛 번호는 남긴다.
                sentence.setdefault("original_requirement_id", claimed)
                sentence["requirement_id"] = actual
                report.citations_fixed.append(
                    {
                        "sentence": str(sentence.get("id") or ""),
                        "from": claimed,
                        "to": actual,
                        "similarity": "1.00",
                        "text": str(target.get("content") or "")[:60],
                    }
                )
            continue

        if old_stable:
            # 옮길 곳이 없다. 요구사항이 실제로 사라졌거나 문장이 달라진 것이다.
            # **손대지 않는다** — 엉뚱한 곳에 새로 붙이는 것보다 낫다.
            report.identity_orphaned.append(
                {"sentence": str(sentence.get("id") or ""), "stable_requirement_id": old_stable, "claimed": claimed}
            )

        probe = _probe_text(sentence)
        match, ratio = _best_requirement(probe, requirements)

        if match is None or ratio < CONFIDENT:
            # 확신이 없으면 손대지 않는다. 어긋난 채로 두더라도 «엉뚱한 번호를 새로
            # 붙이는 것»보다 낫다 — 사람이 보고 판단해야 한다.
            # 주장한 번호가 «가장 가까운» 항목과 같으면 이미 맞는 것이다. 인용문이
            # 「…」로 잘려 유사도가 낮게 나올 뿐이라, 이것까지 흔들면 소음이 된다.
            if claimed and match is not None and str(match.get("requirement_id")) != claimed:
                report.citations_uncertain.append(
                    {
                        "sentence": str(sentence.get("id") or ""),
                        "claimed": claimed,
                        "closest": str(match.get("requirement_id") or ""),
                        "similarity": f"{ratio:.2f}",
                        "text": probe[:60],
                    }
                )
            # 그래도 «주장한 번호»가 지금도 존재하면 그 안정 ID 는 붙여 둔다.
            # 이미 다른 값이 적혀 있으면 덮지 않는다. 그때는 covered 에도 넣지 않는다 —
            # 문장에 적히지 않은 대응을 커버리지로 세면 거짓 집계가 된다.
            fallback = by_req.get(claimed)
            if fallback and fallback.get("stable_id"):
                sentence.setdefault("stable_requirement_id", fallback["stable_id"])
            written = str(sentence.get("stable_requirement_id") or "")
            if written in by_stable:
                covered.add(written)
            continue

        actual = str(match.get("requirement_id") or "")
        sentence["stable_requirement_id"] = match.get("stable_id")
        if match.get("stable_id"):
            covered.add(str(match["stable_id"]))
        if actual and actual != claimed:
            # 이미 «고치기 전 번호»가 적혀 있으면 그것을 살린다. 두 번째 마이그레이션이
            # 첫 기록을 덮으면 원래 무엇을 가리켰는지가 사라진다.
            sentence.setdefault("original_requirement_id", claimed)
            sentence["requirement_id"] = actual
            report.citations_fixed.append(
                {
                    "sentence": str(sentence.get("id") or ""),
                    "from": claimed,
                    "to": actual,
                    "similarity": f"{ratio:.2f}",
                    "text": probe[:60],
                }
            )

    payload["covered_requirement_ids"] = sorted(covered)
    payload.setdefault("proposal_version", 1)
    payload.setdefault("author", payload.get("generation_method") or "RULE")
    payload.setdefault("edited_by_human", False)

    # 없던 requirement_set_hash 를 **만들어 넣지는 않는다**. 그 초안이 어느 집합을 봤는지
    # 기록이 없기 때문이다 — 없는 근거를 만들지 않는다(화면은 필수 건수 차이로 판정한다).
    #
    # 다만 «적혀 있던 값이 옛 규칙으로 계산된 것»이라면 이야기가 다르다. 그때는 구성이
    # 같다는 것이 계산으로 증명되므로 같은 집합의 새 표기로 옮긴다. 옮기지 않으면 바뀐 것이
    # 없는 초안이 「이전 기준」으로 밀리고 제출 전 점검이 409 로 막힌다(실측: 718694).
    recorded = str(payload.get("requirement_set_hash") or "")
    if recorded and legacy_hash and current_hash and recorded == legacy_hash and recorded != current_hash:
        payload["requirement_set_hash"] = current_hash
        report.basis_hash_rewritten.append(
            {"proposal": str(path.relative_to(ROOT)), "from": recorded, "to": current_hash}
        )

    payload["proposal_hash"] = _payload_hash(payload)

    if not dry_run:
        _archive_proposal(path, payload, procurement_id)
        storage.write_json_atomic(path, payload)
    report.proposals_touched.append(str(path.relative_to(ROOT)))


def _payload_hash(payload: dict[str, Any]) -> str:
    import hashlib

    joined = "\n".join(str(s.get("text") or "") for s in payload.get("sentences", []) if isinstance(s, dict))
    normalized = re.sub(r"\s+", " ", joined).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _archive_proposal(path: Path, payload: dict[str, Any], procurement_id: str) -> None:
    """고치기 전 판을 보존한다. 이미 있으면 다시 쓰지 않는다.

    폴더 이름은 `proposal_service.versions_dir()` 와 **같아야 한다** — 다르면 판을
    남겨 두고도 API 가 그것을 찾지 못한다. 공개 위치는 파일명이
    `{pid}.proposal.json` 이고 조직 폴더는 그냥 `proposal.json` 이라,
    경로에서 유추하지 않고 공고 id 를 받아서 쓴다.
    """
    original = storage.read_json(path)
    if not isinstance(original, dict):
        return
    folder = path.parent / f"{procurement_id}.proposal.versions"
    folder.mkdir(parents=True, exist_ok=True)
    version = int(original.get("proposal_version") or 1)
    target = folder / f"v{version:03d}.json"
    if not target.exists():
        storage.write_json_atomic(target, original)
        return

    # 판 번호 자리가 이미 차 있다. 그런데 지금 파일이 그 판과 «다른 내용»이면
    # (한 번 마이그레이션한 뒤 다시 돌리는 경우가 그렇다) 이대로 덮어쓰면 중간 판이
    # 사라진다. 판 목록에는 끼우지 않고(`v*.json` 만 판으로 읽힌다) 따로 남긴다.
    kept = storage.read_json(target)
    if kept == original:
        return
    snapshot = folder / f"snapshot-{_payload_hash(original)}.json"
    if not snapshot.exists():
        storage.write_json_atomic(snapshot, original)


def _proposal_paths(procurement_id: str) -> list[Path]:
    paths = [PROPOSALS_DIR / f"{procurement_id}.proposal.json"]
    if PRIVATE_ORGS.is_dir():
        paths.extend(PRIVATE_ORGS.glob(f"*/analyses/{procurement_id}/proposal.json"))
    return [p for p in paths if p.exists()]


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------


def run(procurement_ids: list[str], *, dry_run: bool) -> list[Report]:
    reports: list[Report] = []
    for procurement_id in procurement_ids:
        path = GENERATED_DIR / f"{procurement_id}.requirements.json"
        if not path.exists():
            print(f"[{procurement_id}] 요구사항 파일이 없습니다 — 건너뜁니다")
            continue
        # 대응표는 «고치기 전»에 만들어야 한다. 고친 뒤에는 옛 id 가 파일에서 사라진다.
        remap = identity_remap(procurement_id)

        # migrate_requirements 가 돌려주는 payload 를 그대로 쓴다. 미리보기에서는 디스크에
        # 쓰지 않으므로 다시 읽으면 옛 값이 나온다 — 예전에는 그래서 미리보기와 실제
        # 결과가 갈렸다.
        report, payload = migrate_requirements(path, dry_run=dry_run)
        requirements = [r for r in payload.get("requirements") or [] if isinstance(r, dict)]

        # 옛 규칙 해시는 «고치기 전 구성»으로 계산해야 한다. migrate_requirements 는
        # 구성을 바꾸지 않고 파생 id 만 다시 찍으므로, 반환된 payload 로 계산해도 같다.
        legacy_hash = legacy_set_hash(payload)
        current_hash = str(payload.get("requirement_set_hash") or "") or None

        for proposal_path in _proposal_paths(procurement_id):
            migrate_proposal(
                proposal_path,
                requirements,
                report,
                procurement_id=procurement_id,
                dry_run=dry_run,
                remap=remap,
                legacy_hash=legacy_hash,
                current_hash=current_hash,
            )
        reports.append(report)
    return reports


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("procurement_id", nargs="?", help="한 건만 처리할 공고 id")
    parser.add_argument("--dry-run", action="store_true", help="저장하지 않고 결과만 보여준다")
    args = parser.parse_args()

    if args.procurement_id:
        ids = [args.procurement_id]
    else:
        ids = sorted(p.name.replace(".requirements.json", "") for p in GENERATED_DIR.glob("*.requirements.json"))

    reports = run(ids, dry_run=args.dry_run)

    print()
    for report in reports:
        print(f"[{report.procurement_id}]")
        print(
            f"  집합 {report.requirement_set_id} (판 {report.requirement_set_version})"
            f" · 안정 ID 새로 찍음 {report.requirements_stamped}건"
            f" · 새 규칙으로 다시 계산 {report.requirements_recomputed}건"
        )
        if report.archived_requirements:
            print(f"  이전 판 보존: {report.archived_requirements}")
        for proposal in report.proposals_touched:
            print(f"  제안서: {proposal}")
        if report.identity_remapped:
            print(f"  안정 ID 이어 붙임 {len(report.identity_remapped)}건 (원문이 같음이 계산으로 확인됨)")
        for item in report.basis_hash_rewritten:
            print(
                f"  기준 집합 표기 갱신 {item['proposal']} — {item['from']} → {item['to']}"
                " (구성은 그대로, 안정 ID 규칙만 바뀐 것이 계산으로 확인됨)"
            )
        if report.identity_orphaned:
            print(f"  **옮길 곳 없음 {len(report.identity_orphaned)}건 — 손대지 않았습니다(사람이 확인)**:")
            for item in report.identity_orphaned:
                print(f"    {item['sentence']} 주장 {item['claimed']} · 옛 안정 ID {item['stable_requirement_id']}")
        if report.citations_fixed:
            print(f"  인용 바로잡음 {len(report.citations_fixed)}건:")
            for fix in report.citations_fixed:
                print(f"    {fix['sentence']} {fix['from']} → {fix['to']} ({fix['similarity']}) {fix['text']}")
        if report.citations_uncertain:
            print(f"  **확신 부족 {len(report.citations_uncertain)}건 — 손대지 않았습니다(사람이 확인)**:")
            for item in report.citations_uncertain:
                print(
                    f"    {item['sentence']} 주장 {item['claimed']} · 가장 가까움 {item['closest']}"
                    f" ({item['similarity']}) {item['text']}"
                )
    if args.dry_run:
        print("\n(미리보기 — 저장하지 않았습니다)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
