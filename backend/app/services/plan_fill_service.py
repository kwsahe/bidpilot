"""사업계획서 일반현황 자동 채움 — 회사자료 → 문서 칸 (29차 · prompt_19 §3-B).

담당자 결정(2026-09-30): **회사자료에 있는 값은 전부 채운다 — AI 에 보내지 않고 문서를 만들 때 이 PC 에서만.**

- 부르는 곳은 둘 — 화면 응답(`_plan_response`)과 내려받기(문서 조립). **저장본에는 쓰지 않는다**(회사자료를 고치면 바로 반영).
- AI 본문(`plan_draft_service.llm_payload`)은 이 모듈을 모른다 — 대표자 · 사업자등록번호 · 매출 · 인원은 그쪽 허용 목록에 없다.
- 채운 칸에는 출처 「회사자료」를 남기고, 회사자료에도 없는 칸만 「(담당자 입력)」으로 둔다.
- 사업자등록증 이미지에서 값을 뽑지 않는다 — 사람이 `/company` 「사업계획서 일반현황」에 입력한 값만.
"""

from __future__ import annotations

import copy
import logging
import re
from typing import Any

from app.services.plan_form_service import HUMAN_INPUT

logger = logging.getLogger(__name__)

#: 채운 칸의 출처 표식.
COMPANY_SOURCE = "회사자료"

#: 양식 칸 이름 → 회사 값 열쇠 — 대응표는 여기 하나다. 값이 없으면 그 칸은 「(담당자 입력)」 그대로.
FIELD_MAP: dict[str, str] = {
    "기업명": "name",
    "대표자": "representative",
    "개업연월일": "opened_on",
    "창업일": "opened_on",
    "사업장 소재지": "address",
    "사업장 주소": "address",
    "사업자등록번호": "business_number",
    "연락처": "phone",
    "업태/종목": "business_type_item",
    "홈페이지": "website",
    "사업분야(주요 생산품)": "business_domains",
    "사업수행 실적": "performance",
    "인증": "certifications",
    # 입찰 제안서 「제안사 일반 › 일반현황」 칸(11-03 · `bid_proposal_service.GENERAL_FIELDS`)
    "기관명": "name",
    "설립년월일": "opened_on",
    "주소": "address",
    "전화번호": "phone",
    "주요 사업내용": "business_domains",
    "보유 인증": "certifications",
    "주요 연혁": "history",
    "주요 실적": "performance",
}

#: 표 → 채우는 회사 값 (인력 구성 = 직무 · 인원 · 정량적 성과 = 연도별 매출 · 고용).
#: 입찰 제안서 「조직 및 인원 현황」(org · `bid_proposal_service.ORG_TABLE`)도 인력 구성(직무 · 인원)으로 채운다(2.7.0 · 계획 6) —
#: 「구분」 칸에 직무 · 「인원(명)」에 인원, 「주요 업무」는 회사자료에 없어 사람 몫 그대로. 참여인력 표(people)는 채우지 않는다(성명 · 경력).
TABLE_KEYS = ("staff", "org", "performance")

_YEAR_RE = re.compile(r"(19|20)\d{2}")


#: 행 이름의 금액 단위 → 원으로 나눌 수 — 「매출액(억원)」 행에 원 값을 그대로 넣지 않게.
_MONEY_UNITS: tuple[tuple[str, int], ...] = (("억원", 100_000_000), ("백만원", 1_000_000), ("천만원", 10_000_000), ("만원", 10_000), ("천원", 1_000))


def _money(value: int, label: str = "") -> str:
    """원 값을 행 이름의 단위로 — 「매출액(억원)」 이면 3.1 · 단위가 없으면 원 그대로(쉼표)."""
    for unit, size in _MONEY_UNITS:
        if unit in label:
            scaled = value / size
            return f"{scaled:,.0f}" if scaled == int(scaled) else f"{scaled:,.2f}".rstrip("0").rstrip(".")
    return f"{value:,}"


