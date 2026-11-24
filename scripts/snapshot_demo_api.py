"""읽기 전용 데모 배포용 API 스냅샷.

로컬 백엔드(:8110)의 GET 응답을 떠서 프론트엔드가 백엔드 없이도 돌게 한다.
Vercel 배포본은 이 스냅샷을 Next Route Handler로 돌려준다.

쓰기 요청(POST/PUT)은 스냅샷하지 않는다 — 데모 모드에서는 실행할 수 없다고 응답한다.

저장 전에 세 가지를 한다.
1. 개인정보 제외: 본문에 직원 실명이 든 회사자료 문서는 아예 담지 않는다.
   담당자·승인자·검토자 필드의 실명은 문서를 빼지 않고 값만 가린다
   (그 필드 때문에 문서를 빼면 색인된 근거까지 사라진다).
2. 정화(sanitize): 담당자 이메일·전화번호를 마스킹한다 (필드는 지우지 않는다 — 화면이 비면 안 된다).
3. 누출 검사: 실제 회사자료 흔적·이메일/전화 패턴·직원 실명·API 키 값이 남아 있으면
   파일을 쓰지 않고 exit 2.

실명 목록은 저장소에 두지 않는다 — 이 스크립트가 Git 에 올라가기 때문이다.
`data/private/pii_names.txt`(gitignore) 또는 환경변수 `SNAPSHOT_PII_NAMES` 에서 읽는다.

    python scripts/snapshot_demo_api.py
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence
from urllib.parse import quote

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    # 마스킹 규칙과 API 키 검사는 백엔드 코드를 그대로 재사용한다 (규칙 이중 정의 금지).
    sys.path.insert(0, str(BACKEND_DIR))

BASE = "http://127.0.0.1:8110"
OUT = REPO_ROOT / "frontend" / "src" / "data" / "demo-snapshot.json"

# 공개 데모의 기본 조직. 프론트의 DEFAULT_ORGANIZATION_ID 와 같아야 스냅샷 키가 맞는다.
DEMO_ORG = "org-sample"

# 스냅샷 자체의 표시. 경로 키가 아니므로 프론트 lookup() 에 걸리지 않는다.
META_KEY = "__snapshot_meta__"

# 목록 화면이 실제로 부르는 조합. api.ts 의 ProcurementQuery 기본값과 맞춘다.
LIST_PATHS = [
    "/api/procurements",
    "/api/procurements?include_low=true",
    # /opportunities 의 조회 기간 선택기(getProcurements({days})). 없으면 14일 목록으로 되돌아간다.
    "/api/procurements?days=14",
    "/api/procurements?days=30",
    "/api/procurements?days=60",
]

# 공고 하나당 부르는 GET 경로. {id} 는 공고 id로 치환한다.
# 분석 결과는 **public_demo 범위만** 뜬다 — 실제 회사(org-*) 내부 결과는 절대 스냅샷에 넣지 않는다.
# (evidence_scope=public_demo 는 공개 위치의 합성 근거 결과만 읽고, 조직 폴더는 보지 않는다.)
PUBLIC_SCOPE = "?evidence_scope=public_demo"
PER_NOTICE = [
    "/api/procurements/{id}",
    "/api/procurements/{id}/attachments",
    "/api/demo/cosmos/{id}",
    "/api/rfp/{id}/requirements",
    "/api/eligibility/{id}" + PUBLIC_SCOPE,
    "/api/proposal/{id}" + PUBLIC_SCOPE,
    "/api/proposal/{id}/full" + PUBLIC_SCOPE,
    "/api/review/{id}" + PUBLIC_SCOPE,
    "/api/auditor/{id}/resolutions" + PUBLIC_SCOPE,
]
# 스냅샷에 절대 넣지 않는 경로 접두사. 테스트가 검사한다.
# 기본값은 **공개 데모** 기준이라 회사자료·조직 등록부를 통째로 막는다.
FORBIDDEN_PREFIXES = ("/api/company", "/api/organizations", "/api/performance-ledger", "/api/exports")
# `--include-company` 를 준 사내 배포용 스냅샷에서만 조직 API 를 연다.
# 그래도 레거시 /api/company, 실적 원장 전용 경로, 파일 내려받기는 계속 막는다
# (파일 내려받기는 백엔드가 있어야 동작하므로 스냅샷에 담아도 쓸모가 없다).
FORBIDDEN_PREFIXES_WITH_COMPANY = ("/api/company", "/api/performance-ledger", "/api/exports")
# 저장 전 누출 검사 — 이 문자열이 응답에 섞이면 스냅샷을 쓰지 않는다.
# 사내 배포(--include-company)에서는 실제 근거가 들어가는 것이 **목적**이라 이 검사만 끈다.
# API 키·연락처 검사는 어떤 경우에도 끄지 않는다.
LEAK_NEEDLES = ('"evidence_id": "CD-', '"evidence_id":"CD-', '"evidence_scope": "internal"', '"evidence_scope":"internal"')


def forbidden_prefixes(include_company: bool) -> tuple[str, ...]:
    return FORBIDDEN_PREFIXES_WITH_COMPANY if include_company else FORBIDDEN_PREFIXES


# 사내 배포에서 담을 조직 읽기 경로. /company 화면이 실제로 부르는 것만 넣는다 (쓰기는 배포본에서 막힌다).
COMPANY_ORG_PATHS = (
    "/api/organizations",
    "/api/organizations/{org}",
    "/api/organizations/{org}/profile",
    "/api/organizations/{org}/documents",
    "/api/organizations/{org}/index",
    "/api/organizations/{org}/ledger/summary",
    "/api/organizations/{org}/ledger/profiles",
)
COMPANY_DOC_DETAIL = "/api/organizations/{org}/documents/{doc}"
COMPANY_DOC_USAGE = "/api/organizations/{org}/documents/{doc}/usage"
COMPANY_DOC_PATHS = (COMPANY_DOC_DETAIL, COMPANY_DOC_USAGE)


# --------------------------------------------------------------------------
# 통합 사업기회 (나라장터 입찰 + 기업마당 지원사업)
# --------------------------------------------------------------------------
# 스냅샷 키 = 요청 경로 + 쿼리스트링 **그대로**다. 못 찾으면 프론트가 `?` 앞부분으로 한 번 더 찾는다.
# 그래서 아래 조합은 frontend/src/lib/api.ts 의 getBusinessOpportunities() 가 만드는
# 파라미터 **순서까지** 같아야 한다: organization_id → source(all이면 생략) → days → sort
# → limit → include_closed → include_low → refresh.


def unified_path(
    *,
    organization_id: str | None = DEMO_ORG,
    source: str = "all",
    days: int | None = None,
    sort: str | None = "priority",
    limit: int | None = None,
    include_closed: bool = False,
    include_low: bool = False,
    refresh: bool = False,
) -> str:
    """getBusinessOpportunities() 와 같은 규칙으로 쿼리스트링을 만든다."""
    parts: list[str] = []
    if organization_id:
        parts.append(f"organization_id={quote(organization_id, safe='')}")
    if source and source != "all":
        parts.append(f"source={source}")
    if days is not None:
        parts.append(f"days={days}")
    if sort:
        parts.append(f"sort={sort}")
    if limit is not None:
        parts.append(f"limit={limit}")
    if include_closed:
        parts.append("include_closed=true")
    if include_low:
        parts.append("include_low=true")
    if refresh:
        parts.append("refresh=true")
    query = "&".join(parts)
    return "/api/business-opportunities" + (f"?{query}" if query else "")


# 화면이 **실제로 만드는** 조합만 담는다 (frontend/src/lib/api.ts 의 getBusinessOpportunities 규칙).
# 저장하지 않은 조합은 프론트 lookup() 이 `?` 앞부분(= 무쿼리 항목)으로 되돌아가므로 404 는 아니지만
# **필터·정렬이 먹지 않은 목록**이 보인다. 그래서 두 화면이 보내는 키를 정확히 맞춘다.
#   /radar          → organization_id, source, sort, limit=20, include_closed   (3 출처 × 3 정렬 × 2)
#   /opportunities  → organization_id, days(14/30/60), sort=priority, include_closed (3 × 2)
RADAR_LIMIT = 20
UNIFIED_VARIANTS: list[dict[str, Any]] = [
    {"organization_id": None, "sort": None},  # 무쿼리 — 어떤 조합도 못 찾을 때의 되돌림 대상
    # /radar — 목록이 20건으로 잘려 조합당 40KB 안팎이라 18개를 다 담아도 부담이 적다.
    *(
        {"source": source, "sort": sort, "limit": RADAR_LIMIT, "include_closed": closed}
        for source in ("all", "g2b", "bizinfo")
        for sort in ("priority", "deadline", "value")
        for closed in (False, True)
    ),
    # /opportunities — 전체 목록(자르지 않음). 조회 기간 선택기와 마감 포함 토글.
    *(
        {"days": days, "sort": "priority", "include_closed": closed}
        for days in (14, 30, 60)
        for closed in (False, True)
    ),
]
UNIFIED_PATHS = [unified_path(**variant) for variant in UNIFIED_VARIANTS]

# 지원사업 목록. 기본 조직이 org-sample 이라 organization_id 를 붙인 응답과 내용이 같다 —
# 무쿼리 키 하나만 두면 프론트가 어떤 쿼리로 불러도 되돌림으로 찾는다 (200KB 중복 방지).
SUPPORT_LIST_PATHS = [
    "/api/support-programs",
]
# 상세는 **public_demo 범위로만** 뜬다. 프론트(getSupportProgram)는 evidence_scope 를 보내지 않으므로
# 실제로 부르는 키로 저장한다 (아래 SUPPORT_DETAIL_KEYS).
SUPPORT_DETAIL_FETCH = "/api/support-programs/{id}?organization_id={org}&evidence_scope=public_demo"
SUPPORT_DETAIL_KEYS = (
    "/api/support-programs/{id}",  # 무쿼리 — 다른 조직 id로 불러도 여기로 되돌아온다
    "/api/support-programs/{id}?organization_id={org}",
)
SUPPORT_DETAIL_LIMIT = 5


# --------------------------------------------------------------------------
# 정화 (공개 스냅샷용 마스킹)
# --------------------------------------------------------------------------
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# 전화번호 판정 규칙. 앞뒤가 숫자면 전화번호가 아니다 —
# 기업마당 사업 id(`bizinfo-PBLN_000000000096203`)나 나라장터 품목코드 같은 긴 숫자열을
# 전화번호로 오인해 마스킹하면 화면의 링크가 깨진다. (실측으로 확인한 함정이다.)
PHONE_RE = re.compile(r"(?<!\d)0\d{1,2}[-.)\s]?\d{3,4}[-.\s]?\d{4}(?!\d)")
# 담당자 필드 전용 대체 규칙 (백엔드 bizinfo_service 와 같은 느슨한 규칙).
_FALLBACK_PHONE_RE = re.compile(r"0\d{1,2}[-.)\s]?\d{3,4}[-.\s]?\d{4}")

try:  # pragma: no cover - 백엔드 의존성이 없는 환경 대비
    from app.services.bizinfo_service import mask_contacts as _backend_mask_contacts
except Exception:  # noqa: BLE001 - 스크립트는 백엔드 없이도 import 가능해야 한다
    _backend_mask_contacts = None

# 담당자 정보가 들어오는 필드 (기업마당 refrncNm / reqstMthPapersCn).
# 이 필드만 백엔드의 느슨한 규칙으로 지운다 — 값이 통째로 연락처라 과하게 지워도 손해가 없다.
CONTACT_FIELDS = ("contact", "apply_method", "reception_contact")


# --------------------------------------------------------------------------
# 직원 실명 (스냅샷에서 제외·마스킹)
# --------------------------------------------------------------------------
# 스냅샷 파일은 Git 에 커밋되고 Vercel 로 배포된다. 회사자료 본문에는 직원 실명과
# 직급·담당업무가 들어 있어 그대로 실으면 개인정보가 배포본과 Git 히스토리에 남는다.
#
# **이 스크립트도 Git 에 올라간다.** 그러므로 이름을 여기에 적으면 그 자체가 유출이다.
# 이름은 반드시 저장소 밖(환경변수) 또는 gitignore 된 곳에서만 읽는다.
PII_NAMES_FILE = REPO_ROOT / "data" / "private" / "pii_names.txt"
PII_NAMES_ENV = "SNAPSHOT_PII_NAMES"
# 한 글자는 우연히 겹친다 (예: 성씨 한 글자가 다른 낱말에 섞임).
MIN_NAME_LEN = 2

# 담당자 이름이 값으로 들어오는 메타 필드. 본문이 아니라 **기록자 표시**다.
# 이 필드 때문에 문서를 통째로 빼면 색인된 근거까지 사라지므로, 문서는 두고 값만 가린다.
PERSON_FIELDS = (
    "uploaded_by",
    "approved_by",
    "reviewer",
    "reviewed_by",
    "decided_by",
    "confirmed_by",
    "created_by",
)
PERSON_MASK = "[담당자]"
# `system`, `system:split-tool` 처럼 사람이 아닌 값은 그대로 둔다.
# 사람이 넣은 것인지 도구가 넣은 것인지는 화면에서 의미가 있는 정보다 —
# 이걸 가리면 「누가 등록했나」가 전부 [담당자] 로 보여 오히려 이력이 나빠진다.
SYSTEM_ACTOR_PREFIX = "system:"
SYSTEM_ACTORS = frozenset({"system", "admin", "importer", "migration", "unknown", "-"})

# 목록에 없는 이름까지 잡는 구조적 backstop — 「성씨+1~2자 + 직급」 형태.
# 이름 자체를 코드에 적지 않고도 `홍길동 대표`, `임꺽정 사원` 같은 문장을 탐지한다.
# 조달·기업마당 원문의 발주기관 담당자까지 지우면 공고 표시가 상하므로
# **회사자료 문서 본문 판정에만** 쓴다 (전체 마스킹에는 쓰지 않는다).
_SURNAMES = (
    "김이박최정강조윤장임한오서신권황안송류전홍고문양손배백허유남심노하곽성차주우구"
    "나민지엄채원천방공현함변염여추도소석선설마길연위표명기반왕금옥육인맹제모탁국어은편용"
)
_TITLES = (
    "대표이사|대표|본부장|팀장|실장|부장|차장|과장|대리|주임|사원"
    "|선임|책임|수석|이사|전무|상무|매니저|강사|연구원|담당자|담당"
)
# 직급 뒤에는 조사가 바로 붙는다(`대표와`, `팀장은`). 조사는 허용하고,
# 직급을 더 긴 낱말로 만드는 글자(`대표성`, `담당업무`)는 막는다.
_PARTICLES = "은는이가와과의로을를도만님께서"
PERSON_TITLE_RE = re.compile(
    "(?<![가-힣])([" + _SURNAMES + "][가-힣]{1,2})\\s*(?:" + _TITLES + ")"
    "(?:(?![가-힣])|(?=[" + _PARTICLES + "]))"
)
# 「성씨+직급」 모양이지만 사람이 아닌 흔한 낱말. 여기 있는 값은 사람 이름이 아니므로
# 코드에 적어도 개인정보가 아니다. 잡아 봐야 문서만 억울하게 빠진다.
NOT_NAMES = frozenset(
    {
        "기업", "회사", "사업", "정책", "담당", "대상", "전체", "외부", "내부",
        "신규", "기존", "우수", "전문", "총괄", "부서", "조직", "현장", "기관",
        "단체", "협회", "학교", "대학", "지역", "국가", "공공", "각급", "해당",
        "관련", "주관", "운영", "교육", "과정", "센터", "본부",
    }
)

# 문서 응답에서 **본문**으로 보는 필드. 여기에 실명이 있으면 그 문서를 스냅샷에서 뺀다.
# (uploaded_by 같은 메타 필드는 여기 없다 — 마스킹으로 처리한다.)
DOC_CONTENT_FIELDS = ("source_text", "note", "title", "file_name", "content", "text")


def pii_names() -> tuple[str, ...]:
    """스냅샷에서 지울 실명 목록. **저장소에 커밋되지 않는 곳에서만** 읽는다.

    우선순위 없이 두 곳을 합친다.
    - 환경변수 `SNAPSHOT_PII_NAMES` (쉼표 구분)
    - `data/private/pii_names.txt` (한 줄에 하나, `#` 뒤는 주석)

    둘 다 없으면 빈 튜플이다 — 그때는 구조적 backstop 만 돈다.
    """
    names: set[str] = set()
    for chunk in os.environ.get(PII_NAMES_ENV, "").split(","):
        value = chunk.strip()
        if len(value) >= MIN_NAME_LEN:
            names.add(value)
    if PII_NAMES_FILE.exists():
        for line in PII_NAMES_FILE.read_text(encoding="utf-8").splitlines():
            value = line.split("#", 1)[0].strip()
            if len(value) >= MIN_NAME_LEN:
                names.add(value)
    return tuple(sorted(names))


def mask_person(value: Any) -> Any:
    """담당자 표시 필드의 값을 가린다. 사람이 아닌 값(`system:...`)과 빈 값은 그대로 둔다."""
    if not isinstance(value, str) or not value.strip():
        return value
    if value.startswith(SYSTEM_ACTOR_PREFIX) or value.strip().lower() in SYSTEM_ACTORS:
        return value
    return PERSON_MASK


def adjust_org_counts(snapshot: dict[str, object], org_id: str, withheld: Sequence[Mapping[str, Any]]) -> None:
    """문서를 뺐으면 조직 요약의 문서 건수도 같이 줄인다.

    목록만 줄이고 요약을 그대로 두면 한 화면 안에서 「등록 문서 10건」과 `document_count: 14`
    가 공존한다. 화면이 지금 그 값을 그리지 않더라도, 서로 어긋나는 응답을 배포본에 담지 않는다.
    """
    if not withheld:
        return
    approved = sum(
        1
        for doc in withheld
        if str(doc.get("status")) in ("approved", "indexed")
        or bool((doc.get("metadata") or {}).get("approved"))
    )
    summaries: list[Any] = []
    detail = snapshot.get(f"/api/organizations/{quote(org_id, safe='')}")
    if isinstance(detail, dict):
        summaries.append(detail)
    listing = snapshot.get("/api/organizations")
    if isinstance(listing, dict):
        for entry in listing.get("organizations") or []:
            organization = entry.get("organization") if isinstance(entry, dict) else None
            if isinstance(organization, dict) and str(organization.get("organization_id")) == org_id:
                summaries.append(entry)
    for summary in summaries:
        for field, delta in (("document_count", len(withheld)), ("approved_document_count", approved)):
            value = summary.get(field)
            if isinstance(value, int):
                summary[field] = max(0, value - delta)


def document_person_names(detail: Any, names: Sequence[str]) -> list[str]:
    """문서 상세 응답의 **본문**에 들어 있는 실명. 비어 있으면 그 문서는 담아도 된다.

    메타 필드(uploaded_by 등)는 보지 않는다 — 그것 때문에 문서를 빼면
    색인된 근거까지 사라져 분석 화면이 빈다.
    구조적 backstop(`성씨+직급`)에 걸린 것도 이름으로 친다 — 목록에 없는 직원을 놓치지 않기 위해서다.
    """
    found: set[str] = set()

    def walk(value: Any, field: str | None) -> None:
        if isinstance(value, str):
            if field not in DOC_CONTENT_FIELDS:
                return
            for name in names:
                if name in value:
                    found.add(name)
            for match in PERSON_TITLE_RE.finditer(value):
                candidate = match.group(1)
                if candidate not in NOT_NAMES:
                    found.add(candidate)
        elif isinstance(value, dict):
            for key, item in value.items():
                walk(item, key if isinstance(key, str) else field)
        elif isinstance(value, list):
            for item in value:
                walk(item, field)

    walk(detail, None)
    return sorted(found)


def mask_contacts(value: str | None) -> str | None:
    """담당자 필드 마스킹 — 백엔드 bizinfo_service.mask_contacts 규칙 그대로.

    필드를 통째로 지우지 않는다. 화면에 항목은 남고 값만 가린다.
    """
    if not value:
        return value
    if _backend_mask_contacts is not None:
        return _backend_mask_contacts(value)
    masked = EMAIL_RE.sub("[이메일 원문 확인]", value)
    return _FALLBACK_PHONE_RE.sub("[전화 원문 확인]", masked)


def mask_text(value: str) -> str:
    """그 밖의 문자열 — 이메일과 **전화번호 모양의 값만** 가린다 (id·코드는 건드리지 않는다)."""
    masked = EMAIL_RE.sub("[이메일 원문 확인]", value)
    return PHONE_RE.sub("[전화 원문 확인]", masked)


def sanitize(value: Any, *, field: str | None = None) -> Any:
    """응답을 재귀적으로 훑어 담당자 이메일·전화를 마스킹한다.

    지원사업의 contact(refrncNm)·apply_method(reqstMthPapersCn) 에 담당자 연락처가 들어 있고,
    조달공고 원문에도 기관 담당자 번호가 섞인다. 공개 배포본에는 남기지 않는다.
    숫자·불리언은 건드리지 않는다 (예산·페이지 번호가 바뀌면 안 된다).

    회사자료의 등록자·승인자·검토자 필드(PERSON_FIELDS)에는 직원 실명이 들어온다.
    그 문서를 통째로 빼면 색인된 근거까지 사라지므로, 문서는 두고 **값만** 가린다.
    """
    if isinstance(value, str):
        if field in PERSON_FIELDS:
            return mask_person(value)
        return mask_contacts(value) if field in CONTACT_FIELDS else mask_text(value)
    if isinstance(value, dict):
        return {key: sanitize(item, field=key if isinstance(key, str) else None) for key, item in value.items()}
    if isinstance(value, list):
        # 리스트 원소는 부모 필드명을 물려받는다 (연락처 배열도 같은 규칙으로 가린다).
        return [sanitize(item, field=field) for item in value]
    return value


# --------------------------------------------------------------------------
# 누출 검사
# --------------------------------------------------------------------------
def iter_strings(value: Any) -> Iterator[str]:
    """스냅샷 안의 모든 문자열 (dict 키 포함). 숫자는 보지 않는다 — 예산 자릿수가 전화번호로 오인된다."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str):
                yield key
            yield from iter_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_strings(item)


