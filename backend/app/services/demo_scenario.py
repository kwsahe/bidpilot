"""대시보드 시연용 합성 시나리오 로더.

등록된 procurement_id에 대해서만 data/synthetic_company 아래 JSON을 읽는다.
실제 Evidence Mapping / Proposal / Auditor가 구현되면 이 모듈을 실서비스 호출로 교체한다.
"""

from app.core.paths import DATA_ROOT
from app.schemas.demo import DemoCosmosScenario

SYNTHETIC_DIR = DATA_ROOT / "synthetic_company"

DEMO_SCENARIOS: dict[str, str] = {
    "synthetic-rfp-0001": "demo_cosmos_scenario.json",
}


class DemoScenarioNotFoundError(LookupError):
    """등록되지 않은 procurement_id."""


def load_demo_scenario(procurement_id: str) -> DemoCosmosScenario:
    file_name = DEMO_SCENARIOS.get(procurement_id)
    if file_name is None:
        raise DemoScenarioNotFoundError(procurement_id)
    path = SYNTHETIC_DIR / file_name
    if not path.is_file():
        # 자료 폴더에 합성 자료가 빠진 사본(10-31 촬영 환경) — 처리 못 한 500 대신 404 로 까닭을 알린다
        raise DemoScenarioNotFoundError(procurement_id)
    return DemoCosmosScenario.model_validate_json(path.read_text(encoding="utf-8"))
