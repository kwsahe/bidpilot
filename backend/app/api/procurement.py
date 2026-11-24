from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.core import identity
from app.services import procurement_service

router = APIRouter(prefix="/api", tags=["procurement"])


def refresh_was_ignored(request: Request) -> bool:
    """옛 클라이언트가 `?refresh=…` 를 보냈는가 (N1).

    이 라우트는 더 이상 그 값을 읽지 않는다. 그래도 **조용히 무시하지는 않는다** —
    보낸 쪽은 「다시 받아 왔다」고 믿고 화면에 옛 목록을 새것처럼 보여줄 수 있다.
    응답에 `refresh_ignored: true` 를 실어 그 오해를 끊는다.
    """
    return identity.is_truthy_query(str(request.url.query), "refresh")


@router.get("/procurements")
async def list_procurements(
    request: Request,
    days: int = Query(default=14, ge=1, le=60, description="공고게시일 기준 조회 기간(일)"),
    include_low: bool = Query(default=False, description="업무 키워드만 맞는 공고도 포함"),
) -> dict[str, Any]:
    """나라장터 AI·AI교육 공고 후보 목록. **조회만 한다.**

    실호출이 실패하면 캐시로 대체하고 source='cached'로 표시한다 (CLAUDE.md 20).

    `refresh` 파라미터는 **없앴다** (N1 · S8). 다시 받아 오는 것은 바깥을 부르고 캐시 파일을
    덮어쓰는 일이라 조회가 아니다. `POST /api/procurements/refresh` 를 쓴다.

    왜 「쓰기 취급 GET」만으로 부족했나: 판정은 쿼리 문자열을 눈으로 훑어 `1·true·yes·on`
    만 봤는데, 프레임워크는 `t`·`y` 도 참으로 읽고 `%31` 은 디코딩되어 `1` 이 된다.
    그래서 `?refresh=t` 는 판정에서 읽기, 라우트에서 새로고침이 됐다 — 열람자가 막히지도
    기록되지도 않은 채 실호출을 일으킬 수 있었다. 판정도 고쳤지만(같은 파싱을 쓴다),
    **애초에 그 길을 없애는 것**이 맞다.
    """
    try:
        result = await procurement_service.list_ai_candidates(days=days, include_low=include_low)
    except procurement_service.NoNoticeDataError as exc:
        raise HTTPException(status_code=503, detail=f"나라장터 조회 실패, 캐시도 없음: {exc}")
    payload = result.to_dict()
    if refresh_was_ignored(request):
        payload["refresh_ignored"] = True
    return payload


@router.post("/procurements/refresh")
async def refresh_procurements(
    days: int = Query(default=14, ge=1, le=60, description="공고게시일 기준 조회 기간(일)"),
    include_low: bool = Query(default=False, description="업무 키워드만 맞는 공고도 포함"),
) -> dict[str, Any]:
    """목록을 **다시 받아온다** (S8).

    `GET /api/procurements?refresh=true` 와 같은 일을 하지만 POST 다. 이 호출은 조회가
    아니라 바깥을 바꾸는 일이기 때문이다 — 나라장터를 실제로 부르고 그 결과로 저장소가
    추적하는 캐시 파일을 덮어쓴다. POST 라야 역할 검사(편집자 이상)와 활동 기록이 붙고,
    다른 사이트의 링크 한 번으로 도달하지 않는다.

    시연 고정 모드(`G2B_LIVE_FETCH=0`)에서는 이 경로도 캐시만 읽는다 — 고정이 먼저다.
    옛 GET 경로는 그대로 두되 미들웨어가 «쓰기»로 취급한다(identity.WRITE_LIKE_GET_PATHS).
    """
    try:
        result = await procurement_service.list_ai_candidates(
            days=days, include_low=include_low, refresh=True
        )
    except procurement_service.NoNoticeDataError as exc:
        raise HTTPException(status_code=503, detail=f"나라장터 조회 실패, 캐시도 없음: {exc}")
    return result.to_dict()


@router.get("/procurements/{notice_id}")
async def get_procurement(notice_id: str) -> dict[str, Any]:
    view = await procurement_service.get_notice(notice_id)
    if view is None:
        raise HTTPException(status_code=404, detail="Notice not found in current candidate window")
    return view.to_dict()