def fill_allowed(evidence_scope: str | None) -> bool:
    """일반현황(대표자 · 사업자번호 · 매출 · 고용)을 채워도 되는가 — 사내 근거 범위이고 공개 배포가 아닐 때만(30차 R29-02)."""
    from app.core.config import get_settings

    return evidence_scope == "internal" and not get_settings().public_demo_mode


#: 이력 줄 속 회사 메모 괄호(「(지금의 … 별개)」 · 「(… 재확인 필요)」).
_HISTORY_NOTE = re.compile(r"\s*\([^)]*(?:확인|별개)[^)]*\)")


def _history_line(entry: Any) -> str:
    """인증 이력 한 줄 → 칸에 넣을 한 줄. 「 · 」 조각은 「, 」로 잇고(칸이 「 · 」에서 줄을 갈랐다),
    회사가 적어 둔 메모(「세부품명 확인 필요」 · 「(… 별개)」)는 뺀다 — 제출 서류에 「확인 필요」가 실렸다(11-03 대표)."""
    parts = (_HISTORY_NOTE.sub("", part).strip() for part in str(entry).split(" · "))
    return ", ".join(part for part in parts if part and "확인 필요" not in part)


def company_values(organization_id: str, evidence_scope: str | None) -> dict[str, Any]:
    """회사자료에서 칸에 넣을 값 — 프로필 · 일반현황 · 실적 대장. 못 읽으면 빈 값(채우지 않을 뿐이다).

    사내 범위가 아니거나 공개 배포면 일반현황을 읽지 않는다(30차 R29-02). 프로필이 합성 기본값(`default_synthetic`)이면
    사업분야 · 인증을 회사 값으로 쓰지 않는다 — 입찰 서식(`bid_application_export`)과 같은 규칙(30차 R29-01)."""
    from app.services import organization_service, plan_draft_service

    general: dict[str, Any] = {}
    if fill_allowed(evidence_scope):
        try:
            general = organization_service.load_plan_general(organization_id).model_dump(mode="json")
        except Exception:  # noqa: BLE001 — 없는 회사 · 못 읽음 → 채우지 않는다
            general = {}
    sources = plan_draft_service.company_sources(organization_id, evidence_scope)
    profile = sources.get("profile") or {}
    if profile.get("source") == "default_synthetic":
        profile = {**profile, "business_domains": [], "certifications": []}
    ledger = sources.get("ledger") or []
    type_item = " / ".join(v for v in (general.get("business_type"), general.get("business_item")) if v)
    opened = general.get("opened_on")
    certs = [str(c.get("name")) if isinstance(c, dict) else str(c) for c in profile.get("certifications") or []]
    # 같은 실적 이름이 원장에 두 행이면 한 번 — 겹친 줄을 먼저 빼고 최근 5건(11-03 제안서 「주요 실적」에 두 번 실렸고, 뺀 뒤 4건만 남았다)
    from app.services import performance_ledger

    # 증빙 확인 전(증빙 메모 「미확인 · 확인 필요」) 실적은 싣지 않는다 — AI 근거(`company_pieces`)와 같은 규칙(2.9.0 · 2.8.0 B7)
    # 외부 사용 · 증빙 칸이 아예 없는 행(옛 저장본 · 시험)은 예전처럼 싣는다 — 칸이 있고 「미확인」일 때만 뺀다
    shown = [r for r in ledger if performance_ledger.evidence_state(r)[0] != "UNVERIFIED"
             or ("eligible" not in r and not r.get("external_use") and not r.get("evidence_note"))]
    recent = list(dict.fromkeys(f"{r.get('year') or ''} {r.get('title')}".strip()
                                for r in sorted(shown, key=lambda r: str(r.get("year") or ""), reverse=True) if r.get("title")))[:5]
    return {
        "name": profile.get("name"),
        "representative": general.get("representative"),
        "opened_on": opened.replace("-", ". ") + "." if isinstance(opened, str) and opened else None,
        "address": profile.get("address"),
        "business_number": general.get("business_number"),
        "phone": profile.get("phone"),
        "business_type_item": type_item or None,
        "website": profile.get("website"),
        "business_domains": " · ".join(str(d) for d in profile.get("business_domains") or []) or None,
        "performance": " / ".join(recent) or None,
        "certifications": " · ".join(certs) or None,
        # 인증 · 지정 이력(앞 6줄 · 한 이력 한 줄) — 입찰 일반현황 「주요 연혁」
        "history": " / ".join(h for h in map(_history_line, (profile.get("certification_history") or [])[:6]) if h) or None,
        "staff": [s for s in general.get("staff") or [] if s.get("role")],
        "revenue": {int(r["year"]): r["value"] for r in general.get("revenue_by_year") or [] if r.get("value") is not None},
        "employees": {int(r["year"]): r["value"] for r in general.get("employees_by_year") or [] if r.get("value") is not None},
    }


