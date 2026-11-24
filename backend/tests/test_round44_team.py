"""44차 §2-C — 여러 사람 · 직접 넣기(36차 TEAM-R36-01~06). 호출 없음.

- 회사 프로필 · 사업계획서 일반현황 저장도 처음 읽은 시각을 보내면 그사이 남의 저장에 409(01) · 저장 응답 시각 = 파일 시각.
- 사전규격 번호는 주소에서만 확정 · 본문에서만 맞으면 「같은 공고일 수 있음」(02).
- 공고문 올리기는 고치기 버전 시각을 바꾸지 않는다(04) · 후보함 공고명만 같은 줄은 따로 셈(05) · 제목 열쇠가 [재공고] · 【긴급】을 뗀다(06).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core import storage
from app.core.config import get_settings
from app.main import app
from app.schemas.manual_notice import ManualNoticeInput
from app.schemas.organization import OrganizationProfileUpdate, PlanGeneralUpdate
from app.services import manual_notice_service as manual
from app.services import notice_inbox_service as inbox
from app.services import organization_service, prespec_service

ORG = get_settings().default_organization_id
KST = timezone(timedelta(hours=9))


def _profile(**kw) -> OrganizationProfileUpdate:
    current = organization_service.load_profile(ORG)
    base = {**current.model_dump(include=set(OrganizationProfileUpdate.model_fields) - {"expected_updated_at"}), "updated_by": "대표"}
    base.update(kw)
    return OrganizationProfileUpdate.model_validate(base)


def test_TEAM01_프로필_그사이_남이_바꿨으면_409_응답_시각은_파일_시각() -> None:
    first = organization_service.save_profile(ORG, _profile(preferred_regions=["광주광역시"]))
    assert first.updated_at == organization_service.load_profile(ORG).updated_at  # 응답 시각 = 파일에 찍힌 시각
    organization_service.save_profile(ORG, _profile(preferred_regions=["광주광역시", "전라남도"], expected_updated_at=first.updated_at))
    with pytest.raises(storage.StaleWriteError) as caught:
        organization_service.save_profile(ORG, _profile(updated_by="김담당", preferred_regions=["서울특별시"], expected_updated_at=first.updated_at))
    assert caught.value.by == "대표"
    assert organization_service.load_profile(ORG).preferred_regions == ["광주광역시", "전라남도"]  # 앞 저장이 남는다
    organization_service.save_profile(ORG, _profile())  # 보내지 않는 키트 · 스크립트는 검사하지 않는다


def test_TEAM01_일반현황도_409_그리고_프로필_버전을_바꾸지_않는다() -> None:
    profile = organization_service.save_profile(ORG, _profile())
    first = organization_service.save_plan_general(ORG, PlanGeneralUpdate(updated_by="대표", representative="홍길동"))
    assert first.updated_at == organization_service.load_plan_general(ORG).updated_at
    assert organization_service.load_profile(ORG).updated_at == profile.updated_at  # 두 카드는 버전을 따로 본다
    organization_service.save_plan_general(ORG, PlanGeneralUpdate(updated_by="대표", representative="홍길동", expected_updated_at=first.updated_at))
    with pytest.raises(storage.StaleWriteError):
        organization_service.save_plan_general(ORG, PlanGeneralUpdate(updated_by="김담당", representative="김철수", expected_updated_at=first.updated_at))
    # 프로필 카드의 다음 저장은 일반현황 저장에 막히지 않는다
    organization_service.save_profile(ORG, _profile(expected_updated_at=profile.updated_at))


def test_TEAM01_API_409_꼴() -> None:
    client = TestClient(app)
    current = client.get(f"/api/organizations/{ORG}/profile").json()
    body = {k: current[k] for k in OrganizationProfileUpdate.model_fields if k in current and k != "expected_updated_at"}
    body.update({"updated_by": "대표", "data_class": "real"})
    saved = client.put(f"/api/organizations/{ORG}/profile", json={**body, "expected_updated_at": current["updated_at"]})
    assert saved.status_code == 200
    res = client.put(f"/api/organizations/{ORG}/profile", json={**body, "updated_by": "김담당", "expected_updated_at": current["updated_at"]})
    assert res.status_code == 409 and res.json()["detail"]["code"] == "stale_write"
    plan = client.get(f"/api/organizations/{ORG}/plan-general").json()
    ok = client.put(f"/api/organizations/{ORG}/plan-general", json={"updated_by": "대표", "expected_updated_at": plan["updated_at"]})
    assert ok.status_code == 200
    stale = client.put(f"/api/organizations/{ORG}/plan-general", json={"updated_by": "김담당", "expected_updated_at": plan["updated_at"]})
    assert stale.status_code == 409


def _index(monkeypatch: pytest.MonkeyPatch) -> manual.StoreIndex:
    index = manual.StoreIndex()
    monkeypatch.setattr(index, "prespecs", lambda: {"R26BD00284797"})
    monkeypatch.setattr(index, "g2b", lambda: {})
    monkeypatch.setattr(index, "bizinfo", lambda: set())
    monkeypatch.setattr(index, "titles", lambda: {})
    return index


def test_TEAM02_사전규격_번호는_주소에서만_확정_본문만이면_같은_공고일_수_있음(monkeypatch: pytest.MonkeyPatch) -> None:
    index = _index(monkeypatch)
    body = "본 공고는 사전규격(R26BD00284797) 공개를 거친 본공고입니다."
    assert manual.find_existing("https://www.univ.ac.kr/notice/77", body, index=index) == (None, None)
    found, why = manual.prespec_in_body("https://www.univ.ac.kr/notice/77", body, index=index)
    assert found == f"{prespec_service.ID_PREFIX}R26BD00284797" and "선제준비 칸에 있음" in why and "같은 공고일 수 있음" in why
    # 주소에 있으면 그대로 확정
    sure, _ = manual.find_existing("https://www.g2b.go.kr/x?bfSpecRgstNo=R26BD00284797", None, index=index)
    assert sure == f"{prespec_service.ID_PREFIX}R26BD00284797"


def _manual_input(**kw) -> ManualNoticeInput:
    base = dict(url="https://www.univ.ac.kr/notice/77", title="AI 교육 운영 수행기관 모집", agency="시험대학",
                deadline=datetime(2026, 11, 30, 16, 0, tzinfo=KST), recruit="operator", methods=["이메일"])
    base.update(kw)
    return ManualNoticeInput(**base)


def test_TEAM02_본문만_맞으면_그래도_새로_넣기로_넘긴다(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(manual, "prespec_in_body", lambda url, body, index=None: ("g2bpre-R26BD00284797", "본문에 … 같은 공고일 수 있음"))
    monkeypatch.setattr(manual, "find_existing", lambda url, body=None, index=None: (None, None))
    first = manual.create(ORG, _manual_input(url="https://www.univ.ac.kr/notice/7801", body_text="사전규격 R26BD00284797"))
    assert first.maybe_duplicate and first.notice is None
    saved = manual.create(ORG, _manual_input(url="https://www.univ.ac.kr/notice/7801", body_text="사전규격 R26BD00284797", confirm_new=True))
    assert saved.notice is not None


def test_TEAM04_공고문_올리기는_고치기_버전_시각을_바꾸지_않는다() -> None:
    notice = manual.create(ORG, _manual_input(url="https://www.univ.ac.kr/notice/7804")).notice
    assert notice is not None
    docx = __import__("docx").Document()
    docx.add_paragraph("1. 참가자격: 소프트웨어사업자로 등록한 업체")
    import io

    buffer = io.BytesIO()
    docx.save(buffer)
    after = manual.attach_document(ORG, notice.id, file_name="공고문.docx", payload=buffer.getvalue())
    assert after.updated_at == notice.updated_at and after.document is not None and after.document.uploaded_at is not None
    # 열린 고치기 폼(처음 읽은 시각 = 넣은 시각)이 올리기 뒤에도 저장된다
    manual.update(ORG, notice.id, _manual_input(url="https://www.univ.ac.kr/notice/7804", agency="시험대학교"), updated_by="김담당",
                  expected_updated_at=notice.updated_at)


def test_TEAM05_후보함_공고명만_같은_줄은_따로_세고_정식으로_넣기를_남긴다(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inbox, "path_of", lambda organization_id: tmp_path / "inbox.json")
    monkeypatch.setattr(manual, "find_existing", lambda url, body=None, index=None: (None, None))
    monkeypatch.setattr(manual, "similar_existing", lambda title, index=None: ("g2b-R26BK01780000-000", "같은 공고일 수 있음"))
    result = inbox.paste("org-x", "공고 [AI 교육 운영 위탁](https://a.go.kr/1)")
    entry = result.entries[0]
    assert entry.existing_id is None and entry.maybe_existing_id == "g2b-R26BK01780000-000"
    assert result.existing == 0 and result.maybe_existing == 1


@pytest.mark.parametrize("title", ["[재공고] 2027년 AI 교육 운영", "【긴급】 AI 교육 운영", "재공고 2027년 AI 교육 운영", "AI 교육 운영(재공고)", "긴급 AI 교육 운영"])
def test_TEAM06_제목_열쇠는_재공고_긴급_괄호와_낱말을_뗀다(title: str) -> None:
    assert prespec_service.title_key(title) == prespec_service.title_key("AI 교육 운영")