def find_contact_leaks(payload: Any) -> list[str]:
    """이메일·전화번호 패턴이 남았는지. 값 자체는 절대 출력하지 않고 건수만 돌려준다."""
    counts = {"이메일": 0, "전화번호": 0}
    for text in iter_strings(payload):
        counts["이메일"] += len(EMAIL_RE.findall(text))
        counts["전화번호"] += len(PHONE_RE.findall(text))
    return [f"{label} 패턴 {count}건" for label, count in counts.items() if count]


# 너무 짧은 값은 우연히 겹칠 수 있어 검사에서 뺀다 (미설정·자리표시자 포함).
MIN_SECRET_LEN = 6


def api_key_values() -> dict[str, str]:
    """설정에 들어 있는 API 키 값. **어디에도 출력하지 않는다** — 검사 입력으로만 쓴다."""
    try:
        from app.core.config import get_settings
    except Exception:  # noqa: BLE001 - 설정을 못 읽으면 키 검사만 건너뛴다
        return {}
    try:
        settings = get_settings()
    except Exception:  # noqa: BLE001
        return {}
    candidates = {
        "BIZINFO_API_KEY": getattr(settings, "bizinfo_api_key", ""),
        "DATA_GO_KR_SERVICE_KEY": getattr(settings, "data_go_kr_service_key", ""),
    }
    return {name: value.strip() for name, value in candidates.items() if len((value or "").strip()) >= MIN_SECRET_LEN}


