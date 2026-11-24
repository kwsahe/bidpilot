"""회사자료 등록 파이프라인 — 조직(회사)별로 완전히 분리된다.

흐름: 업로드 → 텍스트 추출 → 후보 문단 표시 → 담당자 확인(채택/제외) → 문서 승인(근거 등록)
      → 색인(임베딩 키가 있을 때) → 요구사항 매칭에 사용 → 어디에 쓰였는지 역추적

저장 위치는 전부 `app.core.org_storage` 가 정한다 (조직 폴더 data/private/organizations/{organization_id}/).
- 기본 조직(org-sample)은 레거시 data/company/ 를 **읽기 전용**으로 대체 조회한다 (마이그레이션 전 호환).
- 모든 함수는 organization_id 를 명시적으로 받는다. 암묵적 기본 조직은 호환 API(/api/company)에서만 채운다.

원칙
- 실제 자료는 Git에 올리지 않는다. 합성 자료(data/synthetic_company)와 폴더부터 다르다.
- 승인되지 않은 문단은 근거로 쓰지 않는다. 유효기간이 지난 문서, 비활성 문서도 매칭에서 뺀다.
- 임베딩 키가 없으면 "승인됨·색인 대기"로 정직하게 남긴다. 가짜 벡터를 만들지 않는다.
- 로그에 파일 내용·개인정보를 남기지 않는다.
- 중복 검사는 조직 안에서만 한다. 같은 파일을 서로 다른 조직이 각각 등록할 수 있다.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from app.core import org_storage, requester, storage
from app.core.config import get_settings
from app.core.paths import DATA_ROOT
from app.schemas.company import (
    CandidateReviewRequest,
    CompanyDocument,
    CompanyDocumentDetail,
    DOCUMENT_STATUS_LABEL,
    DocumentApproveRequest,
    DocumentListResponse,
    DocumentRetireRequest,
    EvidenceCandidate,
    EvidenceMetadata,
    IndexStatus,
    ReindexResult,
    UsageEntry,
    UsageResponse,
)
from app.services import company_index_service as cis
from app.services import document_extractor, llm_client
from app.services.finding_resolution_service import fnv1a32

logger = logging.getLogger(__name__)

# 공개(합성) 제안서 위치 — 인용 역추적에서 레거시 호환으로만 훑는다. 공개 결과에는 합성 근거만 인용될 수 있다.
PROPOSALS_DIR = DATA_ROOT / "public" / "proposals"

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
ALLOWED_SUFFIXES: tuple[str, ...] = (".pdf", ".hwp", ".hwpx", ".docx", ".md", ".txt")
PARAGRAPHS_PER_PAGE = document_extractor.PARAGRAPHS_PER_PAGE
MIN_CANDIDATE_CHARS = 20

_UNSAFE_NAME_RE = re.compile(r'[\x00-\x1f\x7f<>:"|?*\\/]')


class CompanyDocumentError(ValueError):
    """업로드 검증 실패 (형식·크기·빈 파일)."""


class DuplicateDocumentError(ValueError):
    def __init__(self, existing_id: str) -> None:
        self.existing_id = existing_id
        super().__init__(f"같은 내용의 문서가 이미 등록되어 있습니다: {existing_id}")


class DocumentNotFoundError(LookupError):
    """없는 문서 id (다른 조직의 문서도 '없음'으로만 답한다 — 존재 여부를 누출하지 않는다)."""


class DocumentStateError(ValueError):
    """현재 상태에서 허용되지 않는 동작 (예: 채택 문단 없이 승인)."""


class CompanyRegistryUnavailableError(RuntimeError):
    """회사자료 등록부 JSON 이 깨져 읽지 못했다 (원본은 storage 가 `.corrupt-*` 로 격리).

    빈 목록으로 뭉개면 화면에는 「등록한 자료가 없습니다」로 보인다 — 자료가 증발한 것과 구분되지 않는다.
    「없다」가 아니라 「못 읽었다」라고 말하기 위해 따로 둔 예외다.
    """

    def __init__(self, organization_id: str, quarantined: Path | None) -> None:
        self.organization_id = organization_id
        self.quarantined = quarantined
        where = f" (원본 보관: {quarantined.name})" if quarantined else ""
        super().__init__(f"회사자료 등록부를 읽지 못했습니다: {organization_id}{where}")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _store(organization_id: str) -> org_storage.OrganizationStorage:
    return org_storage.storage_for(organization_id)


# --------------------------------------------------------------------------
# 1) 문서 등록부 (조직별)
# --------------------------------------------------------------------------


def registry_quarantine_files(organization_id: str) -> list[Path]:
    """등록부가 깨져 격리된 파일 목록 (`documents.json.corrupt-*`).

    깨진 파일은 첫 읽기에서 격리되고 그 다음 읽기부터는 「파일 없음 = 빈 등록부」가 되어 버린다.
    그래서 예외 한 번만으로는 사실이 남지 않는다 — 남는 흔적은 이 격리 파일뿐이다.
    호출자(근거 매칭 사유 문구 등)가 「자료 없음」과 「읽기 실패」를 가르는 근거로 쓴다.
    """
    store = _store(organization_id)
    parent = store.documents_file.parent
    if not parent.exists():
        return []
    return sorted(parent.glob(f"{store.documents_file.name}.corrupt-*"))


def _load_registry(organization_id: str) -> list[CompanyDocument]:
    store = _store(organization_id)
    try:
        payload = storage.read_json(store.read_path("documents"), default=None)
    except storage.CorruptJsonError as exc:
        # 조용히 [] 로 떨어뜨리지 않는다. 로그에는 파일명만 남긴다 (내용·개인정보 금지).
        logger.error(
            "회사자료 등록부를 읽지 못했습니다 (organization_id=%s, 격리=%s)",
            organization_id,
            exc.quarantined.name if exc.quarantined else "격리 실패",
        )
        raise CompanyRegistryUnavailableError(organization_id, exc.quarantined) from exc
    if not isinstance(payload, dict):
        return []
    documents: list[CompanyDocument] = []
    for item in payload.get("documents", []):
        doc = CompanyDocument.model_validate(item)
        # 레거시 등록부(organization_id 없음)는 기본 조직 소유로 읽는다. 다른 조직 문서가 섞여 있으면 뺀다.
        if doc.organization_id is None:
            doc.organization_id = organization_id
        if doc.organization_id != organization_id:
            continue
        documents.append(doc)
    return documents


def _stamp_actors(organization_id: str, documents: list[CompanyDocument]) -> None:
    """이번에 **실제로 바뀐** 문서에만 「누가 바꿨는가」를 찍는다 (S12).

    왜 여기서 하는가: 문서 쓰기는 업로드·본문 추출·후보 검토·승인·폐기·삭제·색인까지
    열세 곳에서 이 함수로 모인다. 각 호출부에 인자를 하나씩 더하면 **한 곳만 빠뜨려도
    그 경로는 조용히 비어 있는 기록을 남긴다** — 기록이 비었다는 것을 아무도 모른다.
    모이는 자리에서 한 번 하면 빠질 곳이 없다.

    왜 전부에 찍지 않는가: 이 목록에는 이번에 건드리지 않은 문서도 함께 들어 있다.
    전부 찍으면 남의 승인 기록이 내 이름으로 덮인다.

    비교를 위해 저장된 파일을 한 번 더 읽는다. 등록부는 문서 수십 건짜리 작은 파일이고,
    이 경로는 사람이 버튼을 누를 때만 지나간다.
    """
    actor = requester.current_recorded_by()
    if actor is None:
        return  # 인증이 꺼진 로컬 — 기록할 신원 자체가 없다.
    stored = storage.read_json(_store(organization_id).documents_file, default=None)
    previous: dict[str, Any] = {}
    if isinstance(stored, dict):
        for raw in stored.get("documents", []) or []:
            if isinstance(raw, dict) and isinstance(raw.get("id"), str):
                previous[raw["id"]] = raw
    for doc in documents:
        before = previous.get(doc.id)
        now = doc.model_dump(mode="json")
        # `recorded_by` 자체는 비교에서 뺀다 — 그것만 다른 것은 「바뀐 것」이 아니다.
        if before is not None and {k: v for k, v in before.items() if k != "recorded_by"} == {
            k: v for k, v in now.items() if k != "recorded_by"
        }:
            continue
        doc.recorded_by = actor


def _save_registry(organization_id: str, documents: list[CompanyDocument]) -> None:
    for doc in documents:
        doc.organization_id = organization_id
    _stamp_actors(organization_id, documents)
    payload: dict[str, Any] = {
        "_note": "회사자료 등록부. 내부 전용 — Git에 올리지 않는다.",
        "organization_id": organization_id,
        "documents": [doc.model_dump(mode="json") for doc in documents],
    }
    storage.stamp(payload)
    storage.write_json_atomic(_store(organization_id).documents_file, payload)


def _load_candidates(organization_id: str, document_id: str) -> list[EvidenceCandidate]:
    payload = storage.read_json(_store(organization_id).read_candidate_path(document_id), default=None)
    if not isinstance(payload, dict):
        return []
    owner = payload.get("organization_id")
    if owner not in (None, organization_id):
        return []
    candidates = [EvidenceCandidate.model_validate(item) for item in payload.get("candidates", [])]
    for c in candidates:
        if c.organization_id is None:
            c.organization_id = organization_id
    return candidates


def _save_candidates(organization_id: str, document_id: str, candidates: list[EvidenceCandidate]) -> None:
    for c in candidates:
        c.organization_id = organization_id
    payload: dict[str, Any] = {
        "organization_id": organization_id,
        "document_id": document_id,
        "candidates": [c.model_dump(mode="json") for c in candidates],
    }
    storage.stamp(payload)
    storage.write_json_atomic(_store(organization_id).candidate_path(document_id), payload)


def _get(documents: list[CompanyDocument], document_id: str) -> tuple[int, CompanyDocument]:
    for index, doc in enumerate(documents):
        if doc.id == document_id:
            return index, doc
    raise DocumentNotFoundError(document_id)


def safe_file_name(name: str) -> str:
    cleaned = _UNSAFE_NAME_RE.sub("_", Path(name).name).strip() or "document"
    return cleaned[:120]


def _title_of(file_name: str) -> str:
    return Path(file_name).stem[:200] or file_name


# --------------------------------------------------------------------------
# 2) 업로드 → 추출 → 후보
# --------------------------------------------------------------------------


def register_upload(
    organization_id: str,
    *,
    file_name: str,
    payload: bytes,
    doc_type: str = "기타",
    uploaded_by: str | None = None,
    data_class: str = "real",
) -> CompanyDocumentDetail:
    """파일을 검증·저장하고 즉시 텍스트를 추출해 후보를 만든다. 중복 검사는 이 조직 안에서만 한다."""
    store = _store(organization_id)
    name = safe_file_name(file_name)
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise CompanyDocumentError(f"지원하지 않는 형식입니다: {suffix or '확장자 없음'} (허용: {', '.join(ALLOWED_SUFFIXES)})")
    if not payload:
        raise CompanyDocumentError("빈 파일입니다")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise CompanyDocumentError(f"업로드 상한({MAX_UPLOAD_BYTES // (1024 * 1024)}MB)을 초과했습니다")

    digest = hashlib.sha256(payload).hexdigest()
    documents = _load_registry(organization_id)
    for doc in documents:
        if doc.sha256 == digest and doc.status != "rejected":
            raise DuplicateDocumentError(doc.id)

    # 문서 id 는 조직별로 만든다 (같은 파일을 두 조직이 올려도 id 가 겹치지 않는다). 마이그레이션한 레거시 id 는 그대로 둔다.
    document_id = f"CD-{fnv1a32(f'{organization_id}:{digest}')}-{len(documents) + 1:03d}"
    stored = store.upload_path(document_id, suffix)
    stored.parent.mkdir(parents=True, exist_ok=True)
    stored.write_bytes(payload)

    document = CompanyDocument(
        id=document_id,
        organization_id=organization_id,
        file_name=name,
        title=_title_of(name),
        doc_type=doc_type or "기타",
        status="pending",
        size_bytes=len(payload),
        sha256=digest,
        uploaded_at=_now(),
        uploaded_by=uploaded_by,
        metadata=EvidenceMetadata(
            source_kind="upload",
            location=name,
            data_class=data_class if data_class in ("real", "anonymized", "synthetic") else "real",  # type: ignore[arg-type]
            checksum=digest,
        ),
    )
    documents.append(document)
    _save_registry(organization_id, documents)
    return extract_document(organization_id, document_id)


def _pages_from_text(path: Path) -> list[document_extractor.DocumentPage]:
    text = path.read_text(encoding="utf-8", errors="replace")
    _meta, body = cis.parse_front_matter(text)
    chunks = cis.split_chunks(body)
    if not chunks:
        # 인용(>) 제거는 문서 앞머리의 도구 안내문을 걸러내려는 규칙인데,
        # 본문 전체가 인용으로 적힌 문서에서는 문단이 하나도 남지 않는다.
        # 「추출 실패」로 끝내기 전에 인용 표시만 벗기고 한 번 더 시도한다.
        # (실측: 06_curriculum.md 가 이 경우였다 — 제목·표·인용만 있는 마크다운)
        chunks = cis.split_chunks(body, keep_quotes=True)
    return [document_extractor.DocumentPage(page=i, text=chunk) for i, chunk in enumerate(chunks, start=1)]


def _candidates_from_pages(
    organization_id: str, document_id: str, pages: list[document_extractor.DocumentPage], *, chunked: bool
) -> list[EvidenceCandidate]:
    candidates: list[EvidenceCandidate] = []
    seq = 0
    for page in pages:
        pieces = [page.text] if chunked else cis.split_chunks(page.text)
        for piece in pieces:
            text = piece.strip()
            if len(text) < MIN_CANDIDATE_CHARS:
                continue
            seq += 1
            gap = cis.is_gap_chunk(text)
            candidates.append(
                EvidenceCandidate(
                    id=f"{document_id}:{seq:03d}",
                    document_id=document_id,
                    organization_id=organization_id,
                    page=page.page,
                    source_text=text,
                    approved=False if gap else None,
                    is_gap=gap,
                    note="근거가 아니라 '확인하지 못한 사항'을 적은 문단이라 기본 제외" if gap else None,
                )
            )
    return candidates


def extract_document(organization_id: str, document_id: str) -> CompanyDocumentDetail:
    store = _store(organization_id)
    documents = _load_registry(organization_id)
    index, document = _get(documents, document_id)
    suffix = Path(document.file_name).suffix.lower()
    stored = store.read_upload_path(document.id, suffix)
    if not stored.exists():
        document.status = "failed"
        document.error = "원본 파일이 없습니다 (업로드 폴더에서 삭제됨)"
        documents[index] = document
        _save_registry(organization_id, documents)
        return CompanyDocumentDetail(**document.model_dump(), candidates=[])

    document.status = "extracting"
    document.error = None
    documents[index] = document
    _save_registry(organization_id, documents)

    try:
        if suffix == ".docx":
            pages = document_extractor.extract_docx(stored)
            document.doc_format = "docx"
            candidates = _candidates_from_pages(organization_id, document.id, pages, chunked=False)
        elif suffix in (".md", ".txt"):
            pages = _pages_from_text(stored)
            document.doc_format = suffix.lstrip(".")
            candidates = _candidates_from_pages(organization_id, document.id, pages, chunked=True)
        else:
            extracted = document_extractor.extract_document(stored, file_name=document.file_name)
            document.doc_format = extracted.doc_format
            pages = extracted.pages
            candidates = _candidates_from_pages(organization_id, document.id, pages, chunked=False)
        if not candidates:
            raise document_extractor.DocumentExtractionError("문서에서 근거로 쓸 만한 문단을 찾지 못했습니다")
    except Exception as exc:  # noqa: BLE001 — 사용자 파일은 어떤 예외로도 죽을 수 있다. 상태와 사유를 남긴다.
        document.status = "failed"
        # 예외 문장에는 서버 경로가 섞인다. 화면에 나가는 사유는 우리가 만든 문장만 쓴다.
        document.error = (
            str(exc)[:500]
            if isinstance(exc, document_extractor.DocumentExtractionError)
            else "파일을 읽지 못했습니다. 형식이 맞는지 확인해 주세요."
        )
        document.extracted_at = _now()
        documents[index] = document
        _save_registry(organization_id, documents)
        return CompanyDocumentDetail(**document.model_dump(), candidates=[])

    document.status = "review"
    document.extracted_at = _now()
    document.page_count = len(pages)
    document.candidate_count = len(candidates)
    document.approved_chunk_count = 0
    documents[index] = document
    _save_registry(organization_id, documents)
    _save_candidates(organization_id, document.id, candidates)
    return CompanyDocumentDetail(**document.model_dump(), candidates=candidates)


# --------------------------------------------------------------------------
# 3) 검토 → 승인 → 색인
# --------------------------------------------------------------------------


def review_candidates(organization_id: str, document_id: str, request: CandidateReviewRequest) -> CompanyDocumentDetail:
    documents = _load_registry(organization_id)
    index, document = _get(documents, document_id)
    if document.status not in ("review", "approved", "indexed", "failed"):
        raise DocumentStateError(f"「{DOCUMENT_STATUS_LABEL.get(document.status, document.status)}」 상태의 문서는 검토할 수 없습니다")
    candidates = _load_candidates(organization_id, document_id)
    by_id = {c.id: c for c in candidates}
    now = _now()
    for review in request.reviews:
        candidate = by_id.get(review.candidate_id)
        if candidate is None:
            raise DocumentNotFoundError(review.candidate_id)
        candidate.approved = review.approved
        candidate.reviewer = request.reviewer
        candidate.reviewed_at = now
        if review.note is not None:
            candidate.note = review.note
    _save_candidates(organization_id, document_id, candidates)
    document.approved_chunk_count = sum(1 for c in candidates if c.approved)
    documents[index] = document
    _save_registry(organization_id, documents)
    return CompanyDocumentDetail(**document.model_dump(), candidates=candidates)


def approve_document(organization_id: str, document_id: str, request: DocumentApproveRequest) -> CompanyDocumentDetail:
    """담당자가 근거로 등록한다. 채택 문단이 하나도 없으면 승인할 수 없다."""
    documents = _load_registry(organization_id)
    index, document = _get(documents, document_id)
    candidates = _load_candidates(organization_id, document_id)
    approved = [c for c in candidates if c.approved]
    if not approved:
        raise DocumentStateError("채택한 문단이 없어 근거로 등록할 수 없습니다. 후보 문단을 먼저 확인하세요.")
    if request.valid_from and request.valid_to and request.valid_to < request.valid_from:
        raise DocumentStateError("유효기간 종료일이 시작일보다 앞섭니다")
    now = _now()
    document.metadata = document.metadata.model_copy(
        update={
            "approved": True,
            "approved_by": request.reviewer,
            "approved_at": now,
            "last_verified_at": now,
            "data_class": request.data_class,
            "scope": request.scope,
            "valid_from": request.valid_from,
            "valid_to": request.valid_to,
            "version": document.metadata.version + (1 if document.metadata.approved else 0),
            "retired": False,
        }
    )
    if request.doc_type:
        document.doc_type = request.doc_type
    if request.title:
        document.title = request.title
    if request.note is not None:
        document.note = request.note
    document.status = "approved"
    document.approved_chunk_count = len(approved)
    documents[index] = document
    _save_registry(organization_id, documents)
    # 색인은 키가 있을 때만 자동으로 갱신한다. 없으면 승인 상태로 남는다 (정직하게).
    if llm_client.is_configured():
        rebuild_index(organization_id)
    return get_document(organization_id, document_id)


def retire_document(organization_id: str, document_id: str, request: DocumentRetireRequest) -> CompanyDocument:
    documents = _load_registry(organization_id)
    index, document = _get(documents, document_id)
    document.status = "retired"
    document.metadata = document.metadata.model_copy(update={"retired": True, "approved": False})
    document.note = request.note or document.note
    documents[index] = document
    _save_registry(organization_id, documents)
    if llm_client.is_configured():
        rebuild_index(organization_id)
    return document


def delete_document(organization_id: str, document_id: str) -> None:
    """등록부·후보·원본을 지운다. 승인된 문서는 먼저 비활성으로 돌려야 한다. 조직 폴더 안의 파일만 지운다."""
    store = _store(organization_id)
    documents = _load_registry(organization_id)
    index, document = _get(documents, document_id)
    if document.status in ("approved", "indexed"):
        raise DocumentStateError("근거로 등록된 문서는 먼저 「비활성」으로 바꿔야 삭제할 수 있습니다")
    documents.pop(index)
    _save_registry(organization_id, documents)
    suffix = Path(document.file_name).suffix.lower()
    for path in (store.upload_path(document.id, suffix), store.candidate_path(document.id)):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("파일 삭제 실패: %s", path.name)


def is_active(document: CompanyDocument, today: date | None = None) -> bool:
    """매칭에 써도 되는 문서인지 — 승인·비활성 아님·유효기간 안."""
    moment = today or storage.kst_today()
    meta = document.metadata
    if document.status not in ("approved", "indexed") or not meta.approved or meta.retired:
        return False
    if meta.valid_from and moment < meta.valid_from:
        return False
    if meta.valid_to and moment > meta.valid_to:
        return False
    return True


def active_document_ids(organization_id: str) -> set[str]:
    return {doc.id for doc in _load_registry(organization_id) if is_active(doc)}


def _index_entries(organization_id: str) -> tuple[list[dict[str, Any]], int]:
    entries: list[dict[str, Any]] = []
    doc_count = 0
    for document in _load_registry(organization_id):
        if not is_active(document):
            continue
        approved = [c for c in _load_candidates(organization_id, document.id) if c.approved]
        if not approved:
            continue
        doc_count += 1
        for candidate in approved:
            entries.append(
                {
                    "evidence_id": candidate.id,
                    "organization_id": organization_id,
                    "document_id": document.id,
                    "document_name": document.title,
                    "doc_type": document.doc_type,
                    "page": candidate.page,
                    "source_text": candidate.source_text,
                    "synthetic": document.metadata.data_class == "synthetic",
                    "anonymized": document.metadata.data_class == "anonymized",
                    "data_class": document.metadata.data_class,
                    "source_kind": document.metadata.source_kind,
                    "scope": document.metadata.scope,
                    "valid_to": document.metadata.valid_to.isoformat() if document.metadata.valid_to else None,
                    "source_file": document.file_name,
                }
            )
    return entries, doc_count


def rebuild_index(organization_id: str) -> ReindexResult:
    """이 조직의 승인 문단으로 회사 인덱스를 다시 만든다. 키가 없으면 만들지 않는다. 다른 조직 인덱스는 건드리지 않는다."""
    if not llm_client.is_configured():
        return ReindexResult(ok=False, reason="AI 검색 설정이 없어 색인하지 않았습니다. 승인 상태는 유지됩니다.", organization_id=organization_id)
    entries, doc_count = _index_entries(organization_id)
    documents = _load_registry(organization_id)
    now = _now()
    for doc in documents:
        if is_active(doc):
            doc.status = "indexing"
    _save_registry(organization_id, documents)
    try:
        payload = cis.build_index_payload(
            entries,
            embed=llm_client.embed,
            model=get_settings().embedding_model,
            document_count=doc_count,
            note=f"회사자료 근거 색인 (담당자 승인 문단만) · organization_id={organization_id}. 내부 전용 — Git에 올리지 않는다.",
        )
    except (llm_client.LLMUnavailableError, Exception) as exc:  # noqa: BLE001 — 실패 사유는 상태에 남긴다
        for doc in documents:
            if doc.status == "indexing":
                doc.status = "approved"
                doc.error = f"색인 실패: {exc}"
        _save_registry(organization_id, documents)
        # LLMUnavailableError 의 메시지는 이미 사람이 읽을 한국어 문장이다
        # (「AI 검색 크레딧이 소진되었습니다…」). 앞에 기술어를 붙이면 화면에서 두 번 읽힌다.
        reason = str(exc) if isinstance(exc, llm_client.LLMUnavailableError) else f"임베딩 호출 실패: {exc}"
        return ReindexResult(ok=False, reason=reason, organization_id=organization_id)
    payload["organization_id"] = organization_id
    storage.write_json_atomic(_store(organization_id).index_file, payload)
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry["document_id"]] = counts.get(entry["document_id"], 0) + 1
    for doc in documents:
        if doc.status == "indexing":
            doc.status = "indexed"
            doc.error = None
            doc.indexed_at = now
            doc.indexed_chunk_count = counts.get(doc.id, 0)
    _save_registry(organization_id, documents)
    return ReindexResult(
        ok=True, reason="색인 완료", chunk_count=len(entries), document_count=doc_count, built_at=now, organization_id=organization_id
    )


# --------------------------------------------------------------------------
# 4) 조회
# --------------------------------------------------------------------------


def index_status(organization_id: str) -> IndexStatus:
    store = _store(organization_id)
    documents = _load_registry(organization_id)
    company = cis.index_summary(store.read_path("index"))
    pending = sum(1 for d in documents if d.status == "approved")
    active = [d for d in documents if is_active(d)]
    stale = bool(active) and (not company["exists"] or pending > 0)
    # 키 «문자열이 있는지»가 아니라 **실제로 쓸 수 있는지**를 본다.
    # 거부되는 키를 「사용 가능」이라고 답하면 화면이 검색 단추를 열어 두었다가 500 을 만난다.
    available = llm_client.embedding_available()
    if not available:
        # **왜** 못 쓰는지 알면 그것을 적는다. 크레딧이 바닥난 것을 「설정을 쓸 수 없다」고만
        # 적으면 담당자가 있지도 않은 설정 문제를 찾아 헤맨다 (0920 §4-B-5 · ISSUE-078).
        why = llm_client.embedding_unavailable_reason()
        note = (
            f"{why} 승인한 문서는 '승인·색인 대기'로 남습니다."
            if why
            else "AI 검색 설정을 쓸 수 없어 검색 자료를 만들 수 없습니다. "
            "승인한 문서는 '승인·색인 대기'로 남습니다. 관리자에게 설정 확인을 요청해 주세요."
        )
    elif pending:
        note = f"근거로 등록했지만 검색 준비 전인 문서 {pending}건 — 「AI 검색 다시 준비」를 누르세요."
    else:
        note = "내부 분석은 이 회사의 승인 자료만 검색합니다. 가상 예시 회사자료 색인은 공개 데모에서만 쓰이며 섞이지 않습니다."
    return IndexStatus(
        organization_id=organization_id,
        embedding_available=available,
        embedding_model=get_settings().embedding_model if available else None,
        synthetic_index=cis.index_summary(cis.SYNTHETIC_INDEX_FILE),
        company_index=company,
        pending_documents=pending,
        stale=stale,
        note=note,
    )


def list_documents(organization_id: str) -> DocumentListResponse:
    documents = sorted(_load_registry(organization_id), key=lambda d: d.uploaded_at, reverse=True)
    counts: dict[str, int] = {}
    for doc in documents:
        counts[doc.status] = counts.get(doc.status, 0) + 1
    return DocumentListResponse(organization_id=organization_id, documents=documents, counts=counts, index=index_status(organization_id))


def get_document(organization_id: str, document_id: str) -> CompanyDocumentDetail:
    _index, document = _get(_load_registry(organization_id), document_id)
    return CompanyDocumentDetail(**document.model_dump(), candidates=_load_candidates(organization_id, document_id))


def _usage_from_payload(payload: dict[str, Any], prefix: str, where: str, fallback_pid: str) -> list[UsageEntry]:
    entries: list[UsageEntry] = []
    sections = payload.get("sections") if where == "proposal_document" else [payload]
    for section in sections or []:
        if not isinstance(section, dict):
            continue
        for sentence in section.get("sentences", []):
            evidence_id = str(sentence.get("evidence_id") or "")
            if evidence_id.startswith(prefix):
                entries.append(
                    UsageEntry(
                        procurement_id=str(payload.get("procurement_id") or fallback_pid),
                        organization_id=payload.get("organization_id"),
                        requirement_id=sentence.get("requirement_id"),
                        evidence_id=evidence_id,
                        where=where,  # type: ignore[arg-type]
                        sentence_id=sentence.get("id"),
                    )
                )
    return entries


def usage_of(organization_id: str, document_id: str) -> UsageResponse:
    """이 문서의 문단이 어느 공고의 제안서 문장에 인용됐는지. 이 조직의 분석 결과만 훑는다 (다른 조직 제안서는 보지 않는다)."""
    from app.services import analysis_store

    _get(_load_registry(organization_id), document_id)
    prefix = f"{document_id}:"
    entries: list[UsageEntry] = []
    private_files = [
        (p, "proposal") for p in analysis_store.iter_private_results(organization_id, "proposal.json")
    ] + [(p, "proposal_document") for p in analysis_store.iter_private_results(organization_id, "proposal_document.json")]
    for path, where in private_files:
        try:
            payload = storage.read_json(path, default=None)
        except storage.CorruptJsonError:
            continue
        if not isinstance(payload, dict) or payload.get("organization_id") not in (None, organization_id):
            continue
        entries.extend(_usage_from_payload(payload, prefix, where, path.parent.name))
    # 레거시 호환: 공개 위치의 제안서(합성 근거만 인용될 수 있다). 다른 조직 표시가 있으면 뺀다.
    if PROPOSALS_DIR.exists():
        for path in sorted(PROPOSALS_DIR.glob("*.json")):
            try:
                payload = storage.read_json(path, default=None)
            except storage.CorruptJsonError:
                continue
            if not isinstance(payload, dict) or payload.get("organization_id") not in (None, organization_id):
                continue
            where = "proposal_document" if path.name.endswith(".document.json") else "proposal"
            entries.extend(_usage_from_payload(payload, prefix, where, path.name.split(".")[0]))
    return UsageResponse(organization_id=organization_id, document_id=document_id, used_in=entries)


# --------------------------------------------------------------------------
# 5) 프로필 (조직 서비스로 위임 — 서식 자동 채움 등 기존 호출자용)
# --------------------------------------------------------------------------


def load_profile(organization_id: str):  # noqa: ANN201 — OrganizationProfile (순환 import 회피)
    from app.services import organization_service

    return organization_service.load_profile(organization_id)
