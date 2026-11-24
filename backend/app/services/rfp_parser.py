"""RFP 파싱 서비스 — LLM 없이 재현 가능한 규칙 기반 baseline.

두 가지 경로를 지원한다.

1. **합성 fixture** (`synthetic-rfp-0001`) — 데모 시나리오·Gold 평가 전용.
   등록된 fixture ID만 열 수 있다. 사용자가 보낸 임의 경로는 절대 열지 않는다.
   페이지 텍스트는 pdfplumber로 추출하며 page 번호와 원문(source_text)을 보존한다.
2. **실제 나라장터 공고** — 공고의 제안요청서 첨부를 내려받아(g2b.go.kr 한정)
   document_extractor로 텍스트를 뽑고 rfp_extractor(규칙 기반)로 요구사항을 추출한다.

gold_requirements.json은 평가에만 사용하며 이 모듈은 참조하지 않는다.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pdfplumber

from app.core import storage
from app.core.paths import DATA_ROOT
from app.schemas.requirement import (
    REQUIREMENT_SCHEMA_VERSION,
    PageInfo,
    Requirement,
    RequirementStatus,
    RequirementType,
    RfpParseResult,
)
from app.services import attachment_service, document_extractor, item_classifier, procurement_service, requirement_set

# ROLE B가 담당하는 실제 RFP 추출기. 아직 없을 수 있으므로 import를 보호한다
# (pytest collection이 깨지지 않아야 한다). 실제 호출 시점에만 오류를 낸다.
try:  # pragma: no cover - 모듈 존재 여부에 따른 분기
    from app.services.rfp_extractor import (  # type: ignore[import-not-found]
        extract_with_stats,
    )
except ImportError:  # pragma: no cover
    extract_with_stats = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

SAMPLE_RFP_DIR = DATA_ROOT / "public" / "sample_rfp"
GENERATED_DIR = SAMPLE_RFP_DIR / "generated"


@dataclass(frozen=True)
class RfpFixture:
    procurement_id: str
    file_name: str
    source: str = "synthetic_fixture"

    @property
    def path(self) -> Path:
        return SAMPLE_RFP_DIR / self.file_name


# 서버가 열 수 있는 RFP 파일 목록. 여기 없는 ID는 거부한다.
RFP_FIXTURES: dict[str, RfpFixture] = {
    "synthetic-rfp-0001": RfpFixture(
        procurement_id="synthetic-rfp-0001",
        file_name="synthetic_ai_training_rfp.pdf",
    ),
}


# 실제 공고 ID는 g2b_mapper.notice_id()가 만든 "g2b-<공고번호>-<차수>" 형태뿐이다.
# 이 형태가 아니면 네트워크를 타기 전에 거부한다(경로 유사 문자열 차단 + 불필요한 실호출 방지).
REAL_NOTICE_ID_RE = re.compile(r"^g2b-[A-Za-z0-9]{1,40}-[A-Za-z0-9]{1,8}$")

REAL_NOTICE_SOURCE = "g2b_attachment"


class RfpFixtureNotFoundError(LookupError):
    """등록되지 않은 fixture ID이며 실제 공고 ID 형태도 아님."""


class RfpNotParsedError(LookupError):
    """아직 파싱 결과가 생성되지 않음."""


class RealNoticeNotFoundError(LookupError):
    """현재 조회 창(candidate window)에 없는 공고 ID."""


class RfpAttachmentNotFoundError(LookupError):
    """공고에 제안요청서로 볼 만한 첨부가 없음."""


class RealExtractorUnavailableError(RuntimeError):
    """실제 RFP 요구사항 추출기(rfp_extractor)가 아직 준비되지 않음."""


def get_fixture(procurement_id: str) -> RfpFixture:
    fixture = RFP_FIXTURES.get(procurement_id)
    if fixture is None:
        raise RfpFixtureNotFoundError(procurement_id)
    return fixture


def is_fixture(procurement_id: str) -> bool:
    return procurement_id in RFP_FIXTURES


def is_real_notice_id(procurement_id: str) -> bool:
    return bool(REAL_NOTICE_ID_RE.match(procurement_id))


def generated_path(procurement_id: str) -> Path:
    """파싱 결과 저장 경로. fixture ID와 실제 공고 ID 형태만 허용한다."""
    if not (is_fixture(procurement_id) or is_real_notice_id(procurement_id)):
        raise RfpFixtureNotFoundError(procurement_id)
    return GENERATED_DIR / f"{procurement_id}.requirements.json"


# --------------------------------------------------------------------------
# 1) 페이지 텍스트 추출
# --------------------------------------------------------------------------


def extract_pages(pdf_path: Path) -> list[str]:
    """PDF를 페이지 순서대로 읽어 페이지별 텍스트를 반환한다. 추출 실패 페이지는 빈 문자열."""
    pages: list[str] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text() or "")
    return pages


# --------------------------------------------------------------------------
# 2) 규칙 기반 요구사항 추출
# --------------------------------------------------------------------------

# 페이지 하단 "Page N" 표기는 본문이 아니다.
PAGE_FOOTER_RE = re.compile(r"^Page\s+\d+$")

# "교육횟수 [수치] 교육은 총 12회 ..." 형태의 요구사항 시작 줄
REQ_LINE_RE = re.compile(
    r"^(?P<title>\S{2,20})\s*\[(?P<tag>[^\]]{1,20})\]\s*(?P<body>\S.*)$"
)

# 의무 표현: "~해야 한다", "~여야 하며", "~할 수 없다", "~해서는 안 된다"
OBLIGATION_RE = re.compile(r"[가-힣]야\s*(한다|하며|하고|함)|할\s*수\s*없|해서는\s*안|않아야")
OPTIONAL_RE = re.compile(r"권장|바람직|가능하면|선택사항|가점")
# 자격·실적 조건 중 사람이 판단해야 하는 모호 표현
AMBIGUOUS_RE = re.compile(r"유사|경력|동등|상당")

TAG_CATEGORY: dict[str, str] = {
    "일정": "일정",
    "수치": "수치",
    "운영": "운영",
    "필수내용": "교육내용",
    "제출": "제출",
    "보안": "보안",
    "인력": "인력",
    "자격": "자격",
    "모호조건": "자격",
    "evidence": "증빙",
    "auditor핵심": "검수",
    "auditor": "검수",
    "보고": "보고",
    "humanreview": "승인",
}
AMBIGUOUS_TAGS = {"모호조건"}
AMBIGUOUS_CATEGORIES = {"자격", "인력"}


@dataclass
class _Block:
    page: int
    title: str | None
    tag: str | None
    body_lines: list[str]
    raw_lines: list[str]

    @property
    def body(self) -> str:
        return " ".join(self.body_lines).strip()

    @property
    def closed(self) -> bool:
        return self.body.endswith(".")


def _normalize_tag(tag: str) -> str:
    return re.sub(r"\s+", "", tag).lower()


def _category_for(tag: str) -> str:
    return TAG_CATEGORY.get(_normalize_tag(tag), tag.strip())


def _requirement_type_for(text: str) -> RequirementType:
    if OPTIONAL_RE.search(text) and not OBLIGATION_RE.search(text):
        return "optional"
    return "mandatory"


def _status_for(tag: str | None, category: str, text: str) -> RequirementStatus:
    """근거 매핑 전이므로 기본은 unmatched. 모호한 자격·실적 조건은 자동 판정하지 않고 check."""
    if tag is None:
        return "check"
    if _normalize_tag(tag) in AMBIGUOUS_TAGS:
        return "check"
    if category in AMBIGUOUS_CATEGORIES and AMBIGUOUS_RE.search(text):
        return "check"
    return "unmatched"


def _split_blocks(page_no: int, text: str) -> list[_Block]:
    """한 페이지의 줄들을 문장 단위 블록으로 묶는다. 줄바꿈으로 끊긴 문장을 '.'까지 이어 붙인다."""
    blocks: list[_Block] = []
    current: _Block | None = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line or PAGE_FOOTER_RE.match(line):
            continue

        # 알려진 태그만 요구사항 시작으로 본다. "[별표 1]", "[붙임 2]" 같은 참조 표기는 문장의 일부다.
        match = REQ_LINE_RE.match(line)
        if match and _normalize_tag(match.group("tag")) in TAG_CATEGORY:
            current = _Block(
                page=page_no,
                title=match.group("title"),
                tag=match.group("tag"),
                body_lines=[match.group("body")],
                raw_lines=[line],
            )
            blocks.append(current)
            continue

        if current is None or current.closed:
            current = _Block(page=page_no, title=None, tag=None, body_lines=[line], raw_lines=[line])
            blocks.append(current)
        else:
            current.body_lines.append(line)
            current.raw_lines.append(line)

    return blocks


def extract_requirements(procurement_id: str, pages: list[str]) -> list[Requirement]:
    """페이지 텍스트 목록에서 요구사항을 추출한다. 원문에 없는 내용은 만들지 않는다."""
    requirements: list[Requirement] = []

    for page_no, text in enumerate(pages, start=1):
        for block in _split_blocks(page_no, text):
            body = block.body
            if block.tag is not None:
                category = _category_for(block.tag)
                title = block.title or body[:20]
            elif block.closed and OBLIGATION_RE.search(body):
                # 태그 없는 의무 문장: 추출 확신이 낮으므로 check로 남긴다
                category = "기타"
                title = body[:20]
            else:
                continue

            seq = len(requirements) + 1
            requirement_id = f"REQ-{seq:03d}"
            requirement_type = _requirement_type_for(body)
            source_text = "\n".join(block.raw_lines)
            requirements.append(
                Requirement(
                    id=f"{procurement_id}:{requirement_id}",
                    procurement_id=procurement_id,
                    requirement_id=requirement_id,
                    category=category,
                    requirement_type=requirement_type,
                    title=title,
                    content=body,
                    page=block.page,
                    source_text=source_text,
                    status=_status_for(block.tag, category, body),
                    **item_classifier.classify_fields(
                        category=category,
                        requirement_type=requirement_type,
                        content=body,
                        source_text=source_text,
                        requirement_id=requirement_id,
                    ),
                )
            )

    return requirements


# --------------------------------------------------------------------------
# 3) 파싱 실행 및 결과 저장/조회
# --------------------------------------------------------------------------


def parse_fixture(procurement_id: str) -> RfpParseResult:
    fixture = get_fixture(procurement_id)
    pages = extract_pages(fixture.path)
    requirements = extract_requirements(procurement_id, pages)
    return RfpParseResult(
        procurement_id=procurement_id,
        source=fixture.source,
        document=fixture.file_name,
        page_count=len(pages),
        pages=[PageInfo(page=i, char_count=len(t)) for i, t in enumerate(pages, start=1)],
        empty_pages=[i for i, t in enumerate(pages, start=1) if not t.strip()],
        count=len(requirements),
        # 합성 fixture 경로에는 추출 상한이 없다 (전부 담는다).
        candidate_count=len(requirements),
        truncated=False,
        requirements=requirements,
        generated_at=datetime.now(timezone.utc),
    )


def store_result(result: RfpParseResult) -> RfpParseResult:
    """파싱 결과를 generated 디렉터리에 저장한다.

    저장 전에 **연락처를 가린다.** 요구사항의 source_text 는 공고 원문을 그대로 옮기는데,
    입찰공고문에는 담당자 이름과 직통번호가 흔히 들어 있다
    (실측: 「… AI혁신팀 ○○○ (☎ 02-XXXX-XXXX)」). 이 파일은 Git 에 들어가고
    데모 스냅샷으로도 퍼지므로, 저장 지점에서 막지 않으면 계속 새어 나간다.

    가리는 규칙은 procurement_service 와 같은 것을 쓴다 — 두 벌이 되면 언젠가 갈린다.
    번호 모양만 가리고 부서·맥락은 남긴다. 입찰 실무에서 「어느 팀 담당인지」는 필요하다.
    """
    from app.services import procurement_service

    finalize_result(result)
    payload = procurement_service.mask_contact_fields(result.model_dump(mode="json"))

    # 결과가 **같으면 파일을 다시 쓰지 않는다** (ISSUE-019).
    #
    # 「다시 분석」은 첨부를 다시 내려받아 같은 규칙으로 뽑는다. 거의 언제나 같은 결과가
    # 나오는데, 그때마다 `generated_at` 만 바뀐 파일을 덮어쓰고 이전 판을 versions/ 에
    # 쌓았다. 추적 중인 파일이라 git 이 매번 변경으로 잡히고, 판 목록에는 내용이 같은
    # 판이 늘어나 「무엇이 달라졌는지」를 볼 수 없게 된다.
    #
    # 시각(`generated_at`)만 빼고 비교한다 — 그것이 유일하게 «내용과 무관하게» 바뀌는 값이다.
    if _same_content(generated_path(result.procurement_id), payload):
        logger.info("요구사항이 이전 판과 같아 파일을 다시 쓰지 않았습니다: %s", result.procurement_id)
        return result

    # 덮어쓰기 전에 이전 판을 보존한다. 재추출은 요구사항 번호를 다시 매기므로,
    # 옛 판이 없으면 「무엇이 어떻게 달라졌는지」를 사후에 계산할 방법이 사라진다.
    archive_previous(result.procurement_id)
    storage.write_json_atomic(generated_path(result.procurement_id), payload)
    return result


#: 내용 비교에서 빼는 키 — 내용과 무관하게 매번 달라진다.
_VOLATILE_KEYS = ("generated_at", "stored_at", "updated_at")


def stored_document_role(payload: dict[str, Any]) -> str:
    """옛 저장 파일(역할 없음)의 문서 역할 — 실공고는 문서 이름으로 가리고 합성 fixture 는 제안요청서 (27차 §3-A-4)."""
    document = str(payload.get("document") or "")
    real = payload.get("source") == REAL_NOTICE_SOURCE
    return attachment_service.document_role(document) if real and document else "rfp"


def _same_content(path: Path, payload: dict[str, Any]) -> bool:
    """저장된 파일이 새 결과와 (시각을 빼고) 같은가. 못 읽으면 False — 쓰는 쪽으로 기운다."""
    try:
        stored = storage.read_json(path, default=None)
    except Exception:  # noqa: BLE001 — 깨진 파일이면 새로 쓴다
        return False
    if not isinstance(stored, dict):
        return False
    # 27차에 생긴 `document_role` 은 옛 파일에 없다 — 읽을 때와 같은 규칙으로 채워서 견준다. 채우지 않으면 한 글자도
    # 안 바뀐 재분석도 「바뀜」이 되어 추적 파일을 다시 쓰고 같은 판을 쌓았다(27차 검수 C18).
    if "document_role" not in stored and "document_role" in payload:
        stored["document_role"] = stored_document_role(stored)
    return {k: v for k, v in stored.items() if k not in _VOLATILE_KEYS} == {
        k: v for k, v in payload.items() if k not in _VOLATILE_KEYS
    }


def versions_dir(procurement_id: str) -> Path:
    """이전 요구사항 집합을 모아 두는 폴더."""
    return generated_path(procurement_id).parent / f"{procurement_id}.requirements.versions"


def archive_previous(procurement_id: str) -> Path | None:
    """지금 저장된 판을 버전 폴더로 옮겨 둔다(복사). 이미 있으면 다시 쓰지 않는다.

    멱등이다 — 마이그레이션을 여러 번 돌려도 같은 판이 겹쳐 쌓이지 않는다.
    """
    payload = _stored_payload(procurement_id)
    if not payload:
        return None
    # 옛 파일에는 집합 신원이 없다. 보존하기 전에 찍어 둔다 — 그래야 나중에
    # 「그때 그 집합」을 해시로 식별할 수 있다.
    stamp_identity(payload, previous=payload)
    version = int(payload.get("requirement_set_version") or 1)
    folder = versions_dir(procurement_id)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"v{version:03d}.json"
    if target.exists():
        return target
    storage.write_json_atomic(target, payload)
    return target


def list_versions(procurement_id: str) -> list[dict[str, Any]]:
    """보존된 이전 집합 (오래된 것부터). 없으면 빈 목록."""
    folder = versions_dir(procurement_id)
    if not folder.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(folder.glob("v*.json")):
        payload = storage.read_json(path)
        if isinstance(payload, dict):
            out.append(payload)
    return out


def previous_version(procurement_id: str) -> dict[str, Any] | None:
    """가장 최근에 보존된 «다른» 집합. 없으면 None.

    해시로 거르지 않는다. 집합 해시에는 대응 범위 같은 파생 필드가 들어가서,
    스키마를 올리며 보존한 판은 «요구사항 구성이 같은데» 해시만 달라진다.
    그것을 이전 집합으로 내놓으면 화면이 「56건 → 56건, 전부 그대로」라는 빈 비교를
    보여준다 — 비교가 일어난 것처럼 보이지만 아무 뜻이 없다.

    기준은 **요구사항 구성**이다. 원문 구성이 같으면 같은 집합으로 본다.
    """
    current = _stored_payload(procurement_id) or {}
    current_ids = _identity_set(current)
    for payload in reversed(list_versions(procurement_id)):
        if _identity_set(payload) != current_ids:
            return payload
    return None


def _identity_set(payload: dict[str, Any]) -> frozenset[str]:
    """이 집합에 «어떤 원문»이 들어 있는가.

    예전에는 저장된 `stable_id` 를 먼저 봤다. 그런데 안정 ID 의 재료가 바뀌면
    (2026-09-14, 첨부 파일명을 뺐다) 내용이 똑같은 판끼리도 전부 달라 보인다.
    그러면 「내용이 같은 직전 판」을 이전 집합으로 골라 「56건 → 56건, 전부 그대로」
    라는 빈 비교를 내놓게 된다 — 비교가 일어난 것처럼 보이지만 아무 뜻이 없다.

    그래서 저장된 id 를 믿지 않고 **원문에서 직접** 만든다. 같은 문장이 두 번 나오는
    문서가 있으므로 몇 번째인지까지 붙인다 — 그러지 않으면 중복 한 줄이 늘거나 준
    차이를 못 본다.
    """
    out: set[str] = set()
    seen: dict[str, int] = {}
    for req in payload.get("requirements", []) or []:
        if not isinstance(req, dict):
            continue
        key = requirement_set.source_text_hash(str(req.get("source_text") or req.get("content") or ""))
        ordinal = seen.get(key, 0)
        seen[key] = ordinal + 1
        out.add(f"{key}#{ordinal}")
    return frozenset(out)


def parse_and_store(procurement_id: str) -> RfpParseResult:
    """합성 fixture 파싱 + 저장. (실제 공고는 parse_real_notice를 쓴다)"""
    return store_result(parse_fixture(procurement_id))


def migrate_payload(payload: dict[str, Any]) -> bool:
    """예전 형식(schema_version 1, item_type 없음)을 읽을 때 항목 유형을 채운다.

    파일은 고쳐 쓰지 않는다 (읽기 시 마이그레이션). 영구 반영은
    scripts/migrate_generated_requirements.py 가 같은 함수로 한다. 바뀐 것이 있으면 True.
    """
    changed = False
    # 27차 §3-A-4 — 옛 파일에는 문서 역할이 없다. 실공고는 문서 이름으로 가린다(합성 fixture 는 제안요청서).
    # 읽을 때만 채우고 바뀐 것으로 세지 않는다(파일을 다시 쓰지 않는다).
    if "document_role" not in payload:
        payload["document_role"] = stored_document_role(payload)
    approx = bool(payload.get("page_is_approximate", False))
    for req in payload.get("requirements", []):
        if isinstance(req, dict) and item_classifier.enrich_payload(req, page_is_approximate=approx):
            changed = True
    # schema_version 3 — 안정 ID 와 집합 신원. 이미 있는 항목은 건드리지 않는다
    # (한 번 정해진 신원은 바뀌지 않아야 옛 제안서가 계속 그것을 가리킬 수 있다).
    if stamp_identity(payload):
        changed = True
    if storage.schema_version_of(payload) < REQUIREMENT_SCHEMA_VERSION:
        payload["schema_version"] = REQUIREMENT_SCHEMA_VERSION
        changed = True
    payload["item_counts"] = item_classifier.item_counts(payload.get("requirements", []))
    return changed


def stamp_identity(payload: dict[str, Any], *, previous: dict[str, Any] | None = None) -> bool:
    """요구사항마다 안정 ID 를, 문서에 집합 신원을 찍는다. 바뀐 것이 있으면 True.

    `previous` 를 주면 집합 판 번호를 이어 센다. 주지 않으면 저장된 파일을 읽어
    이어 센다 — 같은 내용으로 다시 뽑으면 번호가 오르지 않는다(멱등).
    """
    requirements = [r for r in payload.get("requirements", []) if isinstance(r, dict)]
    before = (
        payload.get("requirement_set_hash"),
        payload.get("requirement_set_id"),
        payload.get("mandatory_count"),
    )
    changed = bool(
        requirement_set.assign_identity(
            requirements,
            procurement_id=str(payload.get("procurement_id") or ""),
            document=str(payload.get("document") or ""),
        )
    )

    if previous is None:
        previous = _stored_payload(str(payload.get("procurement_id") or ""))
    meta = requirement_set.describe(payload, previous=previous)
    payload.update(meta.to_dict())
    payload["response_scope_counts"] = _response_scope_counts(requirements)

    after = (
        payload.get("requirement_set_hash"),
        payload.get("requirement_set_id"),
        payload.get("mandatory_count"),
    )
    return changed or before != after


def _response_scope_counts(requirements: list[dict[str, Any]]) -> dict[str, int]:
    counts = {scope: 0 for scope in item_classifier.RESPONSE_SCOPES}
    for req in requirements:
        scope = str(req.get("response_scope") or "PROPOSAL_BODY")
        counts[scope] = counts.get(scope, 0) + 1
    return counts


def _stored_payload(procurement_id: str) -> dict[str, Any] | None:
    """디스크에 있는 «이전» 저장본. 없으면 None. 판 번호를 이어 세기 위한 것."""
    if not procurement_id:
        return None
    try:
        path = generated_path(procurement_id)
    except Exception:  # noqa: BLE001 — id 형식이 어긋나면 이전 판이 없는 것으로 본다
        return None
    if not path.exists():
        return None
    payload = storage.read_json(path)
    return payload if isinstance(payload, dict) else None


def finalize_result(result: RfpParseResult) -> RfpParseResult:
    """저장·응답 직전에 유형별 건수와 «집합 신원»을 채운다.

    신원을 여기서 찍는 이유는, 제안서·감사가 「내가 본 요구사항 집합은 이것」이라고
    기록하려면 응답에도 같은 값이 실려 있어야 하기 때문이다.
    """
    result.item_counts = item_classifier.item_counts(result.requirements)
    result.schema_version = REQUIREMENT_SCHEMA_VERSION

    payload = result.model_dump(mode="json")
    stamp_identity(payload)
    for req, enriched in zip(result.requirements, payload.get("requirements", [])):
        req.stable_id = enriched.get("stable_id")
        req.source_text_hash = enriched.get("source_text_hash")
        req.source_locator = enriched.get("source_locator")
        if not req.response_scope:
            req.response_scope = enriched.get("response_scope")
    result.requirement_set_id = payload.get("requirement_set_id")
    result.requirement_set_hash = payload.get("requirement_set_hash")
    result.requirement_set_version = int(payload.get("requirement_set_version") or 1)
    result.source_document_hash = payload.get("source_document_hash")
    result.mandatory_count = int(payload.get("mandatory_count") or 0)
    result.optional_or_conditional_count = int(payload.get("optional_or_conditional_count") or 0)
    result.response_scope_counts = payload.get("response_scope_counts") or {}
    return result


def load_generated(procurement_id: str) -> RfpParseResult:
    # 등록된 fixture ID 또는 실제 공고 ID 형태만 조회 허용 (generated_path가 검증)
    path = generated_path(procurement_id)
    if not path.exists():
        raise RfpNotParsedError(procurement_id)
    payload = storage.read_json(path)
    if not isinstance(payload, dict):
        raise RfpNotParsedError(procurement_id)
    migrate_payload(payload)
    # 담당자 정정 기록을 덧입힌다 (원본 추출 파일은 그대로).
    from app.services import correction_service

    if correction_service.apply_to_payload(procurement_id, payload):
        payload["item_counts"] = item_classifier.item_counts(payload.get("requirements", []))
    return RfpParseResult.model_validate(payload)


def load_generated_payload(procurement_id: str) -> dict[str, Any]:
    """정정까지 덧입힌 dict (Gold 내보내기 등 dict가 필요한 곳)."""
    return load_generated(procurement_id).model_dump(mode="json")


# --------------------------------------------------------------------------
# 4) 실제 나라장터 공고 파싱
# --------------------------------------------------------------------------


def _select_attachment(
    attachments: list[dict[str, str]], attachment_index: int | None
) -> tuple[int, dict[str, str]]:
    if not attachments:
        raise RfpAttachmentNotFoundError("공고에 첨부문서가 없습니다")

    if attachment_index is None:
        picked = attachment_service.pick_rfp_attachment(attachments)
        if picked is None:
            # 제안요청서가 없고 「공고서」만 올린 공고가 있다 (27차 §3-A-4 · 실측 6건). 그러면 입찰공고문에서
            # 뽑는다 — 결과의 `document_role` 이 `notice` 라 화면이 「세부 요구사항이 빠졌을 수 있다」고 알린다.
            picked = attachment_service.pick_notice_document(attachments)
        if picked is None:
            raise RfpAttachmentNotFoundError(
                "제안요청서·과업지시서·입찰공고문으로 볼 만한 첨부가 없습니다"
            )
        index = picked
    else:
        if not 0 <= attachment_index < len(attachments):
            raise RfpAttachmentNotFoundError(
                f"첨부 인덱스 범위를 벗어났습니다 (0~{len(attachments) - 1})"
            )
        index = attachment_index

    return index, attachments[index]


async def parse_real_notice(
    notice_id: str, attachment_index: int | None = None, *, fetch_attachment: bool = False
) -> RfpParseResult:
    """실제 공고의 제안요청서 첨부를 내려받아 요구사항을 추출하고 저장한다.

    원문에 없는 내용은 만들지 않는다. 추출기가 아무것도 찾지 못하면 빈 목록을 그대로 반환한다.
    `fetch_attachment` 는 사람이 확인 창에서 누른 한 건이다 — 로컬에 없으면 그때만 받는다 (27차 §3-A-2).
    """
    if not is_real_notice_id(notice_id):
        raise RfpFixtureNotFoundError(notice_id)

    view = await procurement_service.get_notice(notice_id)
    if view is None:
        raise RealNoticeNotFoundError(notice_id)

    attachments = list_attachments(view)
    index, attachment = _select_attachment(attachments, attachment_index)

    path = await attachment_service.download_attachment(
        attachment["url"],
        file_name=attachment["name"],
        notice_id=notice_id,
        index=index,
        allow_fetch=fetch_attachment,
    )
    doc = document_extractor.extract_document(path, file_name=attachment["name"])

    if extract_with_stats is None:
        raise RealExtractorUnavailableError(
            "app.services.rfp_extractor.extract_with_stats 이 아직 없습니다"
        )
    extracted = extract_with_stats(notice_id, doc)
    requirements = extracted.requirements
    if extracted.truncated:
        logger.warning(
            "%s: 요구사항 후보 %d건 중 상한 %d건까지만 담았습니다 (truncated)",
            notice_id,
            extracted.candidate_count,
            len(requirements),
        )

    result = RfpParseResult(
        procurement_id=notice_id,
        source=REAL_NOTICE_SOURCE,
        document=doc.file_name,
        doc_format=doc.doc_format,
        # HWP/HWPX는 페이지 정보가 없어 문단 묶음으로 근사한다 (document_extractor).
        page_is_approximate=doc.doc_format in ("hwp", "hwpx"),
        document_role=attachment_service.document_role(doc.file_name),
        page_count=doc.page_count,
        pages=[PageInfo(page=p.page, char_count=p.char_count) for p in doc.pages],
        empty_pages=doc.empty_pages,
        count=len(requirements),
        candidate_count=extracted.candidate_count,
        truncated=extracted.truncated,
        requirements=requirements,
        generated_at=datetime.now(timezone.utc),
    )
    return store_result(result)


def list_attachments(view: procurement_service.NoticeView) -> list[dict[str, str]]:
    """공고 raw_data에서 첨부 목록을 꺼낸다 (g2b_mapper가 넣어 둔 [{name, url}]).

    끝에 연결된 사전규격의 규격서를 붙인다(11-03 · `prespec_service.spec_docs_for`) — 본공고 첨부가 공고서뿐이면
    그 규격서(제안요청서)를 고른다. 뒤에 붙이므로 본공고 첨부 번호 · 받아 둔 파일 자리는 그대로다.
    """
    from app.services import prespec_service

    raw = view.notice.raw_data.get("attachments")
    own = [
        {"name": str(item.get("name") or "첨부"), "url": str(item.get("url") or "")}
        for item in (raw if isinstance(raw, list) else [])
        if isinstance(item, dict) and item.get("url")
    ]
    item = view.notice.raw_data.get("item")
    urls = {a["url"] for a in own}
    return own + [d for d in prespec_service.spec_docs_for(item if isinstance(item, dict) else None) if d["url"] not in urls]
