"""나라장터 API 응답 item -> ProcurementNotice 매핑.

필드명은 2026-09-03 실제 응답(getBidPblancListInfoServcPPSSrch, 113개 필드)을
확인한 뒤 작성했다. 추정한 필드는 사용하지 않는다 (CLAUDE.md 25-5).

주요 매핑
    bidNtceNo + bidNtceOrd    -> notice_no        (공고번호-차수)
    bidNtceNm                 -> title            (공고명)
    ntceInsttNm / dminsttNm   -> agency           (공고기관 / 수요기관)
    bidNtceDt                 -> published_at     (공고게시일시)
    bidClseDt                 -> deadline_at      (입찰마감일시, 없으면 개찰일시)
    asignBdgtAmt / presmptPrce-> budget           (배정예산 / 추정가격)
    jntcontrctDutyRgnNm1      -> region           (지역의무공동도급 «대상 지역 이름»)
    rgnLmtBidLocplcJdgmBssNm  -> raw_data.region_limit_basis (지역제한 소재지 «판단기준 이름»)
    bidNtceDtlUrl / bidNtceUrl-> source_url       (공고 상세 URL)
    ntceSpecDocUrl1..10       -> raw_data.attachments (규격서·제안요청서 첨부)

`rgnLmtBidLocplcJdgmBssNm` 를 region 으로 쓰던 것을 끊었다 (2026-09-14).
    이 필드는 지역 «이름»이 아니라 소재지를 무엇으로 판단할지 정하는 «기준의 이름»이다.
    캐시된 실응답 76건을 세어 보니 값의 종류가 세 가지뿐이었다:
        52건 «본사또는참여지사소재지» (판단기준코드 N, 전부 수의계약)
        23건 «»(빈 값)
         1건 «본사소재지» (판단기준코드 Y)
    지역 이름은 한 건도 없었고, 대상 지역을 담은 필드(jntcontrctDutyRgnNm1)는 76건 전부 비어 있었다.
    그런데 이 값이 region 으로 들어가면서 「본사또는참여지사소재지」가 회사 활동 지역과 다르다는
    이유로 참가자격이 FAIL 로 판정됐다 — 들어갈 수 있는 공고를 버리는 판정이다.
    그래서 지역 «이름»이 실제로 들어 있을 때만 region 으로 쓰고, 아니면 판단기준 플래그로만 남긴다.
    대상 지역을 모르면 FAIL 이 아니라 CHECK 다.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from app.schemas.procurement import ProcurementNotice

KST = timezone(timedelta(hours=9))

# 첨부파일 슬롯 개수 (실제 응답 기준 1~10)
ATTACHMENT_SLOTS = 10

_DATETIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d")

# 지역제한 소재지 «판단기준» 필드. 지역 이름이 아니다 (모듈 docstring의 실측 참고).
REGION_LIMIT_BASIS_FIELD = "rgnLmtBidLocplcJdgmBssNm"
REGION_LIMIT_BASIS_CODE_FIELD = "rgnLmtBidLocplcJdgmBssCd"

# 광역자치단체 17곳 + 실제 공고문에 흔한 축약형. 문자열 안에 이 중 하나가 있어야
# «지역 이름»으로 인정한다. 시·군·구까지 넣지 않는 이유 — 「본사」·「지사」 같은
# 판단기준 낱말과 겹칠 위험을 만들지 않기 위해서다. 걸러지지 못하면 CHECK 로 가므로
# 못 찾는 쪽(놓침)은 공고를 버리지 않지만, 잘못 찾는 쪽(오인)은 FAIL 을 만든다.
REGION_NAME_TOKENS: tuple[str, ...] = (
    "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
    "경기", "강원", "충북", "충청북도", "충남", "충청남도",
    "전북", "전라북도", "전남", "전라남도",
    "경북", "경상북도", "경남", "경상남도", "제주",
)


def contains_region_name(value: str | None) -> bool:
    """문자열에 실제 지역(광역자치단체) 이름이 들어 있는가.

    「본사또는참여지사소재지」처럼 지역 이름이 없는 판단기준 문구를 지역으로 읽지 않기 위한 관문이다.
    """
    if not value:
        return False
    return any(token in value for token in REGION_NAME_TOKENS)


def region_name(value: str | None) -> str | None:
    """지역 «이름»일 때만 그대로, 아니면 None.

    이미 저장된 캐시에는 판단기준 이름이 region 으로 들어간 공고가 남아 있다.
    다시 받아오기 전까지 읽는 쪽에서도 한 번 더 걸러야 같은 오독이 되살아나지 않는다.
    """
    text = (value or "").strip()
    return text if contains_region_name(text) else None


def region_limit_basis(raw_data: dict[str, Any]) -> str | None:
    """공고 raw_data 에서 지역제한 «판단기준 이름»을 꺼낸다 (원본 item 우선).

    ProcurementNotice.raw_data 를 받는다. 캐시로 되살린 공고에는 아래에서 새로 넣는
    `region_limit_basis` 키가 없으므로 원본 item 을 먼저 본다.
    """
    item = raw_data.get("item")
    if isinstance(item, dict):
        value = _text(item, REGION_LIMIT_BASIS_FIELD)
        if value:
            return value
    value = raw_data.get("region_limit_basis")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _text(item: dict[str, Any], *keys: str) -> str | None:
    """첫 번째로 값이 있는 필드를 반환한다. 공백 문자열은 없는 값으로 본다."""
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def parse_datetime(value: str | None) -> datetime | None:
    """'2026-08-20 01:14:56' 형태를 KST datetime으로. 실패하면 None."""
    if not value:
        return None
    text = value.strip()
    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=KST)
        except ValueError:
            continue
    return None


def parse_amount(value: str | None) -> int | None:
    """'425000000' 또는 '425,000,000' -> 425000000. 0과 빈 값은 None."""
    if not value:
        return None
    digits = "".join(ch for ch in value if ch.isdigit())
    if not digits:
        return None
    amount = int(digits)
    return amount or None


def extract_attachments(item: dict[str, Any]) -> list[dict[str, str]]:
    """규격서·제안요청서 첨부파일 목록. 실제 RFP 문서를 여기서 받을 수 있다."""
    attachments: list[dict[str, str]] = []
    for index in range(1, ATTACHMENT_SLOTS + 1):
        url = _text(item, f"ntceSpecDocUrl{index}")
        if not url:
            continue
        attachments.append(
            {
                "name": _text(item, f"ntceSpecFileNm{index}") or f"첨부{index}",
                "url": url,
            }
        )
    return attachments


def build_description(item: dict[str, Any]) -> str | None:
    """공고 자체에 과업 설명 필드가 없어, 분류·계약방법 등 구조화 필드로 요약한다."""
    parts: list[str] = []
    classification = _text(item, "pubPrcrmntLrgClsfcNm")
    mid = _text(item, "pubPrcrmntMidClsfcNm")
    detail = _text(item, "pubPrcrmntClsfcNm")
    if classification:
        parts.append(" > ".join(p for p in (classification, mid, detail) if p))
    method = _text(item, "cntrctCnclsMthdNm")
    if method:
        parts.append(f"계약방법: {method}")
    service_div = _text(item, "srvceDivNm")
    if service_div:
        parts.append(f"용역구분: {service_div}")
    return " · ".join(parts) or None


def base_notice_no(notice_no: str) -> str:
    """공고번호에서 차수를 뗀 값 (R26BK01701257-003 → R26BK01701257).

    같은 사업이 정정·재공고되면 차수만 올라간다. 차수까지 붙은 값을 그대로 쓰면
    한 사업이 화면에서 여러 건으로 세어진다.
    끝의 한 조각만 뗀다 — 공고번호 자체에 `-` 가 들어가도 안전하다.
    """
    return notice_no.rsplit("-", 1)[0]


def notice_order(notice_no: str) -> int:
    """차수(숫자). 읽을 수 없으면 0으로 본다 — 비교에서 가장 낮게 놓인다."""
    tail = notice_no.rsplit("-", 1)
    if len(tail) != 2 or not tail[1].isdigit():
        return 0
    return int(tail[1])


# --------------------------------------------------------------------------
# 자격 제한 (0921.md §4-A-1)
# --------------------------------------------------------------------------

#: 「소프트웨어사업자(컴퓨터관련서비스사업)/1468」 처럼 이름과 업종코드가 슬래시로 붙어 온다.
_LICENSE_CODE_RE = re.compile(r"/\s*(\d{3,5})\s*$")


def _industry_tokens(value: Any) -> list[str]:
    """허용 업종 목록(`permsnIndstrytyList`)을 문자열 목록으로.

    응답이 리스트로 올 때와 한 문자열로 올 때가 모두 있을 수 있어 양쪽을 받는다.
    **모르는 모양이면 버리지 않고 문자열 하나로 남긴다** — 판정이 근거를 잃지 않게 한다.
    """
    if value is None or value == "":
        return []
    if isinstance(value, list):
        out: list[str] = []
        for entry in value:
            if isinstance(entry, dict):
                text = str(entry.get("indstrytyNm") or entry.get("indstrytyCd") or "").strip()
            else:
                text = str(entry).strip()
            if text:
                out.append(text)
        return out
    text = str(value).strip()
    if not text:
        return []
    parts = [part.strip() for part in re.split(r"[,;|\r\n]+", text)]
    return [part for part in parts if part]


def license_limits_of(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """면허제한 API 항목 → 화면·판정이 바로 읽는 정규 형태.

    `{name, code, allowed_industries[], group_no, sno}`. 코드는 이름 끝의 `/1468` 에서 뽑고,
    없으면 None 이다 — **0 이나 빈 문자열로 꾸미지 않는다.**
    """
    out: list[dict[str, Any]] = []
    for item in items:
        name = _text(item, "lcnsLmtNm")
        if not name:
            continue
        match = _LICENSE_CODE_RE.search(name)
        code = match.group(1) if match else None
        out.append(
            {
                "name": _LICENSE_CODE_RE.sub("", name).strip() if code else name,
                "code": code,
                "allowed_industries": _industry_tokens(item.get("permsnIndstrytyList")),
                "group_no": _text(item, "lmtGrpNo"),
                "sno": _text(item, "lmtSno"),
            }
        )
    return out


def allowed_regions_of(items: list[dict[str, Any]]) -> list[str]:
    """참가가능지역 API 항목 → 지역 이름 목록. 중복은 접되 순서는 지킨다."""
    out: list[str] = []
    for item in items:
        name = _text(item, "prtcptPsblRgnNm")
        if name and name not in out:
            out.append(name)
    return out


class QualificationLookup(Protocol):
    """「이 공고의 자격은 무엇인가」에 답하는 것. `qualification_store.Coverage` 가 이것이다."""

    def lookup(
        self, key: str, published_at: datetime | None
    ) -> tuple[list[dict[str, Any]] | None, list[str] | None, datetime | None]: ...


def notice_id(item: dict[str, Any]) -> str:
    no = _text(item, "bidNtceNo") or "unknown"
    order = _text(item, "bidNtceOrd") or "000"
    return f"g2b-{no}-{order}"


def map_notice(
    item: dict[str, Any],
    *,
    license_limits: list[dict[str, Any]] | None = None,
    allowed_regions: list[str] | None = None,
    qualification_checked_at: datetime | None = None,
) -> ProcurementNotice | None:
    """API item 1건을 ProcurementNotice로. 필수 필드가 없으면 None(건너뜀).

    `license_limits`·`allowed_regions` 는 **이미 정규화된** 자격 값이다
    (`qualification_store` 가 하루치를 받아 정규 형태로 저장한다, 0922 §4-A-2).
    `None` 이면 **받아 본 적이 없다**(미확인)는 뜻이고, 빈 목록(`[]`)은 「제한이 없다」는
    **다른 사실**이다. `qualification_checked_at` 은 그 값을 언제 받았는지다 — 없으면 미확인.
    """
    no = _text(item, "bidNtceNo")
    title = _text(item, "bidNtceNm")
    published = parse_datetime(_text(item, "bidNtceDt", "rgstDt"))
    if not no or not title or published is None:
        return None

    order = _text(item, "bidNtceOrd") or "000"
    attachments = extract_attachments(item)

    # 지역: «이름»이 들어 있는 값만 쓴다. 판단기준 이름은 지역이 아니다.
    basis = _text(item, REGION_LIMIT_BASIS_FIELD)
    region = region_name(basis) or _text(item, "jntcontrctDutyRgnNm1")

    return ProcurementNotice(
        id=notice_id(item),
        notice_no=f"{no}-{order}",
        title=title,
        agency=_text(item, "ntceInsttNm", "dminsttNm") or "확인 필요",
        published_at=published,
        # 입찰마감일시만 마감이다 — 비어 있으면 None(43차 H1 · 직찰 · 우편 공고). 예전에는 개찰일시를 넣어 끝난 공고가
        # 열려 있었다(목원대 10/22 방문접수 → 「10/23 · 남은 1일」). 개찰일시는 `opening_at` 에 두고, 실제 마감은 공고문 일정표에서 뽑는다.
        deadline_at=parse_datetime(_text(item, "bidClseDt")),
        budget=parse_amount(_text(item, "asignBdgtAmt", "presmptPrce")),
        region=region,
        description=build_description(item),
        source_url=_text(item, "bidNtceDtlUrl", "bidNtceUrl"),
        raw_data={
            "source": "g2b",
            "operation": "getBidPblancListInfoServcPPSSrch",
            "attachments": attachments,
            "demand_institution": _text(item, "dminsttNm"),
            "contract_method": _text(item, "cntrctCnclsMthdNm"),
            "notice_kind": _text(item, "ntceKindNm"),
            "industry_limit": _text(item, "indstrytyLmtYn"),
            # 지역제한 «판단기준». 지역 이름이 아니므로 region 과 섞지 않는다.
            # 대상 지역이 없으면 참가 가능 여부는 CHECK 로 간다 (판정 근거가 없다).
            "region_limit_basis": basis,
            "region_limit_basis_code": _text(item, REGION_LIMIT_BASIS_CODE_FIELD),
            "region_limit_area": region,
            "participation_limit": _text(item, "bidPrtcptLmtYn"),
            "qualification_deadline": _text(item, "bidQlfctRgstDt"),
            "opening_at": _text(item, "opengDt"),
            "estimated_price": _text(item, "presmptPrce"),
            "assigned_budget": _text(item, "asignBdgtAmt"),
            # --- 자격 판정 v2 가 읽는 값들 (0921 §4-A-1 · §4-B) ---
            # 지금까지 `item` 안에만 있어 아무도 안 읽던 것들을 편의 키로 올린다.
            "result_evaluation": _text(item, "arsltCmptYn"),
            "joint_supply_method": _text(item, "cmmnSpldmdMethdNm"),
            "award_method": _text(item, "sucsfbidMthdNm"),
            "tech_ability_rate": _text(item, "techAbltEvlRt"),
            "procurement_class": _text(item, "pubPrcrmntClsfcNm"),
            # **None = 받아 본 적 없음(미확인)**, [] = 제한 없음. 둘은 다른 사실이다.
            "license_limits": license_limits,
            "allowed_regions": allowed_regions,
            # 「언제 받아 확인한 값인가」. 화면이 「미확인」과 「확인함」을 구분해 적는다.
            "qualification_checked_at": (
                qualification_checked_at.isoformat() if qualification_checked_at else None
            ),
            "item": item,
        },
    )


def normalized(notice: ProcurementNotice) -> ProcurementNotice:
    """저장본에서 읽은 공고를 지금 규칙으로 맞춘다(43차 H1) — 옛 저장본은 입찰 마감이 비면 개찰일시를 `deadline_at` 에 넣었다."""
    item = (notice.raw_data or {}).get("item") if isinstance(notice.raw_data, dict) else None
    if isinstance(item, dict) and notice.deadline_at is not None and not _text(item, "bidClseDt"):
        return notice.model_copy(update={"deadline_at": None})
    return notice


def map_notices(
    items: list[dict[str, Any]],
    *,
    qualifications: "QualificationLookup | None" = None,
) -> list[ProcurementNotice]:
    """목록 item 들을 공고로. 자격 제한은 **게시일 + 공고번호+차수**로 붙인다 (0922 §4-A-1).

    `qualifications` 는 「이 공고의 자격은 무엇인가」에 답하는 것 하나뿐이다
    (`qualification_store.Coverage`). 매핑 쪽은 저장소도, 하루 창도 모른다.
    받은 적 없는 날의 공고는 `(None, None, None)` 이라 「미확인」으로 남는다.
    """

    def key(item: dict[str, Any]) -> str:
        return f"{item.get('bidNtceNo', '')}-{item.get('bidNtceOrd', '')}"

    def mapped(item: dict[str, Any]) -> ProcurementNotice | None:
        if qualifications is None:
            return map_notice(item)
        limits, regions, checked = qualifications.lookup(
            key(item), parse_datetime(_text(item, "bidNtceDt", "rgstDt"))
        )
        return map_notice(
            item,
            license_limits=limits,
            allowed_regions=regions,
            qualification_checked_at=checked,
        )

    return [notice for notice in (mapped(item) for item in items) if notice is not None]
