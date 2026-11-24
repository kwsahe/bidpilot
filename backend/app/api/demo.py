from fastapi import APIRouter, HTTPException

from app.schemas.demo import DemoCosmosScenario
from app.services import demo_scenario

router = APIRouter(prefix="/api/demo", tags=["demo"])


@router.get("/cosmos/{procurement_id}", response_model=DemoCosmosScenario)
async def get_demo_cosmos_scenario(procurement_id: str) -> DemoCosmosScenario:
    """대시보드 시연용 합성 Evidence/Proposal/Auditor 시나리오 (source=demo_synthetic)."""
    try:
        return demo_scenario.load_demo_scenario(procurement_id)
    except demo_scenario.DemoScenarioNotFoundError:
        raise HTTPException(status_code=404, detail="가상 예시 시나리오가 없습니다 — 자료 폴더의 synthetic_company 를 확인하세요")
