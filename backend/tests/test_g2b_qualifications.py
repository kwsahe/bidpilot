"""나라장터 **자격 제한** 수집 (0921.md §4-A-1).

## 왜 필요한가

담당자가 물었다 — 「우리가 넣을 수 있는 게 1건밖에 없나?」 6차에서 수집을 고쳐 마감 전
후보 102건을 보게 됐지만, 그중 **어느 것에 실제로 넣을 수 있는지**는 여전히 알 수 없었다.
자격 제한(면허·참가가능지역)이 목록 응답에 없기 때문이다. 검수자가 손으로 조사한 기준
답안(`docs/reports/2026-09-20_apply_candidates.md`)은 개발 공고 15건 중 **9건이
소프트웨어사업자(1468) 등록 업체만** 투찰할 수 있다고 적었다. 그 사실을 앱이 알아야 한다.

## 8차에서 바뀐 것 (0922 §4-A · ISSUE-081)

7차는 창(30일)을 통째로 뒤에서부터 받으려 했다. 창에 35,000행이 있어 예산으로는 끝 페이지
몇 장이 전부였고, 거기에는 물품·공사만 있어 **「이 API 는 용역을 주지 않는다」는 틀린 결론**이
나왔다. 창을 **하루로** 좁히면 1,500~1,850행이라 2페이지로 끝나고 용역 공고의 업종 코드가
그대로 온다. 그래서 수집 단위가 「창」에서 **「날」**로 바뀌었고, 받은 날은
`qualification_store` 에 남아 다시 부르지 않는다.

## 여기서 지키는 약속 넷

1. **공고번호+차수로 합친다.** 두 오퍼레이션 다 공고번호로 콕 집어 물을 수 없어
   (`inqryDiv=2` 는 「필수값 입력 에러」) 같은 **하루 창**으로 받아 묶는다.
2. **「미확인」과 「제한 없음」은 다른 사실이다.** 받아 본 적이 없으면 `None`,
   받았는데 제한이 없으면 `[]`. 빈 목록을 「제한 없음」으로 읽으면 참가할 수 없는 공고를
   참가 가능으로 보여 주게 된다.
3. **자격 조회가 실패해도 목록 수집을 죽이지 않는다.** 대신 사유를 들고 나간다.
4. **호출 예산을 목록과 나눈다.** 같은 예산을 쓰면 목록 페이지가 밀려 공고를 놓친다 —
   ISSUE-072 가 그렇게 생겼다.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import pytest

from app.services import g2b_client, g2b_mapper, procurement_service, qualification_store

NOW = datetime(2026, 9, 17, 3, 0, tzinfo=timezone.utc)

#: conftest 의 autouse 픽스처가 `fetch_qualifications_for_day` 를 「받지 않음」으로 바꿔 둔다.
#: 수집기 자체를 재는 테스트는 진짜 함수를 되돌려 놓아야 한다.
_REAL_FETCH_DAY = g2b_client.fetch_qualifications_for_day


@pytest.fixture()
def real_collector(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(g2b_client, "fetch_qualifications_for_day", _REAL_FETCH_DAY)


def license_item(no: str, order: str = "000", *, name: str, allowed: Any = None) -> dict[str, Any]:
    return {
        "bidNtceNo": no,
        "bidNtceOrd": order,
        "lmtGrpNo": "1",
        "lmtSno": "1",
        "lcnsLmtNm": name,
        "permsnIndstrytyList": allowed,
    }


def region_item(no: str, order: str = "000", *, region: str) -> dict[str, Any]:
    return {"bidNtceNo": no, "bidNtceOrd": order, "lmtSno": "1", "prtcptPsblRgnNm": region, "bsnsDivNm": "용역"}


def notice_item(no: str, order: str = "000", *, title: str = "AI 교육 운영") -> dict[str, Any]:
    return {
        "bidNtceNo": no,
        "bidNtceOrd": order,
        "bidNtceNm": title,
        "bidNtceDt": "2026-09-10 10:00:00",
        "ntceInsttNm": "시험기관",
    }


# ---------------------------------------------------------------------------
# 값을 푸는 규칙
# ---------------------------------------------------------------------------


def test_면허제한_이름_끝의_업종코드를_따로_뽑는다() -> None:
    """실제 값은 「소프트웨어사업자(컴퓨터관련서비스사업)/1468」 처럼 온다 (0921 §2).

    코드를 문자열 안에 둔 채로 두면 회사 등록 업종과 대조할 수 없다.
    """
    [row] = g2b_mapper.license_limits_of(
        [license_item("R1", name="소프트웨어사업자(컴퓨터관련서비스사업)/1468")]
    )
    assert row["code"] == "1468"
    assert row["name"] == "소프트웨어사업자(컴퓨터관련서비스사업)"


def test_코드가_없으면_지어내지_않는다() -> None:
    [row] = g2b_mapper.license_limits_of([license_item("R1", name="엔지니어링사업자")])
    assert row["code"] is None
    assert row["name"] == "엔지니어링사업자"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("1468, 1426", ["1468", "1426"]),
        ("1468\n1426", ["1468", "1426"]),
        (["1468", "1426"], ["1468", "1426"]),
        ([{"indstrytyCd": "1468"}], ["1468"]),
        ("", []),
        (None, []),
    ],
)
def test_허용_업종_목록은_어떤_모양으로_와도_읽는다(raw: Any, expected: list[str]) -> None:
    """응답 모양을 한 가지로 단정하지 않는다 — 모르면 버리지 말고 남긴다."""
    [row] = g2b_mapper.license_limits_of([license_item("R1", name="소프트웨어사업자/1468", allowed=raw)])
    assert row["allowed_industries"] == expected


def test_참가가능지역은_중복을_접되_순서를_지킨다() -> None:
    names = g2b_mapper.allowed_regions_of(
        [region_item("R1", region="대구광역시"), region_item("R1", region="대구광역시"), region_item("R1", region="광주광역시")]
    )
    assert names == ["대구광역시", "광주광역시"]


# ---------------------------------------------------------------------------
# 「미확인」과 「제한 없음」
# ---------------------------------------------------------------------------


def test_받아_본_적이_없으면_빈_목록이_아니라_미확인이다() -> None:
    """빈 목록은 「제한이 없다」는 뜻이다. 참가할 수 없는 공고를 참가 가능으로 보여 주면 안 된다."""
    notice = g2b_mapper.map_notice(notice_item("R1"))
    assert notice is not None
    assert notice.raw_data["license_limits"] is None
    assert notice.raw_data["allowed_regions"] is None


def test_받았는데_제한이_없으면_빈_목록이다() -> None:
    notice = g2b_mapper.map_notice(notice_item("R1"), license_limits=[], allowed_regions=[])
    assert notice is not None
    assert notice.raw_data["license_limits"] == []
    assert notice.raw_data["allowed_regions"] == []


def test_확인_시각을_공고에_적는다() -> None:
    """「미확인」과 「확인함」을 화면이 구분해 적을 수 있어야 한다 (0922 §4-A-2)."""
    stamp = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
    notice = g2b_mapper.map_notice(
        notice_item("R1"), license_limits=[], allowed_regions=[], qualification_checked_at=stamp
    )
    assert notice is not None
    assert notice.raw_data["qualification_checked_at"] == stamp.isoformat()
    assert g2b_mapper.map_notice(notice_item("R1")).raw_data["qualification_checked_at"] is None


def test_공고번호와_차수로_붙인다() -> None:
    """차수가 다르면 다른 공고다. 상세 화면도 차수를 붙여야 열린다 (0921 §2)."""
    day = date(2026, 9, 10)
    record = qualification_store.DayRecord(
        day=day,
        fetched_at=datetime(2026, 9, 17, tzinfo=timezone.utc),
        licenses={"R1-000": [{"name": "소프트웨어사업자", "code": "1468", "allowed_industries": []}]},
        regions={"R1-001": ["광주광역시"]},
    )
    coverage = qualification_store.Coverage(records={day: record})
    notices = g2b_mapper.map_notices(
        [notice_item("R1", "000"), notice_item("R1", "001")], qualifications=coverage
    )
    by_id = {n.id: n for n in notices}
    assert by_id["g2b-R1-000"].raw_data["license_limits"][0]["code"] == "1468"
    assert by_id["g2b-R1-000"].raw_data["allowed_regions"] == []
    assert by_id["g2b-R1-001"].raw_data["allowed_regions"] == ["광주광역시"]
    assert by_id["g2b-R1-001"].raw_data["license_limits"] == []


def test_안_받은_날의_공고는_미확인으로_남는다() -> None:
    """받지 않은 날을 「제한 없음」이라고 적으면 참가할 수 없는 공고를 참가 가능으로 보여 준다."""
    day = date(2026, 9, 10)
    coverage = qualification_store.Coverage(
        records={
            day: qualification_store.DayRecord(
                day=day,
                fetched_at=datetime(2026, 9, 17, tzinfo=timezone.utc),
                licenses={"R1-000": [{"name": "소프트웨어사업자", "code": "1468", "allowed_industries": []}]},
                regions={},
            )
        }
    )
    notices = g2b_mapper.map_notices(
        [
            notice_item("R1", "000"),
            notice_item("R2", "000") | {"bidNtceDt": "2026-09-08 10:00:00"},
        ],
        qualifications=coverage,
    )
    by_id = {n.id: n for n in notices}
    assert by_id["g2b-R1-000"].raw_data["license_limits"][0]["code"] == "1468"
    assert by_id["g2b-R2-000"].raw_data["license_limits"] is None
    assert by_id["g2b-R2-000"].raw_data["qualification_checked_at"] is None


# ---------------------------------------------------------------------------
# 지금까지 아무도 안 읽던 필드들
# ---------------------------------------------------------------------------


def test_자격_판정에_쓸_필드를_편의_키로_올린다() -> None:
    """`arsltCmptYn`·`cmmnSpldmdMethdNm`·`sucsfbidMthdNm`·`techAbltEvlRt`·`pubPrcrmntClsfcNm` 는
    113개 필드짜리 원본 item 안에만 있어 저장소 어디서도 참조하지 않았다."""
    item = notice_item("R1") | {
        "arsltCmptYn": "Y",
        "cmmnSpldmdMethdNm": "공동이행",
        "sucsfbidMthdNm": "협상에의한계약",
        "techAbltEvlRt": "90",
        "pubPrcrmntClsfcNm": "정보시스템개발서비스",
    }
    notice = g2b_mapper.map_notice(item)
    assert notice is not None
    raw = notice.raw_data
    assert raw["result_evaluation"] == "Y"
    assert raw["joint_supply_method"] == "공동이행"
    assert raw["award_method"] == "협상에의한계약"
    assert raw["tech_ability_rate"] == "90"
    assert raw["procurement_class"] == "정보시스템개발서비스"


# ---------------------------------------------------------------------------
# 하루 창 수집기 (0922 §4-A-1)
# ---------------------------------------------------------------------------


def fake_day_pages(pages: dict[str, list[list[dict[str, Any]]]], *, total: dict[str, int] | None = None):
    """오퍼레이션별 페이지 목록을 돌려주는 가짜. 호출 (오퍼레이션, 페이지)를 센다."""
    calls: list[tuple[str, int]] = []

    async def _fetch(operation: str, *, begin=None, end=None, page_no: int = 1, num_rows: int = 999):
        calls.append((operation, page_no))
        sheets = pages.get(operation, [])
        items = sheets[page_no - 1] if page_no <= len(sheets) else []
        count = (total or {}).get(operation)
        if count is None:
            count = sum(len(sheet) for sheet in sheets)
        return items, count

    return _fetch, calls


def test_하루치는_두_오퍼레이션_각_한_페이지면_끝난다(real_collector: None, monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    fetch, calls = fake_day_pages(
        {
            g2b_client.OP_LICENSE_LIMIT: [[license_item("R1", name="소프트웨어사업자/1468")]],
            g2b_client.OP_PARTICIPATION_REGION: [[region_item("R1", region="광주광역시")]],
        }
    )
    monkeypatch.setattr(g2b_client, "fetch_qualification_page", fetch)

    outcome = asyncio.run(g2b_client.fetch_qualifications_for_day(date(2026, 9, 17)))
    assert outcome.complete is True
    assert outcome.calls == len(calls) == 2
    assert outcome.licenses["R1-000"][0]["lcnsLmtNm"].endswith("1468")
    assert outcome.regions["R1-000"][0]["prtcptPsblRgnNm"] == "광주광역시"


def test_하루_창은_00시부터_23시59분까지다() -> None:
    begin, end = g2b_client.day_window(date(2026, 9, 17))
    assert g2b_client.format_inquiry_dt(begin) == "202609170000"
    assert g2b_client.format_inquiry_dt(end) == "202609172359"


def test_두_페이지가_필요하면_두_번_부른다(real_collector: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """실측: 하루 1,500~1,850행이라 999건씩 2페이지다 (2026-09-22 재검증 §2-1)."""
    import asyncio

    full = [license_item(f"R{i}", name="소프트웨어사업자/1468") for i in range(999)]
    rest = [license_item("R999", name="소프트웨어사업자/1468")]
    fetch, calls = fake_day_pages(
        {
            g2b_client.OP_LICENSE_LIMIT: [full, rest],
            g2b_client.OP_PARTICIPATION_REGION: [[region_item("R1", region="광주광역시")]],
        },
        total={g2b_client.OP_LICENSE_LIMIT: 1000, g2b_client.OP_PARTICIPATION_REGION: 1},
    )
    monkeypatch.setattr(g2b_client, "fetch_qualification_page", fetch)

    outcome = asyncio.run(g2b_client.fetch_qualifications_for_day(date(2026, 9, 17)))
    assert outcome.complete is True
    assert [op for op, _ in calls].count(g2b_client.OP_LICENSE_LIMIT) == 2
    assert outcome.license_rows == 1000


def test_한쪽이_실패하면_그_날은_미확인이고_사유를_남긴다(real_collector: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """조용히 빈 목록을 돌려주면 다음 사람이 「제한이 없는 공고」로 읽는다."""
    import asyncio

    async def _fetch(operation: str, **_kwargs: object):
        if operation == g2b_client.OP_PARTICIPATION_REGION:
            raise g2b_client.G2BClientError("시험 실패")
        return [license_item("R1", name="소프트웨어사업자/1468")], 1

    monkeypatch.setattr(g2b_client, "fetch_qualification_page", _fetch)

    outcome = asyncio.run(g2b_client.fetch_qualifications_for_day(date(2026, 9, 17)))
    assert outcome.complete is False
    assert outcome.note and "참가가능지역" in outcome.note
    # 받은 것은 버리지 않는다.
    assert outcome.licenses["R1-000"]


def test_호출_예산을_목록과_나눈다() -> None:
    """같은 예산을 쓰면 목록 페이지가 밀려 공고를 놓친다 — ISSUE-072 가 그렇게 생겼다."""
    assert g2b_client.MAX_QUALIFICATION_CALLS > 0
    assert g2b_client.MAX_QUALIFICATION_CALLS != g2b_client.MAX_COLLECT_CALLS


# ---------------------------------------------------------------------------
# 저장소 (0922 §4-A-2)
# ---------------------------------------------------------------------------


def test_받은_날은_다시_부르지_않는다(monkeypatch: pytest.MonkeyPatch) -> None:
    """백필이 한 번으로 끝나는 근거다. 매번 다시 부르면 호출 예산이 날마다 사라진다."""
    import asyncio

    day = date(2026, 9, 10)
    qualification_store.save_day(
        day,
        licenses={"R1-000": [{"name": "소프트웨어사업자", "code": "1468", "allowed_industries": []}]},
        regions={},
        fetched_at=datetime(2026, 9, 17, tzinfo=timezone.utc),
    )
    assert day in qualification_store.known_days()

    called: list[date] = []

    async def _fetch(target: date, **_kwargs: object):
        called.append(target)
        raise AssertionError("이미 받은 날을 다시 불렀다")

    monkeypatch.setattr(g2b_client, "fetch_qualifications_for_day", _fetch)
    monkeypatch.setattr(procurement_service, "live_fetch_enabled", lambda: True)

    calls, fetched, note = asyncio.run(procurement_service._ensure_qualification_days([day]))
    assert (calls, fetched, note) == (0, 0, None)
    assert called == []


def test_덜_받은_날은_저장하지_않는다(monkeypatch: pytest.MonkeyPatch) -> None:
    """저장하면 다음부터 「받은 날」이 되어 빠진 공고가 영영 「제한 없음」으로 굳는다."""
    import asyncio

    day = date(2026, 9, 11)

    async def _fetch(target: date, **_kwargs: object):
        return g2b_client.DayQualifications(
            day=target, licenses={}, regions={}, calls=2, complete=False, note="시험 실패"
        )

    monkeypatch.setattr(g2b_client, "fetch_qualifications_for_day", _fetch)
    monkeypatch.setattr(procurement_service, "live_fetch_enabled", lambda: True)

    calls, fetched, note = asyncio.run(procurement_service._ensure_qualification_days([day]))
    assert (calls, fetched) == (2, 0)
    assert note and "시험 실패" in note
    assert day not in qualification_store.known_days()


def test_저장소를_돌아_나오면_정규_형태다(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    day = date(2026, 9, 12)

    async def _fetch(target: date, **_kwargs: object):
        return g2b_client.DayQualifications(
            day=target,
            licenses={"R1-000": [license_item("R1", name="소프트웨어사업자(컴퓨터관련서비스사업)/1468")]},
            regions={"R2-000": [region_item("R2", region="경상남도")]},
            calls=4,
            complete=True,
            license_rows=1,
            region_rows=1,
        )

    monkeypatch.setattr(g2b_client, "fetch_qualifications_for_day", _fetch)
    monkeypatch.setattr(procurement_service, "live_fetch_enabled", lambda: True)

    calls, fetched, note = asyncio.run(procurement_service._ensure_qualification_days([day]))
    assert (calls, fetched, note) == (4, 1, None)
    record = qualification_store.load_day(day)
    assert record is not None
    # 저장은 **판정이 읽는 것만** 남긴다 — 정의표를 접으면서 lmtGrpNo·lmtSno 는 뺀다.
    assert record.license_limits("R1-000")[0] == {
        "name": "소프트웨어사업자(컴퓨터관련서비스사업)",
        "code": "1468",
        "allowed_industries": [],
    }
    assert record.allowed_regions("R2-000") == ["경상남도"]
    # 받은 날의 다른 공고는 「제한 없음」이다 — 「미확인」이 아니다.
    assert record.license_limits("R9-000") == []


def test_후보_게시일만_받는다() -> None:
    """창 전체(30일)를 통째로 받지 않는다. 후보가 없는 날은 부를 이유가 없다 (0922 §4-A-3)."""
    days = procurement_service._publish_days(
        [
            notice_item("R1") | {"bidNtceDt": "2026-09-10 10:00:00"},
            notice_item("R2") | {"bidNtceDt": "2026-09-10 18:00:00"},
            notice_item("R3") | {"bidNtceDt": "2026-09-17 09:00:00"},
        ]
    )
    assert days == [date(2026, 9, 10), date(2026, 9, 17)]


def test_자격_조회가_실패해도_목록_수집은_산다(monkeypatch: pytest.MonkeyPatch) -> None:
    """자격 정보가 없다고 공고 목록을 통째로 잃으면 안 된다."""
    import asyncio

    async def _collect(**_kwargs: object):
        return g2b_client.CollectOutcome(
            items=[notice_item("R1")], calls=1, method="시험 수집", keyword_totals={}, truncated=()
        )

    async def _fetch(target: date, **_kwargs: object):
        return g2b_client.DayQualifications(
            day=target, licenses={}, regions={}, calls=2, complete=False, note="면허제한 1페이지 실패: 시험"
        )

    monkeypatch.setattr(g2b_client, "collect_notices", _collect)
    monkeypatch.setattr(g2b_client, "fetch_qualifications_for_day", _fetch)
    monkeypatch.setattr(procurement_service, "live_fetch_enabled", lambda: True)

    collected = asyncio.run(procurement_service.collect_candidates(days=30))
    assert len(collected.notices) == 1
    assert collected.qualification_covered is False
    assert collected.qualification_note and "면허제한" in collected.qualification_note
    # 자격 호출도 「몇 번 불렀는가」에 합쳐진다 — 화면 숫자가 거짓말이 되지 않게.
    assert collected.calls == 3
    assert collected.notices[0].raw_data["license_limits"] is None


def test_받았으면_수집_방식_문구에_적는다(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    async def _collect(**_kwargs: object):
        return g2b_client.CollectOutcome(
            items=[notice_item("R1")], calls=1, method="공고명 키워드 10개 · 마감 제외 · 최근 30일",
            keyword_totals={}, truncated=()
        )

    async def _fetch(target: date, **_kwargs: object):
        return g2b_client.DayQualifications(
            day=target,
            licenses={"R1-000": [license_item("R1", name="소프트웨어사업자/1468")]},
            regions={"R1-000": [region_item("R1", region="광주광역시")]},
            calls=4,
            complete=True,
        )

    monkeypatch.setattr(g2b_client, "collect_notices", _collect)
    monkeypatch.setattr(g2b_client, "fetch_qualifications_for_day", _fetch)
    monkeypatch.setattr(procurement_service, "live_fetch_enabled", lambda: True)

    collected = asyncio.run(procurement_service.collect_candidates(days=30))
    # **건수를 문구에 넣지 않는다.** `collected_by`/`_note` 는 캐시 비교에서 「달라졌는가」를
    # 가리는 키라, 건수를 끼워 넣으면 목록을 읽을 때마다 한 건 차이로 1.5MB 파일이 다시
    # 쓰인다 (ISSUE-038 과 같은 함정). 건수는 `Collected.qualification_*` 로 따로 들고 간다.
    assert collected.method.endswith("자격 제한 포함")
    assert not any(ch.isdigit() for ch in collected.method.split("자격 제한")[1])
    assert collected.notices[0].raw_data["license_limits"][0]["code"] == "1468"
    assert collected.qualification_days_fetched == 1
    assert collected.qualification_days_known == 1


# ---------------------------------------------------------------------------
# 33차 §3-A-1 — 그날 안에 받은 하루치는 반쪽이다(절차서 A · 9-29 15:47 파일)
# ---------------------------------------------------------------------------


def test_그날_안에_받은_하루치는_다시_받는다(monkeypatch: pytest.MonkeyPatch) -> None:
    """9-29 15:47 에 받은 9-29 파일은 그 뒤 올라온 공고가 없다 — 「받은 날」로 굳히지 않고 다음 수집에서 다시 받는다."""
    import asyncio

    day = date(2026, 9, 29)
    qualification_store.save_day(day, licenses={}, regions={}, fetched_at=datetime(2026, 9, 29, 6, 47, tzinfo=timezone.utc))  # 15:47 KST
    settled_day = date(2026, 9, 28)
    qualification_store.save_day(settled_day, licenses={}, regions={}, fetched_at=datetime(2026, 9, 29, 6, 47, tzinfo=timezone.utc))
    called: list[date] = []

    async def _fetch(target: date, **_kwargs: object):
        called.append(target)
        return g2b_client.DayQualifications(day=target, licenses={}, regions={}, calls=4, complete=True)

    monkeypatch.setattr(g2b_client, "fetch_qualifications_for_day", _fetch)
    monkeypatch.setattr(procurement_service, "live_fetch_enabled", lambda: True)
    calls, fetched, _note = asyncio.run(procurement_service._ensure_qualification_days([settled_day, day]))
    assert called == [day] and (calls, fetched) == (4, 1)  # 다음 날 받은 9-28 은 그대로


def test_받은_뒤에_올라온_공고는_제한_없음이_아니라_미확인이다() -> None:
    """반쪽 파일을 다시 받기 전에도 거짓 「제한 없음」을 내지 않는다 — 파일을 받은 시각 뒤에 게시된 공고는 그 파일에 있을 수 없다."""
    day = date(2026, 9, 29)
    qualification_store.save_day(day, licenses={}, regions={}, fetched_at=datetime(2026, 9, 29, 6, 47, tzinfo=timezone.utc))
    coverage = qualification_store.coverage_for([day])
    before = coverage.lookup("R1-000", datetime(2026, 9, 29, 5, 0, tzinfo=timezone.utc))
    after = coverage.lookup("R2-000", datetime(2026, 9, 29, 9, 0, tzinfo=timezone.utc))
    assert before[0] == [] and before[1] == []  # 받기 전에 올라온 공고 — 제한 없음
    assert after == (None, None, None)  # 받은 뒤에 올라온 공고 — 미확인