def find_key_leaks(payload: Any, secrets: Mapping[str, str]) -> list[str]:
    """API 키 값이 스냅샷에 섞였는지. 걸린 **설정 이름만** 돌려준다 (값은 반환하지 않는다)."""
    if not secrets:
        return []
    texts = list(iter_strings(payload))
    hits: list[str] = []
    for name, value in secrets.items():
        # URL 에 붙어 나가면 인코딩된 형태로 남는다.
        variants = {value, quote(value, safe=""), quote(value)}
        if any(variant in text for text in texts for variant in variants if variant):
            hits.append(name)
    return sorted(hits)


def find_name_leaks(payload: Any, names: Sequence[str]) -> list[str]:
    """직원 실명이 스냅샷에 남았는지. **이름 자체는 돌려주지 않는다.**

    사유 문자열은 화면·CI 로그에 그대로 찍히므로 여기에 실명을 넣으면 검사기가 유출 통로가 된다.
    어느 경로에 몇 건인지만 알려 준다 — 고칠 곳을 찾기에는 충분하다.
    """
    if not names:
        return []
    if isinstance(payload, Mapping):
        hits: dict[str, int] = {}
        for key, body in payload.items():
            blob = json.dumps(body, ensure_ascii=False)
            count = sum(blob.count(name) for name in names)
            if count:
                hits[str(key)] = count
        if not hits:
            return []
        worst = sorted(hits.items(), key=lambda item: -item[1])[:5]
        detail = ", ".join(f"{path} {count}건" for path, count in worst)
        more = f" 외 {len(hits) - len(worst)}개 경로" if len(hits) > len(worst) else ""
        return [f"직원 실명 {sum(hits.values())}건 — {detail}{more}"]
    blob = json.dumps(payload, ensure_ascii=False)
    total = sum(blob.count(name) for name in names)
    return [f"직원 실명 {total}건"] if total else []


