"""사업기회 목록 **내보내기** — 담당자가 남에게 보낼 수 있는 형태로 (0921.md §4-D-4).

검수자가 손으로 만든 `docs/reports/2026-09-20_apply_candidates.md/.csv` 와 **같은 열**로
내려준다. 그 표가 담당자에게 실제로 쓸모 있던 모양이기 때문이다 — 앱이 같은 것을 내면
사람이 다시 옮겨 적지 않아도 된다.

**여기서 새 판정을 만들지 않는다.** 목록 응답(`opportunity_service.list_opportunities`)이
이미 만든 값을 형식만 바꿔 적는다. 두 곳에서 따로 계산하면 화면과 파일이 갈린다.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Any

from app.schemas.business_opportunity import SOURCE_NAMES, UnifiedOpportunity, UnifiedOpportunityListResponse
from app.services import practical_priority as practical

#: CSV 열 이름. 기준 답안 CSV 와 같은 순서다(이름은 「추천순」 → 「출처 안 순위」만 다르다 · 40차 RANK-01).
COLUMNS: tuple[str, ...] = (
    "출처",
    "그룹",
    # 40차 RANK-01 — 순위는 출처 안에서만 매긴다(D22) — 「전체」 탭은 출처를 번갈아 세우므로 섞인 통합 순위(1 · 9 · 2 · 204)를 적지 않는다
    "출처 안 순위",
    "공고번호/ID",
    "공고명",
    "발주/주관",
    "예산(원)",
    # 43차 M1 · NUM-05 — 실제 마감(입찰 · 등록 · 공고문 일정 중 가장 이른 것) · 한국 시각 「YYYY-MM-DD HH:MM」 · 종류 · 입찰 마감 따로
    "실제 마감",
    "마감 종류",
    "입찰 마감",
    "계약·낙찰/분야",
    "제한·대상(확인값)",
    "메모",
    # 37차 §3-C-3 — 점수 · 분류 · 유형(근사) · 접수방식 · 공고일. 점수는 「회사 기준 검토 우선순위」(낙찰확률 아님).
    "회사 기준 검토 우선순위",
    "분류",
    "유형(근사)",
    "꼬리표",
    "접수방식",
    "공고일",
    "링크",
)

#: 화면과 같은 말을 쓴다 (0921 §3-11: 영문 값 금지).
GATE_LABELS = {"PASS": "가능", "CHECK": "확인 필요", "FAIL": "불가"}


def _group(item: UnifiedOpportunity) -> str:
    """기준 답안의 그룹 축(개발 · 교육 · 지원사업). 43차 NUM-10 — 유형 A1~D 와 겹치던 글자 접두어(A · B · C)를 뺐다."""
    if item.opportunity_type == "support_program":
        return "지원사업"
    tracks = set(item.work_tracks or ())
    if "education" in tracks:
        return "교육"
    if "development" in tracks:
        return "개발"
    return "그 밖"


_KST = timezone(timedelta(hours=9))


def _kst_text(moment: datetime | None) -> str:
    return moment.astimezone(_KST).strftime("%Y-%m-%d %H:%M") if moment is not None else ""


def _deadline(item: UnifiedOpportunity) -> str:
    """실제 마감 · 한국 시각(43차 NUM-05 — 예전에는 입찰 마감을 UTC ISO 로 적어 0~9시 마감이 하루 앞당겨 찍혔다)."""
    real = practical.effective_deadline(item)
    if real is not None:
        return practical.deadline_stamp(item)  # 시각을 모르면 「YYYY-MM-DD (시각 원문 확인)」(44차 M3)
    return practical.deadline_unknown_text(item) if practical.deadline_unknown(item) else (item.deadline_text or "")


def _limits(item: UnifiedOpportunity) -> str:
    """「제한·대상(확인값)」 — 판정과 사유를 한 칸에. 근거 없는 말을 넣지 않는다."""
    parts = [GATE_LABELS.get(item.eligibility_gate or "", "미확인")]
    if item.gate_reason:
        parts.append(item.gate_reason)
    return " · ".join(parts)


def _row(item: UnifiedOpportunity) -> list[str]:
    # 계약·낙찰 방식은 자격 규칙(ELIG-AWARD)이 만든 한 줄을 그대로 쓴다. 지원사업에는
    # 그 축이 없으므로 분야(category)를 적는다.
    award = item.award_line or (item.category or "")
    return [
        SOURCE_NAMES.get(item.source_type, item.source_type),
        _group(item),
        str(item.source_rank or item.priority_rank),
        item.id.replace("g2b-", "").replace("bizinfo-", ""),
        item.title,
        item.agency,
        str(item.budget) if item.budget else "",
        _deadline(item),
        practical.deadline_kind(item) or ("마감 미상" if practical.deadline_unknown(item) else ""),
        _kst_text(item.deadline) if item.source_type == "g2b" else "",
        award,
        _limits(item),
        " · ".join(filter(None, [item.fit_line, item.caution_line])),
        "" if item.company_priority_score is None else str(item.company_priority_score),
        item.practical_group or "",
        item.fit_type or "",
        " · ".join(practical.tags_of(item)),
        " · ".join(item.submission_methods or ()),
        item.published_at.astimezone(timezone(timedelta(hours=9))).strftime("%Y-%m-%d") if item.published_at else "",
        item.detail_url or "",
    ]


def _csv_cell(value: str) -> str:
    """엑셀이 수식으로 읽는 머리(= + - @ · 탭)로 시작하는 글 앞에 「'」 — 직접 넣은 · 붙여 넣은 제목(38차 검토 · 수식 주입)."""
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") and value != "-" else value


