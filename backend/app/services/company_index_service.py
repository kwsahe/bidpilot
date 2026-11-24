"""회사자료 근거 색인(임베딩 인덱스) 공통 규칙.

`scripts/build_company_index.py`(CLI)와 `company_service`(업로드 파이프라인)가 같은 함수를 쓴다.
CLI는 합성 마크다운(data/synthetic_company/docs)으로 **합성 인덱스**를 만들고,
업로드 파이프라인은 담당자가 승인한 후보만으로 **회사 인덱스**(data/company/index)를 만든다.
두 인덱스는 파일이 다르고, evidence_service가 읽을 때 합친다 (각 chunk에 출처 메타데이터가 붙는다).

원칙
- "확인되지 않은 사항" 문단은 근거가 아니라 공백이다. 인덱스에 넣지 않는다.
- 임베딩 키가 없으면 인덱스를 만들지 않는다. 가짜 벡터를 넣지 않는다.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from app.core import storage
from app.core.paths import DATA_ROOT, REPO_ROOT  # REPO_ROOT 는 index_summary 의 경로 라벨 표시용

SYNTHETIC_DOCS_DIR = DATA_ROOT / "synthetic_company" / "docs"
SYNTHETIC_INDEX_FILE = DATA_ROOT / "synthetic_company" / "index" / "company_index.json"
COMPANY_INDEX_FILE = DATA_ROOT / "company" / "index" / "company_index.json"

KST = timezone(timedelta(hours=9))
MIN_CHUNK_CHARS = 30
_FRONT_MATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.S)

# "확인되지 않은 사항" 절은 **근거가 아니라 공백**이다. 인덱스에 넣으면
# 코사인 유사도가 어휘만 보고 골라 "확인되지 않았습니다"를 충족 근거로 인용한다.
# 실측 사고: REQ-030에 "증빙 서류 목록은 공개 자료에서 확인되지 않았습니다"가 0.608로 채택됨.
_GAP_SECTION_RE = re.compile(r"^\s*(?:#+\s*)?(?:확인되지\s*않은|미확인|확인\s*필요|확인할\s*수\s*없)")
_GAP_SENTENCE_RE = re.compile(r"확인되지\s*않았습니다|확인할\s*수\s*없습니다|공개되(?:어\s*있지|지)\s*않")


def is_gap_chunk(chunk: str) -> bool:
    """근거가 아니라 '확인하지 못한 것'을 적은 문단인지."""
    if _GAP_SECTION_RE.search(chunk):
        return True
    return bool(_GAP_SENTENCE_RE.search(chunk))


def flag(meta: dict[str, str], key: str, *, default: bool) -> bool:
    """front matter의 true/false 문자열을 bool로 읽는다."""
    raw = meta.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in ("true", "yes", "1")


def parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    match = _FRONT_MATTER_RE.match(text)
    if not match:
        return {}, text
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
    return meta, text[match.end() :]


def split_chunks(body: str, *, keep_quotes: bool = False) -> list[str]:
    """빈 줄 기준 문단 분할. 너무 짧은 조각은 앞 문단에 합친다. 인용(>)·머리글(#)은 제외.

    `keep_quotes=True` 면 인용 표시(`>`)를 벗겨 본문으로 쓴다.
    인용을 버리는 것은 문서 맨 앞의 도구 안내문을 걸러내기 위한 규칙인데,
    본문 전체가 인용으로 적힌 문서에서는 문단이 하나도 남지 않는다 —
    실제로 `06_curriculum.md` 가 그래서 「추출 실패」로 표시됐다.
    호출부가 0개를 받으면 이 옵션으로 한 번 더 시도한다.
    """
    chunks: list[str] = []
    for block in re.split(r"\n\s*\n", body):
        lines = []
        for line in block.strip().splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith(">"):
                if not keep_quotes:
                    continue
                stripped = stripped.lstrip(">").strip()
                if not stripped:
                    continue
            lines.append(stripped)
        cleaned = "\n".join(lines).strip()
        if not cleaned:
            continue
        # 제목만 있는 블록은 다음 문단의 접두사로 쓴다.
        if cleaned.startswith("#"):
            heading = cleaned.lstrip("#").strip()
            chunks.append(f"[{heading}]")
            continue
        if chunks and chunks[-1].startswith("[") and chunks[-1].endswith("]"):
            heading = chunks.pop()[1:-1]
            cleaned = f"{heading}: {cleaned}"
        if len(cleaned) < MIN_CHUNK_CHARS and chunks:
            chunks[-1] = f"{chunks[-1]} {cleaned}"
        else:
            chunks.append(cleaned)
    return [c for c in chunks if not (c.startswith("[") and c.endswith("]"))]


def markdown_entries(docs_dir: Path = SYNTHETIC_DOCS_DIR) -> tuple[list[dict[str, Any]], list[str], int]:
    """마크다운 문서 폴더 → (chunk 항목, 제외한 공백 문단 라벨, 문서 수). 임베딩은 아직 없다."""
    files = sorted(docs_dir.glob("*.md"))
    entries: list[dict[str, Any]] = []
    skipped: list[str] = []
    for doc_index, path in enumerate(files, start=1):
        meta, body = parse_front_matter(path.read_text(encoding="utf-8"))
        evidence_id = f"EV-{doc_index:02d}"
        for page, chunk in enumerate(split_chunks(body), start=1):
            if is_gap_chunk(chunk):
                skipped.append(f"{path.name} p{page}")
                continue
            entries.append(
                {
                    "evidence_id": evidence_id,
                    "document_name": meta.get("document_name", path.stem),
                    "doc_type": meta.get("doc_type", "기타"),
                    "page": page,
                    "source_text": chunk,
                    # front matter 값을 그대로 옮긴다. 하드코딩하면 실제 자료에
                    # "합성" 배지가 붙어 화면이 거짓말을 한다.
                    "synthetic": flag(meta, "synthetic", default=True),
                    "anonymized": flag(meta, "anonymized", default=False),
                    "source_file": path.name,
                    "source_kind": "markdown",
                    "data_class": "synthetic" if flag(meta, "synthetic", default=True) else ("anonymized" if flag(meta, "anonymized", default=False) else "real"),
                }
            )
    return entries, skipped, len(files)


def build_index_payload(
    entries: list[dict[str, Any]],
    *,
    embed: Callable[[list[str]], list[list[float]]],
    model: str | None,
    document_count: int,
    note: str,
) -> dict[str, Any]:
    """chunk 항목에 임베딩을 붙여 인덱스 문서를 만든다. embed는 llm_client.embed 같은 함수."""
    vectors = embed([e["source_text"] for e in entries]) if entries else []
    for entry, vector in zip(entries, vectors, strict=True):
        entry["embedding"] = vector
    payload: dict[str, Any] = {
        "_note": note,
        "model": model,
        "built_at": datetime.now(KST).isoformat(),
        "document_count": document_count,
        "chunk_count": len(entries),
        "chunks": entries,
    }
    return storage.stamp(payload)


def index_summary(path: Path) -> dict[str, Any]:
    """인덱스 파일의 요약 (있으면). 벡터는 읽지 않고 헤더만 본다."""
    try:
        label = str(path.relative_to(REPO_ROOT))
    except ValueError:
        label = path.name
    try:
        payload = storage.read_json(path, default=None)
    except storage.CorruptJsonError:
        payload = None
    if not isinstance(payload, dict):
        return {"exists": False, "path": label, "built_at": None, "chunk_count": 0, "document_count": 0, "model": None}
    return {
        "exists": True,
        "path": label,
        "built_at": payload.get("built_at"),
        "chunk_count": int(payload.get("chunk_count") or len(payload.get("chunks", []))),
        "document_count": int(payload.get("document_count") or 0),
        "model": payload.get("model"),
    }
