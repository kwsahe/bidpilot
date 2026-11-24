"""범용 설치 키트 첫 실행 — 기본 회사와 프로필을 만든다 (30차 §3-G).

kit_setup.ps1 이 백엔드를 띄우기 **전에** 키트의 venv 파이썬으로 부른다(회사 이름은 화면에서 못 고치므로 먼저 받는다).
검증 규칙을 다시 쓰지 않고 기존 함수(`ensure_default_organization` · `save_profile`)로 저장한다. 값은 화면에 찍지 않는다.

    backend\\.venv\\Scripts\\python.exe scripts\\kit_first_run.py --name "주식회사 시험" --domains "AI 교육, 컨설팅" --regions ""
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _split(text: str) -> list[str]:
    return [part.strip() for part in (text or "").replace("·", ",").split(",") if part.strip()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--domains", default="")
    parser.add_argument("--regions", default="")
    args = parser.parse_args()

    os.environ["DEFAULT_ORGANIZATION_NAME"] = args.name.strip()
    os.chdir(ROOT / "backend")  # 설정은 backend 기준 ../.env 를 읽는다
    sys.path.insert(0, str(ROOT / "backend"))
    from app.schemas.organization import OrganizationProfileUpdate
    from app.services import organization_service

    org = organization_service.ensure_default_organization()
    profile = organization_service.load_profile(org.organization_id)
    if profile.source == "file":
        print(f"  [OK]   회사 프로필이 이미 있습니다 ({org.organization_id}) — 그대로 둡니다")
        return 0
    organization_service.save_profile(
        org.organization_id,
        OrganizationProfileUpdate(
            name=args.name.strip(),
            business_domains=_split(args.domains),
            preferred_regions=_split(args.regions),
            data_class="real",
            updated_by="키트 첫 실행",
        ),
    )
    print(f"  [OK]   회사를 만들었습니다 ({org.organization_id}) · 사업영역 {len(_split(args.domains))}개 · 활동 지역 {len(_split(args.regions))}개")
    return 0


if __name__ == "__main__":
    sys.exit(main())
