"""회사 자료 임베딩 인덱스 생성.

입력 : data/synthetic_company/docs/*.md  (front matter + 문단)
출력 : data/synthetic_company/index/company_index.json
사용 : backend/.venv/Scripts/python.exe scripts/build_company_index.py
       ... --query "교육은 총 12회 운영해야 하며 회차당 3시간"   (검색 품질 확인)

인덱스 형식은 docs/team_plan.md의 계약을 따른다. 팀원이 문서를 다듬어 다시 실행하면
같은 형식으로 갱신되고, 매칭 코드는 수정 없이 새 인덱스를 쓴다.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.services import company_index_service as cis  # noqa: E402
from app.services import llm_client  # noqa: E402

DOCS_DIR = cis.SYNTHETIC_DOCS_DIR
INDEX_DIR = cis.SYNTHETIC_INDEX_FILE.parent
INDEX_FILE = cis.SYNTHETIC_INDEX_FILE

KST = cis.KST
MIN_CHUNK_CHARS = cis.MIN_CHUNK_CHARS

# 규칙 본체는 backend/app/services/company_index_service.py 에 있다 (업로드 파이프라인과 공유).
# 이름은 예전 그대로 두어 기존 테스트·문서가 깨지지 않게 한다.
is_gap_chunk = cis.is_gap_chunk
_flag = cis.flag
parse_front_matter = cis.parse_front_matter
split_chunks = cis.split_chunks


def build() -> dict:
    entries, skipped, file_count = cis.markdown_entries(DOCS_DIR)
    if file_count == 0:
        raise SystemExit(f"문서가 없습니다: {DOCS_DIR}")
    if skipped:
        print(f"근거가 아닌 '확인되지 않은 사항' 문단 {len(skipped)}개를 제외했습니다.")
    print(f"문서 {file_count}건 -> chunk {len(entries)}건, 임베딩 생성 중...")

    from app.core.config import get_settings

    return cis.build_index_payload(
        entries,
        embed=llm_client.embed,
        model=get_settings().embedding_model,
        document_count=file_count,
        note=(
            "회사자료 임베딩 인덱스. 문서마다 synthetic/anonymized 값을 그대로 담는다 "
            "— 합성 문서와 비식별 처리한 실제 문서를 화면에서 구분하기 위함."
        ),
    )


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def search(index: dict, query: str, top: int = 3) -> None:
    vector = llm_client.embed([query])[0]
    scored = sorted(
        ((cosine(vector, c["embedding"]), c) for c in index["chunks"]),
        key=lambda p: p[0],
        reverse=True,
    )
    print(f'\n질의: "{query}"')
    for score, chunk in scored[:top]:
        print(f"  {score:.3f}  [{chunk['evidence_id']} {chunk['doc_type']} p.{chunk['page']}] {chunk['document_name']}")
        print(f"         {chunk['source_text'][:100]}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", action="append", default=[], help="인덱스 생성 후 검색 품질 확인")
    parser.add_argument("--reuse", action="store_true", help="기존 인덱스를 다시 쓰고 검색만 수행")
    args = parser.parse_args()

    if args.reuse and INDEX_FILE.exists():
        index = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        print(f"기존 인덱스 사용: chunk {index['chunk_count']}건")
    else:
        index = build()
        INDEX_DIR.mkdir(parents=True, exist_ok=True)
        tmp = INDEX_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
        tmp.replace(INDEX_FILE)
        size_kb = INDEX_FILE.stat().st_size / 1024
        print(f"저장: {INDEX_FILE.relative_to(REPO_ROOT)} ({size_kb:.0f}KB, chunk {index['chunk_count']}건)")

    for query in args.query:
        search(index, query)


if __name__ == "__main__":
    main()
