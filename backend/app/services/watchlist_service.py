"""「오늘 열어 본 곳」 목록 (38차 §3-E-6).

기관 게시판 이름 · 주소 · 층 · 메모 · 마지막으로 연 때. 화면의 「열기」는 사람 브라우저가 새 탭으로 연다 —
**서버는 그 사이트를 읽지 않는다(크롤링 없음)**. 서버는 「열었다」는 시각만 받아 적는다.

처음 목록은 `docs/reports/2026-11-01_gpt_workflow/analysis_sources.md` 표와 recheck30 §3 탐색
(`docs/reports/2026-11-03_coverage/sweep_candidates.csv`)에서 효과 있던 게시판이다. **두 문서에 주소가 그대로 있는 것만**
게시판 주소로 넣고, 상세 글 주소만 있던 곳은 누리집 첫 화면(같은 문서의 호스트)으로, 주소가 없던 곳은 비워 둔다
(「고치기」로 넣는다) — 주소를 지어내지 않는다.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core import org_storage, storage
from app.schemas.manual_notice import WatchSite, WatchSiteInput

KST = timezone(timedelta(hours=9))
FILE_NAME = "watchlist.json"
HOME_NOTE = "게시판 주소를 확인하지 못해 누리집 첫 화면입니다 — 「고치기」로 게시판 주소를 넣으세요"
BLANK_NOTE = "주소를 확인하지 못했습니다 — 「고치기」로 넣으세요"

#: (이름, 주소 또는 None, 층, 메모)
DEFAULT_SITES: tuple[tuple[str, str | None, str, str | None], ...] = (
    ("한국과학창의재단 사업공고", "https://www.kosac.re.kr/", "P1", HOME_NOTE),
    ("한국과학창의재단 입찰", "https://www.kosac.re.kr/", "P1", HOME_NOTE),
    ("한국과학창의재단 신청접수", "https://www.kosac.re.kr/menus/281/reg", "P1", None),
    ("NIPA 사업공고", "https://www.nipa.kr/home/2-2", "P1", None),
    ("NIA 입찰", "https://www.nia.or.kr/site/nia_kor/ex/bbs/List.do?cbIdx=78336", "P1", None),
    ("중소벤처기업부 사업공고", "https://www.mss.go.kr/", "P1", HOME_NOTE),
    ("K-Startup 사업공고", "https://www.k-startup.go.kr/", "P1", HOME_NOTE),
    ("한국사회적기업진흥원", "https://www.socialenterprise.or.kr/", "P1", HOME_NOTE),
    ("KIAT 사업공고", "https://www.kiat.or.kr/front/board/boardContentsListPage.do?board_id=90", "P1", None),
    ("KERIS 입찰", "https://www.keris.or.kr/", "P1", HOME_NOTE),
    ("GICON 사업공고", "https://www.gicon.or.kr/board.es?mid=a10204000000&bid=0003", "P1", None),
    ("GICON 입찰", "https://www.gicon.or.kr/", "P1", HOME_NOTE),
    ("광주TP 사업공고", "https://www.gjtp.or.kr/home/business.cs", "P1", None),
    ("전남TP 사업공고", "https://www.jntp.or.kr/base/board/list?boardManagementNo=11&menuLevel=2&menuNo=44", "P1", None),
    ("JCIA 사업공고", "https://www.jcia.or.kr/cf/information/notice/business.do", "P1", None),
    ("JCIA 제안공모", "https://www.jcia.or.kr/", "P1", HOME_NOTE),
    ("AICA(인공지능산업융합사업단)", None, "P1", BLANK_NOTE),
    ("직업능력심사평가원 심사평가공고", "https://www.ksqa.or.kr/?pid=HP010201", "HRD", None),
    ("HRD4U 공지", "https://www.hrd4u.or.kr/hrd4u_new/bbs/list/B0000051.do?menuNo=0401", "HRD", None),
    ("IRIS 사업공고", "https://www.iris.go.kr/contents/retrieveBsnsAncmBtinSituListView.do", "IRIS", None),
    ("e나라도움", "https://www.gosims.go.kr/", "P1", HOME_NOTE),
    ("광주 앵커센터", None, "P1", BLANK_NOTE),
    ("전남 앵커센터", None, "P1", BLANK_NOTE),
    ("평생교육진흥원(1)", None, "P1", BLANK_NOTE),
    ("평생교육진흥원(2)", None, "P1", BLANK_NOTE),
    ("상공회의소", None, "P1", BLANK_NOTE),
    # 39차 §4 — 대학 · 산학협력단 공동 전자조달. recheck31 10-17 탐색(실무 방식)에서 BidPilot 이 못 잡은 기관 · 대학 자체 게시판 16건 중 6건이
    # 여기 공개 입찰 목록이었다(그 보고 자료에 주소가 그대로 있음). 서버는 읽지 않는다 — 연 시각만(읽기는 robots · 약관 확인 뒤 2차).
    ("대학 공동 전자조달(ebiz4u) 공개 입찰", "https://www.ebiz4u.co.kr/bid/bidding.do?cmd=listPublic&subcmd=doPortalList", "P2",
     "대학 · 산학협력단 공동 전자조달 — 공개 입찰 목록(1.3.0 에 더함)"),
)
#: 38차 처음 목록에 이미 있던 이름 — 그 뒤에 더한 기본 곳은 이미 목록을 저장한 회사에도 한 번 보인다(`offered`).
_DEFAULTS_38: frozenset[str] = frozenset(name for name, *_ in DEFAULT_SITES[:26])


def path_of(organization_id: str) -> Path:
    return org_storage.storage_for(organization_id).root / FILE_NAME


def _site_id(name: str) -> str:
    return "site-" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:10]


def defaults() -> list[WatchSite]:
    return [WatchSite(id=_site_id(name), name=name, url=url, layer=layer, memo=memo) for name, url, layer, memo in DEFAULT_SITES]


def load(organization_id: str, *, quarantine: bool = True) -> list[WatchSite]:
    """저장된 목록. 아직 없으면 처음 목록(저장하지 않는다 — 고치거나 열 때 저장).

    저장본이 깨졌으면 `CorruptJsonError` 를 그대로 올린다(2.0.6 — 처음 목록으로 읽어, 다음 「열기」 · 「고치기」가 회사가 더한 곳을
    처음 목록으로 덮어 말없이 사라졌다. 화면에는 원본을 옮겨 둔 파일 이름이 간다). `quarantine=False` 는 오류를 삼키는 브리핑 읽기용.
    """
    payload = storage.read_json(path_of(organization_id), default=None, quarantine=quarantine)
    if not isinstance(payload, dict) or not isinstance(payload.get("sites"), list):
        return defaults()
    out: list[WatchSite] = []
    for row in payload["sites"]:
        try:
            out.append(WatchSite.model_validate(row))
        except ValueError:
            continue
    # 저장한 뒤에 새로 생긴 기본 곳(39차 ebiz4u)은 한 번 덧붙여 보인다 — 저장하면 `offered` 에 적혀 다시 붙지 않는다(빼면 빠진 채로 남는다)
    offered = set(payload.get("offered") or _DEFAULTS_38)
    present = {site.id for site in out}
    out += [site for site in defaults() if site.name not in offered and site.id not in present]
    return out


def _raw(organization_id: str) -> dict:
    try:
        payload = storage.read_json(path_of(organization_id), default=None)
    except storage.CorruptJsonError:
        payload = None
    return payload if isinstance(payload, dict) else {}


def _save(organization_id: str, sites: list[WatchSite], *, saved_by: str | None = None) -> list[WatchSite]:
    payload: dict = {
        "_note": "오늘 열어 본 곳 — 사람이 새 탭으로 연 시각만 적는다(서버는 사이트를 읽지 않음 · 38차 §3-E)",
        "sites": [s.model_dump(mode="json") for s in sites],
        # 이미 보여 준 기본 곳 이름 — 사람이 뺀 기본 곳이 다음에 다시 붙지 않게(39차)
        "offered": sorted(name for name, *_ in DEFAULT_SITES),
    }
    if saved_by is not None:
        # 목록을 고친 사람 · 때(43차 M25). 「열기」만 누른 저장은 목록 고침이 아니라 앞 값을 이어 둔다
        payload.update(saved_by=saved_by, saved_at=storage.utc_now().isoformat())
    else:
        previous = _raw(organization_id)
        payload.update({k: previous[k] for k in ("saved_by", "saved_at") if k in previous})
    storage.write_json_atomic(path_of(organization_id), payload)
    return sites


def _editable(site: WatchSite | WatchSiteInput) -> tuple:
    return (site.id, site.name, site.url, site.layer, site.memo)


def replace(
    organization_id: str,
    rows: list[WatchSiteInput],
    *,
    base: list[WatchSiteInput] | None = None,
    saved_by: str | None = None,
) -> list[WatchSite]:
    """고치기 · 더하기 · 빼기 — 받은 목록으로 바꾼다. 같은 id 면 마지막으로 연 때를 이어 둔다.

    `base`(고치기를 시작할 때 읽은 목록)가 지금 목록과 다르면 `StaleWriteError`
    (43차 M25 — 옛 목록으로 저장해 남이 더한 곳이 지워졌다)."""
    current = load(organization_id)
    if base is not None and [_editable(s) for s in base] != [_editable(s) for s in current]:
        raw = _raw(organization_id)
        try:
            at = datetime.fromisoformat(raw["saved_at"]) if raw.get("saved_at") else None
        except ValueError:
            at = None
        raise storage.StaleWriteError(raw.get("saved_by") or None, at)
    previous = {s.id: s for s in current}
    opened = {k: v.last_opened_at for k, v in previous.items()}
    sites: list[WatchSite] = []
    seen: set[str] = set()
    for row in rows:
        site_id = row.id if row.id and row.id.startswith("site-") and len(row.id) <= 20 else _site_id(row.name)
        if site_id in seen:
            site_id = _site_id(f"{row.name}|{len(sites)}")
        seen.add(site_id)
        before = previous.get(site_id)
        sites.append(WatchSite(
            id=site_id, name=row.name, url=row.url, layer=row.layer, memo=row.memo, last_opened_at=opened.get(site_id),
            last_opened_by=before.last_opened_by if before else None,
        ))
    return _save(organization_id, sites, saved_by=saved_by or "")


def mark_opened(organization_id: str, site_id: str, *, now: datetime | None = None, by: str | None = None) -> WatchSite:
    sites = load(organization_id)
    for site in sites:
        if site.id == site_id:
            site.last_opened_at = now or storage.utc_now()
            site.last_opened_by = by
            _save(organization_id, sites)
            return site
    raise LookupError(site_id)


def opened_today(organization_id: str, *, now: datetime | None = None) -> tuple[int, int]:
    """`(오늘 연 곳, 주소 있는 곳)` — 브리핑 머리 「오늘 사람이 열어 본 곳 n/m」."""
    today = (now or storage.utc_now()).astimezone(KST).date()
    try:
        # (2.0.6) 파일을 옮기지 않고 읽는다 — 브리핑이 먼저 옮기면 화면은 409 없이 처음 목록을 보고 「열기」로 그 위에 저장했다
        sites = [s for s in load(organization_id, quarantine=False) if s.url]
    except storage.CorruptJsonError:
        return 0, 0  # 브리핑은 막지 않는다 — 사유는 「오늘 열어 본 곳」 화면이 409 로 보인다
    opened = sum(1 for s in sites if s.last_opened_at and s.last_opened_at.astimezone(KST).date() == today)
    return opened, len(sites)