def to_csv(listing: UnifiedOpportunityListResponse) -> str:
    """CSV 한 덩어리. 엑셀이 한글을 깨지 않게 BOM 을 붙인다."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(COLUMNS)
    for item in listing.items:
        writer.writerow([_csv_cell(value) for value in _row(item)])
    return "\ufeff" + buffer.getvalue()


def _link_cell(url: str) -> str:
    """md 표의 링크 칸 — http(s) 주소만 · 칸을 가르는 「|」 · 공백 · 꺾쇠는 퍼센트로(40차 MANUAL-06)."""
    text = (url or "").strip()
    if not text.lower().startswith(("https://", "http://")):
        return ""
    for ch, code in (("|", "%7C"), (" ", "%20"), ("<", "%3C"), (">", "%3E")):
        text = text.replace(ch, code)
    return text


def to_markdown(listing: UnifiedOpportunityListResponse) -> str:
    """사람이 그대로 읽는 표. 기준 답안 문서와 같은 모양이다."""
    from app.services.opportunity_brief_service import _md

    stamp = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# 지원할 수 있는 사업 — {listing.organization_name}",
        "",
        f"> 앱이 만든 표 · {stamp} 기준 · 조회 기간 {listing.summary.days}일",
        f"> 마감 전 전체 {listing.summary.open_total}건"
        f"(나라장터 {listing.summary.open_g2b} · 기업마당 {listing.summary.open_bizinfo})"
        f" 중 **참가할 수 있거나 확인이 필요한 {listing.total_count}건**."
        f" 판정이 「불가」인 {listing.blocked_count}건은 뺐다.",
        "",
        "> 추천등급·적합도는 낙찰확률이 아니다. 「제한·대상」은 공고 필드와 회사자료로 판정한"
        " 결과이며, 「공고문 확인」이라고 적힌 것은 사람이 원문을 봐야 한다.",
        "",
        "| " + " | ".join(COLUMNS) + " |",
        "|" + "---|" * len(COLUMNS),
    ]
    for item in listing.items:
        # 40차 MANUAL-06 — 브리핑과 같은 이스케이프(공백 접기 · 「|」 · 링크 · 꺾쇠 · CR) — 직접 넣은 공고명의 [링크](…) · HTML 이 살아났다.
        # 마지막 칸(링크)은 주소라 이스케이프하지 않고 `_link_cell` 로 칸을 가르는 글자만 퍼센트로.
        *body, link = _row(item)
        cells = [_md(c) for c in body] + [_link_cell(link)]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    return "\n".join(lines)


def filename(listing: UnifiedOpportunityListResponse, suffix: str) -> str:
    stamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d")
    return f"사업기회_{listing.organization_id}_{stamp}.{suffix}"


def build(listing: UnifiedOpportunityListResponse, fmt: str) -> tuple[str, str, str]:
    """`(본문, media_type, 파일명)`."""
    if fmt == "csv":
        return to_csv(listing), "text/csv; charset=utf-8", filename(listing, "csv")
    return to_markdown(listing), "text/markdown; charset=utf-8", filename(listing, "md")


def summary_row(listing: UnifiedOpportunityListResponse) -> dict[str, Any]:
    """내보낸 것이 무엇인지 한 줄. 화면이 내려받기 옆에 적는다."""
    return {
        "rows": len(listing.items),
        "blocked_excluded": listing.blocked_count,
        "days": listing.summary.days,
        "open_total": listing.summary.open_total,
    }
