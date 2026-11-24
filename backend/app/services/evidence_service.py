"""요구사항 ↔ 회사 근거 매칭 (임베딩 검색 + 채택 판정).

입력 인덱스는 **근거 범위(evidence_scope)** 로 정한다 — 합성 인덱스와 실제 회사 인덱스를 조용히 합치지 않는다.
- internal      선택한 조직의 승인·유효 real/anonymized 문단만 (data/private/organizations/{org}/index)
- public_demo   합성 인덱스만 (data/synthetic_company/index)
- explicit_test 호출자가 넘긴 chunk 만 (테스트 전용, 운영 API 선택 불가)

출력: EvidenceResult — links 와 함께 출처 범위(scope_info: 조직·범위·사용 문서/문단 수·합성 사용 여부)를 돌려준다.

원칙 (CLAUDE.md 11):
- 인덱스가 없으면 빈 결과를 돌려준다. 화면은 "근거 미연결"로 정직하게 표시되고 시연은 죽지 않는다.
- 유사도가 높다고 자동으로 '충족'이 아니다. selected(채택)와 candidate(후보)를 구분하고,
  모호한 요구사항(status=check)은 아무리 점수가 높아도 채택하지 않고 사람에게 넘긴다.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from app.core import org_storage, storage
from app.core.paths import DATA_ROOT
from app.schemas.organization import AnalysisContext, EvidenceScopeInfo
from app.schemas.requirement import Requirement
from app.services import llm_client

logger = logging.getLogger(__name__)

INDEX_FILE = DATA_ROOT / "synthetic_company" / "index" / "company_index.json"
# 레거시 회사 인덱스 위치 — 기본 조직의 읽기 대체(org_storage)만 여기를 본다. 새 색인은 조직 폴더로 간다.
COMPANY_INDEX_FILE = DATA_ROOT / "company" / "index" / "company_index.json"
CACHE_FILE = DATA_ROOT / "synthetic_company" / "index" / "requirement_vectors.json"

# 채택/후보 임계값 — 실제 나라장터 제안요청서 4건으로 보정했다.
# 합성 RFP는 회사자료와 어휘가 거의 같아 0.73~0.81이 나오지만, 실제 공고는 표현이 달라
# 올바른 매칭도 0.60대에 머문다(실측: '증빙자료 제출'↔'계약 증빙 서류' 0.633).
# 0.50 미만에서는 무관한 문서가 섞이기 시작해 후보에서도 제외한다.
SELECT_THRESHOLD = 0.60
CANDIDATE_THRESHOLD = 0.50
TOP_K = 3


class ScopeError(ValueError):
    """근거 범위에 맞지 않는 호출 (explicit_test 인데 chunk 가 없음 등)."""


@dataclass
class EvidenceChunk:
    evidence_id: str
    document_name: str
    doc_type: str
    page: int | None
    source_text: str
    embedding: list[float]
    # 문서 front matter에서 옮겨온 값. 합성 자료와 비식별한 실제 자료를 구분한다.
    synthetic: bool = True
    anonymized: bool = False
    # 근거 메타데이터 (회사 인덱스). 합성 인덱스는 data_class="synthetic", source_kind="markdown".
    data_class: str = "synthetic"
    source_kind: str = "markdown"
    document_id: str | None = None
    scope: str = "public_demo"
    valid_to: str | None = None
    organization_id: str | None = None


@dataclass
class EvidenceMatch:
    requirement_id: str
    evidence_id: str
    document_name: str
    doc_type: str
    page: int | None
    source_text: str
    similarity_score: float
    selected: bool
    note: str | None = None
    synthetic: bool = True
    anonymized: bool = False
    data_class: str = "synthetic"
    source_kind: str = "markdown"
    document_id: str | None = None
    organization_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "evidence_id": self.evidence_id,
            "document_name": self.document_name,
            "doc_type": self.doc_type,
            "page": self.page,
            "source_text": self.source_text,
            "similarity_score": round(self.similarity_score, 4),
            "selected": self.selected,
            "note": self.note,
            "synthetic": self.synthetic,
            "anonymized": self.anonymized,
            "data_class": self.data_class,
            "source_kind": self.source_kind,
            "document_id": self.document_id,
            "organization_id": self.organization_id,
        }


@dataclass
class EvidenceResult:
    available: bool
    matches: list[EvidenceMatch] = field(default_factory=list)
    documents: list[dict[str, Any]] = field(default_factory=list)
    reason: str | None = None
    scope_info: EvidenceScopeInfo | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "reason": self.reason,
            "count": len(self.matches),
            "selected_count": sum(1 for m in self.matches if m.selected),
            "documents": self.documents,
            "links": [m.to_dict() for m in self.matches],
            "scope": self.scope_info.model_dump(mode="json") if self.scope_info else None,
        }


def _chunks_from(path: Path, *, default_data_class: str, default_source_kind: str, default_scope: str) -> list[EvidenceChunk]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return []
    chunks: list[EvidenceChunk] = []
    for c in payload.get("chunks", []):
        synthetic = bool(c.get("synthetic", default_data_class == "synthetic"))
        anonymized = bool(c.get("anonymized", False))
        chunks.append(
            EvidenceChunk(
                evidence_id=c["evidence_id"],
                document_name=c["document_name"],
                doc_type=c.get("doc_type", "기타"),
                page=c.get("page"),
                source_text=c["source_text"],
                embedding=c["embedding"],
                synthetic=synthetic,
                anonymized=anonymized,
                data_class=str(c.get("data_class") or ("synthetic" if synthetic else ("anonymized" if anonymized else default_data_class))),
                source_kind=str(c.get("source_kind") or default_source_kind),
                document_id=c.get("document_id"),
                scope=str(c.get("scope") or default_scope),
                valid_to=c.get("valid_to"),
                organization_id=c.get("organization_id"),
            )
        )
    return chunks


def _company_chunk_allowed(chunk: EvidenceChunk, active_ids: set[str] | None, today: date) -> bool:
    """회사 인덱스 chunk는 등록부의 승인·비활성·유효기간을 다시 확인한다 (인덱스가 오래됐을 수 있다)."""
    if active_ids is not None and chunk.document_id is not None and chunk.document_id not in active_ids:
        return False
    if chunk.valid_to:
        try:
            if date.fromisoformat(chunk.valid_to) < today:
                return False
        except ValueError:
            return False
    return True


def synthetic_chunks() -> list[EvidenceChunk]:
    """합성 인덱스 (public_demo). 실제 자료로 표시된 chunk가 섞여 있으면 뺀다."""
    chunks = _chunks_from(INDEX_FILE, default_data_class="synthetic", default_source_kind="markdown", default_scope="public_demo")
    return [c for c in chunks if c.data_class == "synthetic"]


def _scope_allows(chunk_scope: str, evidence_scope: str) -> bool:
    """문서 승인 때 담당자가 고른 「공개 범위」(EvidenceMetadata.scope)가 이 분석 범위에 들어와도 되는지.

    - public_demo 분석: 공개로 승인한 문단만. 내부 전용(internal)으로 승인한 문단은 절대 들어오지 않는다.
    - internal 분석: 내부 전용 + 공개 승인분 둘 다. 공개로 열어 둔 자료를 사내 분석에서 뺄 이유가 없다.

    «scope 값이 없는 레거시 chunk» 를 어떻게 볼 것인가가 이 함수의 실제 쟁점이다.
    `_chunks_from` 이 조직 인덱스에는 internal, 합성 인덱스에는 public_demo 를 기본값으로 채워 주지만,
    여기서도 모르는 값은 internal 로 본다 — 「표시가 없다」는 이유로 internal 분석에서 문단을 빼면
    담당자에게는 등록해 둔 회사 근거가 통째로 사라진 것처럼 보인다. 잃는 쪽보다 남기는 쪽으로 기운다.
    """
    if evidence_scope == "public_demo":
        return chunk_scope == "public_demo"
    return True


def _organization_data_class(organization_id: str) -> str:
    """조직 등록부의 자료 등급. 등록부를 못 읽으면 보수적으로 real 로 본다 (합성 chunk 제외)."""
    try:
        from app.services import organization_service

        return organization_service.get_organization(organization_id).data_class
    except Exception as exc:  # noqa: BLE001
        # 조용히 real 로 떨어지면 합성 등급 데모 회사의 근거가 통째로 빠진다. 최소한 흔적은 남긴다.
        logger.error("조직 등록부에서 자료 등급을 읽지 못해 real 로 간주합니다 (organization_id=%s): %s", organization_id, type(exc).__name__)
        return "real"


def organization_chunks(organization_id: str, *, today: date | None = None) -> list[EvidenceChunk]:
    """조직의 승인·유효 문단만 (internal). 다른 조직 chunk 와 공유 합성 인덱스는 뺀다.

    - real/anonymized 조직: real·anonymized 문단만 — 합성 등급 문단은 실제 회사 분석에 섞이지 않는다.
    - synthetic 조직(데모·테스트 회사): 그 조직이 직접 올려 승인한 synthetic 문단만 — 실제 자료는 들어오지 않는다.
    """
    allowed: tuple[str, ...] = ("synthetic",) if _organization_data_class(organization_id) == "synthetic" else ("real", "anonymized")
    store = org_storage.storage_for(organization_id)
    company = _chunks_from(store.read_path("index"), default_data_class="real", default_source_kind="upload", default_scope="internal")
    if not company:
        return []
    active_ids: set[str] | None
    try:
        from app.services import company_service

        active_ids = company_service.active_document_ids(organization_id)
    except Exception as exc:  # noqa: BLE001 — 등록부를 못 읽으면 회사 chunk를 쓰지 않는다 (보수적)
        # 보수적으로 비우는 건 맞지만, 여기서 아무 말도 안 하면 화면에는 「승인·색인된 회사자료가 없습니다」로만
        # 보인다 — 자료가 없는 것과 등록부를 못 읽은 것은 담당자에게 전혀 다른 사건이다.
        # 사유는 `_empty_pool_reason` 이 격리 파일을 보고 갈라 적는다.
        logger.error("회사자료 등록부를 읽지 못해 이 조직의 근거를 쓰지 않습니다 (organization_id=%s): %s", organization_id, type(exc).__name__)
        active_ids = set()
    moment = today or storage.kst_today()
    return [
        c
        for c in company
        if c.data_class in allowed
        and c.organization_id in (None, organization_id)
        and _company_chunk_allowed(c, active_ids, moment)
    ]


def load_index(*, context: AnalysisContext, today: date | None = None) -> list[EvidenceChunk]:
    """근거 범위에 맞는 인덱스만 읽는다. 절대 합치지 않는다.

    chunk 마다 실린 `scope`(승인 때 고른 「공개 범위」)는 여기서 한 번만 거른다.
    전에는 `_chunks_from` 이 값을 읽어 EvidenceChunk 에 담아 두기만 하고 **아무도 보지 않았다** —
    담당자가 「내부 전용」으로 승인해도 공개 데모 분석에서 걸러 주는 코드가 없었다.
    """
    if context.evidence_scope == "public_demo":
        pool = synthetic_chunks()
    elif context.evidence_scope == "internal":
        pool = organization_chunks(context.organization_id, today=today)
    else:
        raise ScopeError("explicit_test 범위는 호출자가 chunk를 직접 넘겨야 합니다")
    return [c for c in pool if _scope_allows(c.scope, context.evidence_scope)]


def index_exists(context: AnalysisContext) -> bool:
    if context.evidence_scope == "public_demo":
        return INDEX_FILE.exists()
    if context.evidence_scope == "internal":
        return org_storage.storage_for(context.organization_id).read_path("index").exists()
    return False


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _load_vector_cache() -> dict[str, list[float]]:
    if not CACHE_FILE.exists():
        return {}
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def _save_vector_cache(cache: dict[str, list[float]]) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    tmp.replace(CACHE_FILE)


def embed_requirements(requirements: list[Requirement]) -> dict[str, list[float]]:
    """요구사항 임베딩 (내용 기준 캐시 — 같은 문장은 다시 호출하지 않는다). 요구사항 문장은 공고 원문이라 회사와 무관하다."""
    cache = _load_vector_cache()
    missing = [r for r in requirements if r.content not in cache]
    if missing:
        vectors = llm_client.embed([r.content for r in missing])
        for req, vec in zip(missing, vectors, strict=True):
            cache[req.content] = vec
        _save_vector_cache(cache)
    return {r.requirement_id: cache[r.content] for r in requirements}


def scope_info_of(context: AnalysisContext, chunks: list[EvidenceChunk], matches: list[EvidenceMatch], *, note: str | None = None) -> EvidenceScopeInfo:
    used_docs = {m.document_id or m.document_name for m in matches}
    return EvidenceScopeInfo(
        organization_id=context.organization_id,
        evidence_scope=context.evidence_scope,
        used_document_count=len(used_docs),
        used_chunk_count=len({m.evidence_id for m in matches}),
        synthetic_evidence_used=any(m.synthetic for m in matches),
        real_evidence_used=any(not m.synthetic for m in matches),
        note=note,
    )


def _empty_pool_reason(context: AnalysisContext) -> str:
    """근거가 하나도 없을 때 화면에 적을 사유. 「자료가 없다」와 「등록부를 못 읽었다」를 갈라 적는다.

    등록부 JSON 이 깨지면 `organization_chunks` 가 보수적으로 빈 목록을 돌려주는데, 그 사실이 위로
    전달되지 않아 화면에는 「승인·색인된 회사자료가 없습니다」로만 보였다 — 담당자 눈에는 등록해 둔
    회사자료가 통째로 증발한 것과 구분되지 않는다. storage 가 남긴 격리 파일(`*.corrupt-*`)이
    그대로 있으면 읽기 실패였다고 말해 준다 (깨진 파일은 첫 읽기에서 격리되므로 예외는 한 번만 난다).
    """
    if context.evidence_scope == "public_demo":
        return "가상 예시 회사자료 인덱스가 없습니다. scripts/build_company_index.py 를 실행하세요."
    quarantined: list[Any] = []
    try:
        from app.services import company_service

        quarantined = list(company_service.registry_quarantine_files(context.organization_id))
    except Exception as exc:  # noqa: BLE001 — 사유 문구를 만들다 분석을 죽이지 않는다
        logger.error("격리 파일 확인에 실패했습니다 (organization_id=%s): %s", context.organization_id, type(exc).__name__)
    # 화면에 붙는 문장이라 회사 코드(org-…) 대신 회사 이름을 쓴다. 이름을 못 읽으면 「이 회사」.
    company = "이 회사"
    try:
        from app.services import organization_service

        company = organization_service.get_organization(context.organization_id).display_name
    except Exception:  # noqa: BLE001 — 이름을 못 읽어도 사유 문장은 낸다
        pass
    if quarantined:
        return (
            f"{company}의 회사자료 등록부를 읽지 못했습니다 — JSON 이 깨져 격리됐습니다"
            f" ({quarantined[-1].name}). 자료가 없는 것이 아니라 읽기에 실패한 것입니다. 관리자 확인이 필요합니다."
        )
    return f"{company}의 승인·색인된 회사자료가 없습니다. 회사자료 화면에서 자료를 등록·승인·색인하세요."


#: 요구사항 하나에 붙이는 원장 후보 수 · 전체 상한(43차 결정 3).
LEDGER_CANDIDATES_PER_REQUIREMENT = 2
LEDGER_CANDIDATES_TOTAL = 40


def ledger_candidates(requirements: list[Requirement], context: AnalysisContext) -> list[EvidenceMatch]:
    """실적 원장(외부 사용 가능 · 내부 범위만)에서 요구사항 분야 낱말로 맞춘 후보 — **미채택**(43차 결정 3). 바깥 AI · 임베딩 없음."""
    from app.services import performance_match_service as _pm

    rows = _pm.eligible_rows(_pm.load_ledger_for(context))
    if not rows:
        return []
    out: list[EvidenceMatch] = []
    for req in requirements:
        if req.requirement_type != "mandatory":
            continue
        criteria = _pm.parse_criteria(f"{req.title} {req.content}")
        if not criteria.domains:
            continue
        for hit in _pm.match_rows(criteria, rows)[:LEDGER_CANDIDATES_PER_REQUIREMENT]:
            out.append(EvidenceMatch(
                requirement_id=req.requirement_id,
                evidence_id=f"ledger-{hit.seq}",
                document_name=f"실적 원장 {hit.seq}번 — {hit.title}",
                doc_type="ledger",
                page=None,
                source_text=" · ".join(filter(None, [hit.year, hit.title, hit.summary]))[:400],
                similarity_score=0.0,
                selected=False,
                note="원장 후보 실적(미채택) — 분야 낱말로 맞춘 것입니다. 사람이 고르면 초안에 씁니다.",
                synthetic=False,
                data_class="internal",
                source_kind="ledger",
                organization_id=context.organization_id,
            ))
            if len(out) >= LEDGER_CANDIDATES_TOTAL:
                return out
    return out


def ai_search_off(context: AnalysisContext) -> bool:
    """지금 이 회사의 회사 근거 연결(AI 검색)이 꺼져 있나 — 색인이 없거나 AI 설정이 없다(46차 H5 · 상태 값 한 곳).

    `match_requirements` 가 원장 후보로 가는 조건과 같다. 화면은 저장된 초안의 옛 사유 글(「설정이 없어 … 건너뜁니다」 ·
    「키가 거부되었습니다」)이 아니라 이 값으로 「AI 검색 꺼 둠」과 「실패」를 가른다."""
    return not load_index(context=context) or not llm_client.is_configured()


def with_search_state(summary: dict | None, context: AnalysisContext) -> dict | None:
    """근거 요약(응답 사본)에 지금 상태 `ai_search_off` 를 붙인다 — 저장본은 그대로. 요약이 없으면 None 그대로."""
    if summary is None:
        return None
    return {**summary, "ai_search_off": ai_search_off(context)}


def match_requirements(
    requirements: list[Requirement],
    *,
    context: AnalysisContext,
    chunks: list[EvidenceChunk] | None = None,
) -> EvidenceResult:
    """요구사항마다 상위 K개 근거를 찾아 채택/후보로 나눈다. 인덱스는 컨텍스트의 범위로만 고른다."""
    if context.evidence_scope == "explicit_test":
        if chunks is None:
            raise ScopeError("explicit_test 범위는 chunks 를 넘겨야 합니다")
        pool = chunks
    else:
        if chunks is not None:
            raise ScopeError("운영 범위(internal/public_demo)에서는 chunk 를 직접 넘길 수 없습니다")
        pool = load_index(context=context)

    if not pool or not llm_client.is_configured():
        # 43차 결정 3 · E2E-06 — 회사 근거 연결(AI 검색)이 꺼져 있으면 실적 원장에서 규칙으로 맞춘 후보(미채택)를 보인다 · 사람이 고른 것만 쓴다
        ledger = ledger_candidates(requirements, context)
        head = _empty_pool_reason(context) if not pool else "회사 근거 연결(AI 검색)은 꺼 두었습니다"
        reason = (
            f"{head} — 원장 후보 실적(미채택) {len(ledger)}건을 규칙으로 맞췄습니다. 쓸 것을 골라 채택하세요(고르기 전에는 초안에 쓰지 않습니다)."
            if ledger else f"{head} — 원장 후보에서 고르세요(지금 맞는 원장 후보 없음)."
        )
        return EvidenceResult(available=bool(ledger), matches=ledger, reason=reason, scope_info=scope_info_of(context, pool, [], note=reason))

    try:
        vectors = embed_requirements(requirements)
    except llm_client.LLMUnavailableError as exc:
        # exc 메시지는 이미 사용자에게 보여줄 한국어다 (llm_client.embed_failure_reason).
        reason = f"회사 수행근거 연결에 실패했습니다. {exc} 규칙 기반 결과만 표시합니다."
        return EvidenceResult(available=False, reason=reason, scope_info=scope_info_of(context, pool, [], note=reason))

    matches: list[EvidenceMatch] = []
    for req in requirements:
        vector = vectors[req.requirement_id]
        scored = sorted(
            ((cosine(vector, c.embedding), c) for c in pool),
            key=lambda p: p[0],
            reverse=True,
        )[:TOP_K]
        for score, chunk in scored:
            if score < CANDIDATE_THRESHOLD:
                continue
            # 모호한 요구사항은 점수가 높아도 자동 채택하지 않는다 (사람 검토).
            ambiguous = req.status == "check"
            selected = score >= SELECT_THRESHOLD and not ambiguous
            note = None
            if ambiguous and score >= SELECT_THRESHOLD:
                note = "유사도는 높지만 모호한 조건이라 자동 충족 처리하지 않습니다 (사람 검토 필요)."
            elif not selected:
                note = "유사도가 채택 기준에 못 미쳐 후보로만 둡니다."
            matches.append(
                EvidenceMatch(
                    requirement_id=req.requirement_id,
                    evidence_id=chunk.evidence_id,
                    document_name=chunk.document_name,
                    doc_type=chunk.doc_type,
                    page=chunk.page,
                    source_text=chunk.source_text,
                    similarity_score=score,
                    selected=selected,
                    note=note,
                    synthetic=chunk.synthetic,
                    anonymized=chunk.anonymized,
                    data_class=chunk.data_class,
                    source_kind=chunk.source_kind,
                    document_id=chunk.document_id,
                    organization_id=chunk.organization_id if chunk.organization_id else (None if chunk.synthetic else context.organization_id),
                )
            )

    seen: dict[str, dict[str, Any]] = {}
    for chunk in pool:
        seen.setdefault(
            chunk.evidence_id,
            {
                "id": chunk.evidence_id,
                "document_name": chunk.document_name,
                "doc_type": chunk.doc_type,
                "page": chunk.page,
                "source_text": chunk.source_text,
                "synthetic": chunk.synthetic,
                "anonymized": chunk.anonymized,
            },
        )
    return EvidenceResult(available=True, matches=matches, documents=list(seen.values()), scope_info=scope_info_of(context, pool, matches))


def search(query_vector: list[float], *, context: AnalysisContext, top_k: int = 5) -> list[tuple[float, EvidenceChunk]]:
    """검색 품질 확인용 (등록 흐름의 '테스트 검색'). 컨텍스트 범위의 인덱스만 본다."""
    pool = load_index(context=context)
    scored = sorted(((cosine(query_vector, c.embedding), c) for c in pool), key=lambda p: p[0], reverse=True)
    return scored[:top_k]
