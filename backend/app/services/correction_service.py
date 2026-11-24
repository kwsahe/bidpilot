"""사람의 정정 기록 (Requirement 항목) + Gold 데이터셋 내보내기.

- 담당자가 항목의 유형·필수여부·내용·페이지를 고치면 **이력**으로 쌓는다 (덮어쓰지 않는다).
- 읽을 때(rfp_parser.load_generated) 최신 정정을 덧입힌다. 원본 추출 결과 파일은 그대로 둔다.
- 정정된 항목은 extraction_method=HUMAN, review_status=corrected/confirmed/rejected 가 된다.
- Gold 내보내기는 사람이 확정(confirmed/corrected)한 항목만 담는다. 시스템 추출 결과를 Gold로 포장하지 않는다.

저장: data/public/corrections/<id>.corrections.json
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core import storage
from app.core.paths import DATA_ROOT
from app.schemas.requirement import ItemType, RequirementType, ReviewStatus
from app.services import item_classifier

CORRECTION_DIR = DATA_ROOT / "public" / "corrections"


class ItemCorrectionRequest(BaseModel):
    reviewer: str = Field(min_length=1, max_length=60)
    review_status: Literal["confirmed", "corrected", "rejected"]
    item_type: ItemType | None = None
    requirement_type: RequirementType | None = None
    category: str | None = Field(default=None, max_length=40)
    title: str | None = Field(default=None, max_length=120)
    content: str | None = Field(default=None, min_length=1, max_length=2000)
    page: int | None = Field(default=None, ge=1)
    note: str | None = Field(default=None, max_length=1000)


class ItemCorrection(BaseModel):
    id: str
    procurement_id: str
    requirement_id: str
    reviewer: str
    review_status: ReviewStatus
    changes: dict[str, Any]
    note: str | None = None
    corrected_at: datetime


class CorrectionHistory(BaseModel):
    procurement_id: str
    corrections: list[ItemCorrection]
    schema_version: int = 2


class GoldExportItem(BaseModel):
    id: str
    procurement_id: str
    requirement_id: str
    category: str
    requirement_type: RequirementType
    item_type: ItemType
    content: str
    page: int | None
    source_text: str
    status: str
    review_status: ReviewStatus
    reviewer: str | None


class GoldExport(BaseModel):
    _note: str = "사람이 확정한 항목만 담은 Gold 데이터셋. 파서 입력으로 쓰지 않는다 (평가 전용)."
    procurement_id: str
    document: str
    page_count: int
    exported_at: datetime
    confirmed_count: int
    rejected_count: int
    requirements: list[GoldExportItem]


#: 표 파일 머리(45차 M20 — 「확정항목.json」은 영어 열쇠라 담당자가 열어 볼 수 없었다)
GOLD_CSV_HEADER: tuple[str, ...] = ("항목 코드", "유형", "필수 여부", "내용", "쪽", "원문", "담당자 확인", "확인한 사람")
_REVIEW_WORDS: dict[str, str] = {"confirmed": "확정(그대로 맞음)", "corrected": "정정", "rejected": "반려(항목 아님)"}


_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _csv_cell(value: object) -> object:
    """엑셀이 수식으로 읽을 칸은 글자로(앞에 '). 숫자 · 빈 칸은 그대로."""
    return f"'{value}" if isinstance(value, str) and value.startswith(_FORMULA_START) else value


def gold_csv(gold: "GoldExport") -> str:
    """확인한 항목을 엑셀에서 바로 여는 표(UTF-8 BOM · 한국어 머리). 값은 Gold 와 같다."""
    import csv
    import io

    from app.services.item_classifier import ITEM_TYPE_LABEL, display_code

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(GOLD_CSV_HEADER)
    for item in gold.requirements:
        writer.writerow([_csv_cell(cell) for cell in (
            display_code(item.item_type, item.requirement_id),
            ITEM_TYPE_LABEL.get(item.item_type, item.item_type),
            "필수" if item.requirement_type == "mandatory" else "선택",
            item.content,
            item.page if item.page is not None else "",
            item.source_text,
            _REVIEW_WORDS.get(item.review_status, item.review_status),
            item.reviewer or "",
        )])
    return "\ufeff" + buffer.getvalue()


class NoConfirmedItemsError(LookupError):
    """확정한 항목이 없어 Gold를 만들 수 없다."""


def history_path(procurement_id: str) -> Path:
    return CORRECTION_DIR / f"{storage.safe_id(procurement_id, what='공고 id')}.corrections.json"


def load_history(procurement_id: str) -> CorrectionHistory:
    payload = storage.read_json(history_path(procurement_id), default=None)
    if not isinstance(payload, dict):
        return CorrectionHistory(procurement_id=procurement_id, corrections=[])
    return CorrectionHistory.model_validate(payload)


def _save(history: CorrectionHistory) -> None:
    payload = history.model_dump(mode="json")
    storage.stamp(payload)
    storage.write_json_atomic(history_path(history.procurement_id), payload)


def add_correction(procurement_id: str, requirement_id: str, request: ItemCorrectionRequest) -> ItemCorrection:
    history = load_history(procurement_id)
    changes = {
        key: value
        for key, value in request.model_dump().items()
        if key in ("item_type", "requirement_type", "category", "title", "content", "page") and value is not None
    }
    entry = ItemCorrection(
        id=f"COR-{len(history.corrections) + 1:04d}",
        procurement_id=procurement_id,
        requirement_id=requirement_id,
        reviewer=request.reviewer,
        review_status=request.review_status,
        changes=changes,
        note=request.note,
        corrected_at=datetime.now(timezone.utc),
    )
    history.corrections.append(entry)
    _save(history)
    return entry


def latest_by_requirement(procurement_id: str) -> dict[str, ItemCorrection]:
    latest: dict[str, ItemCorrection] = {}
    for correction in load_history(procurement_id).corrections:
        latest[correction.requirement_id] = correction
    return latest


def apply_to_payload(procurement_id: str, payload: dict[str, Any]) -> int:
    """저장된 추출 결과(dict)에 최신 정정을 덧입힌다. 적용한 항목 수를 돌려준다."""
    try:
        latest = latest_by_requirement(procurement_id)
    except storage.CorruptJsonError:
        return 0
    if not latest:
        return 0
    applied = 0
    for req in payload.get("requirements", []):
        if not isinstance(req, dict):
            continue
        correction = latest.get(str(req.get("requirement_id")))
        if correction is None:
            continue
        req.update(correction.changes)
        req["review_status"] = correction.review_status
        req["extraction_method"] = "HUMAN"
        # 유형이 바뀌면 화면 코드·중대성도 다시 계산한다 (저장 id는 그대로).
        item_type = req.get("item_type", "REQUIREMENT")
        req["display_code"] = item_classifier.display_code(item_type, str(req.get("requirement_id")))
        req["criticality"] = item_classifier.criticality_of(
            item_type,
            str(req.get("requirement_type", "mandatory")),
            str(req.get("content", "")),
            str(req.get("source_text", "")),
            category=str(req.get("category") or ""),  # 평가 증빙은 확인해도 「참가 차단」이 아니다(classify_fields 와 같은 셈)
        )
        req["action_required"] = item_classifier.action_required_of(item_type, str(req.get("requirement_type", "mandatory")))
        applied += 1
    return applied


def export_gold(procurement_id: str, parse_payload: dict[str, Any]) -> GoldExport:
    """확정(confirmed/corrected) 항목만 Gold 형식으로 만든다. 없으면 오류."""
    latest = latest_by_requirement(procurement_id)
    items: list[GoldExportItem] = []
    rejected = 0
    for req in parse_payload.get("requirements", []):
        if not isinstance(req, dict):
            continue
        correction = latest.get(str(req.get("requirement_id")))
        if correction is None:
            continue
        if correction.review_status == "rejected":
            rejected += 1
            continue
        merged = {**req, **correction.changes}
        items.append(
            GoldExportItem(
                id=f"gold-{procurement_id}-{str(merged['requirement_id']).split('-')[-1]}",
                procurement_id=procurement_id,
                requirement_id=str(merged["requirement_id"]),
                category=str(merged.get("category") or "미분류"),
                requirement_type=merged.get("requirement_type", "mandatory"),
                item_type=merged.get("item_type", "REQUIREMENT"),
                content=str(merged.get("content") or ""),
                page=merged.get("page"),
                source_text=str(merged.get("source_text") or ""),
                status=str(merged.get("status") or "unmatched"),
                review_status=correction.review_status,
                reviewer=correction.reviewer,
            )
        )
    if not items:
        raise NoConfirmedItemsError(procurement_id)
    return GoldExport(
        procurement_id=procurement_id,
        document=str(parse_payload.get("document") or ""),
        page_count=int(parse_payload.get("page_count") or 0),
        exported_at=datetime.now(timezone.utc),
        confirmed_count=len(items),
        rejected_count=rejected,
        requirements=items,
    )