def find_leaks(snapshot: Mapping[str, Any], *, include_company: bool = False) -> list[str]:
    """저장 전 최종 검사. 걸리면 사유(이름·건수)만 돌려준다 — 원문 값은 담지 않는다.

    `include_company` 면 회사자료 흔적 검사만 끈다 (그게 목적이라서).
    API 키·연락처·직원 실명 검사는 **어떤 경우에도** 돈다.
    회사자료를 담는 사내 배포본이라도 개인정보는 담지 않는다.
    """
    blob = json.dumps(snapshot, ensure_ascii=False)
    reasons = [] if include_company else [f"회사자료 흔적: {needle}" for needle in LEAK_NEEDLES if needle in blob]
    reasons += find_contact_leaks(snapshot)
    reasons += find_name_leaks(snapshot, pii_names())
    reasons += [f"API 키 노출: {name}" for name in find_key_leaks(snapshot, api_key_values())]
    return reasons


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="로컬 백엔드의 GET 응답을 떠서 배포용 스냅샷을 만든다")
    parser.add_argument(
        "--include-company",
        action="store_true",
        help="회사자료(조직·문서·근거)를 스냅샷에 포함한다. **사내 배포 전용** — 공개 링크에 쓰지 말 것.",
    )
    args = parser.parse_args(argv)
    include_company = args.include_company
    blocked = forbidden_prefixes(include_company)
    if include_company:
        print("!! --include-company: 실제 회사자료를 스냅샷에 담습니다 (사내 배포 전용).")
        # 실명 목록이 없으면 「깨끗함」이 아니라 「검사 불가」다.
        # 목록은 gitignore 된 곳에만 있으므로 새로 clone 한 기계·CI 에는 없다.
        # 그대로 진행하면 검사가 통과한 것처럼 보이면서 실명이 그대로 실린다 — 조용히 열리면 안 된다.
        if not pii_names():
            print(
                f"실명 목록이 비어 있어 개인정보 검사를 할 수 없습니다. 스냅샷을 만들지 않습니다.\n"
                f"  {PII_NAMES_FILE} 를 만들거나 환경변수 {PII_NAMES_ENV} 에 쉼표로 이름을 넣으세요.\n"
                f"  (목록은 저장소에 커밋되지 않습니다 — 그래서 기계마다 따로 둬야 합니다.)",
                file=sys.stderr,
            )
            return 2

    snapshot: dict[str, object] = {}
    with httpx.Client(base_url=BASE, timeout=90.0) as client:
        try:
            client.get("/health")
        except httpx.HTTPError:
            print("백엔드(:8110)가 떠 있지 않다. scripts\\start_dev.bat 먼저 실행할 것.", file=sys.stderr)
            return 1

        def grab(path: str, keys: Sequence[str] | None = None) -> object | None:
            store_keys = list(keys) if keys else [path]
            for candidate in [path, *store_keys]:
                if candidate.startswith(blocked):
                    raise RuntimeError(f"이 경로는 스냅샷하지 않는다: {candidate}")
            try:
                r = client.get(path)
            except httpx.HTTPError as exc:
                print(f"  skip {path} — {type(exc).__name__}")
                return None
            if r.status_code != 200:
                print(f"  skip {path} — HTTP {r.status_code}")
                return None
            try:
                body = r.json()
            except ValueError:
                print(f"  skip {path} — JSON 아님")
                return None
            # 크롤링 중에는 원본을 들고 있는다 (마스킹된 id 로 다음 경로를 만들면 404 가 난다).
            # 정화는 저장 직전에 스냅샷 전체에 한 번 한다.
            for key in store_keys:
                snapshot[key] = body
            return body

        grab("/health")

        notices: list[dict] = []
        for p in LIST_PATHS:
            body = grab(p)
            if isinstance(body, dict) and not notices:
                notices = body.get("notices") or []
        print(f"공고 {len(notices)}건")

        # 합성 데모 공고는 목록에 없다 — Cosmos 시나리오가 이 id 에만 붙는다.
        EXTRA_IDS = ["synthetic-rfp-0001"]

        ids = [n["id"] for n in notices if n.get("id")] + EXTRA_IDS
        for nid in ids:
            for tmpl in PER_NOTICE:
                grab(tmpl.replace("{id}", quote(nid, safe="")))

        # Auditor 검사 기록 — cosmos 응답이 참조하는 run id 를 따라간다.
        run_ids = set()
        for path, body in list(snapshot.items()):
            if "/demo/cosmos/" in path and isinstance(body, dict):
                blob = json.dumps(body, ensure_ascii=False)
                for key in ("\"audit_run_id\":", "\"run_id\":"):
                    start = 0
                    while (i := blob.find(key, start)) != -1:
                        seg = blob[i + len(key): i + len(key) + 60]
                        val = seg.strip().strip('"').split('"')[0]
                        if val and val != "null":
                            run_ids.add(val)
                        start = i + len(key)
        for rid in sorted(run_ids):
            grab(f"/api/auditor/{quote(rid, safe='')}")
        print(f"Auditor 실행 기록 {len(run_ids)}건")

        # 통합 사업기회 목록 (나라장터 + 기업마당). 점수는 회사 기준 검토 우선순위다.
        support_ids: list[str] = []
        for path in UNIFIED_PATHS:
            body = grab(path)
            if isinstance(body, dict):
                for item in body.get("items") or []:
                    if isinstance(item, dict) and item.get("source_type") == "bizinfo" and item.get("id"):
                        if item["id"] not in support_ids:
                            support_ids.append(str(item["id"]))
        print(f"통합 목록 {len(UNIFIED_PATHS)}조합, 지원사업 후보 {len(support_ids)}건")

        # 지원사업 목록 + 상위 몇 건의 신청 분석 (/support/{id} 화면).
        for path in SUPPORT_LIST_PATHS:
            body = grab(path)
            if isinstance(body, dict):
                for item in body.get("items") or []:
                    program = item.get("program") if isinstance(item, dict) else None
                    pid = program.get("id") if isinstance(program, dict) else None
                    if pid and pid not in support_ids:
                        support_ids.append(str(pid))

        detailed = 0
        for pid in support_ids[:SUPPORT_DETAIL_LIMIT]:
            safe_id = quote(pid, safe="")
            fetch = SUPPORT_DETAIL_FETCH.format(id=safe_id, org=DEMO_ORG)
            keys = [tmpl.format(id=safe_id, org=DEMO_ORG) for tmpl in SUPPORT_DETAIL_KEYS]
            if grab(fetch, keys=keys) is not None:
                detailed += 1
        print(f"지원사업 신청 분석 {detailed}건")

        # 회사자료 (사내 배포 전용). /company 화면이 읽기로 부르는 경로만 담는다.
        # 배포본에서 업로드·승인·색인 같은 쓰기는 여전히 503 이라 **열람 전용 미러**가 된다.
        if include_company:
            org_ids: list[str] = []
            body = grab("/api/organizations")
            if isinstance(body, dict):
                for entry in body.get("organizations") or []:
                    org = entry.get("organization") if isinstance(entry, dict) else None
                    oid = org.get("organization_id") if isinstance(org, dict) else None
                    if oid:
                        org_ids.append(str(oid))
            # main() 앞부분에서 목록이 비면 이미 중단했다. 여기서는 반드시 값이 있다.
            names = pii_names()
            print(f"  직원 실명 목록 {len(names)}개를 읽었습니다 (이름은 출력하지 않습니다).")
            doc_total = 0
            withheld_total = 0
            for oid in org_ids:
                safe_org = quote(oid, safe="")
                for tmpl in COMPANY_ORG_PATHS:
                    if tmpl == "/api/organizations":
                        continue  # 위에서 이미 담았다
                    grab(tmpl.format(org=safe_org))
                listing_key = f"/api/organizations/{safe_org}/documents"
                listing = snapshot.get(listing_key)
                documents = listing.get("documents") if isinstance(listing, dict) else []
                withheld_ids: set[str] = set()
                for doc in documents or []:
                    did = doc.get("id") if isinstance(doc, dict) else None
                    if not did:
                        continue
                    safe_doc = quote(str(did), safe="")
                    detail_key = COMPANY_DOC_DETAIL.format(org=safe_org, doc=safe_doc)
                    detail = grab(detail_key)
                    # 본문에 직원 실명이 있으면 그 문서는 배포본에 담지 않는다.
                    # (등록자·승인자 같은 메타 필드는 보지 않는다 — 그건 마스킹으로 처리한다.)
                    hits = document_person_names(detail, names) if detail is not None else []
                    if hits:
                        snapshot.pop(detail_key, None)
                        withheld_ids.add(str(did))
                        withheld_total += 1
                        # 이름은 찍지 않는다. 어떤 문서를 왜 뺐는지만 남긴다.
                        print(f"  제외 {did} ({doc.get('file_name')}) — 본문에 실명 {len(hits)}종")
                        continue
                    grab(COMPANY_DOC_USAGE.format(org=safe_org, doc=safe_doc))
                    doc_total += 1
                if withheld_ids and isinstance(listing, dict):
                    # 목록에도 남기지 않는다. 남겨 두면 눌렀을 때 404 가 나 고장으로 보인다.
                    # 대신 몇 건을 왜 뺐는지 화면에 표시한다 (조용히 사라지면 안 된다).
                    kept = [d for d in documents if str(d.get("id")) not in withheld_ids]
                    dropped = [d for d in documents if str(d.get("id")) in withheld_ids]
                    adjust_org_counts(snapshot, oid, dropped)
                    counts: dict[str, int] = {}
                    for d in kept:
                        status = str(d.get("status") or "unknown")
                        counts[status] = counts.get(status, 0) + 1
                    listing["documents"] = kept
                    listing["counts"] = counts
                    listing["withheld_count"] = len(withheld_ids)
                    listing["snapshot_note"] = (
                        f"직원 실명이 담긴 문서 {len(withheld_ids)}건은 배포 스냅샷에서 제외했습니다. "
                        "백엔드에 직접 연결하면 전부 보입니다."
                    )
            print(f"회사자료: 조직 {len(org_ids)}곳 · 문서 {doc_total}건 (열람 전용) · 실명으로 제외 {withheld_total}건")

    # 정화: 담당자 이메일·전화 마스킹 (경로 키는 그대로 둔다 — 프론트 lookup 키다).
    clean = sanitize(snapshot)

    # 누출 검사: 실제 회사자료 흔적 + 연락처 패턴 + API 키 값. 하나라도 걸리면 저장하지 않는다.
    reasons = find_leaks(clean, include_company=include_company)
    if reasons:
        print(f"스냅샷에 남으면 안 되는 내용이 있어 저장하지 않습니다: {reasons}", file=sys.stderr)
        return 2
    clean[META_KEY] = {
        "sanitized": True,
        "contact_masked": True,
        "person_names_removed": True,
        "company_data_included": include_company,
        "note": (
            "사내 배포용 스냅샷. 실제 회사자료(조직·문서·근거)가 들어 있으므로 로그인 게이트 없이 공개하지 말 것."
            if include_company
            else "공개 데모용 스냅샷. 담당자 이메일·전화는 마스킹, 실제 회사자료(internal 범위)는 담지 않는다."
        ),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(clean, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    size = OUT.stat().st_size / 1024
    try:
        shown = OUT.relative_to(Path.cwd())
    except ValueError:
        shown = OUT
    checked = ", ".join(sorted(api_key_values())) or "없음(설정 미확인)"
    print(f"\n{shown} — 경로 {len(clean) - 1}개, {size:.0f} KB")
    print(f"API 키 노출 검사 통과: {checked}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