def _fill_staff(table: dict[str, Any], staff: list[dict[str, Any]]) -> tuple[int, bool]:
    """인력 구성 표 — 직무 · 인원(성명 없이). 규칙 표(모든 칸이 빈칸)일 때만 바꾼다. (채운 칸 수, 빈칸이 남았는가)."""
    columns = list(table.get("columns") or [])
    if not staff or any(cell != HUMAN_INPUT for row in table.get("rows") or [] for cell in row[1:]):
        return 0, any(HUMAN_INPUT in row for row in table.get("rows") or [])
    rows, filled = [], 0
    members = [m for m in staff if int(m.get("count") or 0) > 0]  # 0명 줄은 채우지 않는다(30차 R29-10)
    if not members:
        return 0, any(HUMAN_INPUT in row for row in table.get("rows") or [])
    for index, member in enumerate(members, start=1):
        row = [HUMAN_INPUT] * len(columns)
        count = int(member["count"])
        has_count_column = any("인원" in str(c) for c in columns)
        for c, column in enumerate(columns):
            if column == "연번":
                row[c] = str(index)
            elif "담당" in column or column in ("직무", "역할", "구분"):  # 「구분」 — 입찰 조직 표(2.7.0)
                # 인원은 직무 칸에 「AI 교육 강사(4명)」 꼴 — 「구성 상태」(채용 완료/예정) 칸에는 넣지 않는다(30차 R29-10)
                row[c], filled = (str(member["role"]) if has_count_column else f"{member['role']}({count}명)"), filled + 1
            elif "인원" in column:
                # 칸 이름에 단위가 있으면(입찰 조직 표 「인원(명)」) 숫자만
                row[c], filled = (str(count) if "(명)" in column else f"{count}명"), filled + 1
        rows.append(row)
    table["rows"], table["by"], table["filled_by"] = rows, "company", COMPANY_SOURCE
    return filled, any(HUMAN_INPUT in row for row in rows)


def _fill_performance(table: dict[str, Any], revenue: dict[int, int], employees: dict[int, int]) -> tuple[int, bool]:
    """정량적 성과 표 — 행 이름에 「매출」 · 「고용/인원」이 있으면 그 연도 칸을 채운다. (채운 칸 수, 빈칸이 남았는가)."""
    columns = list(table.get("columns") or [])
    years = {c: int(m.group(0)) for c, name in enumerate(columns) if (m := _YEAR_RE.search(str(name)))}
    filled = 0
    for row in table.get("rows") or []:
        label = str(row[0]) if row else ""
        source = revenue if "매출" in label else employees if ("고용" in label or "인원" in label) else None
        if source is None:
            continue
        for c, year in years.items():
            if c < len(row) and row[c] == HUMAN_INPUT and year in source:
                row[c] = _money(int(source[year]), label if source is revenue else "")
                filled += 1
    if filled:
        table["filled_by"] = COMPANY_SOURCE
    return filled, any(HUMAN_INPUT in row for row in table.get("rows") or [])


