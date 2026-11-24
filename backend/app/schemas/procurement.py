from datetime import datetime

from pydantic import BaseModel, Field


class ProcurementNotice(BaseModel):
    """나라장터 공고 1건의 내부 표준 모델.

    실제 나라장터 OpenAPI 응답 필드와의 매핑은
    실제 응답을 확인한 뒤에 작성한다 (CLAUDE.md 25-4, 25-5).
    """

    id: str
    notice_no: str
    title: str
    agency: str
    published_at: datetime
    deadline_at: datetime | None = None
    budget: int | None = None
    region: str | None = None
    description: str | None = None
    source_url: str | None = None
    raw_data: dict = Field(default_factory=dict)
    # 같은 공고번호로 묶인 차수(정정·재공고) 개수. 1이면 묶인 것이 없다.
    # 화면에는 최신 차수 하나만 보이므로, 몇 건이 접혔는지 알려 주기 위해 남긴다.
    revision_count: int = 1
