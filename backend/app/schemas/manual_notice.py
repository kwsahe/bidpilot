"""공고 직접 넣기 · 확인 전 후보함 · 오늘 열어 본 곳 (38차 §3-E · 담당자 결정 3).

세 가지 모두 **사람이 가져온 글**이다 — 믿지 않는다. https 주소만 받고, 길이에 상한을 두고, 화면 · 파일로 나갈 때는
이스케이프한다(브리핑 `_md`). 서버는 사람이 준 주소를 열지 않는다(SSRF 없음 · 크롤링 없음).
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

KST = timezone(timedelta(hours=9))

#: 모집 대상 — **기본값 없음**(수혜 ≠ 수행 · 담당자가 고른다). 입찰 · 수행기관 모집은 매출, 수혜는 지원금.
RecruitChoice = Literal["bid", "operator", "benefit"]
RECRUIT_LABELS: dict[str, str] = {
    "bid": "입찰(매출)",
    "operator": "수행기관 모집(매출)",
    "benefit": "수혜(지원금)",
}
#: 43차 M16 · SOURCE-11 — 「직찰 · 대학 자체 전자입찰」(ebiz4u 등)을 더해 실무순 직찰 자리에 둔다.
SubmitMethod = Literal["이메일", "PMS/기관시스템", "온라인폼", "IRIS", "나라장터", "방문/우편", "직찰 · 대학 자체 전자입찰"]
SUBMIT_METHODS: tuple[str, ...] = ("이메일", "PMS/기관시스템", "온라인폼", "IRIS", "나라장터", "방문/우편", "직찰 · 대학 자체 전자입찰")
SourceLayer = Literal["P1", "P2", "P3", "IRIS", "HRD"]

MAX_URL = 2000
MAX_TITLE = 200
MAX_AGENCY = 120
MAX_SHORT = 300
MAX_BODY = 50_000
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_text(value: str | None, limit: int, *, mask: bool = False) -> str | None:
    """제어 문자를 지우고 앞뒤 공백을 걷는다. 비면 None · 길면 거절(잘라서 다른 뜻으로 저장하지 않는다).

    `mask` — 사람이 적은 칸의 전화 · 이메일을 **가린 뒤** 길이를 잰다(38차 검토). 가린 글은 다시 가려도 같아서
    저장본을 다시 읽을 때도 같은 값이 통과한다.
    """
    if value is None:
        return None
    text = _CONTROL_RE.sub("", str(value)).strip()
    if not text:
        return None
    if mask:
        from app.services.procurement_service import mask_contact_text

        text = mask_contact_text(text)
    if len(text) > limit:
        raise ValueError(f"{limit}자까지 받습니다(지금 {len(text)}자)")
    return text


def https_url(value: str | None) -> str:
    """공식 원문 주소 — https 만. `javascript:` · `data:` · http · 공백 낀 주소는 받지 않는다."""
    text = clean_text(value, MAX_URL)
    if not text:
        raise ValueError("공식 원문 주소(https://…)를 적어 주세요")
    if not re.match(r"^https://[^\s/?#]+\.[^\s/?#]+", text, re.IGNORECASE) or re.search(r"\s", text):
        raise ValueError("https:// 로 시작하는 공식 주소만 받습니다")
    return text


class ManualNoticeInput(BaseModel):
    """넣는 양식 — 필수 다섯(주소 · 공고명 · 기관 · 마감일시 · 모집 대상) + 선택."""

    url: str
    title: str
    agency: str
    #: 43차 Q20 — 「상시 · 미정」(`deadline_open`)이면 비울 수 있다.
    deadline: datetime | None = None
    recruit: RecruitChoice
    deadline_open: bool = False
    #: 참가신청 · 등록 · 협정 마감(43차 Q20) — 입찰 마감보다 이르면 실제 마감이다.
    apply_deadline: datetime | None = None
    #: 사람이 「본업으로 확인」 — 낱말 규칙의 비추천으로 접지 않는다(43차 Q18 · 판정 · 점수 그대로).
    core_confirmed: bool = False
    published_on: date | None = None
    methods: list[SubmitMethod] = Field(default_factory=list, max_length=6)
    budget_text: str | None = None
    region_limit: str | None = None
    briefing: str | None = None
    joint: str | None = None
    layer: SourceLayer | None = None
    body_text: str | None = None
    #: 후보함 줄에서 「정식으로 넣기」로 왔으면 그 줄 id — 넣고 나면 그 줄을 「넣음」으로 바꾼다.
    inbox_id: str | None = None
    #: 「공고명이 같은 나라장터 공고가 있음」을 보고도 새로 넣기(43차 H4).
    confirm_new: bool = False

    @field_validator("url")
    @classmethod
    def _url(cls, value: str) -> str:
        return https_url(value)

    @field_validator("deadline", "apply_deadline")
    @classmethod
    def _deadline(cls, value: datetime | None) -> datetime | None:
        # 39차 MANUAL-09 — 연도를 잘못 적은 마감(0001-01-01 등) 하나가 목록 전체를 「읽기 오류」로 지웠다. 저장 때 막는다.
        if value is not None and not 2000 <= value.year <= 2100:
            raise ValueError("마감 날짜의 연도가 이상합니다(2000~2100년) — 다시 골라 주세요")
        return value

    @field_validator("published_on")
    @classmethod
    def _published(cls, value: date | None) -> date | None:
        # 40차 MANUAL-02 — 공고일에는 연도 검사가 없었다(0001-01-01 한 건이면 사업기회 목록 전체 · 브리핑이 오류로 멈춤)
        if value is None:
            return None
        if not 2000 <= value.year <= 2100:
            raise ValueError("공고일의 연도가 이상합니다(2000~2100년) — 다시 골라 주세요")
        if value > datetime.now(KST).date():
            raise ValueError("공고일이 오늘보다 늦습니다 — 이미 난 공고의 공고일을 골라 주세요")
        return value

    @model_validator(mode="after")
    def _published_before_deadline(self) -> "ManualNoticeInput":
        if self.deadline is None and not self.deadline_open:
            raise ValueError("마감일시를 적거나 「상시 · 미정」을 골라 주세요")
        if self.published_on is not None and self.deadline is not None:
            closing = self.deadline.astimezone(KST).date() if self.deadline.tzinfo else self.deadline.date()
            if self.published_on > closing:
                raise ValueError("공고일이 마감일보다 늦습니다 — 두 날짜를 다시 확인해 주세요")
        return self

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        text = clean_text(value, MAX_TITLE, mask=True)
        if not text:
            raise ValueError("공고명을 적어 주세요")
        return text

    @field_validator("agency")
    @classmethod
    def _agency(cls, value: str) -> str:
        text = clean_text(value, MAX_AGENCY, mask=True)
        if not text:
            raise ValueError("기관을 적어 주세요")
        return text

    @field_validator("budget_text", "region_limit", "briefing", "joint")
    @classmethod
    def _short(cls, value: str | None) -> str | None:
        return clean_text(value, MAX_SHORT, mask=True)

    @field_validator("body_text")
    @classmethod
    def _body(cls, value: str | None) -> str | None:
        return clean_text(value, MAX_BODY, mask=True)

    @field_validator("inbox_id")
    @classmethod
    def _inbox(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not re.fullmatch(r"inbox-[0-9a-f]{12}", value):
            raise ValueError("후보함 줄 id 꼴이 아닙니다")
        return value


class ManualDocument(BaseModel):
    """올린 공고문 파일 하나."""

    file_name: str
    size_bytes: int
    sha256: str
    format: str | None = None
    #: 조항을 읽었나 — 「ok」(참가자격 · 지원대상 조항 있음) · 「no_section」 · 「image」 · 「error」
    status: str
    note: str | None = None
    uploaded_at: datetime


class ManualHumanPass(BaseModel):
    """「원문 확인함 — 가능으로」(44차 M6 · SOURCE-09 · D16) — 사람이 공고 원문을 보고 정한 「가능」. 누가 · 언제 · 한 줄 이유.
    규칙에 불가 줄이 있으면 적용하지 않는다(불가는 그대로) · 공고를 고치면 지워진다(고친 사실로 다시 확인)."""

    by: str = Field(min_length=1, max_length=60)
    at: datetime
    reason: str = Field(min_length=1, max_length=200)
    #: 서버가 본 계정 아이디(45차 SEC-R37-02) — `by` 는 사람이 적은 이름이라 누구든 쓸 수 있다. 로그인 없는 로컬 · 옛 기록은 None.
    recorded_by: str | None = None


class ManualHumanPassRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=200)
    by: str = Field(min_length=1, max_length=60)

    @field_validator("reason", "by")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("비어 있습니다")
        return value


class ManualNotice(ManualNoticeInput):
    id: str
    organization_id: str
    created_at: datetime
    created_by: str | None = None
    updated_at: datetime
    #: 마지막으로 고친 사람(43차 M25 · TEAM-03) — 「누가 · 언제」를 화면에 적고, 먼저 바뀐 것을 알릴 때 쓴다.
    updated_by: str | None = None
    #: 화면용 이름(45차 M11 · 응답에서만 채움 — 저장본은 아이디). 계정이 아니면 아이디 그대로.
    created_by_name: str | None = None
    updated_by_name: str | None = None
    document: ManualDocument | None = None
    #: 사람 확인 뒤 가능(44차 M6). 없으면 None — 자동으로는 「가능」이 되지 않는다(D16).
    human_pass: ManualHumanPass | None = None

    @field_validator("deadline")
    @classmethod
    def _deadline(cls, value: datetime) -> datetime:
        # 저장본을 읽을 때는 연도를 막지 않는다(같은 이름이라 입력 쪽 검사를 덮는다) — 38차에 저장된 0001년 마감도 직접 넣기 탭에
        # 보여 고치거나 지울 수 있게. 입력은 `ManualNoticeInput` 이 막고, 목록 쪽은 그 줄만 건너뛴다(39차 마지막 검토).
        return value

    @field_validator("published_on")
    @classmethod
    def _published(cls, value: date | None) -> date | None:
        # 공고일도 같다(40차 MANUAL-02) — 저장본은 그대로 읽고, 목록 쪽(`unified_items`)이 범위 밖 줄만 건너뛴다
        return value

    @model_validator(mode="after")
    def _published_before_deadline(self) -> "ManualNotice":
        return self


class ManualSaveResult(BaseModel):
    """넣기 결과. 저장본에 이미 있는 공고면 새로 만들지 않고 그 공고 id 를 돌려준다(「이미 있음 — n위」)."""

    notice: ManualNotice | None = None
    duplicate_of: str | None = None
    duplicate_reason: str | None = None
    #: 공고명만 같은 「같은 공고일 수 있음」 — 사람이 「그래도 새로 넣기」를 고를 수 있다(43차 H4).
    maybe_duplicate: bool = False


# --------------------------------------------------------------------------
# 확인 전 후보함 (GPT · 사람이 찾은 것)
# --------------------------------------------------------------------------

InboxStatus = Literal["pending", "added", "discarded"]
MAX_PASTE_BYTES = 200 * 1024
MAX_PASTE_LINES = 300


class InboxEntry(BaseModel):
    id: str
    url: str
    title: str | None = None
    agency: str | None = None
    #: 붙여 넣은 글에 있던 날짜 문자열 그대로(마감 · 공고일 구분 없이 — 확인 전이다).
    date_text: str | None = None
    #: 저장본에 이미 있는 공고(나라장터 · 기업마당)면 그 id — 공고번호로 맞은 것만(확정).
    existing_id: str | None = None
    #: 공고명만 같은 나라장터 공고 — 단정하지 않는다(44차 TEAM-R36-05 · 「같은 공고일 수 있음 →」과 「정식으로 넣기」를 함께 보임).
    maybe_existing_id: str | None = None
    #: 붙여 넣은 표의 공고일 글(43차 M15 · 「정식으로 넣기」가 미리 채운다).
    published_text: str | None = None
    #: GPT 표의 판단 · 제외 사유 — 「GPT: 제외 — 사유」(43차 Q19 · 점수 · 판정 없음 · 📥 숫자에서 따로 셈).
    gpt_note: str | None = None
    status: InboxStatus = "pending"
    discard_reason: str | None = None
    manual_id: str | None = None
    line_no: int
    created_at: datetime


class InboxPasteRequest(BaseModel):
    text: str = Field(max_length=MAX_PASTE_BYTES)


class InboxRejected(BaseModel):
    line_no: int
    reason: str


class InboxPasteResult(BaseModel):
    #: 미리 보기였나(저장하지 않음 · 43차 N19).
    preview: bool = False
    #: 300줄을 넘었으면 다시 붙여 넣을 첫 줄 번호와 그 글(43차 SOURCE-15).
    first_unread_line: int | None = None
    first_unread_text: str | None = None
    added: int
    already_in_inbox: int
    existing: int
    #: 공고명만 같은 공고가 저장본에 있는 줄(따로 셈 · 44차 TEAM-R36-05).
    maybe_existing: int = 0
    lines_without_link: int
    rejected: list[InboxRejected]
    truncated_lines: int
    entries: list[InboxEntry]
    #: 확인 전 줄이 상한(500)이라 받지 못한 줄 수(39차 MANUAL-05 — 예전에는 오래된 줄을 말없이 지웠다).
    refused_full: int = 0


class InboxDiscardRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=MAX_SHORT)


# --------------------------------------------------------------------------
# 오늘 열어 본 곳
# --------------------------------------------------------------------------


class WatchSite(BaseModel):
    id: str
    name: str
    #: 게시판 주소. 처음 목록에서 주소를 확인하지 못한 곳은 None(「고치기」로 넣는다) — 지어내지 않는다.
    url: str | None = None
    layer: str | None = None
    memo: str | None = None
    last_opened_at: datetime | None = None
    #: 마지막으로 연 사람(43차 TEAM-05) — 「오늘 열어 본 곳」을 회사 하나로 세어 누가 봤는지 몰랐다.
    last_opened_by: str | None = None
    #: 화면용 이름(45차 M11 · 응답에서만 채움)
    last_opened_by_name: str | None = None


class WatchSiteInput(BaseModel):
    id: str | None = None
    name: str
    url: str | None = None
    layer: str | None = None
    memo: str | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        text = clean_text(value, MAX_AGENCY)
        if not text:
            raise ValueError("이름을 적어 주세요")
        return text

    @field_validator("url")
    @classmethod
    def _url(cls, value: str | None) -> str | None:
        return https_url(value) if clean_text(value, MAX_URL) else None

    @field_validator("layer", "memo")
    @classmethod
    def _short(cls, value: str | None) -> str | None:
        return clean_text(value, MAX_SHORT)


class WatchListUpdate(BaseModel):
    sites: list[WatchSiteInput] = Field(max_length=100)
    #: 고치기를 시작할 때 읽은 목록(43차 M25). 보내면 그사이 다른 사람이 바꿨을 때 409 — 남이 더한 곳을 말없이 지우지 않게.
    base: list[WatchSiteInput] | None = Field(default=None, max_length=100)