def apply(draft: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    """초안 사본에 회사 값을 채워 돌려준다(원본은 그대로). 결과에 `company_fill` 셈을 싣는다.

    - 칸: 값이 「(담당자 입력)」이고 대응표에 회사 값이 있으면 채운다 — 출처 「회사자료」.
    - 표: 인력 구성(직무 · 인원) · 정량적 성과(연도별 매출 · 고용).
    - 빈칸 목록(`blanks`)에서 채운 칸을 뺀다 → 점검표가 「회사자료로 채움 n · 담당자 입력 남음 m」을 센다.
    - `fillable` — 대응표에 있는데 회사자료에 값이 없어 비어 있는 칸(회사자료에 입력하면 자동으로 채워진다).
    """
    out = copy.deepcopy(draft)
    filled_labels: list[str] = []
    fillable: list[str] = []
    cells = 0
    for section in out.get("sections") or []:
        if section.get("kind") != "fields":
            continue
        for field in section.get("fields") or []:
            key = FIELD_MAP.get(str(field.get("label")))
            if key is None or field.get("value") != HUMAN_INPUT:
                continue
            value = values.get(key)
            if value:
                field.update({"value": str(value), "filled_by": "company", "source": COMPANY_SOURCE})
                filled_labels.append(field["label"])
            else:
                fillable.append(field["label"])
        # 칸 줄(문장)도 같은 값으로 — 화면 · 문서가 칸과 문장을 따로 읽는 곳이 있다
        by_label = {f["label"]: f for f in section.get("fields") or [] if f.get("filled_by") == "company"}
        for sentence in section.get("sentences") or []:
            label = str(sentence.get("text") or "").split(":", 1)[0]
            if label in by_label:
                sentence.update({"text": f"{label}: {by_label[label]['value']}", "type": "COMPANY_EVIDENCE_GROUNDED",
                                 "source": COMPANY_SOURCE, "note": False, "company_fill": True})
    table_done: set[str] = set()
    for table in out.get("tables") or []:
        key = table.get("key")
        if key in ("staff", "org"):
            n, left = _fill_staff(table, values.get("staff") or [])
        elif key == "performance":
            n, left = _fill_performance(table, values.get("revenue") or {}, values.get("employees") or {})
        else:
            continue
        cells += n
        if n and not left:
            table_done.add(str(table.get("title")))
        # 채울 수 있는데 회사 값이 없어 빈 표만 센다 — 정량적 성과는 매출 · 고용 행이 있을 때만
        applicable = key in ("staff", "org") or any(("매출" in str(r[0]) or "고용" in str(r[0]) or "인원" in str(r[0])) for r in table.get("rows") or [] if r)
        if not n and applicable and any(HUMAN_INPUT in row for row in table.get("rows") or []):
            fillable.append(str(table.get("title")))
    filled_set = set(filled_labels) | table_done
    out["blanks"] = [b for b in out.get("blanks") or [] if str(b.get("field")) not in filled_set]
    out["company_fill"] = {
        "filled": len(filled_labels) + cells,
        "filled_fields": filled_labels,
        "filled_table_cells": cells,
        "remaining": len(dict.fromkeys(str(b.get("field")) for b in out["blanks"])),
        # 같은 칸 이름이 두 절(일반 현황 · 기업 현황)에 있어도 회사자료 한 칸이면 둘 다 채워진다 — 이름으로 센다
        "fillable": len(dict.fromkeys(fillable)),
        "fillable_fields": list(dict.fromkeys(fillable)),
    }
    return out


def fill_for(draft: dict[str, Any], organization_id: str | None, evidence_scope: str | None) -> dict[str, Any]:
    """회사 문맥으로 채운 사본. 회사가 없거나 초안이 비면 그대로(셈 없음)."""
    if not organization_id or not draft.get("sections") or not fill_allowed(evidence_scope):
        return draft  # 사내 범위가 아니거나 공개 배포면 채우지 않는다(30차 R29-02)
    try:
        return apply(draft, company_values(organization_id, evidence_scope))
    except Exception:  # noqa: BLE001 — 채우기 실패가 화면 · 내려받기를 막지 않는다
        logger.warning("일반현황 자동 채움 실패 — 채우지 않고 그대로 보냅니다 (organization_id=%s)", organization_id, exc_info=True)
        return draft
