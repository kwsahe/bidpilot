"""E. 공개 데모 산출물에 실제 회사자료가 섞이지 않는다 — 스냅샷 스크립트 경로·Git 추적·공개 결과 파일 회귀 검사."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_SCRIPT = REPO_ROOT / "scripts" / "snapshot_demo_api.py"
SNAPSHOT_FILE = REPO_ROOT / "frontend" / "src" / "data" / "demo-snapshot.json"


def _snapshot_module():
    spec = importlib.util.spec_from_file_location("snapshot_demo_api", SNAPSHOT_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_snapshot_script_only_reads_public_demo_scope() -> None:
    mod = _snapshot_module()
    for path in mod.PER_NOTICE:
        if any(path.startswith(p) for p in ("/api/proposal", "/api/eligibility", "/api/review", "/api/auditor")):
            assert "evidence_scope=public_demo" in path, path
    forbidden = mod.FORBIDDEN_PREFIXES
    assert "/api/company" in forbidden and "/api/organizations" in forbidden
    for path in list(mod.LIST_PATHS) + list(mod.PER_NOTICE):
        assert not path.startswith(forbidden), path
    assert '"evidence_id": "CD-' in mod.LEAK_NEEDLES


# ---------------------------------------------------------------------------
# 통합 사업기회(나라장터 + 기업마당) 스냅샷 경로
# ---------------------------------------------------------------------------


def test_unified_and_support_paths_stay_in_public_scope() -> None:
    """통합 목록·지원사업 경로도 금지 접두사를 쓰지 않고, 상세는 public_demo 범위로만 뜬다."""
    mod = _snapshot_module()
    forbidden = mod.FORBIDDEN_PREFIXES
    paths = list(mod.UNIFIED_PATHS) + list(mod.SUPPORT_LIST_PATHS) + list(mod.SUPPORT_DETAIL_KEYS)
    for path in paths + [mod.SUPPORT_DETAIL_FETCH]:
        assert not path.startswith(forbidden), path
        assert "evidence_scope=internal" not in path, path
    # 지원사업 상세는 회사 내부 근거를 검색하지 않도록 범위를 못박는다.
    assert "evidence_scope=public_demo" in mod.SUPPORT_DETAIL_FETCH
    # 통합 목록은 근거 검색을 하지 않는다 — 범위 파라미터를 붙이지 않는다.
    for path in mod.UNIFIED_PATHS:
        assert "evidence_scope" not in path, path


def test_company_data_is_opt_in_only() -> None:
    """회사자료는 **명시적으로 켤 때만** 스냅샷에 들어간다 (기본값은 공개 데모 기준)."""
    mod = _snapshot_module()
    # 기본: 조직·회사 API 전부 차단
    assert "/api/organizations".startswith(mod.forbidden_prefixes(False))
    assert "/api/company".startswith(mod.forbidden_prefixes(False))
    # 사내 배포: 조직 API 만 열리고, 레거시 회사 API·원장·파일 내려받기는 계속 막힌다
    opened = mod.forbidden_prefixes(True)
    assert not "/api/organizations".startswith(opened)
    for still_blocked in ("/api/company", "/api/performance-ledger", "/api/exports"):
        assert still_blocked.startswith(opened), still_blocked


def test_company_leak_check_only_relaxes_company_needles() -> None:
    """--include-company 는 회사자료 흔적 검사만 끈다. API 키·연락처 검사는 그대로다."""
    mod = _snapshot_module()
    company = {"/api/organizations/org-x/documents": {"evidence_id": "CD-abc:001", "evidence_scope": "internal"}}
    assert mod.find_leaks(company), "기본값에서는 회사자료 흔적이 걸려야 한다"
    assert not mod.find_leaks(company, include_company=True), "사내 배포에서는 회사자료가 목적이라 통과해야 한다"

    # 연락처는 두 경우 모두 걸린다
    contact = {"/api/support-programs/x": {"program": {"contact": "담당 010-1234-5678"}}}
    assert mod.find_leaks(contact), contact
    assert mod.find_leaks(contact, include_company=True), "연락처 검사는 어떤 경우에도 끄지 않는다"


def test_company_read_paths_cover_the_company_screen() -> None:
    """/company 화면이 읽기로 부르는 경로가 모두 수집 목록에 있어야 배포본에서 화면이 뜬다."""
    mod = _snapshot_module()
    org_paths = set(mod.COMPANY_ORG_PATHS)
    for needed in (
        "/api/organizations",
        "/api/organizations/{org}/profile",
        "/api/organizations/{org}/documents",
        "/api/organizations/{org}/ledger/summary",
    ):
        assert needed in org_paths, needed
    doc_paths = set(mod.COMPANY_DOC_PATHS)
    assert "/api/organizations/{org}/documents/{doc}" in doc_paths
    assert "/api/organizations/{org}/documents/{doc}/usage" in doc_paths


def test_unified_paths_match_frontend_query_shape() -> None:
    """스냅샷 키는 getBusinessOpportunities() 가 만드는 쿼리와 **글자 그대로** 같아야 한다."""
    mod = _snapshot_module()
    paths = mod.UNIFIED_PATHS
    org = mod.DEMO_ORG
    # /radar 가 실제로 보내는 조합 — 출처 3종 × 정렬 3종 × 마감 포함 2종, limit=20 (RadarShell.FETCH_LIMIT).
    # limit 이나 include_closed 가 빠지면 프론트 lookup() 이 무쿼리 키로 되돌아가
    # **필터·정렬이 먹지 않은** 목록을 보여준다 (404 는 아니라서 조용히 틀린다).
    for source in ("", "&source=g2b", "&source=bizinfo"):
        for sort in ("priority", "deadline", "value"):
            for closed in ("", "&include_closed=true"):
                expected = f"/api/business-opportunities?organization_id={org}{source}&sort={sort}&limit=20{closed}"
                assert expected in paths, f"레이더 조합 누락: {expected}"
    # /opportunities 가 실제로 보내는 조합 — 조회 기간 선택기(14/30/60일) × 마감 포함 토글.
    for days in (14, 30, 60):
        for closed in ("", "&include_closed=true"):
            expected = f"/api/business-opportunities?organization_id={org}&days={days}&sort=priority{closed}"
            assert expected in paths, f"목록 조합 누락: {expected}"
    # /opportunities 의 나라장터 목록도 기간별로 부른다 (getProcurements({days})).
    for days in (14, 30, 60):
        assert f"/api/procurements?days={days}" in mod.LIST_PATHS, f"공고 기간 조합 누락: days={days}"
    # 쿼리를 못 맞췄을 때 프론트가 되돌아갈 무쿼리 경로
    assert "/api/business-opportunities" in paths
    # source=all 은 프론트가 생략한다 — 키에 남으면 안 된다
    assert not any("source=all" in p for p in paths), paths
    # 파라미터 순서 (organization_id → source → days → sort → limit → 플래그)
    assert mod.unified_path(source="g2b", days=30, sort="deadline", limit=60, include_closed=True, include_low=True) == (
        f"/api/business-opportunities?organization_id={org}&source=g2b&days=30&sort=deadline&limit=60"
        "&include_closed=true&include_low=true"
    )


def test_support_detail_is_stored_under_frontend_keys() -> None:
    """프론트(getSupportProgram)는 evidence_scope 를 보내지 않는다 — 저장 키에도 없어야 찾는다."""
    mod = _snapshot_module()
    keys = [k.format(id="bizinfo-PBLN_TEST", org=mod.DEMO_ORG) for k in mod.SUPPORT_DETAIL_KEYS]
    assert "/api/support-programs/bizinfo-PBLN_TEST" in keys
    assert f"/api/support-programs/bizinfo-PBLN_TEST?organization_id={mod.DEMO_ORG}" in keys
    for key in keys:
        assert "evidence_scope" not in key, key


# ---------------------------------------------------------------------------
# 정화 (담당자 연락처 마스킹)
# ---------------------------------------------------------------------------


def test_sanitize_masks_contact_and_apply_method() -> None:
    mod = _snapshot_module()
    payload = {
        "program": {
            "contact": "한국산업단지공단 김담당 062-123-4567",
            "apply_method": "온라인 접수 후 sample.person@kicox.or.kr 로 제출, 문의 02-6000-1234",
            "budget": 1050000000,
            "page": 17,
        },
        "attachments": [{"name": "신청서식", "url": "https://example.go.kr/a.hwp"}],
    }
    clean = mod.sanitize(payload)
    program = clean["program"]
    assert "062-123-4567" not in program["contact"]
    assert "김담당" in program["contact"]  # 필드를 지우지 않는다 — 값만 가린다
    assert "@" not in program["apply_method"]
    assert "02-6000-1234" not in program["apply_method"]
    assert "온라인 접수" in program["apply_method"]
    # 숫자는 건드리지 않는다 (예산·페이지)
    assert program["budget"] == 1050000000 and program["page"] == 17
    assert clean["attachments"][0]["url"] == "https://example.go.kr/a.hwp"
    assert mod.find_contact_leaks(clean) == []


def test_sanitize_keeps_identifiers_with_long_digit_runs() -> None:
    """id·코드의 긴 숫자열을 전화번호로 오인해 지우면 /support/{id} 링크가 깨진다."""
    mod = _snapshot_module()
    payload = {
        "id": "bizinfo-PBLN_000000000096203",
        "notice_no": "R26BK01687776-000",
        "next_route": {"path": "/support/bizinfo-PBLN_000000000096203"},
        "raw": "[1^8010169901^정보시스템감리서비스]",
    }
    assert mod.sanitize(payload) == payload
    assert mod.find_contact_leaks(payload) == []


def test_find_contact_leaks_reports_counts_without_values() -> None:
    mod = _snapshot_module()
    reasons = mod.find_contact_leaks({"a": "hong@example.go.kr", "b": ["문의 031-000-0000"]})
    assert reasons, reasons
    joined = " ".join(reasons)
    assert "hong@example.go.kr" not in joined and "031-000-0000" not in joined
    assert "이메일" in joined and "전화번호" in joined


def test_contact_scan_ignores_numeric_values() -> None:
    """예산 같은 숫자는 문자열이 아니므로 전화번호로 오인하지 않는다."""
    mod = _snapshot_module()
    assert mod.find_contact_leaks({"budget": 1050000000, "count": 20}) == []


# ---------------------------------------------------------------------------
# API 키 누출 검사
# ---------------------------------------------------------------------------


def test_find_key_leaks_detects_raw_and_encoded_key() -> None:
    mod = _snapshot_module()
    fake = "FAKE-service-key-1234567890+abcdef=="
    secrets = {"DATA_GO_KR_SERVICE_KEY": fake}
    assert mod.find_key_leaks({"/api/x": {"source_url": f"https://x?serviceKey={fake}"}}, secrets) == [
        "DATA_GO_KR_SERVICE_KEY"
    ]
    encoded = "FAKE-service-key-1234567890%2Babcdef%3D%3D"
    assert mod.find_key_leaks({"/api/x": {"url": f"https://x?serviceKey={encoded}"}}, secrets) == [
        "DATA_GO_KR_SERVICE_KEY"
    ]
    # 키가 들어 있는 경로 키(쿼리스트링)도 잡는다
    assert mod.find_key_leaks({f"/api/x?key={fake}": {}}, secrets) == ["DATA_GO_KR_SERVICE_KEY"]
    assert mod.find_key_leaks({"/api/x": {"title": "AI 교육 운영"}}, secrets) == []
    assert mod.find_key_leaks({"/api/x": {"title": fake}}, {}) == []


def test_api_key_values_never_returns_short_or_missing_keys() -> None:
    mod = _snapshot_module()
    values = mod.api_key_values()
    assert isinstance(values, dict)
    assert set(values).issubset({"BIZINFO_API_KEY", "DATA_GO_KR_SERVICE_KEY"})
    for name, value in values.items():
        assert len(value) >= mod.MIN_SECRET_LEN, name


def test_find_leaks_blocks_company_evidence_and_contacts() -> None:
    mod = _snapshot_module()
    assert mod.find_leaks({"/api/x": {"ok": True}}) == []
    dirty = {"/api/x": {"evidence_id": "CD-0001", "contact": "김담당 062-123-4567"}}
    reasons = mod.find_leaks(dirty)
    assert any("CD-" in r for r in reasons), reasons
    assert any("전화번호" in r for r in reasons), reasons


def test_existing_snapshot_declares_whether_it_carries_company_data() -> None:
    """회사자료가 스냅샷에 들어가려면 **메타에 그렇다고 적혀 있어야** 한다.

    사내 배포용으로 `--include-company` 를 주면 실제 근거가 들어가는 것이 목적이다.
    다만 그 일이 **조용히** 일어나면 안 된다 — 표시가 없는데 회사자료가 있으면 사고다.
    표시가 있으면 로그인 게이트(REQUIRE_AUTH=1)가 반드시 함께 켜져야 한다.
    """
    if not SNAPSHOT_FILE.exists():
        pytest.skip("스냅샷 파일 없음")
    mod = _snapshot_module()
    payload = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    blob = SNAPSHOT_FILE.read_text(encoding="utf-8")
    meta = payload.get(mod.META_KEY)
    declared = bool(isinstance(meta, dict) and meta.get("company_data_included"))

    company_traces = [
        needle
        for needle in ('"evidence_id":"CD-', '"evidence_id": "CD-', '"evidence_scope":"internal"', "원장 연번")
        if needle in blob
    ]
    org_keys = [k for k in payload if k.startswith("/api/organizations")]

    if not declared:
        assert not company_traces, f"표시 없이 회사자료가 들어 있다: {company_traces}"
        assert not org_keys, f"표시 없이 조직 API 가 들어 있다: {org_keys[:3]}"
        return

    # 사내 배포용이라고 표시한 경우: 레거시 회사 API 와 파일 내려받기는 여전히 들어가면 안 된다.
    for k in payload:
        assert not k.startswith("/api/company"), k
        assert not k.startswith("/api/exports"), k
        assert not k.startswith("/api/performance-ledger"), k


def test_snapshot_with_company_data_still_hides_contacts_and_keys() -> None:
    """회사자료를 담더라도 연락처·인증키는 절대 들어가지 않는다."""
    if not SNAPSHOT_FILE.exists():
        pytest.skip("스냅샷 파일 없음")
    mod = _snapshot_module()
    payload = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    texts = list(mod.iter_strings(payload))
    assert sum(len(mod.EMAIL_RE.findall(x)) for x in texts) == 0
    assert sum(len(mod.PHONE_RE.findall(x)) for x in texts) == 0
    assert not mod.find_key_leaks(payload, mod.api_key_values())


# ---------------------------------------------------------------------------
# 직원 실명 (배포 스냅샷에서 제외·마스킹)
# ---------------------------------------------------------------------------


def test_pii_name_list_lives_outside_git() -> None:
    """실명 목록은 **저장소 밖**에서만 읽는다.

    이 스크립트는 Git 에 커밋되므로 이름을 코드에 적으면 검사기가 곧 유출 통로가 된다.
    그래서 (1) 목록 파일이 gitignore 되어 있고 (2) 스크립트 본문에 실명이 없어야 한다.
    """
    mod = _snapshot_module()
    rel = mod.PII_NAMES_FILE.relative_to(REPO_ROOT).as_posix()
    result = subprocess.run(["git", "check-ignore", "-q", rel], cwd=REPO_ROOT, capture_output=True)
    assert result.returncode == 0, f"{rel} 이 gitignore 되어 있지 않다"

    names = mod.pii_names()
    if not names:
        pytest.skip("실명 목록이 비어 있어 대조할 값이 없음")
    source = SNAPSHOT_SCRIPT.read_text(encoding="utf-8")
    # 어떤 이름이 걸렸는지는 출력하지 않는다 — 실패 메시지도 로그에 남는다.
    assert not [n for n in names if n in source], "스크립트 본문에 실명이 하드코딩되어 있다"


def test_person_fields_are_masked_not_dropped() -> None:
    """등록자·승인자·검토자 필드는 값만 가린다. 필드를 지우면 화면의 이력이 비어 버린다."""
    mod = _snapshot_module()
    clean = mod.sanitize(
        {
            "uploaded_by": "홍길동",
            "approved_by": "홍길동",
            "reviewer": "홍길동",
            "title": "ledger_회사_기본",
            "indexed_chunk_count": 12,
        }
    )
    for field in ("uploaded_by", "approved_by", "reviewer"):
        assert clean[field] == mod.PERSON_MASK, field
    # 본문·숫자는 그대로다
    assert clean["title"] == "ledger_회사_기본"
    assert clean["indexed_chunk_count"] == 12
    # 사람이 아닌 기록자는 남긴다 — 사람이 넣었는지 도구가 넣었는지는 화면에서 의미가 있다.
    # (전부 [담당자] 로 가리면 「누가 등록했나」가 무의미해져 이력이 오히려 나빠진다.)
    for actor in ("system:split-tool", "system", "migration"):
        assert mod.sanitize({"created_by": actor})["created_by"] == actor, actor
    assert mod.sanitize({"uploaded_by": None})["uploaded_by"] is None


def test_document_is_withheld_for_body_names_not_metadata_names() -> None:
    """본문에 실명이 있으면 문서를 뺀다. 메타 필드의 실명 때문에 빼지는 않는다.

    이 구분이 핵심이다. 등록자 필드는 **색인된 문서 전부**에 붙어 있어서,
    그것까지 제외 사유로 삼으면 근거가 통째로 사라져 분석 화면이 빈다.
    """
    mod = _snapshot_module()
    names = ("홍길동",)
    metadata_only = {
        "file_name": "ledger.md",
        "uploaded_by": "홍길동",
        "metadata": {"approved_by": "홍길동"},
        "candidates": [{"source_text": "AI 교육 20회 운영", "reviewer": "홍길동"}],
    }
    assert mod.document_person_names(metadata_only, names) == []

    body = {
        "file_name": "r_and_r.md",
        "uploaded_by": "system:split-tool",
        "candidates": [{"source_text": "담당: 홍길동 중심, 협업 진행"}],
    }
    assert mod.document_person_names(body, names) == ["홍길동"]


def test_person_title_backstop_catches_unlisted_names() -> None:
    """목록에 없는 직원도 「성씨+직급」 모양이면 잡는다 — 목록은 언제나 불완전하다."""
    mod = _snapshot_module()
    doc = {"candidates": [{"source_text": "전략은 임꺽정 본부장이 총괄하고 전우치 팀장은 운영을 맡는다."}]}
    # names 를 비워 두어도 구조적 규칙만으로 잡혀야 한다
    assert mod.document_person_names(doc, ()) == ["임꺽정", "전우치"]


def test_person_title_backstop_does_not_flag_common_nouns() -> None:
    """「기업 대표」 같은 흔한 표현 때문에 멀쩡한 근거 문서를 빼면 안 된다."""
    mod = _snapshot_module()
    doc = {"candidates": [{"source_text": "대상: 기업 대표·임원·HR·팀리더. 교육 담당 부서와 협의."}]}
    assert mod.document_person_names(doc, ()) == []
    # 직급을 더 긴 낱말로 만드는 글자가 붙으면 이름이 아니다
    longer = {"candidates": [{"source_text": "대표성 있는 표본을 뽑고 담당업무를 나눈다."}]}
    assert mod.document_person_names(longer, ()) == []


def test_find_name_leaks_reports_location_without_the_name() -> None:
    """검사 결과 문자열은 화면·CI 로그에 찍힌다 — 거기에 실명이 들어가면 검사기가 유출 통로다."""
    mod = _snapshot_module()
    dirty = {"/api/organizations/org-x/documents/CD-1": {"candidates": [{"source_text": "홍길동 대표"}]}}
    reasons = mod.find_name_leaks(dirty, ("홍길동",))
    assert reasons, reasons
    joined = " ".join(reasons)
    assert "홍길동" not in joined, "사유 문자열에 실명이 들어가면 안 된다"
    assert "/api/organizations/org-x/documents/CD-1" in joined  # 고칠 위치는 알려 준다
    assert mod.find_name_leaks({"/api/x": {"uploaded_by": mod.PERSON_MASK}}, ("홍길동",)) == []
    assert mod.find_name_leaks({"/api/x": {"a": "홍길동"}}, ()) == []  # 목록이 없으면 검사하지 않는다


def test_name_check_runs_even_when_company_data_is_included() -> None:
    """회사자료를 담는 사내 배포본이라도 **개인정보는** 담지 않는다.

    `--include-company` 는 근거 문단을 담기 위한 것이지 실명을 담기 위한 것이 아니다.
    """
    mod = _snapshot_module()
    names = mod.pii_names()
    if not names:
        pytest.skip("실명 목록이 비어 있어 검사할 값이 없음")
    payload = {"/api/organizations/org-x/documents/CD-1": {"candidates": [{"source_text": names[0]}]}}
    assert mod.find_leaks(payload, include_company=True), "사내 배포본에서도 실명은 걸려야 한다"


def test_company_snapshot_aborts_when_the_name_list_is_missing(monkeypatch, tmp_path, capsys) -> None:
    """실명 목록이 없으면 「깨끗함」이 아니라 「검사 불가」다 — 조용히 통과하면 안 된다.

    목록은 gitignore 된 곳에만 있으므로 새로 clone 한 기계·CI 에는 없다.
    그대로 진행하면 검사가 통과한 것처럼 보이면서 실명이 그대로 실린다(fail-open).
    """
    mod = _snapshot_module()
    monkeypatch.delenv(mod.PII_NAMES_ENV, raising=False)
    monkeypatch.setattr(mod, "PII_NAMES_FILE", tmp_path / "없는파일.txt")
    assert mod.pii_names() == ()

    assert mod.main(["--include-company"]) == 2
    err = capsys.readouterr().err
    assert "검사를 할 수 없습니다" in err
    # 중단 사유만 알리고 이름은 어디에도 찍지 않는다
    assert mod.PII_NAMES_ENV in err


def test_existing_snapshot_has_no_employee_names() -> None:
    """커밋된 스냅샷에 직원 실명이 없다 (이름은 출력하지 않는다)."""
    if not SNAPSHOT_FILE.exists():
        pytest.skip("스냅샷 파일 없음")
    mod = _snapshot_module()
    names = mod.pii_names()
    if not names:
        pytest.skip("실명 목록이 비어 있어 검사할 값이 없음")
    payload = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    reasons = mod.find_name_leaks(payload, names)
    assert reasons == [], f"{reasons} — scripts/snapshot_demo_api.py 를 다시 실행할 것"


def test_snapshot_documents_listing_stays_consistent_after_withholding() -> None:
    """문서를 빼면 목록·건수도 함께 줄어야 한다. 목록에만 남으면 눌렀을 때 404 가 난다."""
    if not SNAPSHOT_FILE.exists():
        pytest.skip("스냅샷 파일 없음")
    mod = _snapshot_module()
    payload = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    meta = payload.get(mod.META_KEY)
    if not (isinstance(meta, dict) and meta.get("company_data_included")):
        pytest.skip("회사자료가 없는 스냅샷")

    for key, listing in payload.items():
        if not (key.startswith("/api/organizations/") and key.endswith("/documents")):
            continue
        documents = listing.get("documents") or []
        # 목록에 있는 문서는 상세도 있어야 한다
        for doc in documents:
            detail_key = f"{key}/{doc['id']}"
            assert detail_key in payload, f"목록에는 있는데 상세가 없다: {detail_key}"
        # 건수는 실제 목록과 맞아야 한다
        counts = listing.get("counts") or {}
        recomputed: dict[str, int] = {}
        for doc in documents:
            status = str(doc.get("status") or "unknown")
            recomputed[status] = recomputed.get(status, 0) + 1
        assert counts == recomputed, f"{key}: 건수 {counts} 가 목록 {recomputed} 과 다르다"
        # 뺀 문서가 있으면 조용히 사라지지 않고 표시가 남아야 한다
        if listing.get("withheld_count"):
            assert listing.get("snapshot_note"), key


def test_snapshot_org_summary_matches_the_document_listing() -> None:
    """조직 요약의 문서 건수가 실제 목록과 맞아야 한다.

    목록만 줄이고 요약을 그대로 두면 한 응답 묶음 안에서 10건과 14건이 공존한다.
    화면이 지금 그 값을 그리지 않더라도, 서로 어긋나는 응답을 배포본에 담지 않는다.
    """
    if not SNAPSHOT_FILE.exists():
        pytest.skip("스냅샷 파일 없음")
    mod = _snapshot_module()
    payload = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    meta = payload.get(mod.META_KEY)
    if not (isinstance(meta, dict) and meta.get("company_data_included")):
        pytest.skip("회사자료가 없는 스냅샷")

    checked = 0
    for key, listing in payload.items():
        if not (key.startswith("/api/organizations/") and key.endswith("/documents")):
            continue
        org_id = key[len("/api/organizations/") : -len("/documents")]
        actual = len(listing.get("documents") or [])
        summary = payload.get(f"/api/organizations/{org_id}")
        if isinstance(summary, dict) and isinstance(summary.get("document_count"), int):
            assert summary["document_count"] == actual, f"{org_id}: 요약 {summary['document_count']} vs 목록 {actual}"
            checked += 1
        index = payload.get("/api/organizations")
        for entry in (index or {}).get("organizations") or []:
            organization = entry.get("organization") or {}
            if organization.get("organization_id") == org_id and isinstance(entry.get("document_count"), int):
                assert entry["document_count"] == actual, f"{org_id}(목록): {entry['document_count']} vs {actual}"
                checked += 1
    if not checked:
        pytest.skip("대조할 조직 요약이 없음")


def test_adjust_org_counts_only_subtracts_what_was_removed() -> None:
    """승인된 문서를 뺐을 때만 승인 건수가 줄고, 음수로 내려가지 않는다."""
    mod = _snapshot_module()
    snapshot = {
        "/api/organizations/org-x": {"document_count": 3, "approved_document_count": 1},
        "/api/organizations": {
            "organizations": [{"organization": {"organization_id": "org-x"}, "document_count": 3, "approved_document_count": 1}]
        },
    }
    # 미승인 문서 1건만 뺀다 → 전체만 줄고 승인 건수는 그대로
    mod.adjust_org_counts(snapshot, "org-x", [{"status": "review", "metadata": {"approved": False}}])
    assert snapshot["/api/organizations/org-x"] == {"document_count": 2, "approved_document_count": 1}
    assert snapshot["/api/organizations"]["organizations"][0]["document_count"] == 2
    # 승인된 문서를 빼면 둘 다 줄고, 0 아래로는 내려가지 않는다
    mod.adjust_org_counts(snapshot, "org-x", [{"status": "indexed"}, {"status": "indexed"}])
    assert snapshot["/api/organizations/org-x"] == {"document_count": 0, "approved_document_count": 0}
    # 다른 조직은 건드리지 않는다
    before = json.dumps(snapshot, sort_keys=True)
    mod.adjust_org_counts(snapshot, "org-y", [{"status": "review"}])
    assert json.dumps(snapshot, sort_keys=True) == before


def test_existing_snapshot_has_no_email_addresses() -> None:
    """커밋된 스냅샷에 이메일 주소가 없다 (담당자 이메일은 마스킹된다)."""
    if not SNAPSHOT_FILE.exists():
        pytest.skip("스냅샷 파일 없음")
    mod = _snapshot_module()
    payload = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    hits = sum(len(mod.EMAIL_RE.findall(text)) for text in mod.iter_strings(payload))
    assert hits == 0, f"이메일 패턴 {hits}건 — scripts/snapshot_demo_api.py 를 다시 실행할 것"


def test_existing_snapshot_has_no_phone_numbers_once_sanitized() -> None:
    """정화 표시가 붙은 스냅샷에는 전화번호가 남지 않는다.

    표시가 없으면 정화 도입 이전 산출물이다 — 통합 담당자가 스크립트를 다시 돌려야 한다.
    """
    if not SNAPSHOT_FILE.exists():
        pytest.skip("스냅샷 파일 없음")
    mod = _snapshot_module()
    payload = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    meta = payload.get(mod.META_KEY)
    if not (isinstance(meta, dict) and meta.get("contact_masked")):
        pytest.skip("정화 이전 스냅샷 — scripts/snapshot_demo_api.py 재실행 후 검사된다")
    assert mod.find_contact_leaks(payload) == []


def test_existing_snapshot_has_no_api_key() -> None:
    """설정에 있는 API 키 값이 커밋된 스냅샷에 없다 (값은 출력하지 않는다)."""
    if not SNAPSHOT_FILE.exists():
        pytest.skip("스냅샷 파일 없음")
    mod = _snapshot_module()
    secrets = mod.api_key_values()
    if not secrets:
        pytest.skip("설정에 API 키가 없어 검사할 값이 없음")
    payload = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    assert mod.find_key_leaks(payload, secrets) == []


def test_tracked_public_results_have_no_real_company_chunks() -> None:
    """data/public/proposals 는 Git 에 올라가는 공개 위치 — 회사자료 문단(CD-)이 인용되면 안 된다."""
    proposals = REPO_ROOT / "data" / "public" / "proposals"
    if not proposals.exists():
        pytest.skip("공개 제안서 폴더 없음")
    for path in proposals.glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        sections = payload.get("sections") or [payload]
        for section in sections:
            for sentence in section.get("sentences", []):
                evidence_id = str(sentence.get("evidence_id") or "")
                assert not evidence_id.startswith("CD-"), f"{path.name}: {evidence_id}"
        assert payload.get("evidence_scope") in (None, "public_demo"), path.name


def test_private_store_and_legacy_company_dir_are_gitignored() -> None:
    def ignored(rel: str) -> bool:
        result = subprocess.run(["git", "check-ignore", "-q", rel], cwd=REPO_ROOT, capture_output=True)
        return result.returncode == 0

    assert ignored("data/private/organizations/registry.json")
    assert ignored("data/private/organizations/org-sample/documents.json")
    assert ignored("data/private/organizations/org-demo-company/index/company_index.json")
    assert ignored("data/company/documents.json")
    assert ignored("docs/SampleEdu/x.md")
    # 추적 중인 실제자료가 없다
    tracked = subprocess.run(["git", "ls-files", "data/private", "data/company/uploads", "data/company/candidates", "data/company/index", "docs/SampleEdu"], cwd=REPO_ROOT, capture_output=True, text=True).stdout.strip()
    assert tracked == "", tracked
