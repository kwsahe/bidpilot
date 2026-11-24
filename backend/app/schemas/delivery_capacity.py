"""개발 수행역량 — 회사가 «실제로 무엇을 할 수 있는가»를 담는 회사자료.

공고 쪽 사실(과업·자격요건)만으로는 「우리가 이걸 할 수 있나」를 답할 수 없다.
반대편 사실이 있어야 하는데, 그건 **회사가 적는 것이지 시스템이 추정할 값이 아니다**
(CLAUDE.md 11장: 근거 없는 회사정보 생성 금지).

그래서 이 파일의 규율은 하나다.

    **모르는 것은 `None` 이고, `None` 은 «없다»가 아니라 «확인되지 않았다»다.**

    - `developer_count=None`  → 인원 규모를 판정하지 않는다. 3으로 가정하지 않는다.
    - `budget_ceiling_krw=None` → 예산 상한을 판정하지 않는다. 코드 상수로 대신하지 않는다.
    - `credentials[].held=None` → 자격 보유 여부를 판정하지 않는다. 「미보유」로 적지 않는다.
    - `skills` 목록에 **없는** 기술은 «모른다»이지 «못 한다»가 아니다.
      못 한다고 말하려면 사람이 `level="none"` 으로 **적어 넣어야** 한다.

`OrganizationProfile` 을 넓히지 않고 파일을 따로 둔 이유: 프로필은 상호·주소처럼
«회사가 무엇인가»를 적는 자리고, 여기는 «회사가 무엇을 할 수 있는가»라 갱신 주기와
근거의 성격이 다르다. 프로필 스키마를 건드리면 서식 자동채움·스냅샷까지 함께 움직인다.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

DELIVERY_CAPACITY_SCHEMA_VERSION = 1

#: 「확인했는데 없다」를 적는 말 (0924 §4-A-4).
#:
#: 빈 목록은 「모른다」이고 판정은 「확인 필요」로 간다. 담당자가 실제로 확인해 「없다」를
#: 적으면 판정이 「불가」로 갈 수 있어야 한다 — 두 사실은 다르다.
NONE_CONFIRMED: str = "없음 확인"

#: 사업기회를 **어떤 순서로 보여 주나** (37차 · 담당자 결정 2026-10-14).
#:
#: score     — 회사 기준 검토 우선순위 점수순(동점이면 마감 빠른 순). 기본값이다.
#: practical — 실무 우선순위(신규 · 준비기간 우선 · 마감 임박은 아래 긴급 칸). 샘플에듀 = 사업담당자 방식.
#: **점수는 어느 방식에서나 같다** — 방식은 순서와 분류 칸만 정한다(CLAUDE.md §12).
RankingMethod = Literal["score", "practical"]
DEFAULT_RANKING_METHOD: RankingMethod = "score"

#: 기술 보유 상태. **중간값을 두지 않는다** — 「조금 할 줄 안다」는 사람이 note 에 적는다.
#: proven : 실제로 수행해 본 영역 (근거를 함께 적는다)
#: none   : 갖고 있지 않다고 **담당자가 적은** 것. 시스템이 채우지 않는다.
SkillLevel = Literal["proven", "none"]


class SkillEntry(BaseModel):
    """회사가 보유(또는 미보유)를 명시한 기술 하나."""

    name: str = Field(min_length=1, max_length=60)
    level: SkillLevel
    #: 같은 뜻으로 공고에 등장하는 다른 표기. 공고 문구와 맞춰 보는 데 쓴다.
    aliases: list[str] = Field(default_factory=list)
    note: str | None = Field(default=None, max_length=400)
    #: 이 사실을 누가·무엇을 근거로 적었는가. 비워 두지 않는다.
    source: str = Field(min_length=1, max_length=200)


class Credential(BaseModel):
    """공고가 요구할 수 있는 등록·신고·인증.

    `held=None` 이 기본이다 — 확인되지 않은 자격을 「있다」고도 「없다」고도 적지 않는다.
    """

    name: str = Field(min_length=1, max_length=80)
    held: bool | None = None
    note: str | None = Field(default=None, max_length=400)
    source: str | None = Field(default=None, max_length=200)
    #: 유효기간 끝나는 날(31차 §3-B · 제품 반영 안 3-2). 비면 모름 — 옛 파일은 이 칸이 없어 None 으로 읽는다.
    #: 「이번 주 할 일」이 30일 안 만료 · 지난 날짜를 알린다.
    valid_until: date | None = None
    #: 「중소기업(소상공인) 확인서」 줄의 **기업 구분** — 확인서에 적힌 그대로(10-10 담당자 결정). 다른 줄은 비워 둔다.
    #: 나라장터 「소기업 · 소상공인 확인서」 조항 · 기업마당 「소상공인만」을 이것으로 가른다. 비면 모름.
    grade: Literal["중기업", "소기업", "소상공인"] | None = None


#: 회사 단위 한 번 확인(43차 결정 2) — 나라장터 「가능」에 닿는 길. 열쇠 → 화면 이름.
COMPANY_CHECK_LABELS: dict[str, str] = {
    "g2b_registration": "나라장터 입찰참가자격 등록",
    "no_sanction": "부정당 제재 없음",
    "no_tax_arrears": "국세 · 지방세 체납 없음",
}


class CompanyCheck(BaseModel):
    """회사 단위 확인 한 칸 — **사람이 등록증 · 조회 결과를 보고 적는다**(개발자 · 프로그램은 값을 고르지 않는다 · 43차 결정 2).

    유효기간이 지나면 판정은 다시 「확인 필요 — 다시 확인」이다. 공고마다 되풀이하던 등록 · 결격 줄을 회사 단위로 한 번에 닫는다.
    """

    confirmed_on: date
    valid_until: date
    confirmed_by: str = Field(min_length=1, max_length=60)
    note: str | None = Field(default=None, max_length=200)


class RegisteredIndustry(BaseModel):
    """나라장터 **입찰참가자격 등록 업종**. 세무서 종목(`business_items`)과 다른 것이다.

    판정에 쓰는 것은 이쪽뿐이다 — 사업자등록증 종목이 있다고 나라장터에 등록된 것은 아니다
    (0921 §2). 코드는 공고의 면허제한 이름 끝에 붙어 오는 값과 같은 축이다(예 1468).
    """

    code: str = Field(min_length=1, max_length=10)
    name: str = Field(default="", max_length=120)


class JointBidPartner(BaseModel):
    """공동수급 파트너를 확보할 수 있는가. 「모른다」를 남기려고 별도 모델로 둔다."""

    available: bool = False
    note: str | None = Field(default=None, max_length=400)


class DeliveryCapacity(BaseModel):
    """조직 하나의 개발 수행역량. 파일이 없으면 `source="absent"` 로 돌아온다."""

    organization_id: str
    #: 개발에 투입 가능한 인원. None 이면 인원 규모를 판정하지 않는다.
    developer_count: int | None = Field(default=None, ge=0, le=1000)
    #: 인력 구성 설명(자유 서술). 판정에 쓰지 않고 화면에만 보여 준다.
    team_note: str | None = Field(default=None, max_length=1000)
    skills: list[SkillEntry] = Field(default_factory=list)
    credentials: list[Credential] = Field(default_factory=list)
    #: 단독 수행 가능한 사업 규모의 상한(원). **회사가 정할 값이다.**
    #: None 이면 규모 판정을 하지 않는다 — 시스템이 임의의 숫자를 넣지 않는다.
    budget_ceiling_krw: int | None = Field(default=None, ge=0)
    #: 동시에 수행 가능한 사업 수. None 이면 판정하지 않는다.
    concurrent_project_limit: int | None = Field(default=None, ge=0)

    # --- 입찰 자격 판정 v2 (0921 §4-B) -------------------------------------
    #: 나라장터 **등록 업종**. 빈 목록은 「미입력」이다 — 「등록한 업종이 없다」가 아니다.
    #: 업종 판정은 이것이 비면 「불가」가 아니라 **「확인 필요」**로 간다.
    registered_industries: list[RegisteredIndustry] = Field(default_factory=list)
    #: 사업자등록증 **종목**. 판정에 쓰지 않는다 — 「등록 후보」 힌트로만 화면에 보여 준다.
    business_items: list[str] = Field(default_factory=list)
    #: 회사 **소재 광역**(예 「전남광주」). 「활동 지역」(profile.preferred_regions)과 다르다 —
    #: 지역제한 공고는 **소재지**로 판정한다.
    location_region: str | None = Field(default=None, max_length=40)
    #: 공동수급 파트너. None 이면 확인되지 않은 것이다.
    joint_bid_partner: JointBidPartner | None = None
    #: 제안서를 쓰는 데 필요한 최소 일수. 마감이 이보다 가까우면 「촉박」이다.
    proposal_lead_days: int = Field(default=4, ge=0, le=60)
    #: 사업기회 순서 — 「score」 점수순(기본) · 「practical」 실무 우선순위(37차). 옛 파일은 이 칸이 없어 기본값으로 읽는다.
    ranking_method: RankingMethod = DEFAULT_RANKING_METHOD
    #: AI 적합도 보조(40차 담당자 결정 2 · D24) — 매일 받기 때 규칙이 본업이라 한 새 공고만 하루 한 번 AI 에 묻는다. **기능 설정이지 회사 사실이 아니다.**
    #: 기본 꺼짐(키트 · 가상 예시 · 시험 회사) · 샘플에듀 만 켬. 옛 파일은 이 칸이 없어 꺼짐으로 읽는다.
    ai_fit_assist: bool = False
    #: 「안 적음(그대로 둠)」으로 고른 빈칸(41차 D31 · `company_blank_fields.FIELDS` 의 열쇠). **회사 값이 아니다** — 빈칸 안내에서만 뺀다.
    #: 판정은 그대로 「확인 필요」(값을 가정하지 않음) · 칸을 다시 적으면 그 칸은 빈칸이 아니라 저절로 안내 밖이다.
    left_blank: list[str] = Field(default_factory=list, max_length=20)
    #: 회사 단위 한 번 확인(43차 결정 2 · `COMPANY_CHECK_LABELS` 의 열쇠). 비면 모름 — 등록 · 결격 줄은 「확인 필요」 그대로.
    company_checks: dict[str, CompanyCheck] = Field(default_factory=dict)
    #: 직접생산확인 **보유 품명**(43차 Q24 · M21 — 「동영상제작서비스」 등). 비면 모름 — 직접생산 조항은 「확인 필요 — 보유 ○ · 요구 ○」.
    direct_production_items: list[str] = Field(default_factory=list, max_length=40)
    #: 보유 **디지털 제품(서비스)** 이름(43차 Q14 · M20). 비면 모름 — 기업마당 「디지털 제품 보유」 요건은 「확인 필요」.
    digital_products: list[str] = Field(default_factory=list, max_length=40)

    # --- 기업마당 공고문 판정 v2 (0924 §4-A-5) ---------------------------
    #
    # 공고문이 요구하는데 앱이 **회사 쪽 값을 몰라서** 판정하지 못하던 것들이다.
    # 전부 「모르면 None·빈 목록」이고, 그것은 「없다」가 아니라 「아직 안 적었다」다.
    #: 지난해 매출(원). 「매출 10억 이상」 같은 요건을 이것으로 잰다.
    revenue_krw_last_year: int | None = Field(default=None, ge=0)
    #: 기업부설연구소 또는 연구개발전담부서를 두었는가. None 이면 확인되지 않았다.
    has_research_department: bool | None = None
    #: 둔 것이 무엇인가 — 「lab」 기업부설연구소 · 「dept_only」 연구개발전담부서만. None 이면 종류를 모른다(옛 「보유」 값 · 36차 R35-DV-02).
    #: 「전담부서 인정서만 보유한 기업은 미포함」 공고(125370 · 127116)를 가르는 값이다.
    research_department_kind: Literal["lab", "dept_only"] | None = None
    #: 인증·평가를 받을 수 있는 **데이터 상품**. 비어 있으면 「모른다」다.
    data_products: list[str] = Field(default_factory=list, max_length=40)
    #: 등록해 둔 **공급기업 풀**(스마트공장 공급기업·데이터바우처 공급기업 등).
    supplier_registrations: list[str] = Field(default_factory=list, max_length=40)
    #: 완료한 **선행 사업**. 「스마트제조혁신R&D 완료과제」처럼 후속 과제의 신청 자격이 된다.
    #:
    #: 담당자가 「없음 확인」이라고 적을 수 있다 — 그러면 그것은 **확인된 사실**이라
    #: 판정이 「확인 필요」가 아니라 「불가」로 간다 (0924 §4-A-4 BIZ-PREREQ).
    completed_programs: list[str] = Field(default_factory=list, max_length=40)

    source: Literal["file", "absent"] = "absent"
    updated_at: datetime | None = None
    updated_by: str | None = Field(default=None, max_length=60)
    note: str | None = Field(default=None, max_length=1000)
    schema_version: int = DELIVERY_CAPACITY_SCHEMA_VERSION

    @property
    def recorded(self) -> bool:
        """회사가 실제로 적어 둔 역량 자료가 있는가."""
        return self.source == "file"

    def skill(self, name: str) -> SkillEntry | None:
        """이름 또는 별칭으로 기술 항목을 찾는다. 없으면 None(= 모른다)."""
        needle = name.strip().lower()
        for entry in self.skills:
            if entry.name.strip().lower() == needle:
                return entry
            if any(alias.strip().lower() == needle for alias in entry.aliases):
                return entry
        return None

    def credential(self, name: str) -> Credential | None:
        needle = name.strip().lower()
        for entry in self.credentials:
            if entry.name.strip().lower() == needle:
                return entry
        return None


class DeliveryCapacityUpdate(BaseModel):
    """저장 요청. `updated_by` 는 누가 적었는지 남기기 위해 필수다."""

    developer_count: int | None = Field(default=None, ge=0, le=1000)
    team_note: str | None = Field(default=None, max_length=1000)
    skills: list[SkillEntry] = Field(default_factory=list)
    credentials: list[Credential] = Field(default_factory=list)
    budget_ceiling_krw: int | None = Field(default=None, ge=0)
    concurrent_project_limit: int | None = Field(default=None, ge=0)
    # 0921 §4-B — 저장 요청에도 같은 이름으로 있어야 화면이 보낸 값이 버려지지 않는다.
    registered_industries: list[RegisteredIndustry] = Field(default_factory=list)
    business_items: list[str] = Field(default_factory=list)
    location_region: str | None = Field(default=None, max_length=40)
    joint_bid_partner: JointBidPartner | None = None
    proposal_lead_days: int = Field(default=4, ge=0, le=60)
    #: 사업기회 순서(37차). **비워 보내면 저장된 값을 그대로 둔다** — 이 칸을 모르는 옛 화면 · 키트가 저장해도 회사가 고른 방식이 지워지지 않게.
    ranking_method: RankingMethod | None = None
    #: AI 적합도 보조(40차). **비워 보내면 저장된 값을 그대로 둔다**(이 칸을 모르는 화면 · 키트가 저장해도 꺼지지 않게).
    ai_fit_assist: bool | None = None
    #: 「안 적음」 칸(41차 D31). **비워 보내면 저장된 값을 그대로 둔다** — 바꾸는 길은 `PUT /api/capability/left-blank`.
    left_blank: list[str] | None = None
    #: 회사 단위 확인(43차 결정 2). **비워 보내면 저장된 값을 그대로 둔다** — 바꾸는 길은 `PUT /api/capability/company-checks`.
    company_checks: dict[str, CompanyCheck] | None = None
    #: 직접생산 보유 품명(43차 Q24). 비워 보내면(None) 저장된 값을 그대로 둔다.
    direct_production_items: list[str] | None = None
    #: 보유 디지털 제품(서비스)(43차 Q14). 비워 보내면(None) 저장된 값을 그대로 둔다.
    digital_products: list[str] | None = None

    # --- 기업마당 공고문 판정 v2 (0924 §4-A-5) ---------------------------
    #
    # 공고문이 요구하는데 앱이 **회사 쪽 값을 몰라서** 판정하지 못하던 것들이다.
    # 전부 「모르면 None·빈 목록」이고, 그것은 「없다」가 아니라 「아직 안 적었다」다.
    #: 지난해 매출(원). 「매출 10억 이상」 같은 요건을 이것으로 잰다.
    revenue_krw_last_year: int | None = Field(default=None, ge=0)
    #: 기업부설연구소 또는 연구개발전담부서를 두었는가. None 이면 확인되지 않았다.
    has_research_department: bool | None = None
    #: 둔 것이 무엇인가 — 「lab」 기업부설연구소 · 「dept_only」 연구개발전담부서만. None 이면 종류를 모른다(옛 「보유」 값 · 36차 R35-DV-02).
    #: 「전담부서 인정서만 보유한 기업은 미포함」 공고(125370 · 127116)를 가르는 값이다.
    research_department_kind: Literal["lab", "dept_only"] | None = None
    #: 인증·평가를 받을 수 있는 **데이터 상품**. 비어 있으면 「모른다」다.
    data_products: list[str] = Field(default_factory=list, max_length=40)
    #: 등록해 둔 **공급기업 풀**(스마트공장 공급기업·데이터바우처 공급기업 등).
    supplier_registrations: list[str] = Field(default_factory=list, max_length=40)
    #: 완료한 **선행 사업**. 「스마트제조혁신R&D 완료과제」처럼 후속 과제의 신청 자격이 된다.
    #:
    #: 담당자가 「없음 확인」이라고 적을 수 있다 — 그러면 그것은 **확인된 사실**이라
    #: 판정이 「확인 필요」가 아니라 「불가」로 간다 (0924 §4-A-4 BIZ-PREREQ).
    completed_programs: list[str] = Field(default_factory=list, max_length=40)
    updated_by: str = Field(min_length=1, max_length=60)
    note: str | None = Field(default=None, max_length=1000)
    #: 처음 읽은 `updated_at`(43차 M25). 보내면 그사이 다른 사람이 저장했을 때 409 로 막는다 — 보내지 않는 키트 · 스크립트는 검사하지 않는다.
    expected_updated_at: datetime | None = None
