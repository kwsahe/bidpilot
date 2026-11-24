"""입찰 제안서 품질 게이트 회귀 — 노트북 저장본 5건(1~5순위 초안)에 게이트를 돌려 지시서 시험 A~F 를 잰다(2.7.0 · 2.8.0).

네트워크 · AI 를 부르지 않는다(나라장터 · 기업마당 · 첨부 받기 끔). 저장본은 읽기만 한다 — 초안 · 승인 · 품질 보고서 · 기록을 쓰지 않는다
(`bid_proposal_service.read_view` 만 부르고, 한글 파일은 메모리에서 만들어 다시 읽는다). 회사 값은 화면에 찍지 않는다.

    backend/.venv/Scripts/python.exe -X utf8 scripts/check_quality_gate.py
    backend/.venv/Scripts/python.exe -X utf8 scripts/check_quality_gate.py --show

저장본은 다시 쓰면 바뀐다 — 그래서 숫자를 박지 않고 「있으면 반드시 잡는다」 꼴로 잰다(공고마다):
  A 제출용 미작성 칸: 게이트가 센 차단 빈칸 = 제출용 빈칸 수 = 메모리에서 만든 한글 제출용 파일을 다시 읽은 수(1~3위 합을 찍는다)
  B 조견표: 평가 대응표의 「목차 없음」은 모두 차단(EVAL_MAP_BLANK) · 「본문 없음」은 모두 중요(EVAL_MAP_NO_CONTENT)
    — 1786460 「취업현황조사 기획」 · 1782790 「품질관리 요구사항」은 대응표에 있어야 한다
  C 번호: 양식 대항목 번호가 겹치면 차단(NUMBER_DUP) · 한글 파일에 겹친 번호가 있으면 양식에도 있어야 한다
  D 인력: 「인력 미확정」 차단 · 참여인력 표의 사람 값 칸은 빈칸 표시뿐(이름 · 경력을 짓지 않음) · 구분 · 담당 업무 칸은 본문 업무분장 값(2.10.0 D4)
  E 기본정보: 1782790 끝날 2027-12-15 · 저장된 terms 가 있으면 금액 350,000,000원
  F 상태: BLOCKED · 파일 이름 「초안」 · 승인 불가
  + 본문에 과장 표현(「반드시 달성」 · 「완벽」 …)이 남았으면 HYPE_LEFT · 1804104 조견표 빈칸 · 원문 번호 건너뜀(Ⅲ → Ⅴ)
저장본이 없으면 그 공고는 실패로 센다.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for _name in ("LIVE_FETCH", "G2B_LIVE_FETCH", "BIZINFO_LIVE_FETCH", "ATTACHMENT_FETCH", "EMBEDDING_LIVE", "SEMANTIC_FIT", "LLM_LIVE"):
    os.environ[_name] = "0"
sys.path.insert(0, str(ROOT / "backend"))

from app.schemas.organization import AnalysisContext  # noqa: E402
from app.services import bid_proposal_service as bid, bid_quality_gate, plan_export_service, plan_hwpx_service  # noqa: E402
from app.services.plan_form_service import HUMAN_INPUT_RE  # noqa: E402

# 읽기만 — `read_view` 는 검증이 예외면 기록 한 줄(bid_quality_log.jsonl)을 남긴다(2.8.0 B1). 이 스크립트는 저장본에 쓰지 않는다.
bid_quality_gate.log_event = lambda *args, **kwargs: None

#: 1~5순위 공고(11-07 · 11-10 다시 씀) — 앞 셋이 지시서 1~3위.
NOTICES = ("1805118", "1786460", "1782790", "1813493", "1804104")
TOP3 = NOTICES[:3]
#: 빈칸 표시를 세는 검사 — 본문 · 표지 · 사람 몫 표 · 조견표.
SPOT_CODES = ("PLACEHOLDER", "STAFFING_UNCONFIRMED", "EVAL_MAP_BLANK")
#: 지시서가 이름으로 짚은 평가 항목(정성 5점 — 조견표 목차가 비었거나 본문이 없었다).
NAMED_ITEMS = {"1786460": "취업현황조사 기획", "1782790": "품질관리 요구사항"}
#: 과장 표현(게이트 `bid.HYPE_RE` 와 따로 — 같은 함수로 재면 회귀가 되지 않는다).
_HYPE_RE = re.compile(r"반드시\s*달성|완벽(?:하게|히|한)|100\s*%\s*(?:달성|보장)")


def _hwpx_recheck(view: dict[str, Any], quality: dict[str, Any]) -> dict[str, Any]:
    """내는 판(평가본만 받는 공고는 평가본 — `plan_export_service.submit_variant` · T6 검토)의 한글 파일을 메모리에서 만들어 다시 읽는다
    (내려받기와 같은 함수 · 저장하지 않음)."""
    form = view.get("form") or {}
    meta = bid.export_meta(view, company=view.get("company_name"))
    meta["file_label"] = quality["file_label"]
    variant = plan_export_service.submit_variant(view)
    payload = plan_hwpx_service.build_hwpx(view, form, title=str(view.get("title") or "제안서"), variant=variant, meta=meta)
    expected = plan_export_service.blank_total(view, form, meta, variant=variant)
    return bid_quality_gate.recheck_hwpx(payload, expected=expected)


def people_made_up(view: dict[str, Any]) -> int:
    """D — 참여인력 표에서 사람 값이거나 본문 업무분장에 없는 칸 수. 사람 값 칸(성명 · 학력 · 경력 · 자격 · 참여율)은 빈칸 표시뿐이고
    (2.10.0 D4 — 「빈칸 표시뿐」에서 바꿈) 구분(역할) · 담당 업무 칸은 빈칸 표시이거나 본문 업무분장 한 줄(「- 역할: … 맡습니다」)의 글
    — 같은 줄에 역할 · 담당 업무가 함께 있어야 한다(작성기 `bid.staff_roles` 와 따로 잼 · 이름 · 경력을 짓지 않음)."""
    people = next((t for t in view.get("tables") or [] if t.get("key") == bid.PEOPLE_TABLE["key"]), None)
    columns = (people or {}).get("columns") or []
    lines = [re.sub(r"\s+", "", str(x.get("text") or "")) for section in view.get("sections") or [] for x in section.get("sentences") or []
             if "맡" in str(x.get("text") or "")]
    made_up = 0
    for row in (people or {}).get("rows") or []:
        kept = {i: re.sub(r"\s+", "", str(cell)) for i, cell in enumerate(row) if str(cell).strip() and not HUMAN_INPUT_RE.fullmatch(str(cell).strip())}
        body = {i: value for i, value in kept.items() if i == 0 or columns[i:i + 1] == ["담당 업무"]}
        made_up += len(kept) - len(body)
        if body and not any(all(value in line for value in body.values()) for line in lines):
            made_up += len(body)
    return made_up


def check(no: str, context: AnalysisContext, *, show: bool) -> tuple[list[str], int]:
    """한 공고 — (합격선에서 어긋난 것(없으면 빈 목록), 1~3위면 제출용 미작성 칸 수)."""
    pid = f"g2b-R26BK0{no}-000"
    try:
        draft = bid.load(pid, context=context)
    except bid.BidPlanNotGeneratedError:
        print(f"{no}: 저장된 초안 없음")
        return [f"{no} 저장된 초안 없음"], 0
    view = bid.read_view(draft, context=context, procurement_id=pid)
    quality = view["quality"]
    codes = {f["code"] for f in quality["findings"]}
    blocker_codes = {f["code"] for f in quality["findings"] if f["severity"] == "BLOCKER"}
    # 차단만 센다 — 조견표 정량 항목 「—」(참고 · 2.8.0)는 빈칸이 아니다
    spots = sum(f["count"] for f in quality["findings"] if f["code"] in SPOT_CODES and f["severity"] == "BLOCKER")
    hwpx = _hwpx_recheck(view, quality)
    counts = " · ".join(f"{name} {quality['counts'][key]}" for key, name in (("BLOCKER", "차단"), ("MAJOR", "중요"), ("MINOR", "보통"), ("INFO", "참고")))
    print(f"{no}: {quality['status']}({quality['status_label']}) · {counts} · 빈칸 {spots}곳(제출용 {view['submit_blanks']} · 한글 {hwpx['placeholders']})"
          f" · 인력 미확정 {'예' if quality['staffing_unconfirmed'] else '아니오'} · 파일 이름 「{quality['file_label']}」"
          + (f" · 한글 번호 겹침 {hwpx['duplicate_majors']}" if hwpx["duplicate_majors"] else ""))
    if show:
        for f in quality["findings"]:
            print(f"    [{f['severity']}] {f['code']} ×{f['count']} {f['title']}" + (f" · {f['section']}" if f["section"] else ""))
    misses: list[str] = []
    # A 제출용 미작성 칸 — 게이트 = 제출용 = 한글 다시 읽기
    if spots != view["submit_blanks"] or spots != quality.get("submit_blanks"):
        misses.append(f"{no} A 「(담당자 입력)」을 다 못 잡음(게이트 {spots} · 제출용 {view['submit_blanks']})")
    if not hwpx["reextract_ok"] or hwpx["placeholders"] != view["submit_blanks"]:
        misses.append(f"{no} A 한글 파일 다시 읽기 {hwpx['placeholders']} ≠ 제출용 {view['submit_blanks']}")
    # B 조견표 — 목차 없음은 차단 · 본문 없음은 중요 · 이름으로 짚은 항목은 대응표에 있다
    coverage = quality.get("evaluation_coverage") or []
    missing = [c for c in coverage if c["status"] == "MISSING"]
    if missing and "EVAL_MAP_BLANK" not in blocker_codes:
        misses.append(f"{no} B 조견표 목차 없음 {len(missing)}건을 차단으로 못 잡음")
    if any(c["body"] == "없음" for c in coverage) and "EVAL_MAP_NO_CONTENT" not in codes:
        misses.append(f"{no} B 조견표 목차에 본문 없음을 못 잡음")
    if no in NAMED_ITEMS:
        row = next((c for c in coverage if c["name"] == NAMED_ITEMS[no]), None)
        if row is None:
            misses.append(f"{no} B 평가 대응표에 「{NAMED_ITEMS[no]}」가 없음")
        else:
            print(f"    B 「{row['name']}」: 목차 {row['mapped'] or '없음'} · 본문 {row['body']} · {row['status']}")
    # C 번호 — 양식 겹침은 차단 · 한글 파일 겹침은 양식에도
    _skip, dup = bid_quality_gate._number_breaks(view.get("form") or {})
    if dup and "NUMBER_DUP" not in blocker_codes:
        misses.append(f"{no} C 대항목 번호 겹침({dup})을 차단으로 못 잡음")
    if hwpx["duplicate_majors"] and not dup:
        misses.append(f"{no} C 한글 파일 번호 겹침 {hwpx['duplicate_majors']}를 양식 검사가 못 봄")
    # D 인력 — 「인력 미확정」 차단 · 사람 값 칸은 빈칸 표시뿐 · 역할 · 담당 업무 칸은 본문 업무분장 값(2.10.0 D4 · `people_made_up`)
    if "STAFFING_UNCONFIRMED" not in blocker_codes or not quality["staffing_unconfirmed"]:
        misses.append(f"{no} D 「인력 미확정」 차단을 못 잡음")
    if made_up := people_made_up(view):
        misses.append(f"{no} D 참여인력 표에 사람 값이거나 본문 업무분장에 없는 칸 {made_up}개")
    # E 기본정보 — 3위 끝날 · 금액(저장된 terms 가 있을 때)
    if no == "1782790":
        terms = quality.get("terms") or {}
        print(f"    E 사업기간 「{terms.get('period')}」 · 끝날 {terms.get('end')} · 금액 「{terms.get('budget')}」")
        if terms.get("end") != "2027-12-15":
            misses.append(f"1782790 E 끝날 {terms.get('end')} ≠ 2027-12-15")
        if isinstance(draft.get("terms"), dict) and draft["terms"].get("budget_won") != 350_000_000:
            misses.append(f"1782790 E 금액 {draft['terms'].get('budget')} ≠ 350,000,000원")
    # F 상태 — 차단 · 「초안」 · 승인 불가
    if quality["status"] != "BLOCKED" or quality["file_label"] != "초안" or bid_quality_gate.approvable(quality):
        misses.append(f"{no} F 상태 {quality['status']} · 이름 「{quality['file_label']}」 — 제출 차단이 아님")
    # 과장 표현이 본문에 남았으면 HYPE_LEFT(인용 원문과 같은 말인 RFP_GROUNDED 는 빼고)
    hyped = [x for section in view.get("sections") or [] for x in section.get("sentences") or []
             if _HYPE_RE.search(str(x.get("text") or ""))
             and not (x.get("type") == "RFP_GROUNDED" and _HYPE_RE.search(str(x.get("source") or "")))]
    if hyped and "HYPE_LEFT" not in codes:
        misses.append(f"{no} 과장 표현 {len(hyped)}문장을 못 잡음")
    if no == "1804104" and "NUMBER_SKIP" not in codes:
        # (2.9.0) 조견표 빈칸은 저장본마다 다르다(다시 쓰면 짝이 지어진다) — B 불변 조건(목차 없음 → 차단)이 같은 것을 일반 규칙으로 본다
        misses.append("1804104 원문 번호 건너뜀을 못 잡음")
    # G 두 축(3차 지시서 §12 · 게이트 판 3) — 담당자 입력만 남으면 자동 작성은 실패가 아니다 · 앱 몫 차단이면 실패 · 갈래는 넷 중 하나
    generation = (quality.get("generation") or {}).get("status")
    blockers = [f for f in quality["findings"] if f["severity"] == "BLOCKER"]
    print(f"    G 자동 작성 {generation} · 갈래 {quality.get('axes')}")
    if any(f.get("axis") not in bid_quality_gate.AXES for f in quality["findings"]):
        misses.append(f"{no} G 갈래가 없는 검사 줄")
    if blockers and all(f.get("axis") == "input" for f in blockers) and generation == "FAIL":
        misses.append(f"{no} G 담당자 입력만 남았는데 자동 작성 실패")
    if any(f.get("axis") == "auto" for f in blockers) and generation != "FAIL":
        misses.append(f"{no} G 앱이 고칠 차단이 있는데 자동 작성 {generation}")
    # H 일정표(3차 지시서 §4) — AI 일정표 행 중 월별 칸 표에 못 그리는 줄이 있으면 SCHEDULE_GRID
    # (2.10.0 D1) 짧은 사업(weeks)은 주차(Wn) 칸 — 간트 · 게이트와 같은 읽기(`period_reader` · 개월차만 보면 주차 저장본이 거짓 실패)
    schedule = next((t for t in view.get("tables") or [] if t.get("key") == "schedule" and t.get("by") == "llm"), None)
    rows = (schedule or {}).get("rows") or []
    read = plan_export_service.period_reader(rows, ((view.get("form") or {}).get("agreement_period") or {}).get("weeks"))
    undrawn = [row for row in rows if row and not HUMAN_INPUT_RE.search(str(row[0])) and not read(str(row[1]) if len(row) > 1 else "")]
    if undrawn and "SCHEDULE_GRID" not in codes:
        misses.append(f"{no} H 월별 칸 표에 못 그리는 일정 {len(undrawn)}줄을 못 잡음")
    return misses, (view["submit_blanks"] if no in TOP3 else 0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--org", default="org-sample")
    parser.add_argument("--show", action="store_true", help="검사 목록까지 찍는다")
    args = parser.parse_args()
    context = AnalysisContext(organization_id=args.org, evidence_scope="internal")
    misses: list[str] = []
    top3 = 0
    for no in NOTICES:
        found, blanks = check(no, context, show=args.show)
        misses += found
        top3 += blanks
    print(f"\nA 1~3위 제출용 미작성 칸 합 {top3}곳(게이트 · 한글 다시 읽기와 같음이 합격선)")
    if misses:
        print("\n합격선 미달:")
        for miss in misses:
            print(f"  - {miss}")
        return 1
    print("\n합격선 통과 — A~G · 과장 표현 · 1804104 번호 건너뜀")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
