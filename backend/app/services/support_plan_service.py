"""사업계획서 핵심 섹션 초안 (ISSUE-112 · prompt_02 §4-B).

## 무엇을 만드는가

6단계 「사업계획서」는 12차까지 **목차 뼈대**뿐이었다. 뼈대는 절마다 「근거 있음 /
확인 필요」와 인용을 달지만, 담당자가 그대로 옮겨 쓸 **문장**은 없었다. 이 서비스가
그 문장을 만든다.

## 지키는 것

- **지어내지 않는다.** 규칙 경로의 문장은 (a) 공고문 조항 **원문**과 (b) 이미 규칙이
  판정해 둔 회사 사실, 둘뿐이다. 새 주장을 쓰지 않는다(CLAUDE.md §11).
- 문장 유형은 **기존 enum** 을 쓴다 — `RFP_GROUNDED · COMPANY_EVIDENCE_GROUNDED ·
  AI_SUGGESTION`. 12차가 확인한 대로 `NOTICE_GROUNDED` 는 저장소에 없다. 지원사업에서
  `RFP_GROUNDED` 는 「공고문 근거」로 읽는다 — **화면 라벨만** 그렇게 적는다.
- 규칙 경로는 `AI_SUGGESTION` **0건**이다. AI 가 만든 문장이 하나도 없다는 뜻이고,
  화면은 그것을 「AI 없이 만든 초안」으로 표시한다.
- LLM 경로는 `llm_client.credit_ok()` 가 참일 때만 탄다. 크레딧 0 에서 부르면 429
  실호출이다(§4-B-1). 이 파일은 크레딧을 **직접 확인하지 않는다** — 나가는 문
  (`complete_structured`)이 이미 막고 있고, 여기서 또 확인하면 규칙이 두 곳에 생긴다.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from pathlib import Path

from app.core import org_storage, storage
from app.schemas.business_opportunity import SupportProgram
from app.schemas.organization import AnalysisContext
from app.services import llm_client

KST = timezone.utc  # 저장은 UTC, 화면이 KST 로 바꾼다 (다른 저장과 같은 규칙)

#: 문장 유형 — `schemas/proposal.py` 의 `GroundingType` 과 같은 값만 쓴다.
NOTICE = "RFP_GROUNDED"
COMPANY = "COMPANY_EVIDENCE_GROUNDED"
SUGGESTION = "AI_SUGGESTION"

#: 절 이름 → 공고에서 그 절의 근거로 쓸 값. 조항이 없을 때 **원문 필드**를 인용한다.
#: 지어낸 문장이 아니라 공고가 준 값 그대로다.
#:
#: 「기대 효과」는 여기 없다 (ISSUE-119 · prompt_03 §4-D-2). 예전에는 `category` 를 썼는데
#: 그 값은 「창업」 같은 **한 낱말**이라 근거가 되지 못했다 — 아래 `_purpose_sentence` 가
#: 사업 개요에서 목적 문장을 찾고, 못 찾으면 「확인 필요」로 둔다.
_PROGRAM_FIELD_BY_SECTION: dict[str, str] = {
    "사업 개요·추진 배경": "summary",
    "추진 계획·일정": "apply_period_text",
}

#: 「기대 효과」의 근거로 쓸 **목적 문장**의 꼬리 (prompt_03 §4-D-2).
#:
#: 공고 요약문은 「… 를 촉진하고자 함」·「… 을 지원하고자 합니다」처럼 목적을 한 문장으로
#: 적는다. 그 문장이 기대 효과의 근거다. 낱말 하나(`category`)를 근거로 내놓지 않는다.
_PURPOSE_TAILS: tuple[str, ...] = (
    "촉진", "지원하고자", "지원함", "육성", "제고", "활성화", "강화하고자",
    "확산", "도모", "기여", "창출", "목적으로", "위하여", "위해",
)

#: 목적 문장이라 부르기에 너무 짧은 것. 「창업 지원」 같은 조각은 근거가 아니다.
_PURPOSE_MIN_CHARS = 15


def _program_value(program: SupportProgram, field: str) -> str | None:
    value = getattr(program, field, None)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _purpose_sentence(program: SupportProgram) -> str | None:
    """사업 개요에서 **목적 문장** 하나 (ISSUE-119 · prompt_03 §4-D-2).

    13차의 「기대 효과」 근거는 분야 필드 한 낱말(「창업」)이었다. 화면에는 「공고 원문:
    「창업」」이라고 찍혔는데, 그것으로는 기대 효과를 쓸 수 없다 — 근거가 있는 척하는
    빈칸이었다. 공고 요약문에서 목적을 말하는 문장을 찾아 **원문 그대로** 인용하고,
    없으면 아무것도 내지 않는다(그러면 「확인 필요」로 떨어진다).
    """
    summary = _program_value(program, "summary")
    if not summary:
        return None
    for raw in re.split(r"(?<=[.。])\s+|\n+", summary):
        sentence = raw.strip(" ·-–—\t")
        if len(sentence) < _PURPOSE_MIN_CHARS:
            continue
        if any(tail in sentence for tail in _PURPOSE_TAILS):
            return sentence
    return None


def _sentence(text: str, kind: str | None, source: str | None) -> dict[str, Any]:
    """문장 한 줄. `kind` 가 None 이면 **유형 없는 안내**다 (ISSUE-119 · §4-D-1).

    「확인 필요 — …」는 근거가 아니라 **빈칸 표시**다. 그런데 유형을 `RFP_GROUNDED` 로
    달아 두었더니 화면이 「공고문 근거」 배지를 붙여, 근거가 없다는 말에 근거 배지가
    달리는 자리가 됐다. 유형을 비우고 `note: True` 로 「이건 안내」임을 적는다.
    """
    row: dict[str, Any] = {"text": text, "type": kind, "source": source}
    if kind is None:
        row["note"] = True
    return row


def build_sections(
    program: SupportProgram,
    outline: list[dict[str, Any]],
    *,
    matches: list[dict] | None = None,
) -> list[dict[str, Any]]:
    """뼈대 → 섹션별 문장 목록. **규칙만** 쓴다.

    문장은 세 갈래다.
      공고문 근거 — 조항 원문 그대로, 또는 조항이 없으면 그 절이 근거로 삼은 공고 필드값
      회사 근거   — 규칙이 이미 판정한 「맞은 회사 사실」과 채택된 회사자료
      확인 필요   — 근거가 없는 절. 채우지 않고 무엇이 없는지 적는다
    """
    selected = [m for m in (matches or []) if m.get("selected")]
    sections: list[dict[str, Any]] = []

    for entry in outline:
        name = entry["section"]
        sentences: list[dict[str, Any]] = []

        for quote in entry.get("quotes") or []:
            sentences.append(_sentence(f"공고문: 「{quote}」", NOTICE, quote))

        # 조항이 없는 절은 그 절이 근거로 삼은 **공고 필드값**을 인용한다.
        if not sentences and name in _PROGRAM_FIELD_BY_SECTION:
            value = _program_value(program, _PROGRAM_FIELD_BY_SECTION[name])
            if value:
                short = value if len(value) <= 160 else value[:160] + "…"
                sentences.append(_sentence(f"공고 원문: 「{short}」", NOTICE, short))

        # 「기대 효과」는 **목적 문장**을 인용한다 (ISSUE-119 · §4-D-2).
        # 예전에는 분야 필드 한 낱말(「창업」)이 근거였다 — 근거가 있는 척하는 빈칸이었다.
        if not sentences and name == "기대 효과":
            purpose = _purpose_sentence(program)
            if purpose:
                short = purpose if len(purpose) <= 160 else purpose[:160] + "…"
                sentences.append(_sentence(f"공고 원문: 「{short}」", NOTICE, short))

        for fact in entry.get("company_facts") or []:
            sentences.append(_sentence(fact, COMPANY, "회사 프로필(규칙 판정)"))

        if name == "수행 역량·유사 실적":
            for match in selected[:3]:
                title = str(match.get("document_name") or match.get("title") or "회사자료")
                sentences.append(_sentence(f"회사자료: {title}", COMPANY, str(match.get("id") or title)))

        if not sentences:
            # **유형 없는 안내다** (ISSUE-119 · §4-D-1). 근거가 아니라 빈칸 표시이므로
            # 「공고문 근거」 배지를 달지 않는다 — 근거가 없다는 말에 근거 배지가 붙던 자리.
            note = entry.get("note") or "근거를 찾지 못했습니다. 원문에서 확인하세요."
            sentences.append(_sentence(f"확인 필요 — {note}", None, None))

        sections.append(
            {
                "section": name,
                "grounded": bool(entry.get("grounded")),
                "sentences": sentences,
            }
        )

    return sections


def generate(
    program: SupportProgram,
    outline: list[dict[str, Any]],
    *,
    matches: list[dict] | None = None,
    notice_version: str | None = None,
) -> dict[str, Any]:
    """초안 한 벌. LLM 은 크레딧이 확인될 때만 탄다.

    크레딧 0 이면 `llm_client.complete_structured` 가 `LLMUnavailableError` 를 던지므로
    (§4-B-1 의 문), 여기서는 **잡아서 규칙 결과를 그대로 돌려준다.** 화면이 멈추지 않는다.
    """
    sections = build_sections(program, outline, matches=matches)
    generated_by = "rules"

    if llm_client.credit_ok():
        try:
            sections = _refine_with_llm(sections)
            generated_by = "llm"
        except llm_client.LLMUnavailableError:
            generated_by = "rules"

    return {
        "program_id": program.id,
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": generated_by,
        "notice_version": notice_version,
        "sections": sections,
        "sentence_count": sum(len(s["sentences"]) for s in sections),
        "ai_sentence_count": sum(
            1 for s in sections for sentence in s["sentences"] if sentence["type"] == SUGGESTION
        ),
    }


def _refine_with_llm(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """LLM 다듬기 자리. 지금은 크레딧이 없어 한 번도 실행되지 않는다.

    **일부러 비워 두지 않았다** — 입찰 `proposal_service.refine_with_llm` 과 같은 골격을
    쓰려면 그쪽 프롬프트·스키마를 그대로 가져와야 하는데, 크레딧이 없어 **한 줄도
    돌려볼 수 없다.** 돌려보지 못한 LLM 경로를 지어 넣으면 크레딧이 생긴 날 처음
    실행되면서 무엇이 틀렸는지 모른 채 429 아닌 다른 실패를 만난다.

    그래서 지금은 「크레딧이 생기면 여기서부터」를 분명히 남기고 규칙 결과를 그대로 둔다.
    호출 자체가 `complete_structured` 를 지나므로 크레딧 0 에서는 애초에 오지 않는다.
    """
    raise llm_client.LLMUnavailableError(
        "LLM 다듬기는 크레딧이 생긴 뒤 입찰 경로와 같은 프롬프트로 붙인다 — 아직 실행해 본 적이 없다."
    )


def uncovered_quotes(draft: dict[str, Any], requirements) -> list[str]:
    """초안이 아직 담지 않은 공고문 조항 (prompt_02 §4-B-6).

    12차는 **뼈대**의 인용으로 셌다. 이제 초안 문장의 `source` 로 센다 — 초안이
    실제로 담은 것이 기준이어야 「미반영」이 뜻을 갖는다.

    **조항 id 로도 센다** (25차 §4-C-9). AI 초안은 조항을 제 말로 다시 쓰므로 원문 문자열 대조로는
    담은 조항도 「미반영」이 된다. 문장의 `source_ids` 가 조항 id(`plan_draft_service.clause_id`)를
    가리키면 담은 것이다 — 그래서 AI 초안과 규칙 초안의 미반영 수가 같다.
    """
    from app.services.plan_draft_service import PLAN_SKIPPED_CLAUSE_KINDS, clause_id
    from app.services.support_application_service import UNCOVERED_CLAUSE_KINDS

    if requirements is None or not getattr(requirements, "document_read", False):
        return []
    sentences = [s for section in draft.get("sections", []) for s in section.get("sentences", [])]
    used = {str(sentence.get("source") or "").strip() for sentence in sentences}
    used_ids = {str(i) for sentence in sentences for i in sentence.get("source_ids") or []}
    missing: list[str] = []
    for kind in UNCOVERED_CLAUSE_KINDS:
        if kind in PLAN_SKIPPED_CLAUSE_KINDS:
            continue  # 초안이 싣지 않는 제외 조항 — 신청 자격 단계가 공고 인용으로 따로 보여 준다(26차 ISSUE-147 · 27차 R26-14)
        for clause in requirements.of(kind):
            text = (clause.source_text or "").strip()
            if text and text not in used and clause_id(kind, text) not in used_ids and text not in missing:
                missing.append(text)
    return missing


# --------------------------------------------------------------------------
# 저장 (prompt_02 §4-B-3)
# --------------------------------------------------------------------------

FILE_NAME = "plan_draft.json"
VERSIONS_DIR = "plan_draft.versions"


def draft_dir(context: AnalysisContext, program_id: str) -> Path:
    """`data/private/organizations/<org>/analyses/<program_id>/`.

    회사 사실이 인용되므로 **공개 폴더에 쓰지 않는다**(CLAUDE.md §21). 기존 분석 결과와
    같은 자리에 둔다 — 한 공고에 딸린 결과는 한 폴더에 모인다.
    """
    return org_storage.storage_for(context.organization_id).analysis_dir(program_id)


def save(draft: dict[str, Any], *, context: AnalysisContext, program_id: str) -> Path:
    """초안을 저장하고 이전 판을 `plan_draft.versions/` 로 남긴다.

    덮어쓰기만 하면 「다시 누르면 새 버전」이 거짓이 된다 — 담당자가 고친 뒤 다시 눌러
    나빠졌을 때 돌아갈 자리가 있어야 한다.
    """
    target_dir = draft_dir(context, program_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / FILE_NAME

    if target.exists():
        previous = load(context=context, program_id=program_id)
        if previous:
            versions = target_dir / VERSIONS_DIR
            versions.mkdir(parents=True, exist_ok=True)
            stamp = str(previous.get("executed_at") or "previous").replace(":", "-")
            storage.write_json_atomic(versions / f"{stamp}.json", previous)

    payload = dict(draft)
    payload["organization_id"] = context.organization_id
    payload["evidence_scope"] = context.evidence_scope
    storage.write_json_atomic(target, payload)
    return target


def save_draft(
    draft: dict[str, Any], *, context: AnalysisContext, program_id: str, force_rules: bool = False
) -> tuple[dict[str, Any], bool]:
    """저장. **AI 초안을 규칙 초안으로 덮지 않는다** (25차 §4-C-8) → (지금 보일 초안, 유지했는가).

    지금 저장본이 AI 초안이고 이번 결과가 규칙으로 떨어졌으면(키가 꺼졌거나 크레딧이 없다) 저장본을 그대로 두고
    규칙 결과는 `plan_draft.versions/` 에만 남긴다. 규칙 초안으로 바꾸려면 화면의 확인 창을 거쳐 `force_rules`.
    """
    current = load(context=context, program_id=program_id)
    if current.get("generated_by") == "llm" and draft.get("generated_by") == "rules" and not force_rules:
        versions = draft_dir(context, program_id) / VERSIONS_DIR
        versions.mkdir(parents=True, exist_ok=True)
        stamp = str(draft.get("executed_at") or "rules").replace(":", "-")
        storage.write_json_atomic(versions / f"rules-{stamp}.json", {**draft, "organization_id": context.organization_id})
        return current, True
    save(draft, context=context, program_id=program_id)
    return {**draft, "organization_id": context.organization_id, "evidence_scope": context.evidence_scope}, False


def load(*, context: AnalysisContext, program_id: str) -> dict[str, Any]:
    """저장된 초안. 없으면 빈 dict — 화면은 그때 「아직 만들지 않음」으로 그린다."""
    target = draft_dir(context, program_id) / FILE_NAME
    if not target.exists():
        return {}
    data = storage.read_json(target)
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------------------
# 사업계획서 작성 페이지의 저장본 목록 (28차 §3-D) — **메타만**(본문 · 회사 문장은 싣지 않는다)
# ---------------------------------------------------------------------------

def _task_title(task: Any) -> str | None:
    if isinstance(task, dict):
        return str(task.get("title") or task.get("name") or "") or None
    return str(task) if task else None


def blank_field_count(blanks: list | None) -> int:
    """담당자가 채울 **항목** 수 — 같은 항목이 여러 절에 있어도 하나(점검표 `plan_completeness_service` 와 같은 셈 · 45차 M6 「46 · 47」)."""
    return len({str(b.get("field")) for b in blanks or [] if isinstance(b, dict)})


def _count_versions(folder: Path) -> int:
    return sum(1 for p in folder.glob("*.json")) if folder.is_dir() else 0


def list_saved(context: AnalysisContext) -> list[dict[str, Any]]:
    """이 회사가 저장한 사업계획서(지원사업) · 제안서(입찰) 초안의 메타 — 공고 id · 제목 · 과제 · 만든 방식 · 공급자 ·
    모델 · 시각 · 걸린 시간 · AI 문장 수 · 빈칸 수 · 판 수. 본문 필드는 없다(시험이 못 박는다)."""
    root = org_storage.storage_for(context.organization_id).analyses_dir
    if not root.exists():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(root.glob(f"*/{FILE_NAME}")):
        data = storage.read_json(path)
        if not isinstance(data, dict) or not data.get("sections"):
            continue
        title = data.get("form_title")
        if not title:
            # 10-31 최종 점검 — 서식 제목이 빈 저장본은 /plan 고르기 줄이 id 글자로 섰다 · 같은 폴더 공고 사본(program.json)의 제목
            from app.services.support_application_service import archived_program

            archived = archived_program(path.parent.name, context.organization_id)
            title = archived.title if archived else None
        out.append({
            "kind": "support",
            "id": path.parent.name,
            "title": title,
            "task": _task_title(data.get("selected_task")),
            "generated_by": data.get("generated_by"),
            "provider": data.get("provider"),
            "model": data.get("model"),
            "executed_at": data.get("executed_at"),
            "elapsed_seconds": data.get("elapsed_seconds"),
            "ai_sentences": data.get("ai_sentence_count"),
            "blanks": blank_field_count(data.get("blanks")),
            "versions": _count_versions(path.parent / VERSIONS_DIR),
        })
    # 11-03 — 입찰 제안서 초안은 `bid_plan_draft.json`(제안요청서 목차대로 · `bid_proposal_service`). 옛 전체 초안
    # (`proposal_document.json`)은 /plan 이 열지 않으므로 목록에 싣지 않는다 — 실으면 열어도 「초안 없음」인 행이 고정됐다.
    from app.services import bid_proposal_service, notice_version_service

    for path in sorted(root.glob(f"*/{bid_proposal_service.FILE_NAME}")):
        data = storage.read_json(path)
        if not isinstance(data, dict) or not data.get("sections"):
            continue
        out.append({
            "kind": "proposal",
            "id": path.parent.name,
            # 45차 M20 — 받아 둔 공고 기록의 제목을 먼저
            "title": notice_version_service.latest_title(path.parent.name) or data.get("title"),
            "task": None,
            "generated_by": data.get("generated_by"),
            "provider": data.get("provider"),
            "model": data.get("model"),
            "executed_at": data.get("executed_at"),
            "elapsed_seconds": None,
            "ai_sentences": None,
            "blanks": blank_field_count(data.get("blanks")),
            "versions": _count_versions(path.parent / bid_proposal_service.VERSIONS_DIR),
        })
    out.sort(key=lambda row: str(row.get("executed_at") or ""), reverse=True)
    return out


def list_versions(context: AnalysisContext, program_id: str) -> list[dict[str, Any]]:
    """이전 판 목록(메타만 · 읽기 전용 · 되살리기 없음)."""
    folder = draft_dir(context, program_id) / VERSIONS_DIR
    if not folder.is_dir():
        return []
    rows = []
    for path in sorted(folder.glob("*.json"), reverse=True):
        data = storage.read_json(path)
        if not isinstance(data, dict):
            continue
        rows.append({
            "name": path.stem,
            "generated_by": data.get("generated_by"),
            "provider": data.get("provider"),
            "model": data.get("model"),
            "executed_at": data.get("executed_at"),
            "ai_sentences": data.get("ai_sentence_count"),
            "blanks": blank_field_count(data.get("blanks")),
            "kept_rules": path.stem.startswith("rules-"),
        })
    # 만든 시각 최신 순 — 파일 이름 순이면 「rules-…」 판이 늘 맨 위였다(29차 R28-08). 시각이 없으면 이름의 시각 부분.
    rows.sort(key=lambda r: str(r.get("executed_at") or r["name"].removeprefix("rules-")), reverse=True)
    return rows


def load_version(context: AnalysisContext, program_id: str, name: str) -> dict[str, Any] | None:
    """이전 판 하나(읽기 전용). 이름은 **그 폴더에 실제로 있는 파일 이름과 똑같을 때만** 받는다(경로 이동 차단 —
    판 이름에 「+」가 있어 `storage.safe_id` 모양이 맞지 않는다)."""
    folder = draft_dir(context, program_id) / VERSIONS_DIR
    path = next((p for p in folder.glob("*.json") if p.stem == name), None) if folder.is_dir() else None
    if path is None:
        return None
    data = storage.read_json(path)
    return data if isinstance(data, dict) else None
