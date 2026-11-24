"""기업마당(bizinfo.go.kr) 실응답 확인 — 필드 매핑 검증 + 캐시 저장.

    backend/.venv/Scripts/python.exe scripts/verify_bizinfo_api.py                # 실호출 → 필드 대조 → 캐시 저장
    backend/.venv/Scripts/python.exe scripts/verify_bizinfo_api.py --count 20     # 가져올 건수
    backend/.venv/Scripts/python.exe scripts/verify_bizinfo_api.py --no-cache     # 캐시 저장 없이 확인만

무엇을 하나:
- BIZINFO_API_KEY(.env)로 실제 목록을 부르고, 응답의 **실제 필드명**을 매퍼가 기대하는 문서 필드명과 대조한다.
- 각 필드가 몇 건에서 실제로 값이 있는지, 매핑 후 어떤 값이 비는지 센다.
- 모두 채워지면 bizinfo_service.FIELD_MAPPING_VERIFIED 를 True 로 바꾸라고 알려 준다 (자동으로 바꾸지 않는다).
- 성공하면 실응답을 캐시에 저장한다 (API 장애 시 화면 대체용, CLAUDE.md 20).

원칙:
- 인증키는 출력·로그·저장 파일 어디에도 남기지 않는다 (CLAUDE.md 21).
- 응답이 문서와 다르면 이 스크립트가 아니라 bizinfo_service.map_program 을 고친다.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.services import bizinfo_client, bizinfo_service  # noqa: E402

# map_program 이 읽는 문서 필드 (bizinfo_service.map_program 과 같은 순서)
EXPECTED_FIELDS: tuple[tuple[str, str, bool], ...] = (
    ("pblancId", "공고 ID", True),
    ("pblancNm", "지원사업명", True),
    ("jrsdInsttNm", "소관기관", False),
    ("excInsttNm", "수행기관", False),
    ("bsnsSumryCn", "사업 개요", False),
    ("reqstBeginEndDe", "신청 기간", False),
    ("pldirSportRealmLclasCodeNm", "지원분야 대분류", False),
    ("pldirSportRealmMlsfcCodeNm", "지원분야 중분류", False),
    ("hashtags", "해시태그", False),
    ("trgetNm", "지원 대상", False),
    ("pblancUrl", "공고 링크", False),
    ("creatPnttm", "등록 일시", False),
)

# map_program 결과에서 비었는지 확인할 모델 필드
MAPPED_FIELDS = (
    "agency",
    "executing_agency",
    "summary",
    "apply_start",
    "apply_end",
    "category",
    "subcategory",
    "hashtags",
    "target",
    "url",
    "created_at",
)


def _filled(items: list[dict[str, Any]], key: str) -> int:
    return sum(1 for item in items if str(item.get(key) or "").strip())


def _bar(n: int, total: int, width: int = 20) -> str:
    if total <= 0:
        return " " * width
    filled = round(width * n / total)
    return "█" * filled + "·" * (width - filled)


async def run(count: int, write_cache: bool) -> int:
    if not bizinfo_client.is_configured():
        print("BIZINFO_API_KEY 가 설정되지 않았습니다.")
        print(f"  {REPO_ROOT / '.env'} 의 BIZINFO_API_KEY= 뒤에 발급받은 인증키를 붙여 넣고 다시 실행하세요.")
        print("  (.env 는 git 추적 대상이 아니며, 키는 backend 에서만 씁니다.)")
        return 2

    print(f"기업마당 실호출 — {bizinfo_client.BASE_URL} (searchCnt={count})")
    try:
        body = await bizinfo_client.fetch_programs_raw(count=count)
    except bizinfo_client.BizinfoError as exc:
        # 메시지는 client 가 이미 인증키를 가린 상태다.
        print(f"\n실패: {exc}")
        print("  인증키가 승인 대기 상태이거나 허용 IP·일일 호출 한도 문제일 수 있습니다. 기업마당 마이페이지에서 키 상태를 확인하세요.")
        return 1

    root_keys = sorted(body.keys())
    items = bizinfo_client.extract_items(body)
    print(f"응답 루트 키: {root_keys}")
    print(f"받은 항목 수: {len(items)}")
    if not items:
        print("\n항목이 0건입니다. 응답 구조가 문서와 다를 수 있습니다 — 위 루트 키를 보고 extract_items 를 고치세요.")
        return 1

    # ---------------------------------------------------------------- 필드 대조
    print("\n[1] 문서 필드명 대조 — 매퍼가 기대하는 이름이 실응답에 있는가")
    print(f"  {'필드':<30} {'의미':<14} {'값 있는 건수':>12}")
    missing_required: list[str] = []
    missing_optional: list[str] = []
    for key, label, required in EXPECTED_FIELDS:
        n = _filled(items, key)
        present = any(key in item for item in items)
        mark = "OK " if n else ("없음" if not present else "빈값")
        if not n:
            (missing_required if required else missing_optional).append(key)
        print(f"  {key:<30} {label:<14} {n:>5}/{len(items)}  {_bar(n, len(items))} {mark}")

    actual_keys: set[str] = set()
    for item in items:
        actual_keys.update(item.keys())
    extra = sorted(actual_keys - {k for k, _l, _r in EXPECTED_FIELDS})
    if extra:
        print(f"\n  매퍼가 쓰지 않는 응답 필드 {len(extra)}개: {', '.join(extra[:20])}{' …' if len(extra) > 20 else ''}")

    # ---------------------------------------------------------------- 매핑 결과
    print("\n[2] map_program 매핑 결과")
    programs = [bizinfo_service.map_program(item) for item in items]
    mapped = [p for p in programs if p is not None]
    print(f"  매핑 성공 {len(mapped)}/{len(items)}건 (id·제목이 없으면 건너뜁니다)")
    if mapped:
        for field in MAPPED_FIELDS:
            n = sum(1 for p in mapped if getattr(p, field))
            print(f"  {field:<20} {n:>5}/{len(mapped)}  {_bar(n, len(mapped))}")
        first = mapped[0]
        print("\n  첫 건 예시 (공개 정보):")
        print(f"    {first.title}")
        print(f"    {first.agency} · {first.category or '분야 미상'} · 신청 {first.apply_start or '?'} ~ {first.apply_end or '?'}")
        print(f"    {first.url or '링크 없음'}")

    # ---------------------------------------------------------------- 캐시
    if write_cache:
        # 크게 줄어드는 저장은 막힌다 (ISSUE-121). 막혔으면 그 사유를 그대로 적는다 —
        # 「저장했다」고 적어 놓고 실제로는 안 쓰인 것이 가장 나쁘다.
        shrink = bizinfo_service._save_cache(items, datetime.now(timezone.utc))
        if shrink:
            print(f"\n[3] 캐시 저장 **거부**: {shrink}")
        else:
            print(f"\n[3] 캐시 저장: {bizinfo_service.CACHE_FILE.relative_to(REPO_ROOT)} ({len(items)}건, 인증키 미포함)")
    else:
        print("\n[3] 캐시 저장 건너뜀 (--no-cache)")

    # ---------------------------------------------------------------- 판정
    print("\n[판정]")
    if missing_required:
        print(f"  필수 필드가 비었습니다: {', '.join(missing_required)}")
        print("  → bizinfo_service.map_program 의 필드명을 실응답에 맞게 고치세요. FIELD_MAPPING_VERIFIED 는 False 로 두세요.")
        return 1
    if missing_optional:
        print(f"  선택 필드 {len(missing_optional)}개가 모든 건에서 비었습니다: {', '.join(missing_optional)}")
        print("  → 해당 필드가 실제로 다른 이름인지 확인하고 매퍼를 고치세요. 고친 뒤 다시 실행하세요.")
        return 1
    print("  기대한 필드가 모두 실응답에 있습니다.")
    print("  → backend/app/services/bizinfo_service.py 의 FIELD_MAPPING_VERIFIED = True 로 바꾸고,")
    print("     README.md·docs/limitations.md 의 「기업마당 API 실응답 미확인」 항목을 확인 완료로 갱신하세요.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="기업마당 실응답 확인 및 필드 매핑 검증")
    parser.add_argument("--count", type=int, default=bizinfo_client.DEFAULT_COUNT, help="가져올 건수 (기본 100)")
    parser.add_argument("--no-cache", action="store_true", help="캐시 파일을 저장하지 않는다")
    args = parser.parse_args()
    return asyncio.run(run(args.count, write_cache=not args.no_cache))


if __name__ == "__main__":
    raise SystemExit(main())
