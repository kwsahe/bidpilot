"""공고 직접 넣기 (38차 §3-E-1~4 · 담당자 결정 3 · D16).

## 규율

- **저장**: `data/private/organizations/<org>/manual_notices/<id>.json`(+ 올린 공고문 `<id>.<확장자>`). id 는 `manual-<정규화 URL 해시>` —
  해시에 회사 id 를 함께 넣는다(같은 주소를 두 회사가 넣어도 한 회사가 올린 공고문 · 조항이 다른 회사 판정에 섞이지 않게).
  입력 시각 · 입력자를 남긴다. 본문 · 공고문 속 연락처는 `procurement_service.mask_contact_fields` 로 가린다.
- **중복**: 주소 · 본문에 나라장터 공고번호(R26BK…) · 기업마당 `pblancId`(PBLN_…)가 있고 저장본에 있으면 새로 만들지 않는다.
- **판정**: 입찰 · 수행기관 모집(매출)은 나라장터와 같은 규칙 경로(`eligibility_engine.evaluate_notice_fields` · 사람이 적은 칸만
  같은 열쇠로 옮김), 수혜(지원금)는 지원사업 경로(`support_application_service.judge`). 공고문 파일이 있으면 조항을 뽑아
  원문 근거로 판정한다. **D16 — 직접 넣은 공고는 자동으로 「가능」이 되지 않는다**: 규칙이 가능이라 해도 「확인 필요」로 두고,
  공고문 파일이 없으면 「확인 필요 — 공고문 아직 안 읽음」이다. 불가(마감 지남 · 지역 등 회사 사실과 어긋남)는 그대로 불가다.
- 서버는 사람이 준 주소를 **열지 않는다**(SSRF 없음). 주소는 화면 · 브리핑의 링크로만 나간다.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from app.core import org_storage, storage
from app.schemas.manual_notice import (
    ManualDocument,
    ManualHumanPass,
    ManualNotice,
    ManualNoticeInput,
    ManualSaveResult,
)

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
FOLDER = "manual_notices"
ID_PREFIX = "manual-"
ALLOWED_SUFFIXES: tuple[str, ...] = (".pdf", ".hwp", ".hwpx", ".docx")
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
G2B_NO_RE = re.compile(r"R\d{2}BK\d{8}")
#: 사전규격 등록번호(43차 H4 — 사전규격 링크를 붙여도 「확인 전」이었다).
PRESPEC_NO_RE = re.compile(r"R\d{2}BD\d{8}")
PBLN_RE = re.compile(r"PBLN_\d{12,15}")
_ID_RE = re.compile(r"^manual-[0-9a-f]{12}$")

#: 판정 사유 (화면 · 브리핑이 같은 글을 쓴다).
NOT_READ_REASON = "확인 필요 — 공고문 아직 안 읽음(직접 넣은 공고 · 공고문 파일을 올리면 조항으로 판정합니다)"
HUMAN_CHECK_REASON = "확인 필요 — 직접 넣은 공고는 공고문 원문을 사람이 확인한 뒤 「가능」입니다"
SOURCE_NAME = "직접 넣음"


class ManualNoticeError(ValueError):
    """사람이 고칠 수 있는 입력 문제(형식 · 크기 · 없는 공고)."""


class ManualNoticeNotFoundError(LookupError):
    pass


# --------------------------------------------------------------------------
# 경로 · id
# --------------------------------------------------------------------------


def folder(organization_id: str) -> Path:
    return org_storage.storage_for(organization_id).root / FOLDER


def normalize_url(url: str) -> str:
    """같은 공고를 같은 id 로 — 스킴 · 호스트 소문자, 조각(#…) 버림, 경로 끝 「/」 버림. 쿼리는 그대로(공고 번호가 거기 있다)."""
    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/") or ""
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def _title_key(title: str | None) -> str:
    return re.sub(r"\s+", "", title or "")


def notice_id_of(organization_id: str, url: str, title: str | None = None) -> str:
    """회사 · 주소(· 공고명) → id. 39차 MANUAL-03 — 같은 게시판 목록 주소에 걸린 다른 공고를 넣을 수 있게 공고명도 넣는다(옛 id 는 그대로 둔다)."""
    key = f"{organization_id}|{normalize_url(url)}" + (f"|{_title_key(title)}" if title else "")
    return ID_PREFIX + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def is_manual_id(value: str | None) -> bool:
    return bool(value and _ID_RE.match(value))


def _path(organization_id: str, notice_id: str) -> Path:
    if not is_manual_id(notice_id):
        raise ManualNoticeNotFoundError(notice_id)
    return folder(organization_id) / f"{notice_id}.json"


# --------------------------------------------------------------------------
# 읽기 · 쓰기
# --------------------------------------------------------------------------


def list_notices(organization_id: str) -> list[ManualNotice]:
    base = folder(organization_id)
    if not base.exists():
        return []
    out: list[ManualNotice] = []
    for path in sorted(base.glob("manual-*.json")):
        try:
            payload = storage.read_json(path, default=None)
            if isinstance(payload, dict):
                out.append(ManualNotice.model_validate(payload))
        except (storage.CorruptJsonError, ValueError):
            logger.warning("직접 넣은 공고 파일을 읽지 못했습니다: %s", path.name)
    return out


def get(organization_id: str, notice_id: str) -> ManualNotice:
    path = _path(organization_id, notice_id)
    try:
        payload = storage.read_json(path, default=None)
    except storage.CorruptJsonError as exc:
        raise ManualNoticeNotFoundError(notice_id) from exc
    if not isinstance(payload, dict):
        raise ManualNoticeNotFoundError(notice_id)
    return ManualNotice.model_validate(payload)


def _masked(data: ManualNoticeInput) -> dict[str, Any]:
    """저장할 칸 — 연락처는 입력 검증(`clean_text(mask=True)`)이 이미 가렸다(공고명 · 기관 · 짧은 칸 · 본문)."""
    return data.model_dump(mode="json")


def _write(notice: ManualNotice) -> ManualNotice:
    storage.write_json_atomic(_path(notice.organization_id, notice.id), notice.model_dump(mode="json"))
    return notice


class StoreIndex:
    """저장본 대조표 — 나라장터 공고번호(차수 없음) → id · 기업마당 `pblancId` 모음. **한 번만 읽는다**(39차 MANUAL-04 —
    붙여넣기 298줄이 줄마다 저장본을 다시 읽어 55초 동안 서버가 멈췄다). 필요한 쪽만 늦게 읽는다."""

    def __init__(self) -> None:
        self._g2b: dict[str, str] | None = None
        self._bizinfo: set[str] | None = None
        self._titles: dict[str, str] | None = None
        self._prespecs: set[str] | None = None

    def g2b(self) -> dict[str, str]:
        if self._g2b is None:
            from app.services import procurement_service

            cached = procurement_service.load_cache()
            self._g2b = {}
            for view in cached.notices if cached else []:
                self._g2b.setdefault(str(view.notice.notice_no or "")[:13], view.notice.id)
        return self._g2b

    def titles(self) -> dict[str, str]:
        """정규화한 공고명(연도 · 띄어쓰기 · 문장부호 뺌) → 나라장터 공고 id(43차 H4 — 민간 입찰정보 · 기관 게시판 주소로 넣은 같은 공고)."""
        if self._titles is None:
            from app.services import prespec_service, procurement_service

            cached = procurement_service.load_cache()
            self._titles = {}
            for view in cached.notices if cached else []:
                key = prespec_service.title_key(view.notice.title)
                if len(key) >= 8:
                    self._titles.setdefault(key, view.notice.id)
        return self._titles

    def prespecs(self) -> set[str]:
        if self._prespecs is None:
            from app.services import prespec_service

            rows, _ = prespec_service.load_prespecs()
            self._prespecs = {str(r.get("bfSpecRgstNo")) for r in rows if r.get("bfSpecRgstNo")}
        return self._prespecs

    def bizinfo(self) -> set[str]:
        if self._bizinfo is None:
            from app.services import bizinfo_service

            try:
                payload = storage.read_json(bizinfo_service.CACHE_FILE, default=None)
            except storage.CorruptJsonError:
                payload = None
            self._bizinfo = {str(i.get("pblancId")) for i in (payload or {}).get("items") or [] if isinstance(i, dict)}
        return self._bizinfo


def find_existing(url: str, body: str | None = None, *, index: StoreIndex | None = None) -> tuple[str | None, str | None]:
    """저장본에 이미 있는 공고인가 — 나라장터 공고번호 · 사전규격 등록번호 · 기업마당 `pblancId`. `(공고 id, 사유)` 또는 `(None, None)`.

    `index` — 여러 줄을 견줄 때 한 번 읽은 대조표(붙여넣기). 없으면 이 줄만을 위해 읽는다."""
    text = f"{url} {body or ''}"
    numbers = list(dict.fromkeys(G2B_NO_RE.findall(text)))
    pblanc = list(dict.fromkeys(PBLN_RE.findall(text)))
    # 사전규격 등록번호는 **주소에서만** 확정한다(44차 TEAM-R36-02 — 본문의 「사전규격 R26BD…」 한 줄로 본공고 넣기가 막혔다).
    # 본문에서만 맞으면 `prespec_in_body` 가 「같은 공고일 수 있음」으로 돌려 「그래도 새로 넣기」로 넘길 수 있다.
    pre = list(dict.fromkeys(PRESPEC_NO_RE.findall(url)))
    if not numbers and not pblanc and not pre:
        return None, None
    lookup = index or StoreIndex()
    for number in pre:
        if number in lookup.prespecs():
            from app.services import prespec_service

            return f"{prespec_service.ID_PREFIX}{number}", f"사전규격 {number} — 이미 받아 둔 사전규격입니다(선제준비 칸)"
    for base in numbers:
        found = lookup.g2b().get(base)
        if found:
            return found, f"나라장터 공고번호 {base} — 이미 받아 둔 공고입니다"
    for pid in pblanc:
        if pid in lookup.bizinfo():
            return f"bizinfo-{pid}", f"기업마당 공고 {pid} — 이미 받아 둔 공고입니다"
    return None, None


def prespec_in_body(url: str, body: str | None, *, index: StoreIndex | None = None) -> tuple[str | None, str | None]:
    """본문에만 받아 둔 사전규격 번호가 있다 — 단정하지 않는다(44차 TEAM-R36-02 · 「그래도 새로 넣기」로 넘길 수 있음)."""
    from app.services import prespec_service

    lookup = index or StoreIndex()
    for number in dict.fromkeys(PRESPEC_NO_RE.findall(body or "")):
        if number in lookup.prespecs() and number not in url:
            return (f"{prespec_service.ID_PREFIX}{number}",
                    f"본문에 받아 둔 사전규격 {number} 이(가) 적혀 있습니다 — 선제준비 칸에 있음 · 같은 공고일 수 있음(본공고면 그대로 넣으세요)")
    return None, None


def similar_existing(title: str | None, *, index: StoreIndex | None = None) -> tuple[str | None, str | None]:
    """공고명(정규화)이 같은 나라장터 공고 — 번호 없는 주소(jodaldata · 기관 게시판)로 넣은 같은 공고(43차 H4). 단정하지 않는다(「일 수 있음」)."""
    from app.services import prespec_service

    key = prespec_service.title_key(title or "")
    if len(key) < 8:
        return None, None
    found = (index or StoreIndex()).titles().get(key)
    return (found, "공고명이 같은 나라장터 공고가 이미 있습니다 — 같은 공고일 수 있음(마감 · 등록 마감은 그 공고를 보세요)") if found else (None, None)


def create(organization_id: str, data: ManualNoticeInput, *, created_by: str | None = None, now: datetime | None = None) -> ManualSaveResult:
    existing, reason = find_existing(data.url, data.body_text)
    if existing:
        return ManualSaveResult(duplicate_of=existing, duplicate_reason=reason)
    if not data.confirm_new:
        similar, why = prespec_in_body(data.url, data.body_text)
        if not similar:
            similar, why = similar_existing(data.title)
        if similar:
            return ManualSaveResult(duplicate_of=similar, duplicate_reason=why, maybe_duplicate=True)
    # 같은 주소 · 같은 공고명이면 같은 공고(39차 MANUAL-03 — 주소만 보면 한 게시판의 다른 공고를 넣지 못했다). 옛 id(주소만)도 함께 본다.
    url_key, title_key = normalize_url(data.url), _title_key(data.title)
    for other in list_notices(organization_id):
        if normalize_url(other.url) == url_key and _title_key(other.title) == title_key:
            return ManualSaveResult(duplicate_of=other.id, duplicate_reason="같은 주소 · 같은 공고명으로 이미 직접 넣은 공고입니다")
    notice_id = notice_id_of(organization_id, data.url, data.title)
    path = _path(organization_id, notice_id)
    if path.exists():
        return ManualSaveResult(duplicate_of=notice_id, duplicate_reason="같은 주소 · 같은 공고명으로 이미 직접 넣은 공고입니다")
    moment = now or storage.utc_now()
    notice = ManualNotice(
        **_masked(data), id=notice_id, organization_id=organization_id, created_at=moment, updated_at=moment,
        created_by=(created_by or None),
    )
    _write(notice)
    if data.inbox_id:
        from app.services import notice_inbox_service

        notice_inbox_service.mark_added(organization_id, data.inbox_id, notice_id)
    return ManualSaveResult(notice=notice)


def update(
    organization_id: str,
    notice_id: str,
    data: ManualNoticeInput,
    *,
    now: datetime | None = None,
    updated_by: str | None = None,
    expected_updated_at: datetime | None = None,
) -> ManualNotice:
    """고치기 — 주소는 바꿀 수 있지만 id 는 처음 것 그대로(올린 공고문 · 순위표가 id 로 잇는다).

    `expected_updated_at`(폼을 연 때 읽은 시각)을 주면 그사이 다른 사람이 고쳤을 때 `StaleWriteError`
    (43차 M25 — 옛 폼이 남의 마감 고침을 되돌렸다)."""
    current = get(organization_id, notice_id)
    if expected_updated_at is not None:
        storage.ensure_unchanged(current.updated_at, expected_updated_at, stored_by=current.updated_by or current.created_by)
    moment = now or storage.utc_now()
    updated = ManualNotice(
        **_masked(data), id=current.id, organization_id=organization_id, created_at=current.created_at,
        created_by=current.created_by, updated_at=moment, updated_by=updated_by, document=current.document,
    )
    saved = _write(updated)
    if current.document is not None and current.recruit != updated.recruit:
        # 44차 S7 — 모집 대상(입찰 · 수행 ↔ 수혜)을 바꾸면 올린 공고문을 새 규칙으로 다시 읽는다(참가자격 조항 ↔ 지원대상 글).
        # 예전에는 옛 규칙으로 뽑은 것이 남아 「공고문 아직 안 읽음」이거나 다른 갈래 조항으로 판정했다.
        return _reread_document(organization_id, saved) or saved
    return saved


def _reread_document(organization_id: str, notice: ManualNotice) -> ManualNotice | None:
    """저장해 둔 공고문 파일로 다시 읽는다(S7). 파일이 없으면 None(그대로 둠). 옛 갈래의 읽은 결과는 지운다."""
    from app.services import qualification_clause_service as qc

    document = notice.document
    if document is None:
        return None
    stored = folder(organization_id) / f"{notice.id}{Path(document.file_name).suffix.lower()}"
    if not stored.exists():
        return None
    if notice.recruit == "benefit":
        qc.clause_path(notice.id, private=True).unlink(missing_ok=True)  # 입찰 갈래로 뽑은 참가자격 조항
    else:
        _text_path(organization_id, notice.id).unlink(missing_ok=True)  # 수혜 갈래로 뽑은 지원대상 글
    return attach_document(organization_id, notice.id, file_name=document.file_name, payload=stored.read_bytes())


class HumanPassRefusedError(ManualNoticeError):
    """규칙에 불가 줄이 있어 「원문 확인함 — 가능으로」를 받을 수 없다(44차 M6)."""


def set_human_pass(
    organization_id: str,
    notice_id: str,
    *,
    by: str,
    reason: str | None,
    expected_updated_at: datetime | None = None,
    gate_now: str | None = None,
    now: datetime | None = None,
    recorded_by: str | None = None,
) -> ManualNotice:
    """「원문 확인함 — 가능으로」 남기기 · 되돌리기(`reason=None`) — 44차 M6 · D16.

    `gate_now` 는 지금 규칙이 낸 판정(부르는 쪽이 목록과 같은 길로 잰 값) — 불가면 거절한다. 그사이 남이 고쳤으면 `StaleWriteError`."""
    current = get(organization_id, notice_id)
    if expected_updated_at is not None:
        storage.ensure_unchanged(current.updated_at, expected_updated_at, stored_by=current.updated_by or current.created_by)
    if reason is not None and gate_now == "FAIL":
        raise HumanPassRefusedError("규칙에 「불가」 줄이 있어 「가능」으로 바꿀 수 없습니다 — 불가 사유를 먼저 확인하세요.")
    moment = now or storage.utc_now()
    current.human_pass = ManualHumanPass(by=by, at=moment, reason=reason, recorded_by=recorded_by) if reason is not None else None
    current.updated_at = moment
    # 45차 SEC-R37-02 — 「고친 사람」은 서버가 본 계정(사람이 적은 이름은 human_pass.by 에). 로그인 없는 로컬은 적은 이름
    current.updated_by = recorded_by or by
    return _write(current)


def gate_now(organization_id: str, notice_id: str) -> str | None:
    """지금 규칙이 낸 판정(목록과 같은 길 · 44차 M6) — 「원문 확인함 — 가능으로」 · 「참여」 결정은 불가 줄이 있으면 받지 않는다."""
    from app.services import organization_service

    profile = organization_service.load_profile(organization_id)
    items = unified_items(organization_id=organization_id, profile=profile, now=storage.utc_now())
    return next((item.eligibility_gate for item in items if item.id == notice_id), None)


def human_pass_reason(notice: ManualNotice) -> str | None:
    """판정 사유 한 줄 — 「사람 확인 뒤 가능 — 담당자 10/24: 원문 참가자격 확인」. 없으면 None."""
    hp = notice.human_pass
    if hp is None:
        return None
    return f"사람 확인 뒤 가능 — {hp.by} {_kst(hp.at):%m/%d}: {hp.reason}"


def delete(organization_id: str, notice_id: str) -> None:
    """지우기 — 그 회사 폴더 안의 이 공고 파일과 올린 공고문 · 조항 파일만."""
    from app.services import qualification_clause_service as qc

    path = _path(organization_id, notice_id)
    if not path.exists():
        raise ManualNoticeNotFoundError(notice_id)
    base = folder(organization_id)
    for doc in base.glob(f"{notice_id}.*"):
        if doc.parent == base and doc.suffix.lower() in (*ALLOWED_SUFFIXES, ".json", ".txt"):
            doc.unlink(missing_ok=True)
    # 참가자격 조항 파일은 판정 규칙이 읽는 Git 밖 조항 폴더에 이 공고 id(회사마다 다름)로 있다.
    qc.clause_path(notice_id, private=True).unlink(missing_ok=True)


# --------------------------------------------------------------------------
# 공고문 파일 — 조항 뽑기
# --------------------------------------------------------------------------


def _text_path(organization_id: str, notice_id: str) -> Path:
    return folder(organization_id) / f"{notice_id}.txt"


def attach_document(organization_id: str, notice_id: str, *, file_name: str, payload: bytes, now: datetime | None = None) -> ManualNotice:
    """공고문 파일을 받아 저장하고 조항을 뽑는다(입찰 · 수행은 참가자격 조항, 수혜는 지원대상 조항 · 판정은 목록이 한다)."""
    from app.services import company_service, document_extractor, procurement_service
    from app.services import qualification_clause_service as qc

    notice = get(organization_id, notice_id)
    name = company_service.safe_file_name(file_name)
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ManualNoticeError(f"공고문은 {' · '.join(s[1:] for s in ALLOWED_SUFFIXES)} 파일만 받습니다(받은 것: {suffix or '확장자 없음'})")
    if not payload:
        raise ManualNoticeError("빈 파일입니다")
    if len(payload) > MAX_DOCUMENT_BYTES:
        raise ManualNoticeError(f"공고문 파일은 {MAX_DOCUMENT_BYTES // (1024 * 1024)}MB 까지 받습니다")
    base = folder(organization_id)
    for old in base.glob(f"{notice_id}.*"):
        if old.suffix.lower() in ALLOWED_SUFFIXES:
            old.unlink(missing_ok=True)
    stored = base / f"{notice_id}{suffix}"
    stored.parent.mkdir(parents=True, exist_ok=True)
    stored.write_bytes(payload)

    status, fmt, note = "error", None, None
    if notice.recruit == "benefit":
        try:
            if suffix == ".docx":
                doc = document_extractor.ExtractedDocument(file_name=name, doc_format="docx", pages=document_extractor.extract_docx(stored))
            else:
                doc = document_extractor.extract_document(stored, file_name=name)
            fmt = doc.doc_format
            text = procurement_service.mask_contact_text(doc.text)
            if len(text.strip()) < qc.MIN_TEXT_CHARS:
                status, note = "image", "글자를 거의 읽지 못했습니다 — 스캔 이미지로 보입니다"
            else:
                _text_path(organization_id, notice_id).write_text(text, encoding="utf-8")
                status = "ok"
        except Exception as exc:  # noqa: BLE001 — 깨진 파일도 저장은 하고 사유를 남긴다
            note = f"{type(exc).__name__}: {exc}"[:200]
    else:
        result = procurement_service.mask_contact_fields(qc.extract_clauses(stored, file_name=name))
        status, fmt, note = result.get("status") or "error", result.get("format"), result.get("note")
        # 나라장터 공고와 **같은 꼴 · 같은 폴더**(Git 밖)에 둔다 — 판정 규칙(`evaluate_notice_fields`)이 공고 id 로 읽는다.
        qc.save({
            "notice_id": notice_id,
            "document": {"name": result.get("file") or name, "index": None, "format": fmt, "hash": hashlib.sha256(payload).hexdigest()[:16]},
            "fetched_at": (now or storage.utc_now()).isoformat(),
            "status": status,
            "page_is_approximate": bool(result.get("page_is_approximate")),
            "section": result.get("section"),
            "clauses": result.get("clauses") or [],
            "second_source": None,
            "note": note,
            # 41차 R40-CLAUSE-D — 판이 없으면 근거 줄이 늘 「옛 판」으로 읽혀 「판정 조항을 찾지 못함」이 났다
            "extractor_version": qc.EXTRACTOR_VERSION,
        }, private=True)
    # 44차 마지막 검토 — 읽는 데 수십 초가 걸린다. 그사이 들어온 「원문 확인함 — 가능으로」 · 고친 칸을 옛 사본으로 덮지 않게
    # 쓰기 직전에 다시 읽어 공고문 칸만 붙인다.
    latest = get(organization_id, notice_id)
    latest.document = ManualDocument(
        file_name=name, size_bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest(), format=fmt,
        status=status, note=note, uploaded_at=now or storage.utc_now(),
    )
    # 44차 TEAM-R36-04 — 공고문 올리기는 고치기 버전 시각(`updated_at`)을 건드리지 않는다(`document.uploaded_at` 에만).
    # 바꾸면 열린 고치기 폼이 엉뚱한 이름(지난 수정자)으로 「먼저 바꿨습니다」 409 를 받았다.
    return _write(latest)


def clause_payload(organization_id: str, notice_id: str) -> dict[str, Any] | None:
    """입찰 · 수행 공고문에서 뽑은 참가자격 조항(있을 때만 · 이 회사 공고만)."""
    from app.services import qualification_clause_service as qc

    get(organization_id, notice_id)  # 이 회사 폴더에 있는 공고인가
    return qc.load(notice_id)


def document_text(organization_id: str, notice_id: str) -> str | None:
    path = _text_path(organization_id, notice_id)
    return path.read_text(encoding="utf-8") if path.exists() else None


# --------------------------------------------------------------------------
# 판정 · 통합 목록 항목
# --------------------------------------------------------------------------

#: 화면의 접수방식 → 실무순 접수방식(이메일 · PMS · 온라인폼 · IRIS = 0 · 38차 §3-E-3).
FAST_METHODS: frozenset[str] = frozenset({"이메일", "PMS/기관시스템", "온라인폼", "IRIS"})


#: 「지역 제한」 칸에 적은 「제한 없음」 — 참가 가능 지역 목록이 아니다(38차 검토 · 「전국」이 지역 이름으로 들어가 불가가 되던 것).
#: 39차 MANUAL-01 — 「지역 제한 없음」(칸 이름 그대로) · 「-」 · 「해당없음」 · 「N/A」 · 「제한 없음(전국)」 · 「없음(전국 가능)」도(괄호 · 빈칸 지우고 견줌).
NO_REGION_LIMIT: frozenset[str] = frozenset({
    "전국", "제한없음", "없음", "무관", "지역무관", "전지역", "지역제한없음", "해당없음", "해당사항없음", "na", "n/a", "-", "–", "—",
    "제한없음전국", "없음전국", "없음전국가능", "전국가능", "전국누구나",
})
NO_REGION_REASON = "직접 넣을 때 지역 제한을 「{text}」(제한 없음)로 적었습니다 — 공고문 원문으로 확인하세요."
#: 지역 이름이 없는 글(「있음」 · 「관내 기업」 · 「본사 소재지 기준」) — 어느 지역인지 모른다(40차 MANUAL-01).
UNKNOWN_REGION_REASON = "직접 넣을 때 지역 제한을 「{text}」로 적었습니다 — 어느 지역인지 공고문 원문으로 확인하세요."
#: 사람이 적은 참가 가능 지역에 회사 소재지가 없을 때 — 「불가」로 닫지 않는다(40차 MANUAL-01 · 사람이 적은 글로 불가를 내지 않는다).
LIST_REGION_MISS_REASON = "직접 넣을 때 적은 지역 제한 「{text}」에 회사 소재지가 없어 보입니다 — 공고문 원문으로 확인하세요(사람이 적은 글이라 「불가」로 닫지 않습니다)."
EXCLUDE_REGION_REASON = "직접 넣을 때 지역 제한을 「{text}」로 적었습니다 — 회사 소재지가 빠지는지 공고문 원문으로 확인하세요."
BLANK_REGION_REASON = "지역 제한 칸을 비워 두었습니다 — 공고문 원문으로 확인하세요."


#: 빼는 꼴 — 「○○ 제외」 · 「서울 외 지역」 · 「수도권 이외」 · 「타지역 불가」 · 「비수도권」 · 「○○ 아닌」(40차 MANUAL-01 · 「제외」 한 낱말만 막던 것).
_EXCLUDE_REGION_RE = re.compile(r"제외|이외|타\s*지역|비\s*수도권|불가|아닌|(?<![가-힣])외(?![가-힣])|[가-힣]외\s*(?:지역|$)")
#: 지역 이름 없이 「없음 · 전국」 꼴 — 「없음(공고문 확인)」 · 「제한 없음 - 공고문 참조」 · 「전국 누구나 가능」 · 「전국 대상」.
_NO_LIMIT_WORD_RE = re.compile(r"없음|없다|전국|무관|누구나|해당\s*없")


def region_kind(text: str | None) -> str:
    """사람이 적은 지역 제한의 갈래 — blank(비움) · none(제한 없음) · exclude(빼는 꼴 — 확인 필요) · unknown(지역 이름 없음 — 확인 필요) ·
    list(참가 가능 지역 목록 — **조각마다** 실제 시 · 도 이름이 나올 때만 · 40차 MANUAL-01)."""
    if not (text or "").strip():
        return "blank"
    if _EXCLUDE_REGION_RE.search(text):
        return "exclude"
    squash = lambda part: re.sub(r"[\s()（）\[\]]", "", part).lower()  # noqa: E731
    if squash(text) in NO_REGION_LIMIT:
        return "none"  # 「N/A」처럼 빗금이 낀 한 낱말
    parts = [part.strip() for part in re.split(r"[·,/]|\s{2,}", text) if part.strip()]
    if parts and all(squash(p) in NO_REGION_LIMIT for p in parts):
        return "none"
    from app.services.eligibility_engine import _region_names  # 대표 지역 이름 표 하나(나라장터 규칙과 같다)

    if parts and all(_region_names(p) for p in parts):
        return "list"
    return "none" if _NO_LIMIT_WORD_RE.search(text) else "unknown"


def _regions(text: str | None) -> list[str]:
    if region_kind(text) == "none":
        return []
    return [part.strip() for part in re.split(r"[·,/]|\s{2,}", text or "") if part.strip()]


def _kst(moment: datetime) -> datetime:
    return moment.astimezone(KST) if moment.tzinfo else moment.replace(tzinfo=KST)


#: 직접 넣은 공고에 나라장터 전용 문장을 쓰지 않는다(43차 M16 · SOURCE-08) — 받을 일이 없는 「자격 정보」 약속 · PMS · 이메일 접수의 나라장터 등록.
_MANUAL_UNLOCK_TEXT = {
    "자격 정보를 받으면 지역 제한이 확정됩니다": "공고문에서 지역 제한 확인",
    "자격 정보를 받으면 요구 업종이 확정됩니다": "공고문에서 요구 업종 확인",
}
_NON_G2B_METHODS = frozenset({"이메일", "PMS/기관시스템", "온라인폼", "IRIS", "방문/우편"})


def _manual_unlock(condition: str, notice: ManualNotice) -> str:
    from app.services import eligibility_engine  # 늦게 — 모듈 맨 위에서 부르면 import 고리

    if condition in _MANUAL_UNLOCK_TEXT:
        return _MANUAL_UNLOCK_TEXT[condition]
    if condition == eligibility_engine.REGISTRATION_UNLOCK and (notice.recruit == "operator" or (set(notice.methods) and set(notice.methods) <= _NON_G2B_METHODS)):
        return "접수처(PMS · 이메일 · 기관 시스템) 등록 · 제출서류 확인"
    return condition


def _raw_fields(notice: ManualNotice) -> dict[str, Any]:
    """사람이 적은 칸만 나라장터 규칙의 열쇠로 옮긴다(없는 칸은 비워 둔다 — 지어내지 않는다)."""
    item: dict[str, Any] = {"bidClseDt": f"{_kst(notice.deadline):%Y-%m-%d %H:%M:%S}" if notice.deadline else ""}
    if notice.apply_deadline is not None:
        item["bidQlfctRgstDt"] = f"{_kst(notice.apply_deadline):%Y-%m-%d %H:%M:%S}"
    raw: dict[str, Any] = {"item": item}
    if region_kind(notice.region_limit) in ("none", "list"):
        raw["allowed_regions"] = _regions(notice.region_limit)
    if notice.joint:
        raw["joint_supply_method"] = notice.joint
    return raw


def _cap(gate: str, reason: str | None, *, document_ok: bool) -> tuple[str, str | None]:
    """D16 — 직접 넣은 공고는 자동으로 「가능」이 되지 않는다. 공고문이 없으면 「공고문 아직 안 읽음」. 불가는 그대로."""
    if gate == "FAIL":
        return gate, reason
    if not document_ok:
        return "CHECK", NOT_READ_REASON
    if gate == "PASS":
        return "CHECK", HUMAN_CHECK_REASON
    return gate, reason


def unified_items(*, organization_id: str, profile: Any, now: datetime, context: Any = None) -> list[Any]:
    """직접 넣은 공고 → 통합 목록 항목(`source_type="manual"`). 파일 읽기와 규칙뿐이다(바깥을 부르지 않는다)."""
    from app.schemas.business_opportunity import NextRoute, SupportProgram, UnifiedOpportunity
    from app.schemas.procurement import ProcurementNotice
    from app.services import (
        bizinfo_service,
        delivery_capacity_service,
        eligibility_engine,
        g2b_mapper,
        opportunity_filter,
        practical_priority as practical,
        support_application_service,
        support_requirement_extractor,
        work_kinds,
    )
    from app.services import opportunity_priority as priority
    from app.services import qualification_clause_service as qc

    notices = list_notices(organization_id)
    if not notices:
        return []
    capacity = delivery_capacity_service.load(organization_id)
    scope = getattr(context, "evidence_scope", "internal")
    company = eligibility_engine.company_facts_for(organization_id, evidence_scope=scope)
    regions = tuple(r for r in getattr(profile, "preferred_regions", ()) if r)
    today = now.astimezone(KST).date()
    items: list[Any] = []
    for notice in notices:
        try:
            deadline = _kst(notice.deadline) if notice.deadline is not None else None  # 범위 밖 날짜(0001-01-01 등)는 여기서 OverflowError
            apply_deadline = _kst(notice.apply_deadline) if notice.apply_deadline is not None else None
            if notice.published_on is not None:
                # 40차 MANUAL-02 — 공고일도 같다(실무순 `_kst_date` 가 0001-01-01 에서 OverflowError — 목록 응답 전체가 500 이었다)
                datetime.combine(notice.published_on, datetime.min.time(), tzinfo=KST).astimezone(timezone.utc)
                if not 2000 <= notice.published_on.year <= 2100:
                    raise ValueError("공고일 연도 범위 밖")
        except (OverflowError, ValueError):
            # 39차 MANUAL-09 — 마감 하나가 범위 밖이면 그 줄만 건너뛴다(목록 전체가 「읽기 오류」로 0건이 됐다)
            logger.warning("직접 넣은 공고의 마감 · 공고일을 읽지 못해 건너뜁니다: %s", notice.id)
            continue
        published = (
            datetime.combine(notice.published_on, datetime.min.time(), tzinfo=KST) if notice.published_on else None
        )
        budget = g2b_mapper.parse_amount(notice.budget_text or "")
        document_ok = bool(notice.document and notice.document.status == "ok")
        recruit = {
            "bid": practical.RECRUIT_BID, "operator": practical.RECRUIT_OPERATOR, "benefit": practical.RECRUIT_BENEFIT,
        }[notice.recruit]
        evidence: str | None
        clause_count = 0
        unlocks: list[str] = []
        if notice.recruit == "benefit":
            program = SupportProgram(
                id=notice.id, title=notice.title, agency=notice.agency, summary=(notice.body_text or "")[:2000] or None,
                apply_end=deadline.astimezone(KST).date() if deadline else None, apply_period_kind="dated" if deadline else "unknown", url=notice.url,
                # 「제한 없음」 · 「○○ 제외」를 지역 이름으로 읽지 않는다(39차 MANUAL-01 — 「서울 제외」가 대상 지역 서울로 읽혀 불가였다)
                region_tags=bizinfo_service.region_tags_of(notice.region_limit) if region_kind(notice.region_limit) == "list" else [],
            )
            fit = bizinfo_service.support_fit(program, today=today, organization_id=organization_id)
            text = document_text(organization_id, notice.id) if document_ok else None
            requirements = (
                support_requirement_extractor.extract_from_text(notice.id, text)
                if text
                else None
            )
            judgement = support_application_service.judge(
                program, fit, company=company, profile=profile, source="manual", today=today, requirements=requirements,
            )
            gate, gate_reason = _cap(judgement.gate, judgement.gate_reason, document_ok=bool(text))
            if notice.human_pass is not None and gate != "FAIL":
                gate, gate_reason = "PASS", human_pass_reason(notice)  # 44차 M6 — 사람이 원문을 보고 정한 「가능」(불가는 그대로)
            components, reasons, checks, source_score = (
                judgement.components, judgement.reasons, judgement.checks, judgement.source_score,
            )
            if region_kind(notice.region_limit) == "list" and judgement.gate == "FAIL" and all(
                r.rule_id == "BIZ-REGION" for r in judgement.rules if r.status == "FAIL"
            ):
                # 40차 MANUAL-01 — 사람이 적은 지역 글로 「불가」를 내지 않는다(그 줄도 확인 필요로)
                gate, gate_reason = _cap("CHECK", LIST_REGION_MISS_REASON.format(text=notice.region_limit), document_ok=bool(text))
            if gate != judgement.gate:
                # D16 은 점수에서도 — 낮춘 판정으로 다시 매긴다(입찰 쪽 `score_procurement(gate=…)` 와 같다 · 38차 검토)
                components, reasons, checks, source_score = priority.score_support(
                    program, fit, profile=profile, source="manual", today=today, gate=gate,
                    relevance=judgement.relevance, signals={**judgement.signals, "gate": gate, "gate_reason": gate_reason},
                )
            unlocks = list(judgement.unlock_conditions)
            evidence = (
                f"근거: 공고문 「{judgement.clause_quotes[0][: qc.EVIDENCE_CHARS]}」" if judgement.clause_quotes and text else qc.NOT_READ
            )
            opportunity_type, fit_type = "support_program", practical.bizinfo_type(notice.title, notice.body_text, recruit)
            relevance_note = None if judgement.relevance.related else judgement.relevance.reason
            work = {"kinds": [], "tracks": [], "basis": None}
            industry_partner = None
        else:
            pnotice = ProcurementNotice(
                id=notice.id, notice_no=notice.id, title=notice.title, agency=notice.agency,
                published_at=published or notice.created_at, deadline_at=deadline, budget=budget,
                description=(notice.body_text or "")[:2000] or None, source_url=notice.url, raw_data=_raw_fields(notice),
            )
            match = opportunity_filter.classify(pnotice)
            # 공고문을 올렸으면 참가자격 조항 줄(QUAL-*)까지 — 나라장터 공고와 같은 규칙표 · 같은 조항 파일 꼴이다.
            payload = qc.load(notice.id) if document_ok else None
            rules = eligibility_engine.evaluate_notice_fields(
                pnotice.raw_data, as_of=now, regions=regions, company=company,
                notice_id=notice.id if document_ok else None,
            )
            kind = region_kind(notice.region_limit)
            if kind == "list":
                # 40차 MANUAL-01 — 사람이 적은 참가 가능 지역에 회사 소재지가 없어도 「불가」가 아니라 확인 필요다
                rules = [
                    r.model_copy(update={"status": "CHECK", "check_side": "notice",
                                         "source": f"사람이 적은 지역 제한 「{notice.region_limit}」",
                                         "reason": LIST_REGION_MISS_REASON.format(text=notice.region_limit)})
                    if r.rule_id == "ELIG-REGION" and r.status == "FAIL" else r
                    for r in rules
                ]
            else:
                # 「나라장터에 지역 제한이 등록돼 있지 않습니다」 · 「자격 정보를 아직 받지 못해」는 나라장터 공고의 말이다 — 사람이 적은 칸이라고 적는다.
                # 「○○ 제외」는 목록이 아니라 확인 필요다(39차 MANUAL-01 — 「서울 제외」가 참가 가능 지역 서울로 읽혀 불가였다).
                update = {
                    "none": {"reason": NO_REGION_REASON.format(text=notice.region_limit)},
                    "exclude": {"status": "CHECK", "reason": EXCLUDE_REGION_REASON.format(text=notice.region_limit)},
                    "unknown": {"status": "CHECK", "reason": UNKNOWN_REGION_REASON.format(text=notice.region_limit)},
                    "blank": {"status": "CHECK", "reason": BLANK_REGION_REASON},
                }[kind]
                source = f"사람이 적은 지역 제한 「{notice.region_limit}」" if kind != "blank" else "사람이 적은 지역 제한(빈칸)"
                rules = [r.model_copy(update={"source": source, **update}) if r.rule_id == "ELIG-REGION" else r for r in rules]
            if notice.deadline is None:
                # 43차 Q20 — 「상시 · 미정」은 사람이 고른 것 — 나라장터 「입찰 마감이 없습니다(개찰일 …)」 문장을 쓰지 않는다
                rules = [
                    r.model_copy(update={"status": "CHECK", "check_side": "notice", "source": "사람이 고른 마감 「상시 · 미정」",
                                         "reason": "마감을 「상시 · 미정」으로 넣었습니다 — 공고 원문에서 신청 마감을 확인하세요."})
                    if r.rule_id == "ELIG-BID-DEADLINE" else r
                    for r in rules
                ]
            raw_gate, raw_reason = priority.procurement_eligibility_gate(
                pnotice, match, profile=profile, now=now, organization_id=organization_id, results=rules,
            )
            gate, gate_reason = _cap(raw_gate, raw_reason, document_ok=document_ok)
            if notice.human_pass is not None and gate != "FAIL":
                gate, gate_reason = "PASS", human_pass_reason(notice)  # 44차 M6 — 사람이 원문을 보고 정한 「가능」(불가는 그대로)
            work = work_kinds.of_notice(pnotice)
            components, reasons, checks, source_score = priority.score_procurement(
                pnotice, match, profile=profile, source="manual", now=now, organization_id=organization_id,
                gate=gate, capacity=capacity, tracks=list(work["tracks"]), rules=rules,
            )
            unlocks = list(dict.fromkeys(
                _manual_unlock(r.unlock_condition, notice) for r in rules if r.unlock_condition and r.status in ("FAIL", "CHECK")
            ))
            evidence, clause_count = qc.evidence_line(payload, field_requires=qc.field_requires(rules)) if payload else (qc.NOT_READ, 0)
            opportunity_type = "procurement"
            fit_type = practical.type_of_kinds(list(work["kinds"]), notice.title)
            relevance_note = None if match.is_candidate else (match.low_reason or "후보 낱말 조합이 아닙니다(낱말 관련도 낮음)")
            industry_partner = eligibility_engine.industry_partner(rules, pnotice.raw_data)  # 44차 결정 4 — 나라장터와 같은 규칙
        if notice.core_confirmed:
            relevance_note = None  # 43차 Q18 — 사람이 본업으로 확인했다(낱말 규칙으로 접지 않음 · 판정 · 점수 그대로)
        # 43차 M16 · SOURCE-08 — 「예산(기초금액)이 공고에 없습니다」는 사람이 사업비 칸을 비운 것이다
        checks = ["사업비 칸을 비워 두었습니다 — 공고 원문의 사업비를 적으면 규모를 판정합니다." if "예산(기초금액)" in c else c for c in checks]
        score = priority.normalize(components)
        items.append(
            UnifiedOpportunity(
                id=notice.id,
                source_type="manual",
                opportunity_type=opportunity_type,
                title=notice.title,
                agency=notice.agency,
                summary=(notice.body_text or "")[:300] or None,
                deadline=deadline,
                deadline_text=None if deadline else "상시 · 미정(직접 넣음 — 공고 원문에서 마감 확인)",
                qualification_deadline=apply_deadline,
                detail_url=notice.url,
                organization_id=organization_id,
                company_priority_score=score,
                procurement_fit_score=score if opportunity_type == "procurement" else None,
                support_fit_score=score if opportunity_type == "support_program" else None,
                review_priority_score=score,
                priority_rank=0,
                priority_label="미확인",
                eligibility_gate=gate,
                gate_reason=gate_reason,
                confidence=priority.confidence_of(components, source="manual"),
                score_components=components,
                source_specific_score=source_score,
                next_route=NextRoute(kind="manual", path=f"/opportunities?tab=manual&manual={notice.id}", label="직접 넣은 공고 보기"),
                source="manual",
                closed=deadline is not None and deadline < now,
                reasons=reasons,
                checks=checks,
                budget=budget,
                work_kinds=work["kinds"],
                work_tracks=work["tracks"],
                work_basis=work["basis"],
                unlock_conditions=unlocks,
                published_at=published,
                submission_methods=list(notice.methods) or [practical.METHOD_UNKNOWN],
                recruit_kind=recruit,
                fit_type=fit_type[0],
                fit_type_basis=fit_type[1],
                practical_company_gap=False,
                practical_candidate=relevance_note is None,
                evidence_line=evidence,
                clause_count=clause_count,
                relevance_note=relevance_note,
                document_read=document_ok,
                source_layer=notice.layer,
                industry_partner=industry_partner,
            )
        )
    return items
