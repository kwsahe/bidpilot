"""조직(회사)별 저장공간 경로 해결 계층.

여러 회사가 등록될 수 있고, 하나의 공고 분석은 하나의 회사에만 연결된다.
회사별 파일은 **전부 이 모듈을 통해서만** 경로를 만든다 — 코드 곳곳에서 `data/...`를 직접 조립하지 않는다.

    data/private/organizations/
    ├─ registry.json                      조직 목록 (organization_service)
    └─ {organization_id}/
       ├─ profile.json                    회사 프로필
       ├─ delivery_capacity.json          개발 수행역량 (인원·기술·자격)
       ├─ documents.json                  회사자료 등록부
       ├─ performance_ledger.json         실적 원장 (구조화)
       ├─ uploads/                        원본 파일
       ├─ candidates/                     추출 후보 문단 + 검토 결과
       ├─ ledger_docs/                    원장에서 만든 근거 문서(md)
       ├─ analyses/{procurement_id}/      공고 분석 결과 (제안서·조건·결정·Auditor …)
       ├─ proposals/                      (예약) 제안서 산출물
       └─ index/company_index.json        승인 문단 임베딩 인덱스

규칙
- `organization_id`는 회사 이름과 분리된 영구 식별자다 (`org-sample`). 이름이 바뀌어도 id는 그대로다.
- id는 소문자 slug만 허용한다 — 경로 이동 문자(`..`, `/`, `\\`)와 URL 인코딩된 변형은 정규식에서 걸러진다.
- 기본 조직(`org-sample`)만 레거시 `data/company/` 를 **읽기 전용**으로 대체 조회한다 (마이그레이션 전 호환).
  쓰기는 항상 조직 폴더로 간다. 레거시 폴더는 삭제하지 않는다.
- 실제자료 저장공간(`data/private/`)은 통째로 .gitignore 대상이다.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.core import storage
from app.core.config import get_settings
from app.core.paths import DATA_ROOT

# 데이터 루트는 app.core.paths 가 정한다 (DATA_DIR 환경변수 → 영구 볼륨 마운트).
DATA_DIR = DATA_ROOT
# 테스트는 이 두 값을 monkeypatch 한다. 함수들은 호출 시점에 모듈 값을 읽는다 (import 시점에 묶지 않는다).
ORGANIZATIONS_DIR = DATA_DIR / "private" / "organizations"
LEGACY_COMPANY_DIR = DATA_DIR / "company"
REGISTRY_FILE_NAME = "registry.json"

# 설정에서 읽는다(30차 §3-G 키트 — 기본은 그대로 org-sample). 테스트는 이 값을 monkeypatch 한다.
DEFAULT_ORGANIZATION_ID = get_settings().default_organization_id

# org-로 시작하는 소문자 slug. 3~48자 본문, 하이픈 연속·끝 하이픈 불가.
_ORG_ID_RE = re.compile(r"^org-(?!-)(?:[a-z0-9]+-?){2,48}(?<!-)$")
_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")


class InvalidOrganizationIdError(ValueError):
    """저장 경로로 쓸 수 없는 organization_id (형식 위반·경로 조작 시도)."""


def validate_organization_id(value: str) -> str:
    """허용 형식(`org-xxx`)만 통과시킨다. URL 인코딩된 `%2e%2e`나 `../` 는 정규식에서 걸린다."""
    if not isinstance(value, str) or not _ORG_ID_RE.match(value) or len(value) > 52:
        raise InvalidOrganizationIdError(f"허용되지 않는 organization_id 입니다: {value!r}")
    return value


def suggest_organization_id(display_name: str, *, taken: set[str] | frozenset[str] = frozenset()) -> str:
    """회사명에서 안전한 slug를 만든다. 영문·숫자가 없으면(한글 상호 등) 짧은 uuid를 쓴다."""
    base = _SLUG_STRIP_RE.sub("-", display_name.lower()).strip("-")
    base = re.sub(r"-{2,}", "-", base)[:24].strip("-")
    if len(base) < 2:
        base = uuid.uuid4().hex[:10]
    candidate = f"org-{base}"
    if not _ORG_ID_RE.match(candidate):
        candidate = f"org-{uuid.uuid4().hex[:10]}"
    if candidate not in taken:
        return candidate
    for _ in range(50):
        alt = f"{candidate[:40]}-{uuid.uuid4().hex[:6]}"
        if alt not in taken and _ORG_ID_RE.match(alt):
            return alt
    raise InvalidOrganizationIdError("organization_id를 만들지 못했습니다 (충돌 반복)")


def organizations_dir() -> Path:
    return ORGANIZATIONS_DIR


def registry_file() -> Path:
    return ORGANIZATIONS_DIR / REGISTRY_FILE_NAME


def legacy_company_dir() -> Path:
    return LEGACY_COMPANY_DIR


@dataclass(frozen=True)
class OrganizationStorage:
    """조직 하나의 저장 경로 묶음. 생성자에서 id를 검증한다."""

    organization_id: str
    root: Path

    # --- 파일 ---
    @property
    def profile_file(self) -> Path:
        return self.root / "profile.json"

    @property
    def documents_file(self) -> Path:
        return self.root / "documents.json"

    @property
    def ledger_file(self) -> Path:
        return self.root / "performance_ledger.json"

    @property
    def delivery_capacity_file(self) -> Path:
        """개발 수행역량 (인원·기술·자격). 프로필과 갱신 주기가 달라 파일을 나눈다."""
        return self.root / "delivery_capacity.json"

    @property
    def uploads_dir(self) -> Path:
        return self.root / "uploads"

    @property
    def candidates_dir(self) -> Path:
        return self.root / "candidates"

    @property
    def ledger_docs_dir(self) -> Path:
        return self.root / "ledger_docs"

    @property
    def analyses_dir(self) -> Path:
        return self.root / "analyses"

    @property
    def proposals_dir(self) -> Path:
        return self.root / "proposals"

    @property
    def index_dir(self) -> Path:
        return self.root / "index"

    @property
    def index_file(self) -> Path:
        return self.index_dir / "company_index.json"

    @property
    def exports_dir(self) -> Path:
        return self.root / "exports"

    def candidate_path(self, document_id: str) -> Path:
        return self.candidates_dir / f"{storage.safe_id(document_id, what='문서 id')}.json"

    def upload_path(self, document_id: str, suffix: str) -> Path:
        safe = storage.safe_id(document_id, what="문서 id")
        if not re.match(r"^\.[a-z0-9]{1,8}$", suffix or ""):
            raise storage.InvalidIdError(f"허용되지 않는 확장자입니다: {suffix!r}")
        return self.uploads_dir / f"{safe}{suffix}"

    def analysis_dir(self, procurement_id: str) -> Path:
        return self.analyses_dir / storage.safe_id(procurement_id, what="공고 id")

    def exists(self) -> bool:
        return self.root.exists()

    # --- 레거시 대체 조회 (기본 조직만, 읽기 전용) ---
    @property
    def has_legacy(self) -> bool:
        return self.organization_id == DEFAULT_ORGANIZATION_ID and LEGACY_COMPANY_DIR.exists()

    def legacy_path(self, kind: str) -> Path | None:
        """레거시 data/company/ 의 대응 경로. 기본 조직이 아니면 None."""
        if not self.has_legacy:
            return None
        legacy = LEGACY_COMPANY_DIR
        mapping = {
            "profile": legacy / "company_profile.json",
            "identity": legacy / "company_identity.json",
            "documents": legacy / "documents.json",
            "ledger": legacy / "performance_ledger.json",
            "uploads": legacy / "uploads",
            "candidates": legacy / "candidates",
            "ledger_docs": legacy / "ledger_docs",
            "index": legacy / "index" / "company_index.json",
        }
        return mapping.get(kind)

    def read_path(self, kind: str) -> Path:
        """읽기용 경로: 조직 폴더에 있으면 그것, 없고 레거시(기본 조직)에 있으면 레거시. 둘 다 없으면 조직 경로."""
        own = {
            "profile": self.profile_file,
            "documents": self.documents_file,
            "ledger": self.ledger_file,
            "index": self.index_file,
        }[kind]
        if own.exists():
            return own
        legacy = self.legacy_path(kind)
        if legacy is not None and legacy.exists():
            return legacy
        return own

    def read_candidate_path(self, document_id: str) -> Path:
        own = self.candidate_path(document_id)
        if own.exists():
            return own
        legacy_dir = self.legacy_path("candidates")
        if legacy_dir is not None:
            alt = legacy_dir / own.name
            if alt.exists():
                return alt
        return own

    def read_upload_path(self, document_id: str, suffix: str) -> Path:
        own = self.upload_path(document_id, suffix)
        if own.exists():
            return own
        legacy_dir = self.legacy_path("uploads")
        if legacy_dir is not None:
            alt = legacy_dir / own.name
            if alt.exists():
                return alt
        return own


def storage_for(organization_id: str) -> OrganizationStorage:
    """검증된 id로만 경로를 만든다. 존재 여부는 확인하지 않는다 (등록 여부는 organization_service가 본다)."""
    org = validate_organization_id(organization_id)
    return OrganizationStorage(organization_id=org, root=ORGANIZATIONS_DIR / org)


def is_under_private(path: Path) -> bool:
    """경로가 실제자료 저장공간(data/private) 아래인지 — 공개 산출물에 섞이면 안 되는 파일 판정용."""
    try:
        path.resolve().relative_to((DATA_DIR / "private").resolve())
    except ValueError:
        return False
    return True
