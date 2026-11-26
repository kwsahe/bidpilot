"""입찰 제안서 품질 게이트(2.7.0 · 계획 1~3 · 11 · 대표 결정 11-08) — 저장된 초안을 규칙으로 다시 보고 검사 목록과 제출 상태를 낸다.

- AI · 네트워크 없음. 입력은 `bid_proposal_service.read_view` 가 만든 화면 초안(회사자료로 채운 사본) · 표지 값 · 받아 둔 공고 목록.
- 게이트 결과는 **저장하지 않는 계산값**(`read_view` 의 `quality`). 파일로 남는 것은 사람 승인(`bid_plan_approval.json` — 초안 내용 해시에
  묶임 · 다시 쓰면 저절로 풀림) · 품질 보고서(`bid_quality.json` — 최신 결과 · 마지막 한글 다시 읽기 `last_hwpx`) ·
  기록(`bid_quality_log.jsonl` — 쓰기 · 내려받기 · 승인 · 취소 · 오류마다 한 줄 · 2.8.0 B9)뿐이다.
- 내려받기를 막지 않는다(대표 결정 11-08) — 「제출 준비」가 아니면 제출용 · 평가본 파일 이름만 「…초안…」.
- 본문 · 표지 글은 바꾸지 않는다(대표 11-03 — 제출용에 「확인 필요」 · 메모를 싣지 않는다). 검사 결과는 화면 · 보고서에만 남는다.
- 검증을 못 하면 통과가 아니라 차단이다(`error_quality` · GATE_ERROR · 2.8.0 B1).

심각도: BLOCKER(차단) · MAJOR(중요) · MINOR(보통) · INFO(참고).
상태: BLOCKED(차단 1+) · NEEDS_REVIEW(중요 1+) · VERIFIED_DRAFT(차단 · 중요 0) · READY_TO_SUBMIT(차단 0 + 지금 초안에 묶인 사람 승인 ·
승인을 무효로 하는 검사(`VOID_CODES`)가 없을 때).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import tempfile
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core import storage
from app.schemas.organization import AnalysisContext
from app.services import analysis_store, bid_proposal_service as bid, performance_ledger, plan_draft_service, plan_export_service, plan_validation
from app.services.plan_form_service import unwritten_count

logger = logging.getLogger(__name__)

#: 게이트 규칙 판 — 검사를 바꾸면 올린다(보고서 · 기록 · 화면에 싣는다).
GATE_VERSION = 5  # 5 — 2.11.0 PDF 검사(PDF_BLANKS_FEWER · PDF_OVERLAP · PDF_TABLE_ORPHAN) · 제출서류 못 읽음(PAPERS_UNREAD) · 작성 도구 낱말(TOOL_WORD) ·
#   제목 조각(TITLE_WORD_GAP) · 확정 전 인력 경력(STAFFING_PROMISE) · 평가본 실적 사업명 · 사전규격뿐(SOURCE_PRESPEC_ONLY) · 참가 자격(ELIGIBILITY)
#   4 — 2.10.0 주차 일정 · 원문 대면 활동의 온라인 전환(REMOTE_SWAP) · 본문 시점 ↔ 일정표(SCHEDULE_BODY_GAP) ·
#   증빙 전 실적 수치(EVIDENCE_NUMBER) · 역할 이름 한 벌(ROLE_MISMATCH) · 예산 산수(BUDGET_MATH) · 평가본 식별 낱말(BLIND_IDENT_LEFT) ·
#   평가표 못 읽음(EVAL_UNREAD)
SEVERITIES = ("BLOCKER", "MAJOR", "MINOR", "INFO")
STATUS_LABELS = {"BLOCKED": "차단", "NEEDS_REVIEW": "검토 필요", "VERIFIED_DRAFT": "자동검증 통과", "READY_TO_SUBMIT": "제출 준비"}

#: 검사 갈래(3차 지시서 §1 · §9 · §12 · 게이트 판 3) — 같은 「빈칸」이라도 누가 고치나가 다르다.
#: auto — 앱이 자동으로 쓸 수 있었는데 못 함(B · 「자동 작성 검사」만 이 갈래를 본다) · input — 자료로 확인할 수 없어 담당자가
#: 채우는 정상 담당자 입력(A) · evidence — 증빙을 붙이거나 확인해야 함 · fact — 사람이 원문 · 사실을 확인할 것(C).
#: 제출 상태(`status` · `file_label` · 승인)는 네 갈래를 모두 본다(대표 결정 11-08 그대로) — 담당자 입력이 남으면 「제출 준비」가 아니다.
AXES = ("auto", "input", "evidence", "fact")
AXIS_LABELS = {"auto": "수정 필요", "input": "담당자 입력 필요", "evidence": "증빙 필요", "fact": "사실 확인 필요"}
#: 코드 → 갈래(PLACEHOLDER · MOVED_SENTENCES · OUTLINE_STANDARD · EVAL_MAP_BLANK 는 자리 · 사유로 `_finding(axis=…)` 이 정한다).
AXIS_OF: dict[str, str] = {
    "GATE_ERROR": "auto", "LLM_FAILED": "auto", "OUTLINE_STANDARD": "auto", "EVAL_MAP_BLANK": "auto", "EVAL_MAP_NO_CONTENT": "auto",
    "EVAL_UNREAD": "auto",
    "NUMBER_DUP": "auto", "NUMBER_FIXED": "auto", "NOTICE_TERMS": "auto", "NOTICE_MISMATCH": "auto", "STALE": "auto",
    "HYPE_LEFT": "auto", "REVIEW_FLAGS": "auto", "PLACEHOLDER": "auto", "MOVED_SENTENCES": "input",
    "SCHEDULE_GRID": "auto", "SCHEDULE_OUTSIDE": "auto", "SCHEDULE_TASK_MISSING": "auto", "SCHEDULE_ORDER": "auto", "SCHEDULE_OUTPUT": "auto",
    "SCHEDULE_BODY_GAP": "auto", "REMOTE_SWAP": "auto", "ROLE_MISMATCH": "auto",
    "NUMBER_SUM": "auto", "NOTICE_VALUE": "auto", "NOTICE_AMBIGUOUS": "fact", "BLIND_IDENT_LEFT": "auto",
    "NO_SIMILAR_RULE": "fact", "TASK_DETAIL_GAP": "auto", "CAPABILITY_LEAP": "auto", "TOOL_WORD": "auto", "TITLE_WORD_GAP": "auto",
    "STAFFING_UNCONFIRMED": "input", "REVIEW_BLANKS": "input", "FORMAT_TWO_VOLUME": "input", "FORMAT_PPT": "input",
    "FORMAT_LANDSCAPE": "input", "BLIND_RULE": "input", "APPROVAL_VOID": "input", "BUDGET_MATH": "input",
    "STAFFING_PROMISE": "evidence", "EVIDENCE_UNVERIFIED": "evidence", "EVIDENCE_NUMBER": "evidence",
    "COMMITMENT": "fact", "NUMBER_SKIP": "fact", "NOTICE_UNCHECKED": "fact", "PAGES_APPROX": "fact",
    # 한글에서 저장한 PDF 검사(2.10.0 T8 · 사람이 고친 파일 — 게이트 판정 밖 · D10)
    "PDF_UNREADABLE": "fact", "PDF_PAGES": "fact", "PDF_PAGES_OVER": "input", "PDF_NOT_A4": "input", "PDF_UNWRITTEN": "input",
    "PDF_LINK_CUT": "input", "PDF_BUDGET_UNREAD": "fact", "PDF_EVAL_PAGE": "input", "PDF_EVAL_PAGES": "fact",
    "PDF_BLANKS_FEWER": "fact", "PDF_OVERLAP": "input", "PDF_TABLE_ORPHAN": "input",
    "SOURCE_PRESPEC_ONLY": "fact", "ELIGIBILITY": "fact",
    "PAPERS_UNREAD": "fact",  # 입찰공고문 제출서류 0건(2.11.0 T6b · 보통 — 제출서류는 판정 밖 · 2.10.0 D10)
}
#: 자동 작성 검사(`generation`) — 앱이 고칠 것(auto)만 본다. 담당자 입력이 남았다는 이유만으로 실패하지 않는다(3차 지시서 §12).
GENERATION_LABELS = {"PASS": "자동 작성 완료", "REVIEW": "자동 작성 완료 · 검토할 경고 있음", "FAIL": "자동 작성 결함 — 수정 필요",
                     "ERROR": "검증 못 함"}
#: 참가 자격 판정 엔진이 예외를 냄 — 게이트를 막지 않고 참고 한 줄(2.11.0 D3).
ELIGIBILITY_ERROR = "error"
APPROVAL_FILE = "bid_plan_approval.json"
REPORT_FILE = "bid_quality.json"
LOG_FILE = "bid_quality_log.jsonl"
#: 이 검사가 있으면 승인이 있어도 「제출 준비」가 아니다(승인 뒤 공고 · 요구사항이 바뀜 · 본문 기간 · 금액이 원문과 다름 · 검증 실패 · 2.8.0 B2 · B6).
VOID_CODES = ("STALE", "NOTICE_MISMATCH", "NOTICE_TERMS", "GATE_ERROR")

#: 공고가 요구한 사람 몫 표 — 비어 있으면 「인력 미확정」(대표 결정 11-08 — 명부 칸을 만들지 않고 이름 · 경력을 짓지 않는다).
STAFF_TABLES = (bid.ORG_TABLE["key"], bid.PEOPLE_TABLE["key"])
#: 「인력 미확정」 풀이 — 조직 표의 구분 · 인원은 회사자료 「인력 구성」이 채우지만 「주요 업무」는 앱이 채우지 않고, 참여인력 표는 통째로 사람 몫이다.
STAFF_ORG_HOW = ("「구분 · 인원」은 회사자료 › 일반현황 「인력 구성」으로 채워지지만 「주요 업무」 칸은 앱이 채우지 않습니다. "
                 "받은 한글 · 워드 파일에서 채우세요(앱 안 상태는 차단으로 남고 파일 이름은 「초안」)")
STAFF_PEOPLE_HOW = ("앱은 참여인력 성명 · 학력 · 경력 · 자격 · 참여율을 채우거나 지어내지 않습니다(역할 · 담당 업무는 본문 업무분장을 읽을 수 있을 때만 옮깁니다). "
                    "받은 한글 · 워드 파일에서 직접 채우세요(앱 안 상태는 차단으로 남고 파일 이름은 「초안」)")


def approvable(quality: dict[str, Any]) -> bool:
    """승인할 수 있나 — 차단 0 이고 승인을 무효로 하는 검사(`VOID_CODES`)도 없을 때(있으면 승인해도 곧바로 무효 · 2.8.0 B2)."""
    codes = {f.get("code") for f in quality.get("findings") or []}
    return not quality.get("counts", {}).get("BLOCKER") and not codes & set(VOID_CODES)


def approve_block_reason(quality: dict[str, Any]) -> str:
    """승인할 수 없는 까닭(409 · 화면 `approveBlockReason` 과 같은 글) — 남은 차단이 앱 안에서 채울 수 없는 담당자 입력(인력 칸 ·
    회사 값 칸 · 갈래 input)뿐이면 「다시 쓰세요」를 권하지 않는다(게이트 판 3)."""
    findings = quality.get("findings") or []
    if any(f.get("code") == "GATE_ERROR" for f in findings):
        return "검증을 실행하지 못해 승인할 수 없습니다 — 잠시 뒤 다시 열어 보고, 계속되면 관리자에게 알리세요"
    blockers = [f for f in findings if f.get("severity") == "BLOCKER"]
    void = {f.get("code") for f in findings if f.get("code") in VOID_CODES}
    # 남은 차단이 담당자 입력뿐이어도 승인 무효 검사가 있으면 다시 쓰기가 먼저다(3차 검토 — 「빈칸만 채우면 된다」로 읽혔다)
    only_input = bool(blockers) and all(f.get("axis") == "input" or f.get("code") == "STAFFING_UNCONFIRMED" for f in blockers)
    if (not blockers or only_input) and void == {"NOTICE_TERMS"}:
        return "본문의 사업기간 · 사업금액이 공고 원문과 달라 승인할 수 없습니다 — 원문 값으로 고쳐 초안을 다시 쓴 뒤 승인하세요"
    if (not blockers or only_input) and void:
        return "초안을 쓴 뒤 공고 · 요구사항이 바뀌어 승인할 수 없습니다 — 초안을 다시 쓴 뒤 승인하세요"
    if blockers and all(f.get("code") == "STAFFING_UNCONFIRMED" for f in blockers):
        return "앱 안에서는 채울 수 없는 인력 칸만 남았습니다 — 받은 한글 · 워드 파일에서 채워 내세요(파일 이름은 「초안」으로 나갑니다)"
    if only_input:
        return "자동 작성은 끝났고 담당자 입력 칸만 남았습니다 — 회사자료에 적거나 받은 한글 · 워드 파일에서 채워 내세요(파일 이름은 「초안」으로 나갑니다)"
    return f"차단 {len(blockers) or quality.get('counts', {}).get('BLOCKER', 0)}건이 남아 승인할 수 없습니다 — 먼저 채우거나 고친 뒤 초안을 다시 쓰세요"
#: 본문에서 빼 빈칸 목록으로 옮긴 문장(`bid_filter`) — 묶어서 건수로.
MOVED_FIELDS = ("회사 근거 없는 회사 주장", "값을 정하면 넣을 문장", "회사가 정할 사항", "담당자 확인", bid.HYPE_FIELD)
#: 그중 빈칸 사유가 「안내 — 문장」 꼴인 것(`bid_filter`) — 예문은 문장만 보인다.
_PREFIXED_FIELDS = ("회사 근거 없는 회사 주장", "회사가 정할 사항", bid.HYPE_FIELD)
#: 인력 자격을 약속하는 문장(「보안직무 현직자 … 인력으로 배치하겠습니다」) — 인력이 미확정이면 근거 없는 약속이다(11-07 1786460 · 1782790).
_STAFF_WHO_RE = re.compile(r"인력|강사|컨설턴트|전문가|PM|심사원|멘토|연구원")
_STAFF_QUAL_RE = re.compile(r"자격|심사원|현직자|경력자|(?:경력|경험)(?:과\s*경험)?을\s*(?:다수\s*)?(?:보유|갖춘)|\d+\s*년\s*이상|자격증|박사|석사")
_STAFF_VERB_RE = re.compile(r"배치|투입|구성|꾸리|꾸립|선발|채용|섭외|배정|확보")
_STAFF_SKIP_RE = re.compile(r"교체")
#: 확정 전 인력의 지난 경력을 단정하는 꼴(2.11.0 T7c · 「컨설팅을 수행해 온 코치」 · 「경력이 풍부한 강사」 · 「○○ 출신 전문가」) — 동사가 없어도.
#: 「온」과 사람 낱말 사이 낱말은 조사로 끝나지 않을 때만(「운영해 온 프로그램을 전문가와」는 사람 이력이 아니다).
_STAFF_PERSON = r"(?:인력|강사|컨설턴트|전문가|PM|심사원|멘토|연구원|코치|퍼실리테이터|튜터)"
_STAFF_PAST_RE = re.compile(
    rf"(?:해|하여|해서)\s*온\s+(?:[^\s.,]+(?<![을를에로와과은는이가의])\s+){{0,2}}?(?:[가-힣]{{1,4}})?{_STAFF_PERSON}"
    rf"|(?:경력|경험|이력)이\s*(?:풍부한|많은|있는)\s*(?:[^\s.,]+(?<![을를에로와과은는이가의])\s+)?{_STAFF_PERSON}"
    rf"|출신\s*(?:의\s*)?{_STAFF_PERSON}")
#: 인력 표가 없는 공고에서도 보는 외부 인력 낱말 · 조건형(단정이 아니라 선정 기준).
_STAFF_EXTERNAL_RE = re.compile(r"위촉|외부|초빙|섭외")
_STAFF_COND_RE = re.compile(r"선정\s*기준|기준으로|요건|이상인\s*자|갖춘\s*자|후보")
#: 일정표 담당(역할) 칸에 든 경력 · 자격(2.9.0) — 그 칸은 역할 이름만(「PM · 운영 담당」).
_OWNER_PERSON_RE = bid.PERSON_VALUE_RE  # 참여인력 표 역할 · 담당 칸(2.10.0 D4)과 한 꼴 · 「교체할 때는 동등 이상의 자격 · 경력자로」 — 교체 규칙이지 지금 인력 약속이 아니다
_HWP_RE = re.compile(r"\.hwpx?$", re.I)
_SNIPPET = 90


def _snip(text: Any) -> str:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    return clean if len(clean) <= _SNIPPET else clean[:_SNIPPET - 1] + "…"


def _compact(text: Any) -> str:
    return re.sub(r"[\s·ㆍ()（）\[\]「」『』\"'.,]+", "", str(text or ""))


def draft_hash(draft: dict[str, Any]) -> str:
    """승인을 묶는 초안 내용 해시 — 쓴 시각 · 소항목 · 표 · 빈칸(저장본 그대로 · 회사자료로 채우기 전). 다시 쓰면 바뀌어 승인이 풀린다."""
    body = {key: draft.get(key) for key in ("executed_at", "sections", "tables", "blanks")}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


#: 고치는 법 — 코드별 한 줄(finding `action` · 2.8.0 B3). 같은 코드라도 심각도마다 다르면 `_finding(action=…)` 으로 준다.
ACTIONS: dict[str, str] = {
    "GATE_ERROR": "잠시 뒤 다시 열어 보고, 계속되면 관리자에게 알리세요",
    "PLACEHOLDER": "회사자료에 값을 적고 다시 열거나, 받은 한글 · 워드 파일에서 그 칸을 채우세요",
    "STAFFING_UNCONFIRMED": "받은 한글 · 워드 파일에서 인력 칸을 채우세요(앱은 성명 · 경력을 짓지 않습니다)",
    "EVAL_MAP_BLANK": "본문에서 그 평가 항목을 다룬 목차 번호를 받은 파일의 조견표에 적거나, 초안을 다시 쓰세요",
    "LLM_FAILED": "초안을 다시 쓰거나, 받은 파일에서 그 소항목을 직접 쓰세요",
    "OUTLINE_STANDARD": "제안요청서 목차와 맞춰 받은 파일의 목차를 고치세요",
    "EVAL_UNREAD": "원문 평가표를 보고 받은 파일 맨 앞에 조견표(평가항목 · 배점 · 제안서 해당 목차)를 직접 넣으세요",
    "MOVED_SENTENCES": "검토용 파일 「담당자가 채울 항목」에서 확인하고, 필요하면 근거와 함께 넣으세요",
    "HYPE_LEFT": "그 문장을 빼거나 달성 방법을 담은 확정형 계획으로 고치세요",
    "STAFFING_PROMISE": "실제 투입할 인력이 그 자격을 갖췄는지 확인하고, 아니면 문장을 고치세요",
    "NOTICE_MISMATCH": "공고가 바뀌었으면 초안을 다시 쓰세요",
    "STALE": "초안을 다시 쓰세요",
    "APPROVAL_VOID": "초안을 다시 읽고(바뀌었으면 다시 쓰고) 다시 승인하세요",
    "FORMAT_TWO_VOLUME": "받은 파일을 정량 · 정성 두 권으로 나눠 저장하세요",
    "FORMAT_PPT": "받은 본문을 PPT 로 옮기세요",
    "FORMAT_LANDSCAPE": "받은 파일의 쪽 방향을 가로로 바꾸세요",
    "REVIEW_FLAGS": "검토용 파일에서 경고를 보고 고치세요",
    "REVIEW_BLANKS": "검토용 파일 끝 「담당자가 채울 항목」을 하나씩 확인하세요",
    "NOTICE_UNCHECKED": "공고 원문과 표지의 사업명 · 발주기관을 직접 맞춰 보세요",
    "NOTICE_TERMS": "본문의 사업기간 · 사업금액을 공고 원문 값으로 고치세요(초안을 다시 쓰거나 받은 파일에서)",
    "EVAL_MAP_NO_CONTENT": "그 목차에 평가 기준 내용을 보강하거나, 조견표 목차를 내용이 있는 곳으로 고치세요",
    "EVIDENCE_UNVERIFIED": "증빙을 확인해 회사자료(실적 원장 증빙 메모 · 인증 유효기간)를 고치거나, 그 문장을 빼세요",
    "EVIDENCE_NUMBER": "결과보고서 · 만족도 결과 같은 증빙으로 그 수치를 확인한 뒤 남기거나, 수치를 빼고 수행 역할만 쓰세요",
    "COMMITMENT": "계약상 부담이 되는 약속입니다 — 대표 · 담당자가 승인하거나 문장을 고치세요",
    "NUMBER_SKIP": "원문 목차를 확인하세요",
    "NUMBER_FIXED": "원문 목차와 대조해 고친 번호가 맞는지 보세요",
    "NUMBER_DUP": "초안을 다시 쓰면 겹친 번호를 고쳐 붙입니다 — 또는 받은 파일에서 번호를 고치세요",
    "BLIND_RULE": "평가본으로도 받고, 영문 이름 · 로고는 직접 확인하세요",
    "BLIND_IDENT_LEFT": "받은 평가본 파일의 그 자리에서 회사 이름 · 대표자 · 연락처 · 번호 · 실적 기관 이름 · 실적 사업명을 지우거나 「당사」 · 기관 유형(대학 · 지자체 …) · 연도와 분야로 바꾸세요",
    "PAGES_APPROX": "원문 위치는 원문 파일에서 직접 확인하세요",
    "SCHEDULE_GRID": "초안을 다시 쓰면 추진 기간을 개월차(짧은 사업은 주차 「Wn~Wm」)로 씁니다 — 또는 받은 파일 일정표의 추진 기간을 "
                     "「n~m개월차」(짧은 사업은 「Wn~Wm」)로 고치세요",
    "SCHEDULE_OUTSIDE": "사업기간 안으로 일정을 고치세요(초안을 다시 쓰거나 받은 파일에서)",
    "SCHEDULE_TASK_MISSING": "초안을 다시 쓰거나 받은 파일 일정표에 그 보고 줄을 넣으세요",
    "SCHEDULE_ORDER": "착수 · 최종 보고 줄의 추진 기간을 확인하세요",
    "SCHEDULE_OUTPUT": "일정표 산출물 칸에 제안요청서 산출물 이름을 적으세요",
    "SCHEDULE_BODY_GAP": "본문 시점을 일정표 그 과업 기간 안으로 고치거나, 일정표 시작을 본문에 맞춰 앞당기세요",
    "REMOTE_SWAP": "기본 계획은 원문 방식(대면 · 집합 · 현장)대로 두고, 온라인 · 원격은 「발주기관과 협의해 정하는 대안」으로 고쳐 쓰세요",
    "ROLE_MISMATCH": "업무분장의 역할 이름 한 벌로 과업 「- 담당:」 줄과 일정표 담당 칸을 맞추세요(같은 이름 · 「주 담당 / 지원」 순서)",
    "NUMBER_SUM": "항목 수와 총계를 원문 값으로 맞추세요(초안을 다시 쓰거나 받은 파일에서)",
    "BUDGET_MATH": "받은 파일의 예산 배분안에서 수량 × 단가 · 소계 · 부가세 · 합계를 다시 계산해 고치세요(합계는 사업금액 안)",
    "NOTICE_VALUE": "제안요청서 기준 수치(값 · 「이상 · 이하」)로 고치세요(초안을 다시 쓰거나 받은 파일에서)",
    "NOTICE_AMBIGUOUS": "원문 표현은 그대로 두고, 발주기관에 질의하거나 내부 기준을 정하세요",
    "NO_SIMILAR_RULE": "원문이 막는 범위를 확인하고, 해당하면 받은 파일에서 그 실적 문장을 빼세요",
    "TASK_DETAIL_GAP": "초안을 다시 쓰거나, 과업마다 담당 · 일정 · 산출물 · 검수 · 위험 대응을 보강하세요",
    "CAPABILITY_LEAP": "원문이 요구한 산출물인지 확인하고, 아니면 그 문장을 빼세요",
    "TOOL_WORD": "「원문」을 「제안요청서」(또는 공고 · 과업지시서)로 바꾸세요 — 초안을 다시 쓰거나 받은 파일에서",
    "TITLE_WORD_GAP": "소항목 제목이 말한 내용을 본문에 넣으세요(초안을 다시 쓰거나 받은 파일에서)",
    "PDF_UNREADABLE": "한글에서 「PDF 로 저장」(인쇄 · 그림 저장 아님)한 파일을 다시 올리세요 — 암호를 걸었으면 풀고 올리세요",
    "PDF_PAGES": "원문 쪽수 상한(표지 · 목차 포함 여부)을 직접 확인하세요",
    "PDF_PAGES_OVER": "원문 쪽수 상한 안으로 줄이세요(표지 · 목차를 빼는 규정이면 원문으로 확인)",
    "PDF_NOT_A4": "한글 「편집 용지」를 A4(원문이 가로면 가로)로 맞춰 다시 저장하세요",
    "PDF_UNWRITTEN": "한글 파일에서 그 칸을 채우거나 지운 뒤 다시 PDF 로 저장하세요",
    "PDF_LINK_CUT": "표지 「공고 원문」 링크를 나라장터 공고 주소(공고번호 · 차수 포함)로 고치거나 링크 줄을 지우세요",
    "PDF_BUDGET_UNREAD": "예산 배분안 산수(수량 × 단가 · 소계 · 부가세 · 합계)는 직접 검산하세요",
    "PDF_EVAL_PAGE": "조견표의 쪽 번호를 실제 PDF 쪽으로 고치세요(표지 = 1쪽)",
    "PDF_EVAL_PAGES": "조견표에 쪽 번호를 적는다면 이 쪽 번호를 쓰세요(표지 = 1쪽)",
    "PDF_BLANKS_FEWER": "PDF 쪽 그림으로 「(담당자 입력)」이 남은 칸이 없는지 확인하세요 — 채운 칸 수가 차이와 같으면 정상입니다",
    "PDF_OVERLAP": "한글에서 그 쪽 긴 표 뒤에 빈 문단을 넣거나 표 앞에서 쪽을 나눠 글이 겹치지 않게 한 뒤 다시 PDF 로 저장하세요",
    "PDF_TABLE_ORPHAN": "그 표 제목 줄 앞에서 쪽을 나눠 제목 · 칸 이름 줄이 표 내용과 같은 쪽에 오게 한 뒤 다시 PDF 로 저장하세요",
    "SOURCE_PRESPEC_ONLY": "입찰 분석에서 본공고 첨부(공고서 · 입찰공고문)를 받은 뒤 초안을 다시 쓰세요",
    "ELIGIBILITY": "입찰 분석 › 참가 자격에서 사유를 보세요 — 회사자료(등록 업종 · 직접생산 품명 …)가 틀렸으면 고치고, "
                   "원문상 충족이면 조항 확인에 「충족」으로 남기세요(제출 · 참여 판단은 사람)",
    "PAPERS_UNREAD": "제안요청서 · 입찰공고문의 제출 서류 · 파일 구분 줄을 보고 낼 서류를 직접 정리하세요",
}


#: 빈 조견표 목차의 세 상태(3차 지시서 §3) — (제목, 풀이, 고치는 법, 갈래).
EVAL_GAPS: dict[str, tuple[str, str, str, str]] = {
    "auto_link": ("조견표 목차 자동 연결 실패 — 본문에 내용 있음",
                  "본문에 그 평가 기준 내용이 있는데 조견표에 연결하지 못했습니다(앱이 고칠 것)",
                  "초안을 다시 쓰면 다시 연결합니다 — 지금 파일이 급하면 받은 파일의 조견표에 그 내용이 있는 목차 번호를 적으세요", "auto"),
    "no_body": ("조견표 목차 미연결 — 본문에 그 평가 내용 없음",
                "평가위원이 이 항목을 찾을 본문이 없습니다(누락 · 앱이 고칠 것)",
                "초안을 다시 쓰거나, 그 평가 기준 내용을 본문에 보강한 뒤 조견표에 목차를 적으세요", "auto"),
    "evidence": ("조견표 목차 미연결 — 인력 · 증빙 항목",
                 "인력 · 전문성 항목입니다 — 참여인력 표 · 증빙(담당자 입력)을 정한 뒤 그 목차를 적으세요",
                 "참여인력 · 증빙을 정한 뒤 받은 파일 조견표에 참여인력 목차 번호를 적으세요", "evidence"),
}


def _finding(code: str, severity: str, title: str, detail: str, *, section: str | None = None, count: int = 1,
             location: str | None = None, action: str | None = None, axis: str | None = None) -> dict[str, Any]:
    """검사 한 줄 — `location`(소항목 · 표 이름 · 행 — 없으면 소항목) · `action`(고치는 법 — 없으면 코드별 한 줄) ·
    `axis`(갈래 — 없으면 코드별 `AXIS_OF` · 모르는 코드는 사람이 볼 「fact」)."""
    return {"code": code, "severity": severity, "title": title, "detail": detail, "section": section, "count": count,
            "location": location or section, "action": action or ACTIONS.get(code, ""), "axis": axis or AXIS_OF.get(code, "fact")}


# ---------------------------------------------------------------------------
# 검사
# ---------------------------------------------------------------------------


def _text_sample(block: tuple) -> str:
    kind = block[0]
    if kind in plan_export_service.TEXT_KINDS:
        return next((s[0] for s in block[1] if unwritten_count(str(s[0]))), "")
    if kind == "field":
        return f"{block[1]}: {block[2]}"
    return "사진 칸" if kind == "photo" else ""


def _scan_submit(view: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    """내는 문서 블록(내려받는 파일과 같은 블록 · 평가본만 받는 공고는 평가본 — `plan_export_service.submit_variant`)에서 남은 미작성 칸
    (`plan_export_service.block_blanks` 한 규칙) —
    spots {소항목(사람 몫 표는 「소항목 › 표 「제목」」): {count, sample, location, axis}} · staff [사람 몫 표 {key, title, count, section}] · eval [조견표 빈 행 (평가 항목, 칸 수, 행)] ·
    total(제출용 미작성 칸 수 = `submit_blank_count`)."""
    spots: dict[str, dict[str, Any]] = {}
    staff: list[dict[str, Any]] = []
    eval_rows: list[tuple[str, int, int]] = []
    total = 0
    # 사람이 채우는 소항목(서식 · 조직 · 일반현황 칸 절) — 그 빈칸은 정상 담당자 입력(A · 3차 지시서 §1)
    human_titles = {plan_export_service._heading(title) for section in (view.get("form") or {}).get("sections") or []
                    for item in section.get("items") or [] if item.get("kind") in ("human", "fields")
                    # 소항목 없는 대항목(열쇠가 대항목과 같음)은 머리가 대항목 제목(h1)이다
                    for title in (item.get("title"), section.get("title") if item.get("key") == section.get("key") else None) if title}

    def add(section: str, count: int, sample: str, location: str, axis: str) -> None:
        entry = spots.setdefault(section, {"count": 0, "sample": sample, "location": location, "axis": axis})
        entry["count"] += count
        if axis == "auto":  # 같은 소항목에 앱 몫 빈칸이 하나라도 있으면 앱이 고칠 것
            entry["axis"] = "auto"

    current = "본문"
    variant = plan_export_service.submit_variant(view)
    for block in plan_export_service.document_blocks(view, view.get("form") or {}, variant=variant, meta=meta):
        kind = block[0]
        if kind in ("h1", "h2"):
            current = str(block[1])
            continue
        count = plan_export_service.block_blanks(block)
        total += count
        if not count:
            continue
        if kind == "cover":
            blank = [str(label) for label, value in plan_export_service.cover_rows(block[1]) if not value]
            add("표지", count, " · ".join(f"{label} 칸" for label in blank), "표지", "input")
            continue
        if kind == "table":
            table = block[1]
            title = str(table.get("title") or "")
            rows = [[str(cell) for cell in row] for row in table.get("rows") or []]
            marked = [(n, row, sum(unwritten_count(cell) for cell in row)) for n, row in enumerate(rows, start=1)]
            marked = [entry for entry in marked if entry[2]]
            if table.get("key") == bid.EVAL_TABLE_KEY:
                eval_rows += [(row[1] if len(row) > 1 else "", n_cells, n) for n, row, n_cells in marked]
            elif table.get("key") in STAFF_TABLES:
                staff.append({"key": table.get("key"), "title": title, "count": count, "section": current})
            else:
                # 사람 몫 표(예산 배분안 · 2.10.0 D3)의 빈칸은 정상 담당자 입력 — 자기 묶음(같은 소항목의 앱 몫 빈칸과 합치면 auto 가 된다 · T5 검토) ·
                # 그 밖 표(AI 가 못 채운 칸)는 앱 몫
                n, row, _cells = marked[0]
                human = bool(table.get("human_only"))
                add(f"{current} › 표 「{title}」" if human else current, count, " · ".join(row), f"{current} › 표 「{title}」 {n}행",
                    "input" if human else "auto")
            continue
        # 일반현황 칸(회사자료에 값이 없음) · 사람이 채우는 소항목은 정상 담당자 입력 · 그 밖(AI 가 못 쓴 소항목 …)은 앱 몫
        add(current, count, _text_sample(block), current, "input" if kind == "field" or current in human_titles else "auto")
    return {"spots": spots, "staff": staff, "eval": eval_rows, "total": total}


def _eval_none(view: dict[str, Any]) -> list[str]:
    """조견표에서 「—」로 둔 정량 항목(짝 없음 — 제출 서류로 평가하는 항목 · `bid.EVAL_NONE`)."""
    table = next((t for t in view.get("tables") or [] if t.get("key") == bid.EVAL_TABLE_KEY), None)
    return [str(row[1]) for row in (table or {}).get("rows") or [] if len(row) >= 4 and str(row[3]).strip() == bid.EVAL_NONE]


def _body_sentences(view: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """본문 문장(칸 절 · 표만 있는 절 제외) — (소항목, 문장)."""
    return [(str(section.get("section") or ""), sentence) for section in view.get("sections") or []
            if section.get("kind") not in ("fields", "table_only") for sentence in section.get("sentences") or []]


def _grouped(pairs: list[tuple[str, str]]) -> list[tuple[str, int, str]]:
    """(소항목, 예문) → 소항목별 (소항목, 건수, 첫 예문)."""
    out: dict[str, list[Any]] = {}
    for section, text in pairs:
        entry = out.setdefault(section, [0, text])
        entry[0] += 1
    return [(section, count, sample) for section, (count, sample) in out.items()]


def _number_breaks(form: dict[str, Any]) -> tuple[str | None, str | None]:
    """(건너뛴 곳 「Ⅲ → Ⅴ」, 겹치거나 거꾸로 간 곳 「Ⅵ → Ⅵ」) — 첫 곳만. 건너뜀은 원문대로 옮긴 것(2.6.1) · 겹침은 2.8.0 전 옛 초안
    (새 초안은 `bid.major_numbers` 가 고쳐 붙인다 · B5)."""
    skip = dup = None
    previous: tuple[str, int] | None = None
    for section in form.get("sections") or []:
        no = str(section.get("no") or "")
        value = bid._ROMAN.get(no) or (int(no) if no.isdigit() else None)
        if value is None:
            previous = None
            continue
        if previous and value - previous[1] >= 2 and skip is None:
            skip = f"{previous[0]} → {no}"
        if previous and value <= previous[1] and dup is None:
            dup = f"{previous[0]} → {no}"
        previous = (no, value)
    return skip, dup


# --- 조견표 대응(2.8.0 B4) ---------------------------------------------------------------------------------------


def _unit_texts(view: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    """(목차 열쇠 → 그 목차 글, 소항목 글만) — 제목 + 문장 + 딸린 표 칸(공백 · 문장부호 뺌). 대항목 열쇠는 소항목 글을 모두 이어 붙인다."""
    tables = {t.get("key"): t for t in view.get("tables") or []}
    entries: dict[str, str] = {}
    texts: dict[str, str] = {}
    for entry in view.get("sections") or []:
        if entry.get("kind") == "table_only" or not entry.get("key"):
            continue
        parts = [str(entry.get("section") or ""), *(str(s.get("text") or "") for s in entry.get("sentences") or [])]
        parts += [str(cell) for key in entry.get("tables") or [] if key != bid.EVAL_TABLE_KEY
                  for row in (tables.get(key) or {}).get("rows") or [] for cell in row]
        text = bid._name_key(" ".join(parts))
        entries[entry["key"]] = texts[entry["key"]] = text
        major = entry.get("major_key")
        if major and major != entry["key"]:
            texts[major] = texts.get(major, "") + text
    return texts, entries


def _unit_keys(form: dict[str, Any]) -> dict[str, str]:
    """조견표 목차 글(「Ⅲ-4」 · 「1.1」 · 「Ⅵ」) → 목차 열쇠 — 작성기 `unit_number` 를 거꾸로."""
    numbers: dict[str, str] = {}
    for section in form.get("sections") or []:
        if not section.get("no") or not section.get("key"):  # 11-03 옛 초안 목차에는 번호 칸이 없다 — 짝을 못 찾으면 「미확인」
            continue
        numbers.setdefault(str(section["no"]), section["key"])
        for item in section.get("items") or []:
            numbers.setdefault(bid.unit_number(form, item["key"]), item["key"])
    return numbers


#: 핵심 낱말 찾기 — 작성기 짝 찾기와 같은 규칙(`bid.word_re` · 3차 지시서 §3).
_SAME_WORDS = bid.SAME_WORDS
_word_re = bid.word_re
#: 인력 · 전문성 평가 항목(「투입인력 전문성」 · 「수행능력 및 전문성」 · 「인력사항」) — 목차가 비면 그 내용은 참여인력 표 · 증빙(담당자 입력)이다.
_STAFF_ITEM_RE = re.compile(r"인력|전문성|투입\s*인원|참여\s*인원|수행\s*능력")
#: 이름 낱말이 목차에 없어도 평가 기준 낱말이 이만큼 있으면 「없음」 대신 「미확인」(같은 뜻 다른 말 · 게이트 판 3).
RESCUE_MIN_WORDS = 3


def evaluation_coverage(view: dict[str, Any]) -> list[dict[str, Any]]:
    """평가항목 대응표(`quality.evaluation_coverage` · 2.8.0 B4) — 평가 항목마다 배점 · 조견표 목차 · 짝 출처 · 본문(확인 · 없음 · 미확인) ·
    상태(OK · REVIEW · MISSING). 본문(근사)은 항목 이름의 핵심 낱말이 그 목차 글(제목 포함)에 하나라도 있으면 「확인」 · 하나도 없으면
    「없음」 — 큰 과업 소항목에는 기준 낱말(「취업률 · 조사」)이 늘 있어 「취업현황조사」가 0번인데도 「확인」이 됐다(11-07 판 2위 Ⅲ-4).
    이름에 핵심 낱말이 없으면(「사업 이해도」) 평가 기준 낱말(소항목 절반 넘게 나오는 흔한 낱말은 뺌)로 본다. 목차를 못 찾았거나 볼 낱말이
    없거나 정량 항목(제출 서류로 평가)이면 「미확인」."""
    form = view.get("form") or {}
    items = (form.get("evaluation") or {}).get("items") or []
    table = next((t for t in view.get("tables") or [] if t.get("key") == bid.EVAL_TABLE_KEY), None)
    if not items or table is None:
        return []
    rows = [row for row in table.get("rows") or [] if len(row) >= 4]
    sources = table.get("sources") or []
    texts, entries = _unit_texts(view)
    numbers = _unit_keys(form)
    by_number = {key: no for no, key in numbers.items()}
    staffed = any(t.get("key") in STAFF_TABLES for t in view.get("tables") or [])
    guides = {item["key"]: bid._name_key(f"{item.get('plain') or item.get('title') or ''} {item.get('guide') or ''}")
              for section in form.get("sections") or [] for item in section.get("items") or [] if item.get("key")}
    out: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        name = str(item.get("name") or "")
        aligned = index < len(rows) and str(rows[index][1]) == name
        row = rows[index] if aligned else next((r for r in rows if str(r[1]) == name), None)
        cell = str(row[3]).strip() if row else ""
        mapped = cell if cell and cell != bid.EVAL_NONE and not unwritten_count(cell) else None
        body = "미확인"
        crit = [_word_re(w) for w in bid.criteria_words(item, entries)]
        if mapped and item.get("kind") != "정량":
            keys = [numbers.get(part.strip()) for part in mapped.split(",")]
            named = [_word_re(w) for w in sorted({bid._name_key(w) for w in bid.eval_core_words(name)} - {""})]
            # 이름에 핵심 낱말이 없으면 기준 낱말로 — 하나뿐이면(「추진전략」 → 「프로그램」) 내용 근거로 약해 판단하지 않는다(게이트 판 3)
            words = named or (crit if len(crit) >= bid.GUIDE_MIN_WORDS else [])
            if keys and all(keys) and words:
                body = "확인" if any(word.search(texts.get(str(key), "")) for key in keys for word in words) else "없음"
                # 이름 낱말이 0번이어도 같은 뜻 다른 말(「투입인력」 ↔ 「인력 투입」)일 수 있다 — 기준 낱말이 셋 이상 있으면 「미확인」(게이트 판 3 ·
                # 둘이면 「사후 · 지원」처럼 다른 뜻으로도 맞아 진짜 누락(11-11 3위 Claude 「품질관리 요구사항」 → Ⅲ-2)을 놓쳤다)
                if body == "없음" and named and sum(1 for word in crit if any(word.search(texts.get(str(key), "")) for key in keys)) >= RESCUE_MIN_WORDS:
                    body = "미확인"
        status = "OK" if mapped and body == "확인" else "REVIEW" if mapped or item.get("kind") == "정량" else "MISSING"
        gap = candidate = None
        if status == "MISSING":
            # 빈 「제안서 해당 목차」의 세 상태(3차 지시서 §3) — 본문에 내용 있음(자동 연결 실패) · 인력 · 증빙 항목 · 본문에 내용 없음.
            # 후보 목차는 작성 방법에 기준 낱말이 많은 곳 → 본문에 많은 곳 순(작성기 `guide_matches` 와 같은 순서)
            # 흔한 기준 낱말 둘이 우연히 맞는 곳(1804104 「사업의 이해도」 → Ⅴ-1 사업수행 일정)은 후보가 아니다 — 본문 2개 이상에 더해 작성 방법 2개
            # 이상이거나 항목 이름의 핵심 낱말이 본문에 있어야 한다(관련성 확인 · 3차 검토). 후보 번호는 단독 1위일 때만(동점이면 번호 없이)
            core = [_word_re(w) for w in sorted({bid._name_key(w) for w in bid.eval_core_words(name)} - {""})]
            hits = sorted(((sum(1 for word in crit if word.search(guides.get(key, ""))), sum(1 for word in crit if word.search(text)), key)
                           for key, text in entries.items()), key=lambda hit: (hit[0], hit[1]), reverse=True)
            hits = [hit for hit in hits if hit[1] >= bid.GUIDE_MIN_WORDS
                    and (hit[0] >= bid.GUIDE_MIN_WORDS or any(word.search(entries[hit[2]]) for word in core))]
            if hits:
                alone = len(hits) == 1 or hits[0][:2] != hits[1][:2]
                gap, candidate = "auto_link", by_number.get(hits[0][2]) if alone else None
            elif staffed and _STAFF_ITEM_RE.search(f"{name} {' '.join(map(str, item.get('criteria') or []))}"):
                gap = "evidence"
            else:
                gap = "no_body"
        out.append({"name": name, "area": item.get("area"), "kind": item.get("kind"), "points": item.get("points"), "mapped": mapped,
                    "source": (sources[index] if aligned and index < len(sources) else None) if mapped else None,
                    "body": body, "status": status, "gap": gap, "candidate": candidate})
    return out


# --- 과업 상세 · 역량 비약(3차 지시서 §6 · §8 · 게이트 판 3) -----------------------------------------------------

#: 과업 블록의 다섯 신호 — 담당 · 일정 · 산출물 · 검수 · 위험 대응(근사 · 낱말).
_TASK_SIGNALS = (re.compile(r"담당|PM|책임|운영\s*인력|강사"),
                 re.compile(r"\d+\s*(?:~\s*\d+\s*)?개월\s*차|\d+\s*월|매월|매주|분기|주간|격주|착수|종료|(?<![A-Za-z])W\s*\d|\d+\s*주\s*차"),
                 re.compile(r"산출물|보고서|결과물|교재|자료집|결과\s*보고"), re.compile(r"검수|검토|점검|평가|만족도|확인"),
                 re.compile(r"위험|리스크|→|대응|대비"))
_LEAP_RE = re.compile(r"(?:역량|기술)(?:으로|로|을\s*활용해|을\s*살려)[^.。]{0,40}?(?:도구|시스템|챗봇|대시보드|플랫폼)\S*\s*(?:을|를)?\s*(?:만들|구축|개발|구성|운영)")


def task_gaps(view: dict[str, Any]) -> list[tuple[str, int, int]]:
    """과업 소항목(세부과제 · 추진방안)마다 「○」 블록 중 다섯 신호 가운데 둘 이상이 빠진 블록 수 — 절반을 넘을 때만 (소항목, 빠진 수, 블록 수)."""
    form = view.get("form") or {}
    targets = {unit["key"] for unit in bid.form_units(form) if unit.get("target") == "task"} if form.get("sections") else set()
    out: list[tuple[str, int, int]] = []
    for entry in view.get("sections") or []:
        if entry.get("key") not in targets or entry.get("by") != "llm":
            continue
        blocks: list[str] = []
        for sentence in entry.get("sentences") or []:
            text = str(sentence.get("text") or "")
            if plan_export_service._subheading(text) or not blocks:
                blocks.append(text)
            else:
                blocks[-1] += " " + text
        blocks = [block for block in blocks if len(block) >= 40]
        if len(blocks) < 2:
            continue
        missing = sum(1 for block in blocks if sum(1 for signal in _TASK_SIGNALS if not signal.search(block)) >= 2)
        if missing * 2 > len(blocks):
            out.append((str(entry.get("section") or ""), missing, len(blocks)))
    return out


# --- 작성 도구 낱말 · 제목 조각 · 확정 전 인력 경력(2.11.0 T7a~c · 게이트 판 5) ---------------------------------------

#: 작성 지시문이 자료를 부르는 말 「원문」이 제출용에 샌 것 — 「원문과 대조」 · 「원문공개」처럼 과업 낱말인 꼴은 뺀다.
_TOOL_WORD_RE = re.compile(r"원문(?!\s*(?:과|와|을|를)?\s*(?:대조|비교|공개|정보|데이터|DB|보존|파일))")
_TOOL_CHUNK_RE = re.compile(r"원문\S*(?:\s+\S+)?")


def tool_words(view: dict[str, Any], sentences: list[tuple[str, dict[str, Any]]]) -> list[tuple[str, str]]:
    """본문 문장 · AI 표(일정 · 핵심 마감 · 과업별 대응) 칸에 남은 「원문」 — (자리, 글). 인용 원문에 그 낱말이 있는 제안요청서 문장과
    이번 공고 글에 같은 덩어리가 있는 것(기록물 원문 과업)은 뺀다."""
    notice: str | None = None  # 낱말이 나온 초안만 공고 글을 모은다
    out: list[tuple[str, str]] = []

    def left(text: str) -> bool:
        nonlocal notice
        if not _TOOL_WORD_RE.search(text):
            return False
        if notice is None:
            notice = _compact(notice_text(view))
        chunks = [m.group(0) for m in _TOOL_CHUNK_RE.finditer(text) if _TOOL_WORD_RE.match(m.group(0))]
        return any(_compact(chunk) not in notice for chunk in chunks)

    for section, sentence in sentences:
        if sentence.get("type") == plan_draft_service.NOTICE and "원문" in str(sentence.get("source") or ""):
            continue
        if left(str(sentence.get("text") or "")):
            out.append((section, str(sentence.get("text") or "")))
    keys = (bid.SCHEDULE_TABLE["key"], bid.MILESTONE_TABLE["key"], bid.SCOPE_TABLE["key"])
    for table in view.get("tables") or []:
        if table.get("key") not in keys or table.get("by") != "llm":
            continue
        for row in table.get("rows") or []:
            for cell in row:
                text = plan_export_service._CELL_MARK.sub("", str(cell or ""))
                if left(text):
                    out.append((f"{table.get('title')} 표", text))
    return out


#: 소항목 제목에서만 흔한 말 — 공고 낱말을 박지 않으려 다섯에서 멈춘다.
_TITLE_GENERIC = frozenset(("제안", "기타", "특징", "장점", "사항"))
_TITLE_SPLIT_RE = re.compile(r"\s+및\s+|\s*[·ㆍ,/]\s*")
_TITLE_MAX = 25


def title_gaps(view: dict[str, Any]) -> list[tuple[str, str]]:
    """소항목 제목 「A 및 B」 · 「A · B」에서 한 조각의 핵심 낱말이 본문 · 딸린 표 어디에도 없는 것(근사) — (소항목, 조각).
    긴 제목(작성 방법 문장을 목차로 둔 공고) · AI 가 쓰지 않은 소항목은 보지 않는다. 네 글자 넘는 한글 낱말은 뒤 두 글자(머리 명사)만
    있어도 있음으로 본다(「업무보고」 → 「착수 보고」)."""
    plains = {item["key"]: str(item.get("plain") or "") for section in (view.get("form") or {}).get("sections") or []
              for item in section.get("items") or [] if item.get("key")}
    tables = {t.get("key"): t for t in view.get("tables") or []}
    out: list[tuple[str, str]] = []
    for entry in view.get("sections") or []:
        plain = plains.get(entry.get("key"), "")
        if entry.get("by") != "llm" or not entry.get("sentences") or not plain or len(plain) > _TITLE_MAX:
            continue
        # 괄호 안의 「·」 「,」는 제목 조각이 아니다(「추진 일정(주차별 · 월별)」 · 2.11.0 검토)
        parts = [part.strip() for part in _TITLE_SPLIT_RE.split(re.sub(r"[(（][^)）]*[)）]", "", plain)) if part.strip()]
        if len(parts) < 2:
            continue
        body = bid._name_key(" ".join([*(str(s.get("text") or "") for s in entry["sentences"]),
                                       *(str(cell) for key in entry.get("tables") or [] if key != bid.EVAL_TABLE_KEY
                                         for row in (tables.get(key) or {}).get("rows") or [] for cell in row)]))
        for part in parts:
            words = bid.eval_core_words(part) - _TITLE_GENERIC
            if words and not any(bid.word_re(word).search(body) or (len(word) >= 4 and re.fullmatch(r"[가-힣]+", word) and word[-2:] in body)
                                 for word in words):
                out.append((str(entry.get("section") or ""), part))
    return out


def past_career(sentence: dict[str, Any]) -> bool:
    """확정 전 인력의 지난 경력을 단정하는 문장인가 — 교체 규칙 · 선정 기준 꼴 · 인용 원문에 같은 꼴이 있는 제안요청서 문장은 아니다."""
    text = str(sentence.get("text") or "")
    match = _STAFF_PAST_RE.search(text)
    if not match or _STAFF_SKIP_RE.search(text) or _STAFF_COND_RE.search(text):
        return False
    return not (sentence.get("type") == plan_draft_service.NOTICE and _compact(match.group(0)) in _compact(sentence.get("source")))


# --- 세부 추진 일정표(3차 지시서 §4 · 게이트 판 3) ---------------------------------------------------------------


def _llm_schedule(view: dict[str, Any]) -> tuple[dict[str, Any] | None, str, str]:
    """AI 가 쓴 세부 추진 일정표 · 그 소항목 · 위치 글(「소항목 › 표 「…」」) — 없으면 (None, "", "")."""
    table = next((t for t in view.get("tables") or [] if t.get("key") == bid.SCHEDULE_TABLE["key"] and t.get("by") == "llm"), None)
    if not table:
        return None, "", ""
    section = next((item.get("title") for s in (view.get("form") or {}).get("sections") or [] for item in s.get("items") or []
                    if item.get("key") == table.get("item")), None) or str(table.get("title") or "")
    return table, section, f"{section} › 표 「{table.get('title') or '추진 일정'}」"


def schedule_findings(view: dict[str, Any]) -> list[dict[str, Any]]:
    """AI 가 쓴 세부 추진 일정표 검사(모두 앱이 고칠 것 · auto) — 월별 칸 표(간트)에 못 그린 과업(추진 기간이 개월차가 아님 · 11-11 Codex 1 · 3위
    간트가 통째로 빠졌는데 아무 경고가 없었다) · 사업기간을 넘는 일정 · 원문이 요구한 보고 줄(착수 · 중간 · 최종) 없음 · 착수 · 최종 보고 순서 ·
    산출물 칸이 모두 빔. 사람이 채우는 규칙 표(by rules)는 보지 않는다."""
    form = view.get("form") or {}
    table, section, location = _llm_schedule(view)
    if not table:
        return []
    rows = [[str(cell) for cell in row] for row in table.get("rows") or [] if row and not unwritten_count(str(row[0]))]
    if not rows:
        return []
    found: list[dict[str, Any]] = []
    period = form.get("agreement_period") or {}
    # 짧은 사업(weeks)은 주차(Wn) 칸 — 간트와 같은 읽기(`period_reader` · 2.10.0 D1)
    weeks = period.get("weeks")
    read = plan_export_service.period_reader(rows, weeks)
    weekly = read is plan_export_service.period_weeks
    # 말은 사업 단위로 — 짧은 사업은 개월차 읽기로 떨어져도 「주차」(T2 검토 — 「n주차」만 쓴 표가 「개월차가 아닙니다 · 월별」로 나갔다)
    unit, grid = ("주차(Wn)", "주차별") if weeks else ("개월차", "월별")
    spans = [(row, read(plan_export_service._CELL_MARK.sub("", row[1]) if len(row) > 1 else "")) for row in rows]
    undrawn = [row for row, months in spans if not months]
    if undrawn:
        found.append(_finding("SCHEDULE_GRID", "MAJOR", f"{grid} 일정표(간트)에 그리지 못한 과업이 있음",
                              f"{len(undrawn)}/{len(rows)}줄 — 추진 기간이 {unit}가 아닙니다(예: 「{_snip(undrawn[0][1] if len(undrawn[0]) > 1 else '')}」). "
                              f"그 줄은 {grid} 칸 표에서 빠집니다", section=section, count=len(undrawn), location=location))
    monthly = [row for row, months in spans if months] if weeks and not weekly else []
    if monthly:
        # 짧은 사업인데 개월차 — 사업기간 안이어도 월별 간트가 나가고 주차 표와 단위가 어긋난다(T2 검토 · 주차 표는 이때 붙이지 않음)
        found.append(_finding("SCHEDULE_GRID", "MAJOR", "짧은 사업인데 일정표를 개월차로 씀",
                              f"{len(monthly)}/{len(rows)}줄 — 사업기간 약 {weeks}주는 착수일 기준 주차(「W1~W2」)로 씁니다"
                              f"(예: 「{_snip(plan_export_service._CELL_MARK.sub('', monthly[0][1]))}」) · 지금은 월별 칸 표로 그려집니다", section=section, count=len(monthly), location=location))
    limit, span_label = period.get("months"), f"사업기간 {period.get('months')}개월"
    if weekly:
        limit, span_label = weeks, f"사업기간 {weeks}주(착수일 기준)"
    elif weeks and period.get("days"):
        # 짧은 사업에 개월차 — 계약 예정일 ~ 끝날 일수를 넘는 개월차는 사업기간 밖(44일이면 3개월차부터 · 2.10.0 D1)
        limit = -(-int(period["days"]) // 30)
        span_label = f"사업기간 약 {weeks}주({period['days']}일 · 계약 예정 이후)"
    over = [row for row, months in spans if months and limit and max(months) > int(limit)]
    over += [row for row in rows if len(row) > 1 and "협약 기간 밖" in row[1] and row not in over]
    if over:
        found.append(_finding("SCHEDULE_OUTSIDE", "MAJOR", "사업기간 밖 일정",
                              f"{len(over)}줄 — 「{_snip(over[0][0])} · {_snip(plan_export_service._CELL_MARK.sub('', over[0][1]))}」"
                              + (f" · {span_label}" if limit else ""), section=section, count=len(over), location=location))
    tasks = [row[0] for row in rows]
    expect = set(form.get("schedule_expect") or [])
    missing = [name for name, _required, present in bid.SCHEDULE_REPORTS
               if name in expect and not any(bid.report_task(name, task) for task in tasks)]
    if missing:
        found.append(_finding("SCHEDULE_TASK_MISSING", "MAJOR", "원문이 요구한 보고 줄이 일정표에 없음",
                              " · ".join(f"「{name}」" for name in missing) + " — 제안요청서는 이 보고를 요구합니다(원문 · 근사)",
                              section=section, count=len(missing), location=location))
    drawn = [(min(months), max(months), row[0]) for row, months in spans if months]
    if drawn:
        first, last = min(s for s, _e, _t in drawn), max(e for _s, e, _t in drawn)
        wrong = [task for start, _end, task in drawn if bid.report_task("착수 보고", task) and start != first]
        wrong += [task for _start, end, task in drawn if bid.report_task("최종 보고", task) and end != last]
        if wrong:
            found.append(_finding("SCHEDULE_ORDER", "MINOR", "착수 · 최종 보고 일정 순서가 어긋남",
                                  f"「{_snip(wrong[0])}」 — 착수는 가장 먼저, 최종 보고는 가장 늦게 끝나야 합니다",
                                  section=section, count=len(wrong), location=location))
    if len(table.get("columns") or []) == 5 and not any(len(row) >= 5 and row[4].strip() for row in rows):
        found.append(_finding("SCHEDULE_OUTPUT", "MINOR", "일정표 산출물 칸이 모두 비었음",
                              "과업별 산출물(보고서 · 교재 · 결과물)을 제안요청서 이름 그대로 적어야 일정 · 산출물이 이어집니다",
                              section=section, location=location))
    return found


#: 본문이 적은 시점 — 「1개월차」 · 「2~3개월차」 · 「W2」 · 「W1~W3」(2.10.0 · diff11).
_WHEN_RE = re.compile(r"\d+\s*(?:~\s*\d+\s*)?개월\s*차|(?<![A-Za-z])W\s*\d{1,2}(?:\s*[~\-–～∼]\s*W?\s*\d{1,2})?")
#: 과업 블록 소제목 머리(「○ 마. 」 · 「○ 3) 」) — 일정표 과업 칸과 짝지을 때 뗀다.
_HEAD_NO_RE = re.compile(r"^[\s○□❍◦■▪•\-]*(?:(?:[가-하]|\d{1,2})\s*[.)]\s*)?")


def body_schedule_gaps(view: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    """과업 블록(「○ 과업 이름」 아래 줄)에 적은 시점이 일정표 그 과업 시작보다 앞섬 → [(소항목, 과업, 본문 시점, 일정표 기간)] (2.10.0 · diff11 —
    「매칭 상대 확보 지연 → 1개월차부터 후보 사전 접촉」인데 일정표는 2~3개월차). 미룬 시점(지연 대응 「W6 초로 조정」 · 「- 연결:」 다음 과업)은
    아니다(T2 검토). 짝은 블록 소제목과 과업 칸의 글(공백 · 문장부호 뺌 · 4자 이상)이 한쪽에 들어가는 줄이 하나일 때만 · 못 찾으면 건너뛴다(근사 — 놓치는 쪽)."""
    form = view.get("form") or {}
    table = next((t for t in view.get("tables") or [] if t.get("key") == bid.SCHEDULE_TABLE["key"] and t.get("by") == "llm"), None)
    rows = [[str(cell) for cell in row] for row in (table or {}).get("rows") or [] if len(row) > 1 and not unwritten_count(str(row[0]))]
    if not rows:
        return []
    read = plan_export_service.period_reader(rows, (form.get("agreement_period") or {}).get("weeks"))
    clean = plan_export_service._CELL_MARK.sub  # 칸 끝 검토 표식(「⚠ 공고 문장과 거의 같음」)은 짝 · 글에서 뗀다
    tasks = [(_compact(clean("", row[0])), clean("", row[0]), clean("", row[1]), read(clean("", row[1]))) for row in rows]
    out: list[tuple[str, str, str, str]] = []
    for section, head, lines in _task_blocks(view):
        name = _compact(_HEAD_NO_RE.sub("", head))
        pairs = [t for t in tasks if _same_task(name, t[0])]
        if len(pairs) != 1 or not pairs[0][3]:
            continue
        _key, task, period, marked = pairs[0]
        for line in lines:
            for match in _WHEN_RE.finditer(line):
                when = read(match.group(0))
                if when and min(when) < min(marked):
                    out.append((section, task, match.group(0), period))
    return out


def _task_blocks(view: dict[str, Any]) -> list[tuple[str, str, list[str]]]:
    """AI 가 쓴 소항목의 「○」 블록 — (소항목, 소제목, 아래 줄). 첫 소제목 앞 줄은 블록이 아니다."""
    out: list[tuple[str, str, list[str]]] = []
    for entry in view.get("sections") or []:
        if entry.get("by") != "llm":
            continue
        blocks: list[tuple[str, str, list[str]]] = []
        for sentence in entry.get("sentences") or []:
            text = str(sentence.get("text") or "")
            if plan_export_service._subheading(text):
                blocks.append((str(entry.get("section") or ""), text, []))
            elif blocks:
                blocks[-1][2].append(text)
        out += blocks
    return out


def _same_task(name: str, task: str) -> bool:
    """블록 소제목과 일정표 과업 칸이 같은 과업인가 — 공백 · 문장부호를 뺀 글(4자 이상)이 한쪽에 들어감(근사)."""
    return len(name) >= 4 and len(task) >= 4 and (name in task or task in name)


#: 업무분장 역할 줄(「- PM(사업총괄): … 맡습니다」 · 2.10.0 T3) — 참여인력 표(`bid.staff_roles` · D4)와 한 곳.
_ROLE_LINE_RE, _ROLE_LABELS = bid.ROLE_LINE_RE, bid.ROLE_LABELS
_OWNER_LINE_RE = re.compile(r"^\s*-\s*담당\s*[:：]")


def _role_key(text: Any) -> str:
    """역할 이름 비교 글 — 괄호 풀이(「PM(사업총괄)」의 「(사업총괄)」)를 떼고 공백 · 문장부호를 뺀다."""
    return _compact(re.sub(r"[(（][^)）]*[)）]", "", str(text or "")))


def _role_names(text: str) -> set[str]:
    """업무분장 역할 하나의 이름들 — 괄호 밖 이름 · 괄호 안 별칭(2자 이상 · 「사업 총괄(PM)」 = 「사업총괄」 · 「PM」 · T3 검토)."""
    inner = {_compact(name) for name in re.findall(r"[(（]([^)）]*)[)）]", text)}
    return {name for name in {_role_key(text), *inner} if len(name) >= 2}


def role_findings(view: dict[str, Any]) -> list[dict[str, Any]]:
    """역할 이름 한 벌(2.10.0 T3 · wording6 · diff10 — 대항목 호출이 따로라 일정표 「PoC · 네트워킹 담당」 ↔ 과업 「- 담당: PM(매칭 총괄)」 ·
    업무분장에 없는 「예산 · 정산 담당」). AI 일정표 줄마다 담당 칸이 업무분장 역할 이름을 쓰는가 · 짝 과업 블록의 「- 담당:」 줄에 주 담당(칸의 첫 역할)이
    있는가. 업무분장 역할 줄이 없으면 건너뛴다(놓치는 쪽 · 보통 · 앱이 고칠 것)."""
    table, section, location = _llm_schedule(view)
    if len((table or {}).get("columns") or []) != 5:  # 담당 칸이 없는 옛 3칸 일정표(2.9.0 전 · 셋째 칸은 세부 내용)
        return []
    rows = [[str(cell) for cell in row] for row in (table or {}).get("rows") or [] if len(row) > 2 and not unwritten_count(str(row[0]))]
    # 역할마다 이름 한 벌(괄호 밖 이름 + 괄호 안 별칭)
    roles = [names for entry in view.get("sections") or [] if entry.get("by") == "llm" for sentence in entry.get("sentences") or []
             if (match := _ROLE_LINE_RE.match(str(sentence.get("text") or ""))) and _role_key(match.group(1)) not in _ROLE_LABELS
             and (names := _role_names(match.group(1)))]
    if not rows or not roles:
        return []
    blocks = _task_blocks(view)
    clean = plan_export_service._CELL_MARK.sub
    off: list[tuple[str, str, str]] = []
    for row in rows:
        task, owner = clean("", row[0]), clean("", row[2])
        key = _role_key(owner)
        # 칸에서 먼저 나온 역할이 주 담당(같은 자리면 긴 이름)
        named = sorted((min((key.find(name), -len(name)) for name in names if name in key), i)
                       for i, names in enumerate(roles) if any(name in key for name in names))
        if not named:
            off.append((task, owner, "업무분장(역할별 담당 업무)에 없는 역할 이름"))
            continue
        pairs = [lines for _s, head, lines in blocks if _same_task(_compact(_HEAD_NO_RE.sub("", head)), _compact(task))]
        line = next((text for text in pairs[0] if _OWNER_LINE_RE.match(text)), None) if len(pairs) == 1 else None
        if line and not any(name in _compact(line) for name in roles[named[0][1]]):
            off.append((task, owner, f"과업 「{_snip(line.strip())}」 줄에 주 담당이 없음"))
    if not off:
        return []
    task, owner, why = off[0]
    return [_finding("ROLE_MISMATCH", "MINOR", "역할 이름이 업무분장 · 과업 담당 · 일정표에서 다름(근사)",
                     f"{len(off)}/{len(rows)}줄 — 「{_snip(task)}」 일정표 담당 「{_snip(owner)}」: {why}",
                     section=section, count=len(off), location=location)]


#: 온라인 · 화상 · 원격으로 바꾸는 말(「온라인 미팅으로 전환」 · 「대면(화상) 미팅」) — 원문이 대면으로 정한 활동 낱말(`bid.onsite_activities`)과
#: 같은 문장일 때만 · 「협의 · 승인 · 합의」 꼴(발주기관과 협의해 정하는 대안)은 아니다(2.10.0 · D2 · 11-13 동국대).
_REMOTE = r"(?:온라인|화상|원격|비\s*대면)"
_REMOTE_RE = re.compile(_REMOTE)
#: 대안 병기 — 「대면 · 화상」 · 「대면/온라인」 · 「대면 또는 화상」(T3 검토 · wording0 (b) — 괄호 꼴만 잡았다)
_PAIR = r"(?:[·ㆍ/]|또는|혹은)"
_SWAP_RE = re.compile(rf"대체|전환|바꿔|바꾸|바뀌|대신|돌려|[(（]\s*{_REMOTE}|{_PAIR}\s*{_REMOTE}|{_REMOTE}\s*{_PAIR}")
_AGREE_RE = re.compile(r"협의|승인|합의")
#: 「온라인으로 대체하지 않습니다」 · 「비대면 전환은 하지 않습니다」 — 지시를 지킨 부정문(T2 검토).
_NO_SWAP_RE = re.compile(r"(?:대체|전환|바꾸|바꿔|대신)\S{0,6}\s*(?:하지\s*)?않")


def _swapped(text: str, word: str) -> bool:
    """온라인 낱말이 그 활동을 바로 꾸밀 때만 — 「온라인 미팅」 · 「대면(화상) 미팅」 · 「교육(온라인)」 · 「미팅을 온라인으로」 ·
    병기 「온라인 · 대면 미팅」. 「교육 자료는 온라인 게시판으로」처럼 다른 대상이 바뀐 문장은 아니다(T2 검토)."""
    w = re.escape(word)
    return bool(re.search(rf"{_REMOTE}\s*[)）]?\s*{w}|{w}\s*[(（]\s*{_REMOTE}|{w}\S{{0,2}}\s*{_REMOTE}\s*(?:으로|로)"
                          rf"|{_REMOTE}\s*{_PAIR}\s*\S{{1,4}}\s*{w}", text))


def remote_swaps(view: dict[str, Any], sentences: list[tuple[str, dict[str, Any]]]) -> list[tuple[str, str, str]]:
    """원문이 대면으로 정한 활동을 본문이 온라인 · 원격으로 바꾼 문장 → [(소항목, 문장, 원문 줄)]. 원문에 대면 활동이 없는 공고 · 옛 초안(칸 없음)은 빈 목록.
    원문을 인용한 문장(인용에 온라인 낱말) · 부정문은 아니다."""
    onsite = [(str(a.get("word")), str(a.get("quote") or "")) for a in (view.get("form") or {}).get("onsite") or [] if a.get("word")]
    out: list[tuple[str, str, str]] = []
    for section, sentence in sentences:
        text = str(sentence.get("text") or "")
        if (not (_REMOTE_RE.search(text) and _SWAP_RE.search(text)) or _AGREE_RE.search(text) or _NO_SWAP_RE.search(text)
                or _REMOTE_RE.search(str(sentence.get("source") or ""))):
            continue
        quote = next((q for word, q in onsite if _swapped(text, word)), None)
        if quote is not None:
            out.append((section, text, quote))
    return out


# --- 사업 기본정보(2.8.0 B6) -------------------------------------------------------------------------------------

#: 본문의 사업 금액 — 「총사업비 3억 5천만원」 · 「사업금액은 350,000,000원」(낱말 바로 뒤 금액만 — 「사업비의 10%인 …」은 아님).
#: 사업 전체를 뜻하는 머리만 — 「총사업비」 · 「사업금액」 · 「사업예산」 · 「총 용역금액」 · 문장 머리 · 「본」 뒤 맨 「사업비」.
#: 「교육운영 사업비 1억」 · 「전문가 풀 운영 사업비」처럼 앞에 다른 명사가 붙은 일부 금액은 대조하지 않는다(오탐이면 승인이 막힌다).
_TERM_MONEY_RE = re.compile(r"(?:(?:총|전체)\s*(?:사업\s*비|예산|용역\s*(?:비|금액))|사업\s*(?:금액|예산)|용역\s*금액|(?:^[-•·\s]*|본\s*)사업\s*비)"
                            r"\s*(?:은|는|이|가|:|：|으로|로|총액|규모)?\s*(?:총\s*)?(?:약\s*)?(\d[\d,.]*\s*(?:억|만|천|백)?[\d,.\s억만천백]*원)")
#: 일부 금액을 말하는 문장(「세부 사업비」 · 「회당」 · 「과정별」 · 비율)은 금액 대조를 하지 않는다(근사 — 오탐이면 승인이 막힌다).
_PART_MONEY_RE = re.compile(r"세부|회당|인당|건당|과정별|항목별|연간|비율|%")
#: 본문의 사업 기간 머리 — 그 뒤 45자 안에서 시작하는 끝날(「~ 날짜」 · 「날짜까지」)을 원문 끝날과 견준다. 「사업기간 내 · 중 · 동안 ·
#: 종료 · 만료 · 개시 …」는 기간 안 · 뒤 일정이라 뺀다. 「계약 체결 후 … 까지」 · 「수행기간」 · 「계약 체결일로부터 … 착수 보고」도
#: 중간 일정이라 머리로 보지 않는다(「계약 체결일 ~ 날짜」만). 오탐이면 승인이 막혀(승인 무효 코드) 애매하면 놓치는 쪽을 택한다.
_TERM_HEAD_RE = re.compile(r"(?:사업|용역|계약|과업)\s*기간(?!\s*(?:내|중|동안|안|이내|종료|만료|완료|이후|경과|개시|시작))"
                           r"|계약\s*체결일\s*(?=[~～∼])")
#: n차년도 · 단계 · 차수(「1차 계약기간」 · 「1차:」 · 「(1차분)」) · 과정별 · 분기 기간 문장은 사업 전체 기간이 아니다.
_TERM_PHASE_RE = re.compile(r"\d\s*차\s*(?:년도|연도)|\d\s*차(?:분|\s*[:：]|\s*(?:사업|계약|용역|예산|기간|과업))|차분|전체분|\d\s*단계"
                            r"|과정별|차수별|회차별|분기|상반기|하반기")
#: 머리와 날짜 사이에 끼면 사업 끝날이 아니라 중간 일정이다(「사업기간 종료 전인 …까지」 · 「과업기간을 고려해 …까지」).
_TERM_GAP_BAD_RE = re.compile(r"종료|만료|완료|이후|경과|개시|시작|고려|(?<![가-힣])(?:후|전)(?:인|에|에는|까지)?(?![가-힣])")
_TERM_GAP = 45
_TERM_DATE = r"(20\d{2})\s*[.년-]\s*(\d{1,2})\s*(?:[.월-]\s*(?:(\d{1,2})\s*[.일]?)?)?"
_TERM_END_RE = re.compile(rf"[~～∼]\s*{_TERM_DATE}|{_TERM_DATE}\s*\.?\s*까지")
#: 끝 연도를 생략한 범위 — 「2027년 1월 1일 ~ 12월 10일」 · 「2027년 1월 1일부터 12월 10일까지」(끝 연도는 앞 날짜에서 · 2.8.0 검토).
#: 끝 월 · 일이 시작보다 앞(해 넘김) · 날짜가 아닌 꼴(「~ 27. 2. 26.」 두 자리 연도 · 「11.3개월」)은 받지 않는다(`_noyear_end` — 애매하면 놓친다).
_TERM_NOYEAR_RE = re.compile(r"(20\d{2})\s*[.년-]\s*(\d{1,2})\s*[.월-]\s*(\d{1,2})\s*[.일]?\s*(?:[~～∼]|부터)\s*(\d{1,2})\s*[.월-]\s*(\d{1,2})"
                             r"(?!\d|\s*[.]?\s*\d|\s*개월)")


def _noyear_end(match: re.Match[str]) -> tuple[int, int, int] | None:
    """연도 생략 범위의 끝(연, 월, 일) — 끝 월 1~12 · 일 1~31 · 끝이 시작보다 뒤일 때만."""
    year, start_m, start_d, end_m, end_d = (int(g) for g in match.groups())
    if not (1 <= end_m <= 12 and 1 <= end_d <= 31) or (end_m, end_d) <= (start_m, start_d):
        return None
    return year, end_m, end_d


def _term_end(text: str) -> tuple[int, int, int | None] | None:
    """본문 문장 속 사업 끝날(연, 월, 일) — 기간 머리 뒤 45자 안에서 시작하는 날짜만 · 날짜는 자르지 않고 끝까지 읽는다
    (차년도 · 차수 · 단계 · 과정별 문장 · 머리와 날짜 사이에 종료 · 만료 · 개시 · 고려 …가 낀 문장은 아님)."""
    if _TERM_PHASE_RE.search(text):
        return None
    for head in _TERM_HEAD_RE.finditer(text):
        noyear = _TERM_NOYEAR_RE.search(text, head.end())
        found = [m for m in (_TERM_END_RE.search(text, head.end()), noyear if noyear and _noyear_end(noyear) else None)
                 if m and m.start() - head.end() <= _TERM_GAP]
        if not found:
            continue
        match = min(found, key=lambda m: m.start())
        if _TERM_GAP_BAD_RE.search(text[head.end():match.start()]):
            continue
        if match.re is _TERM_NOYEAR_RE:
            return _noyear_end(match)
        y, m, d = (match.group(1), match.group(2), match.group(3)) if match.group(1) else (match.group(4), match.group(5), match.group(6))
        return int(y), int(m), int(d) if d else None
    return None


#: 기간 머리 뒤 시작 날짜(「2027년 1월 1일부터 · ~」) — 원문 시작이 날짜가 아닐 때(「계약 체결일 ~ …」) 본문이 시작일을 지으면 다름(3차 지시서 §5 사례 3).
_TERM_START_RE = re.compile(rf"{_TERM_DATE}\s*\.?\s*(?:[~～∼]|부터)")
_TERM_DATE_RE = re.compile(_TERM_DATE)


def _term_start(text: str) -> str | None:
    """본문 문장이 기간 머리 뒤 45자 안에 적은 시작 날짜(「2027. 1. 1.」) — 차수 · 단계 문장 · 사이에 종료 · 개시 …가 낀 문장은 아님."""
    if _TERM_PHASE_RE.search(text):
        return None
    for head in _TERM_HEAD_RE.finditer(text):
        first = _TERM_DATE_RE.search(text, head.end())
        start = _TERM_START_RE.match(text, first.start()) if first else None
        if start and start.start() - head.end() <= _TERM_GAP and not _TERM_GAP_BAD_RE.search(text[head.end():start.start()]):
            return f"{start.group(1)}. {start.group(2)}." + (f" {start.group(3)}." if start.group(3) else "")
    return None


def _terms_mismatch(text: str, terms: dict[str, Any]) -> str | None:
    """본문 한 문장이 원문 사업금액 · 끝날과 다르면 그 까닭(금액 기준은 원문 사업금액 — 나라장터 배정예산은 다를 수 있어 쓰지 않는다).
    원문 시작이 날짜가 아닌데(「계약 체결일 ~」) 본문이 시작 날짜를 적어도 다름(게이트 판 3)."""
    if terms.get("start_label") and (start := _term_start(text)):
        return f"시작 {start} · 원문 {terms.get('period')}"
    won = terms.get("budget_won")
    if won and not _PART_MONEY_RE.search(text):
        for match in _TERM_MONEY_RE.finditer(text):
            value = plan_validation.won(match.group(1))
            if value and value != won:
                return f"금액 {match.group(1).strip()} · 원문 {terms.get('budget')}"
    end = str(terms.get("end") or "")
    if re.match(r"^\d{4}-\d{2}", end) and (found := _term_end(text)):
        y, m, d = found
        parts = [int(x) for x in end.split("-")]
        if (y, m) != tuple(parts[:2]) or (d is not None and len(parts) == 3 and d != parts[2]):
            return f"끝날 {y}. {m}." + (f" {d}." if d else "") + f" · 원문 {terms.get('period')}"
    return None


# --- 계약상 부담이 되는 약속(2.8.0 B8) -----------------------------------------------------------------------------

_FREE_RE = re.compile(r"무상|무료|(?:별도|추가)\s*(?:의\s*)?비용\s*(?:없이|부담\s*없이|청구\s*없이)|(?:당사|회사|자체)\s*(?:의\s*)?(?:비용\s*)?부담(?:으로)?|자부담")
#: 원문이 그 약속을 요구했나 — 인용 원문(source)이 본문과 **같은 대상**을 말할 때만(2.8.0 검토 · 낱말 묶음만 보면 「추가 비용은 협의」 ·
#: 참여율 정의의 「인건비 … 지급」 · 산업안전 조항의 「상주하는 참여인력」 같은 반대 뜻 · 다른 대상 원문으로도 면제됐다).
#: 원문은 명사형(「취업 성공 수당(15만원) 개별 지급」 · 「추가개설 시 별도 비용 지원 없음」)이라 동사 꼬리는 보지 않는다.
_EXTRA_OPEN_RE = re.compile(r"추가\s*(?:개설|과정|교육|회차|강좌|강의|특강)|증설")
_NO_COST_RE = re.compile(r"(?:별도\s*)?비용\s*(?:지원\s*)?(?:없|미지원|불가)|(?:당사|수행\s*(?:사|업체|기관)|용역\s*사|계약\s*상대자|자체)\s*부담|무상|무료")
_PAY_NOUN_RE = re.compile(r"수당|인건비|참가비|활동비|교통비|장학금")
_PERIOD_WORD_RE = re.compile(r"(?:사업|계약|용역|과업)\s*기간|전\s*기간|기간\s*(?:동안|내내|전체)")


def _quoted_extra_open(_text: str, source: str) -> bool:
    return bool(_EXTRA_OPEN_RE.search(source) and _NO_COST_RE.search(source))


def _quoted_pay(text: str, source: str) -> bool:
    return bool(set(_PAY_NOUN_RE.findall(text)) & set(_PAY_NOUN_RE.findall(source)) and re.search(r"지급|지원", source))


_PAY_PHRASE_RE = re.compile(r"[가-힣]+\s*(?:수당|인건비|참가비|활동비|교통비|장학금)")


def _quoted_same_pay(text: str, quote: str) -> bool:
    """초안 다른 문장의 인용 면제(D10) — 본문의 「○○수당」 꼴(공백 뺀)이 인용에 그대로 있고 · 인용이 지급을 말하고 · 부정 · 비율 정의가 아닐 때만."""
    compact = re.sub(r"\s+", "", quote)
    return ("지급" in quote and not re.search(r"않|불가|없|비율", quote)
            and any(re.sub(r"\s+", "", phrase) in compact for phrase in _PAY_PHRASE_RE.findall(text)))


def _quoted_dedicated(_text: str, source: str) -> bool:
    return bool(re.search(r"전담", source) and _PERIOD_WORD_RE.search(source))


def _quoted_words(*patterns: str) -> Callable[[str, str], bool]:
    compiled = [re.compile(p) for p in patterns]
    return lambda _text, source: all(p.search(source) for p in compiled)


#: (본문 꼴, 원문이 요구했나) — 본문 꼴이 모두 맞으면 약속. 그 문장의 인용 원문이 같은 요구를 담으면 원문이 요구한 과업이라 뺀다.
_COMMIT_RES: tuple[tuple[tuple[re.Pattern[str], ...], Callable[[str, str], bool] | None], ...] = (
    # 추가 교육 · 과정을 무상 · 당사 부담으로 개설 · 제공
    ((_FREE_RE, re.compile(r"추가|증설|확대"), re.compile(r"교육|과정|강의|강좌|회차|특강|프로그램|개설")), _quoted_extra_open),
    # 전원 수료 · 수료율 100% 보장
    ((re.compile(r"전원\s*(?:이\s*)?수료|수료율\s*100\s*%|수료(?:율)?(?:을|를)?\s*보장"),),
     _quoted_words(r"전원\s*(?:이\s*)?수료|수료율\s*100")),
    # 사업기간 전체 전담 인력
    ((re.compile(r"(?:사업|계약|용역)\s*기간\s*(?:전체|내내)|전\s*기간"), re.compile(r"전담|상주")), _quoted_dedicated),
    # 외부 시스템 연동 확약 · 보장
    ((re.compile(r"연동[^.。]{0,20}?(?:확약|보장|책임지|약속)|(?:확약|보장)[^.。]{0,10}?연동"),), _quoted_words(r"연동")),
    # 수당 · 인건비 지급 · 지원 — 같은 명사(교통비면 교통비)를 원문이 지급 · 지원하라고 할 때만 면제
    ((re.compile(r"(?:수당|인건비|참가비|활동비|교통비|장학금)[^.。]{0,15}?(?:지급|지원)(?:하겠|합니다|하며|하고|함)"),), _quoted_pay),
    # 무조건 · 어떠한 경우에도 달성 — 원문이 요구할 수 없는 말이라 빼지 않는다
    ((re.compile(r"무조건|어떠한\s*경우에도|어떤\s*경우에도"),), None),
)


def commitment(sentence: dict[str, Any], quotes: Iterable[str] = ()) -> bool:
    """계약상 부담이 되는 약속 문장인가 — 그 문장의 인용 원문(source)이 같은 대상의 같은 요구를 담고 있으면 아니다(type 과 상관없이 ·
    AI 는 원문 요구를 옮긴 문장도 AI_SUGGESTION 으로 적는다). 수당 · 인건비 지급만은 같은 초안 다른 문장의 원문 인용(quotes)이 같은 명사의
    지급을 담으면 면제한다(2.9.0 · 11-11 2위 「취업성공수당을 지급합니다」 — 같은 초안이 원문 「취업 성공 수당(15만원) 개별 지급」을 인용)."""
    text = str(sentence.get("text") or "")
    source = str(sentence.get("source") or "")
    for body, quoted in _COMMIT_RES:
        if all(pattern.search(text) for pattern in body):
            if quoted and source and quoted(text, source):
                continue
            if quoted is _quoted_pay and any(_quoted_same_pay(text, other) for other in quotes):
                continue
            return True
    return False


# --- 근거 상태(2.8.0 B7) ---------------------------------------------------------------------------------------


def _cert_state(name: str, credentials: list[Any], today: str) -> tuple[str, list[str]]:
    """인증 · 자격 이름 → (EXPIRED · MISSING · SELF_REPORTED, 까닭) — 입찰 자격 자료(credentials)의 유효기간으로. 짝 줄이 없거나 유효기간이 비면 「모름」."""
    key = _compact(name)
    match = next((c for c in credentials if isinstance(c, dict) and key and (other := _compact(c.get("name")))
                  and (key in other or other in key)), None)
    until = str((match or {}).get("valid_until") or "")[:10]
    if not until:
        return "MISSING", ["유효기간 모름"]
    if until < today:
        return "EXPIRED", [f"유효기간 {until} 지남"]
    return "SELF_REPORTED", []


#: 실적 문장의 수치 — 인원 · 만족도 점수 · 비율 · 개사 · 회(2.10.0 T3 · 「30명 대상 … 만족도는 4.9점」 · 연도 「2025년」은 아님).
_LEDGER_NUMBER_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(명|점|%|개사|회)")


def evidence_status(view: dict[str, Any], *, capacity: dict[str, Any], ledger_rows: list[dict[str, Any]],
                    today: str | None = None) -> dict[str, Any]:
    """초안 본문이 인용한 회사 근거의 상태(`quality.evidence_status` · 2.8.0 B7 · 지금 있는 칸으로만 · 새 회사 값 없음) —
    실적(`ledger:n`) 은 `performance_ledger.evidence_state` · 인증(`profile:cert:` · `cap:cred:`)은 입찰 자격 자료(credentials)의
    유효기간(프로필 인증은 이름뿐이다) · 참여인력은 늘 MISSING(명부 칸 없음 · 대표 결정 11-08). VERIFIED 는 사람이 확인일 · 확인자를
    적는 칸이 생길 때만(지금 없음). `unverified` 는 문장마다 증빙 확인 전 실적 · 유효기간 지난 인증(EVIDENCE_UNVERIFIED) ·
    `numbers` 는 그 밖 원장 행(증빙 메모 「미확인」이 아닌 행)의 수치(인원 · 만족도 · 비율 · 개사 · 회)를 확정 실적으로 옮긴 문장(EVIDENCE_NUMBER · 2.10.0)."""
    today = today or storage.kst_today().isoformat()
    rows = {str(row.get("seq")): row for row in ledger_rows}
    credentials = list(capacity.get("credentials") or [])
    ledger = {"cited": 0, "SELF_REPORTED": 0, "UNVERIFIED": 0, "MISSING": 0}
    certs = {"cited": 0, "SELF_REPORTED": 0, "EXPIRED": 0, "MISSING": 0}
    notes: list[str] = []
    unverified: list[dict[str, Any]] = []
    numbers: list[dict[str, Any]] = []
    seen: set[str] = set()
    for section, sentence in _body_sentences(view):
        text = str(sentence.get("text") or "")
        hits: list[str] = []
        for source in map(str, sentence.get("source_ids") or []):
            if source.startswith("ledger:"):
                seq = source.split(":", 1)[1]
                row = rows.get(seq)
                state, why = performance_ledger.evidence_state(row) if row else ("MISSING", ["원장에 없음"])
                counter, label = ledger, f"실적 연번 {seq}"
                if row and state != "UNVERIFIED":  # 원장에 적힌 수치를 그대로 옮긴 것만(증빙 확인 전 — VERIFIED 칸이 없다 · 2.8.0)
                    have = f"{row.get('title') or ''} {row.get('summary') or ''}"
                    hits += [m.group(0) for m in _LEDGER_NUMBER_RE.finditer(text)
                             if re.search(rf"(?<![\d.]){re.escape(m.group(1))}\s*{re.escape(m.group(2))}", have)]
            elif source.startswith(("profile:cert:", "cap:cred:")):
                name = source.split(":", 2)[2]
                state, why = _cert_state(name, credentials, today)
                counter, label = certs, f"인증 「{name}」"
            else:
                continue
            if state in ("UNVERIFIED", "EXPIRED"):
                unverified.append({"section": section, "source": source, "label": label, "reason": " · ".join(why)})
            if source in seen:
                continue
            seen.add(source)
            counter["cited"] += 1
            counter[state] += 1
            if why:
                notes.append(f"{label} — {' · '.join(why)}")
        if hits:
            numbers.append({"section": section, "numbers": list(dict.fromkeys(hits)), "text": text})
    return {"ledger": ledger, "certifications": certs, "personnel": "MISSING", "notes": notes, "unverified": unverified, "numbers": numbers}


# ---------------------------------------------------------------------------
# 평가본 식별 낱말(2.10.0 D7 — 원문이 평가본을 요구할 때만 · 제출 전 PDF 검사도 같은 함수)
# ---------------------------------------------------------------------------

#: 남으면 차단(회사를 바로 가리킴 · D7) — 그 밖(주소 · 홈페이지 · 설립일 · 실적 기관 이름 · 실적 사업명)은 중요.
IDENTITY_BLOCKING = ("회사 이름", "대표자", "전화", "사업자번호", "인증번호")
#: 종류 ← 회사 값 열쇠(`plan_fill_service.company_values`).
_IDENTITY_FIELDS = (("회사 이름", "name"), ("대표자", "representative"), ("전화", "phone"), ("사업자번호", "business_number"),
                    ("주소", "address"), ("홈페이지", "website"), ("설립일", "opened_on"))
_CORP_RE = re.compile(r"^(?:주식회사|\(주\)|㈜)\s*|\s*(?:주식회사|\(주\)|㈜)$")
#: 실적 사업명으로 볼 견주기 꼴 길이 — 짧은 「AI 교육」류는 회사를 가리키지 않는다(2.11.0 D4).
PROJECT_TITLE_MIN = 10


def _ident_key(text: Any) -> str:
    """식별 낱말 견주기 꼴 — 띄어쓰기 · 「·」 · 붙임표 · 점 · 괄호 · 빗금 · 쌍점을 지우고 소문자(「가나다 21」 · 「062) 111-2222」 · 「제 1234-56 호」)."""
    return re.sub(r"[\s·ㆍ\-–.()（）/:]+", "", str(text or "")).lower()


def identity_words(values: dict[str, Any], ledger_rows: Iterable[dict[str, Any]] = (), *, exclude: str = "") -> list[tuple[str, str]]:
    """평가본에 남으면 안 되는 회사 식별 낱말 (종류, 낱말) — 회사 값(`plan_fill_service.company_values` 꼴 — 이름 짧은 꼴 · 대표자 · 전화 ·
    사업자번호 · 주소 · 홈페이지 · 설립일 · 인증 이력 속 「제…호」)과 실적 원장 기관 이름(`bid.agency_names`) · 수행 실적 사업명(원장 제목 —
    그대로와 AI 에 보낸 가림 꼴(`bid.blind_text`) · 견주기 꼴 10자 이상만 · 인증 · 지정 행 제외 · 2.11.0 D4). 이번 공고 글(`exclude` ·
    `notice_text`)에 있는 낱말과 견주기 꼴 2자 미만은 뺀다. 값은 보고서 · 기록에 싣지 않는다(검사 줄은 종류 · 수 · 자리만)."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    skip = _ident_key(exclude)

    def add(kind: str, word: str) -> None:
        key = _ident_key(word)
        if len(key) >= 2 and key not in seen and key not in skip:
            seen.add(key)
            out.append((kind, word.strip()))

    for kind, field in _IDENTITY_FIELDS:
        value = str(values.get(field) or "").strip()
        if field == "name":
            value = _CORP_RE.sub("", value)
        elif field == "website":
            value = re.sub(r"^https?://(?:www\.)?", "", value, flags=re.I).rstrip("/")
        add(kind, value)
    for match in plan_export_service.CERT_NO_RE.finditer(str(values.get("history") or "")):
        add("인증번호", match.group(0))
    rows = list(ledger_rows)
    agencies = [bid.agency_names(row.get("agency")) for row in rows]
    for names in agencies:
        for name in names:
            add("실적 기관", name)
    every = {name for names in agencies for name in names}
    for row in rows:
        title = str(row.get("title") or "")
        if row.get("field") in bid.PROJECT_FIELDS:
            for word in (title, bid.blind_text(title, every)):
                if len(_ident_key(word)) >= PROJECT_TITLE_MIN:
                    add("실적 사업명", word)
    return out


def identity_leaks(text: str, words: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    """글(평가본 블록 글 · 올린 PDF 글)에 남은 식별 낱말 (종류, 낱말) — 띄어쓰기 · 「·」 · 붙임표 · 점 · 괄호 · 대소문자는 무시한다."""
    key = _ident_key(text)
    return [(kind, word) for kind, word in words if _ident_key(word) in key]


def notice_text(view: dict[str, Any]) -> str:
    """이번 공고 글 — 식별 낱말에서 뺄 것(사업명 · 발주기관 · 원문 목차 · 작성 방법 · 평가 기준(양식) · 원문 기준 수치 줄 · 본문이 인용한
    제안요청서 문장). 받아 둔 원문 전부를 화면마다 다시 읽지는 않는다(근사 — 원문에만 있는 기관 이름은 경고로 남을 수 있다)."""
    quotes = [str(x.get("source") or "") for _s, x in _body_sentences(view) if x.get("type") == plan_draft_service.NOTICE]
    return " ".join([str(view.get("title") or ""), str(view.get("agency") or ""), json.dumps(view.get("form") or {}, ensure_ascii=False),
                     json.dumps([view.get("facts"), view.get("derived")], ensure_ascii=False, default=str), *quotes])


def blind_texts(view: dict[str, Any], meta: dict[str, Any]) -> list[tuple[str, str]]:
    """평가본 문서 글(내려받는 평가본과 같은 블록 · 세 형식 같음) — (자리, 글). 자리는 「표지」 또는 바로 위 대항목 · 소항목 머리."""
    out: list[tuple[str, str]] = []
    where = "표지"
    for block in plan_export_service.document_blocks(view, view.get("form") or {}, variant="blind", meta=meta):
        if block[0] == "cover":
            out.append(("표지", " ".join(str(value or "") for _label, value in plan_export_service.cover_rows(block[1]))))
        elif block[0] in ("h1", "h2"):
            where = str(block[1])
        else:
            out.append((where, plan_export_service._block_text(block)))
    return out


def identity_findings(pairs: Iterable[tuple[str, str]], words: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """글 (자리, 글) 목록에 남은 식별 낱말 → 검사 줄(BLIND_IDENT_LEFT) — 차단 종류 한 줄 · 중요 종류 한 줄. 풀이는 종류 · 낱말 수 · 자리만
    (값은 싣지 않음 · D7). 게이트는 `blind_texts`, 제출 전 PDF 검사는 (「n쪽」, 쪽 글)을 넘긴다."""
    left: dict[str, dict[str, list[str]]] = {}  # 종류 → 낱말 견주기 꼴 → 자리
    for where, text in pairs:
        for kind, word in identity_leaks(text, words):
            places = left.setdefault(kind, {}).setdefault(_ident_key(word), [])
            if where not in places:
                places.append(where)
    order = [kind for kind in dict.fromkeys(kind for kind, _word in words) if kind in left]
    out = []
    for severity, title, kinds in (
            ("BLOCKER", "평가본에 회사를 알아볼 수 있는 값이 남음 — 회사 이름 · 대표자 · 연락처 · 번호", [k for k in order if k in IDENTITY_BLOCKING]),
            ("MAJOR", "평가본에 회사를 짐작할 수 있는 값이 남음 — 실적 기관 · 실적 사업명 · 주소 · 홈페이지 · 설립일", [k for k in order if k not in IDENTITY_BLOCKING])):
        if not kinds:
            continue
        places = list(dict.fromkeys(place for kind in kinds for spots in left[kind].values() for place in spots))
        shown = " · ".join(_snip(place) for place in places[:3]) + (" 외" if len(places) > 3 else "")
        out.append(_finding("BLIND_IDENT_LEFT", severity, title,
                            " · ".join(f"{kind} {len(left[kind])}" for kind in kinds) + f" — 자리: {shown} (값은 기록에 남기지 않습니다)",
                            section=places[0], count=sum(len(left[kind]) for kind in kinds), location=f"평가본 › {places[0]}"))
    return out


def _ppt_required(fmt: dict[str, Any]) -> bool:
    """PPT 로 쓰라는 규정인가 — 저장된 옛 초안의 형식 메모도 「희망 시 · 가능」(선택)이면 요구로 보지 않는다(계획 10)."""
    if not fmt.get("ppt"):
        return False
    lines = [note for note in fmt.get("notes") or [] if bid._PPT_RE.search(str(note))]
    return not lines or not all(bid.ppt_optional(str(note)) for note in lines)


def _names(names: list[str]) -> str:
    return "「" + "」 · 「".join(_snip(name) for name in names[:3]) + "」" + (" 외" if len(names) > 3 else "")


def _source_gap_findings(gap: dict[str, list[str]]) -> list[dict[str, Any]]:
    """사전규격 규격서만 읽고 쓴 초안(2.11.0 T9) — 초안을 쓴 뒤 본공고 첨부를 받았으면 다시 쓰면 되는 것(auto), 아직 안 받았거나 받아 둔
    파일의 글을 읽지 못했으면 사람이 볼 것(fact). 안 받은 · 못 읽은 첨부 이름도 함께 적는다."""
    missing, received, unread = gap.get("missing") or [], gap.get("received") or [], gap.get("unread") or []
    rest = " · ".join(part for part in (f"아직 안 받음 {_names(missing)}" if missing else "",
                                        f"받았지만 글을 읽지 못함 {_names(unread)}" if unread else "") if part)
    if received:
        return [_finding("SOURCE_PRESPEC_ONLY", "MAJOR", "사전규격 규격서만으로 쓴 초안 — 그 뒤 본공고 첨부를 받아 둠",
                         f"{_names(received)} — 초안을 다시 쓰면 함께 읽습니다" + (f" ({rest})" if rest else ""),
                         count=len(received) + len(missing) + len(unread), axis="auto",
                         action="초안을 다시 쓰세요 — 받아 둔 본공고 첨부를 함께 읽습니다")]
    if missing or unread:
        title = "본공고 첨부를 받지 않아 사전규격 규격서만으로 씀" if missing else "본공고 첨부의 글을 읽지 못해 사전규격 규격서만으로 씀"
        action = None if missing else "받아 둔 본공고 첨부가 그림 PDF · 깨진 파일인지 열어 보고, 입찰공고문 조건은 원문에서 직접 확인하세요"
        return [_finding("SOURCE_PRESPEC_ONLY", "MAJOR", title, f"{rest} — 입찰공고문 제출서류 · 계약 예정일 · 공고문 조건을 읽지 못했습니다",
                         count=len(missing) + len(unread), action=action)]
    return []


def eligibility_findings(report: Any) -> list[dict[str, Any]]:
    """입찰 분석 참가 자격 판정 한 줄(2.11.0 T10 · D3) — 「불가」는 중요(회사 사실 · 문서 결함이 아니라 승인을 막지 않음), 「확인 필요」 · 판정 못 함은
    참고. 가능 · 판정 없음이면 줄이 없다."""
    where = "입찰 분석 › 참가 자격"
    if report is None:
        return []
    if report == ELIGIBILITY_ERROR:
        return [_finding("ELIGIBILITY", "INFO", "참가 자격 판정을 하지 못함", "입찰 분석에서 참가 자격을 직접 확인하세요", location=where)]
    fails = [r for r in report.results if r.status == "FAIL"]
    if fails:
        shown = " · ".join(f"{r.label}: {_snip(r.clause_text or r.reason)}" for r in fails[:3]) + (" 외" if len(fails) > 3 else "")
        return [_finding("ELIGIBILITY", "MAJOR", "입찰 분석 참가 자격 판정이 「불가」 — 제안서 결함이 아니라 회사 사실", shown, count=len(fails),
                         location=where)]
    checks = [r for r in report.results if r.status == "CHECK"]
    if not checks:
        return []
    company = [r for r in checks if r.check_side == "company"]
    tail = (" — " + " · ".join(_snip(r.label) for r in company[:2]) + (" 외" if len(company) > 2 else "")) if company else ""
    return [_finding("ELIGIBILITY", "INFO", "입찰 분석 참가 자격에 확인 필요가 남음", f"확인 필요 {len(checks)}줄(회사 쪽 {len(company)}){tail}",
                     count=len(checks), location=where)]


def _review_flags(sentences: list[tuple[str, dict[str, Any]]]) -> list[tuple[str, int, str]]:
    """검토용 경고가 남은 본문 문장 — 경고 종류별 (종류, 문장 수, 첫 예문). 과장 표현(`HYPE_LEFT`)으로 이미 센 문장의 금칙어 경고는 뺀다."""
    out: dict[str, list[Any]] = {}
    for _section, sentence in sentences:
        hyped = bool(bid.hype_words(sentence))
        for flag in dict.fromkeys(str(f) for f in sentence.get("flags") or []):
            if hyped and flag.startswith(plan_draft_service.FLAG_BANNED):
                continue
            if flag.startswith((bid.FLAG_SUM, bid.FLAG_FACT)):  # NUMBER_SUM · NOTICE_VALUE 가 따로 센다(2.9.0)
                continue
            label = re.split(r"\s*(?::|\(|—)", flag, maxsplit=1)[0].strip() or flag
            entry = out.setdefault(label, [0, str(sentence.get("text") or "")])
            entry[0] += 1
    return [(label, count, sample) for label, (count, sample) in out.items()]


def findings_of(view: dict[str, Any], *, meta: dict[str, Any], notice: dict[str, Any] | None = None,
                scan: dict[str, Any] | None = None, evidence: dict[str, Any] | None = None,
                coverage: list[dict[str, Any]] | None = None,
                identity: list[tuple[str, str]] | None = None, eligibility: Any = None) -> tuple[list[dict[str, Any]], bool]:
    """검사 목록(심각도 순) · 인력 미확정 여부. view 는 `read_view` 가 만든 화면 초안(`stale` · `terms` 포함). scan 은 `_scan_submit` 결과 ·
    coverage 는 `evaluation_coverage`(없으면 센다) · evidence 는 `evidence_status`(회사 자료를 읽는 `read_view` 가 넘긴다 · 없으면 그 검사를 건너뜀) ·
    identity 는 `identity_words`(원문이 평가본을 요구할 때 `read_view` 가 넘긴다 · 없으면 식별 낱말 검사를 건너뜀) ·
    eligibility 는 입찰 분석 판정(`EligibilityReport` · 예외면 `ELIGIBILITY_ERROR` · 없으면 건너뜀)."""
    found: list[dict[str, Any]] = []
    form = view.get("form") or {}
    fmt = view.get("format") or {}
    coverage = evaluation_coverage(view) if coverage is None else coverage

    # --- 차단: 제출용에 남는 미작성 칸 · 사람 몫 표(인력 미확정) · 조견표 빈칸 -----------------------------------
    scan = scan or _scan_submit(view, meta)
    for section, entry in scan["spots"].items():
        found.append(_finding("PLACEHOLDER", "BLOCKER", "제출용에 미작성 칸 「(담당자 입력)」 등이 남음",
                              f"「{_snip(entry['sample'])}」 — 회사자료에 값을 적거나 받은 파일에서 채우세요",
                              section=section, count=entry["count"], location=entry["location"], axis=entry.get("axis") or "auto"))
    for table in scan["staff"]:
        # 표마다 앱 안에서 할 수 있는 일이 다르다 — 참여인력 표는 앱이 채우지 않는다(대표 결정 11-08 「인력 미확정 표시만」 · 2.7.0 검토)
        how = (STAFF_ORG_HOW if table.get("key") == bid.ORG_TABLE["key"] else STAFF_PEOPLE_HOW)
        found.append(_finding("STAFFING_UNCONFIRMED", "BLOCKER", f"인력 미확정 — 「{table['title']}」 표에 빈칸이 남음",
                              f"공고가 요구한 「{table['title']}」 칸 {table['count']}곳이 비어 있습니다 — {how}",
                              section=table["section"], count=table["count"], location=f"{table['section']} › 표 「{table['title']}」"))
    staffing_unconfirmed = bool(scan["staff"])
    if scan["eval"]:
        # 조견표도 제출용 글이다 — 빈 「제안서 해당 목차」가 그대로 찍힌다(2.8.0 B3 · 정량 항목은 「—」라 여기 오지 않는다).
        # 세 상태로 나눠 알린다(3차 지시서 §3 · 게이트 판 3) — 본문에 내용 있음(자동 연결 실패) · 본문에 내용 없음 · 인력 · 증빙 항목
        gaps = {c["name"]: (c.get("gap") or "no_body", c.get("candidate")) for c in coverage}
        for gap, (title, tail, action, axis) in EVAL_GAPS.items():
            group = [(name, cells, row) for name, cells, row in scan["eval"] if gaps.get(name, ("no_body", None))[0] == gap]
            if not group:
                continue
            names = [f"{name}」 → 본문 {gaps[name][1]}" if gap == "auto_link" and gaps.get(name, (None, None))[1] else f"{name}」"
                     for name, _cells, _row in group]
            numbers = [str(row) for _name, _cells, row in group]
            rows = " · ".join(numbers[:5]) + (f" 외 {len(numbers) - 5}" if len(numbers) > 5 else "")
            found.append(_finding("EVAL_MAP_BLANK", "BLOCKER", title,
                                  "「" + " · 「".join(names[:5]) + (" 외" if len(names) > 5 else "") + f" — {tail}",
                                  section=bid.EVAL_TITLE, count=sum(cells for _name, cells, _row in group),
                                  location=f"{bid.EVAL_TITLE} {rows}행 「제안서 해당 목차」", action=action, axis=axis))

    # --- 중요 --------------------------------------------------------------------------------------------
    for title in view.get("llm_failures") or []:
        found.append(_finding("LLM_FAILED", "MAJOR", "AI 가 쓰지 못한 소항목", "그 소항목은 작성 방법만 담은 빈칸입니다 — 초안을 다시 쓰거나 직접 채우세요",
                              section=str(title)))
    if view.get("outline_source") and view.get("outline_source") != "rfp":
        where = view.get("outline_found_at") or {}
        at = f" — 목차 머리는 「{where.get('document')}」 {where.get('page')}쪽에 있었습니다" if where.get("document") else ""
        # 목차 머리를 찾고도 못 읽음(unread)은 앱 몫 · 원문에 목차 규정이 없음(standard)은 사람이 원문을 볼 것
        found.append(_finding("OUTLINE_STANDARD", "MAJOR", "제안요청서 목차를 읽지 못해 표준 목차로 씀",
                              f"평가위원은 제안요청서 목차대로 읽습니다{at} — 원문 목차와 맞춰 보세요",
                              axis="auto" if view.get("outline_source") == "unread" else "fact"))
    if (where := view.get("evaluation_where") or {}) and not (form.get("evaluation") or {}).get("items"):
        # 평가표 머리는 찾았는데 항목을 못 읽어 조견표가 빠짐(2.10.0 T7 · 11-13 동국대 옛 초안 — 게이트가 조용했다)
        found.append(_finding("EVAL_UNREAD", "MAJOR", "제안요청서 평가표를 찾았지만 항목을 읽지 못해 조견표가 없음",
                              f"원문 「{where.get('document')}」 {where.get('page')}쪽 평가표 — 평가위원이 항목마다 제안서 위치를 찾을 조견표가 빠졌습니다"))
    blanks = view.get("blanks") or []
    for field in MOVED_FIELDS:
        rows = [b for b in blanks if str(b.get("field")) == field]
        if rows:
            sections = {str(b.get("section") or "") for b in rows}
            why = str(rows[0].get("why") or "")
            # 「근거를 붙이거나 지우세요 — 문장」 꼴은 문장만(안내 머리말은 이 항목 제목이 대신한다)
            sample = why.rsplit(" — ", 1)[-1] if field in _PREFIXED_FIELDS and " — " in why else why
            found.append(_finding("MOVED_SENTENCES", "MAJOR", f"본문에서 뺀 문장 — {field}",
                                  f"「{_snip(sample)}」 — 「담당자가 채울 항목」에서 확인하고 필요하면 근거와 함께 넣으세요",
                                  section=sections.pop() if len(sections) == 1 else None, count=len(rows),
                                  # 근거 없는 회사 주장은 사실 확인 · 과장 표현은 앱이 고칠 것 · 회사가 정할 값은 담당자 입력
                                  axis={"회사 근거 없는 회사 주장": "fact", bid.HYPE_FIELD: "auto"}.get(field, "input")))
    sentences = _body_sentences(view)
    for section, count, sample in _grouped([(s, str(x.get("text") or "")) for s, x in sentences if bid.hype_words(x)]):
        found.append(_finding("HYPE_LEFT", "MAJOR", "과장 표현이 본문에 남음(「반드시 달성」 · 「완벽」 · 「보장」 · 「100% 달성」)",
                              f"「{_snip(sample)}」 — 빼거나 달성 방법을 담은 확정형 계획으로 고치세요", section=section, count=count))
    promised: set[int] = set()  # 자격 약속으로 이미 센 문장 — 지난 경력 단정으로 두 번 세지 않는다
    if staffing_unconfirmed:
        pledges = [(s, x) for s, x in sentences
                   if (t := str(x.get("text") or "")) and _STAFF_WHO_RE.search(t) and _STAFF_QUAL_RE.search(t)
                   and _STAFF_VERB_RE.search(t) and not _STAFF_SKIP_RE.search(t)]
        promised = {id(x) for _s, x in pledges}
        promises = [(s, str(x.get("text") or "")) for s, x in pledges]
        schedule = next((t for t in view.get("tables") or [] if t.get("key") == bid.SCHEDULE_TABLE["key"] and t.get("by") == "llm"
                         and len(t.get("columns") or []) == 5), None)
        promises += [(f"{schedule.get('title')} 표 담당 칸", f"{row[0]} — {row[2]}") for row in (schedule or {}).get("rows") or []
                     if len(row) >= 5 and _OWNER_PERSON_RE.search(str(row[2]))]
        # 「핵심 마감과 책임」 책임 역할 칸도 같은 조건(2.10.0 · T2 검토)
        milestones = next((t for t in view.get("tables") or [] if t.get("key") == bid.MILESTONE_TABLE["key"] and t.get("by") == "llm"), None)
        promises += [(f"{bid.MILESTONE_TABLE['title']} 표 책임 역할 칸", f"{row[0]} — {row[1]}") for row in (milestones or {}).get("rows") or []
                     if len(row) >= 2 and _OWNER_PERSON_RE.search(str(row[1]))]
        for section, count, sample in _grouped(promises):
            found.append(_finding("STAFFING_PROMISE", "MAJOR", "인력 미확정인데 인력 자격을 약속하는 문장",
                                  f"「{_snip(sample)}」 — 실제 투입할 인력이 그 자격을 갖췄는지 확인하세요", section=section, count=count))
    # 확정 전 · 외부 위촉 인력의 지난 경력 단정(2.11.0 T7c) — 인력 표가 없는 공고도 위촉 · 외부 · 초빙 · 섭외 문장은 본다
    careers = [(s, str(x.get("text") or "")) for s, x in sentences if id(x) not in promised
               and (staffing_unconfirmed or _STAFF_EXTERNAL_RE.search(str(x.get("text") or ""))) and past_career(x)]
    for section, count, sample in _grouped(careers):
        found.append(_finding("STAFFING_PROMISE", "MAJOR", "확정 전 인력의 지난 경력을 단정하는 문장",
                              f"「{_snip(sample)}」 — 확정한 사람이 아니면 선정 기준(「…경력을 갖춘 전문가를 위촉 기준으로」)으로 고치세요",
                              section=section, count=count))
    if notice:
        for label, ours, theirs in (("사업명", view.get("title"), notice.get("title")), ("발주기관", view.get("agency"), notice.get("agency"))):
            if ours and theirs and _compact(ours) != _compact(theirs):
                found.append(_finding("NOTICE_MISMATCH", "MAJOR", f"공고 기본정보와 다름 — {label}",
                                      f"초안 「{_snip(ours)}」 · 공고 「{_snip(theirs)}」 — 공고가 바뀌었으면 초안을 다시 쓰세요"))
    if view.get("stale"):
        found.append(_finding("STALE", "MAJOR", "초안을 쓴 뒤 공고 분석이 바뀜",
                              "제안요청서를 다시 읽어 요구사항이 달라졌습니다 — 초안을 다시 쓰세요"))
    if gap := view.get("source_gap"):
        found += _source_gap_findings(gap)
    found += eligibility_findings(eligibility)
    # 본문의 사업기간 · 금액이 원문과 다름(2.8.0 B6 · 승인을 무효로 한다 — 금액 기준은 원문 사업금액)
    terms = view.get("terms") or bid.draft_terms(view)
    off = [(s, f"{_snip(x.get('text'))} — {why}") for s, x in sentences if (why := _terms_mismatch(str(x.get("text") or ""), terms))]
    for section, count, sample in _grouped(off):
        found.append(_finding("NOTICE_TERMS", "MAJOR", "본문의 사업기간 · 사업금액이 공고 원문과 다름",
                              f"「{sample}」 — 원문 값으로 고치세요", section=section, count=count))
    # 조견표가 가리킨 목차에 그 평가 내용이 없음(근사 · 짝은 지우지 않음 · 2.8.0 B4)
    empty = [c for c in coverage if c["body"] == "없음"]
    if empty:
        found.append(_finding("EVAL_MAP_NO_CONTENT", "MAJOR", "조견표 목차에 그 평가 내용이 없음(근사)",
                              " · ".join(f"「{c['name']}」 → {c['mapped']}" for c in empty[:5]) + (" 외" if len(empty) > 5 else "")
                              + " — 평가 기준의 핵심 낱말이 그 목차에 없습니다. 본문을 보강하거나 조견표 목차를 고치세요",
                              section=bid.EVAL_TITLE, count=len(empty), location=f"{bid.EVAL_TITLE} 「제안서 해당 목차」"))
    # 증빙 확인 전 실적 · 유효기간 지난 인증을 인용(2.8.0 B7 — 회사 자료를 읽은 `read_view` 일 때만)
    for section, count, sample in _grouped([(u["section"], f"{u['label']} — {u['reason']}") for u in (evidence or {}).get("unverified") or []]):
        found.append(_finding("EVIDENCE_UNVERIFIED", "MAJOR", "확인되지 않은 회사 근거를 인용함",
                              f"{sample} — 증빙을 확인하거나 그 문장을 빼세요", section=section, count=count))
    # 증빙 확인 전 실적의 수치를 확정 실적으로 씀(2.10.0 T3 · diff9 — 경고만 · 자동으로 빼지 않음: VERIFIED 칸이 없어 모든 원장 수치가 빠진다)
    for section, count, sample in _grouped([(n["section"], f"「{' · '.join(n['numbers'])}」 — 「{_snip(n['text'])}」")
                                            for n in (evidence or {}).get("numbers") or []]):
        found.append(_finding("EVIDENCE_NUMBER", "MINOR", "증빙 확인 전 실적 수치를 확정 실적처럼 씀",
                              f"{sample} — 결과보고서 · 만족도 결과로 확인한 뒤 남기세요", section=section, count=count))
    # 계약상 부담이 되는 약속(2.8.0 B8 — 원문 요구를 옮긴 인용은 아님)
    quotes = [str(x.get("source")) for _s, x in sentences if x.get("source")]
    for section, count, sample in _grouped([(s, str(x.get("text") or "")) for s, x in sentences if commitment(x, quotes)]):
        found.append(_finding("COMMITMENT", "MAJOR", "계약상 부담이 되는 약속 — 담당자 승인 필요",
                              f"「{_snip(sample)}」 — 인용 원문에 없는 약속(무상 추가 · 전원 수료 · 전담 인력 · 연동 확약 · 수당 지급 …)입니다. "
                              "원문 요구인지 확인하세요",
                              section=section, count=count))
    # 원문이 유사경험 기재를 막는데 회사 실적 문장이 있음(경고만 · 자동으로 빼지 않음 · 2.9.0)
    rule = fmt.get("no_similar") or {}
    cited = [(s, str(x.get("text") or "")) for s, x in sentences if any(str(i).startswith("ledger:") for i in x.get("source_ids") or [])]
    if rule and cited:
        found.append(_finding("NO_SIMILAR_RULE", "MAJOR", "원문이 유사 경험 기재를 막는데 회사 실적 문장이 있음",
                              f"원문 「{_snip(rule.get('line'))}」 — 실적 문장 {len(cited)}개(예: 「{_snip(cited[0][1])}」)", count=len(cited)))
    # 과업 상세(3차 지시서 §6) — 과업 소항목의 「○」 블록 절반 넘게 담당 · 일정 · 산출물 · 검수 · 위험 중 둘 이상이 빠짐(근사 · 보통)
    for section, missing, blocks in task_gaps(view):
        found.append(_finding("TASK_DETAIL_GAP", "MINOR", "과업 실행계획이 빈약함(근사)",
                              f"「○」 과업 {blocks}개 중 {missing}개가 담당 · 일정 · 산출물 · 검수 · 위험 대응 중 둘 이상을 빠뜨렸습니다", section=section, count=missing))
    # 회사 역량 · 실적 뒤 원문 밖 도구 · 시스템 제작 약속(2.9.0 · 경고만)
    leaps = [(s, str(x.get("text") or "")) for s, x in sentences if _LEAP_RE.search(str(x.get("text") or ""))
             and not re.search(r"도구|시스템|챗봇|대시보드|플랫폼", str(x.get("source") or ""))]
    for section, count, sample in _grouped(leaps):
        found.append(_finding("CAPABILITY_LEAP", "MINOR", "회사 역량으로 원문 밖 도구 · 시스템을 만들겠다는 문장",
                              f"「{_snip(sample)}」 — 제안요청서가 요구하지 않은 산출물 약속입니다. 원문 요구가 아니면 빼세요", section=section, count=count))
    # 작성 도구 낱말 「원문」(2.11.0 T7a) · 소항목 제목 조각이 본문에 없음(근사 · T7b)
    for section, count, sample in _grouped(tool_words(view, sentences)):
        found.append(_finding("TOOL_WORD", "MINOR", "작성 도구 낱말 「원문」이 본문 · 표에 남음",
                              f"「{_snip(sample)}」 — 평가위원에게는 「제안요청서」로 보여야 합니다", section=section, count=count))
    for section, part in title_gaps(view):
        found.append(_finding("TITLE_WORD_GAP", "MINOR", f"소항목 제목의 「{_snip(part)}」 내용이 본문에 없음(근사)",
                              f"「{_snip(section)}」 본문 · 표에서 「{_snip(part)}」의 핵심 낱말을 찾지 못했습니다", section=section))
    # 세부 추진 일정표(3차 지시서 §4 · 게이트 판 3) · 역할 이름 한 벌(2.10.0 T3 · 보통)
    found += schedule_findings(view)
    found += role_findings(view)
    # 본문 과업 블록의 시점이 일정표 그 과업 기간 밖(근사 · 보통 · 2.10.0)
    gaps = body_schedule_gaps(view)
    for section, count, sample in _grouped([(s, f"「{task}」 본문 「{when}」 · 일정표 「{period}」") for s, task, when, period in gaps]):
        found.append(_finding("SCHEDULE_BODY_GAP", "MINOR", "본문 시점이 일정표 그 과업 시작보다 앞섬(근사)",
                              f"{sample} — 앞당긴 시점이면 일정표 기간도 같은 값으로 맞추세요", section=section, count=count))
    # 원문이 대면 · 집합 · 현장으로 정한 활동을 온라인 · 원격으로 바꿈(제안서는 계약조건 — 「발주기관과 협의해 정하는 대안」 꼴만 · 2.10.0 D2)
    swaps = remote_swaps(view, sentences)
    for section, count, sample in _grouped([(s, f"{_snip(text)}」 — 원문 「{_snip(quote)}") for s, text, quote in swaps]):
        found.append(_finding("REMOTE_SWAP", "MAJOR", "원문이 대면으로 정한 활동을 온라인 · 원격으로 바꿈",
                              f"「{sample}」 — 바꾸려면 「발주기관과 협의해 정하는 대안」으로 쓰세요", section=section, count=count))
    # 평가본에 남은 회사 식별 낱말(2.10.0 D7 — 원문이 평가본을 요구할 때만 · 회사 이름 · 대표자 · 연락처 · 번호는 차단 · 그 밖은 중요)
    if fmt.get("blind") and identity:
        found += identity_findings(blind_texts(view, meta), identity)
    # 정량정보(3차 지시서 §5) — 문장 안 합계 어긋남(옛 초안도) · 원문 기준 수치와 다름(2.9.0 초안의 `facts`) · 원문 안 모호한 값
    sums = [(s, f"{_snip(x.get('text'))} — {why}") for s, x in sentences if (why := plan_validation.sum_breaks(str(x.get("text") or "")))]
    for section, count, sample in _grouped(sums):
        found.append(_finding("NUMBER_SUM", "MAJOR", "본문 합계가 맞지 않음", f"「{sample}」", section=section, count=count))
    # 예산 배분안 산수(2.10.0 D3) — 사람이 채운 금액이 있을 때만(제출 PDF 검사와 같은 함수)
    for table in view.get("tables") or []:
        if table.get("key") == bid.BUDGET_TABLE["key"] and (breaks := plan_validation.budget_breaks(table.get("rows") or [], terms.get("budget_won"))):
            found.append(_finding("BUDGET_MATH", "MAJOR", "예산 배분안 산수가 맞지 않음", " · ".join(breaks[:3]) + (" 외" if len(breaks) > 3 else ""),
                                  section=str(table.get("title") or ""), count=len(breaks), location=f"표 「{table.get('title')}」"))
    facts = view.get("facts") or []
    allowed = {(d.get("unit"), float(d.get("value") or 0)) for d in view.get("derived") or []}
    values = [(s, f"{_snip(x.get('text'))} — {', '.join(c)}") for s, x in sentences
              if (c := plan_validation.fact_conflicts(str(x.get("text") or ""), facts, allowed))]
    for section, count, sample in _grouped(values):
        found.append(_finding("NOTICE_VALUE", "MAJOR", "본문 수치가 제안요청서 기준 수치와 다름", f"「{sample}」", section=section, count=count))
    vague = [d for d in view.get("derived") or [] if d.get("approx") is not None and d.get("approx") != d.get("value")]
    if vague:
        d = vague[0]
        found.append(_finding("NOTICE_AMBIGUOUS", "MINOR", "제안요청서 정량값이 모호함(원문 안 어긋남)",
                              f"원문 「{_snip(d.get('quote'))}」 — {d['base']}명의 {d['percent']}%는 최소 {d['value']}{d['unit']}(올림) · 원문 「약 {d['approx']}{d['unit']}」",
                              count=len(vague)))
    skip, dup = _number_breaks(form)
    if dup:
        found.append(_finding("NUMBER_DUP", "BLOCKER", f"대항목 번호가 겹치거나 거꾸로 감({dup})",
                              "평가위원에게 같은 장이 두 번 있는 것처럼 보입니다 — 원문 목차를 확인하고 번호를 고치세요"))
    if fmt.get("two_volume"):
        names = " · ".join(fmt.get("volumes") or []) or "정량 · 정성"
        found.append(_finding("FORMAT_TWO_VOLUME", "MAJOR", "제안요청서가 두 권으로 나눠 내라고 함 — 앱은 한 권으로 만듦",
                              f"{names} — 따로 묶어 내야 합니다. 받은 파일을 나눠 저장하세요"))
    if _ppt_required(fmt):
        note = next((n for n in fmt.get("notes") or [] if bid._PPT_RE.search(str(n))), "")
        found.append(_finding("FORMAT_PPT", "MAJOR", "제안요청서가 PPT 로 쓰라고 함 — 앱은 한글 · 워드로 만듦",
                              f"원문: 「{_snip(note)}」 — 받은 본문을 PPT 로 옮기세요"))
    if fmt.get("landscape"):
        note = next((n for n in fmt.get("notes") or [] if "가로" in str(n)), "")
        found.append(_finding("FORMAT_LANDSCAPE", "MAJOR", "제안요청서가 A4 가로로 쓰라고 함 — 앱은 세로로 만듦",
                              f"원문: 「{_snip(note)}」 — 받은 파일의 쪽 방향을 바꾸세요"))

    # --- 보통: 검토용 경고가 남은 문장 · 담당자가 채울 항목 ---------------------------------------------------
    for label, count, sample in _review_flags(sentences):
        found.append(_finding("REVIEW_FLAGS", "MINOR", f"검토 경고가 남은 문장 — {label}", f"「{_snip(sample)}」 — 검토용 파일에서 경고를 보고 고치세요",
                              count=count))
    if blanks:
        # 빈칸 목록은 제출용에 나가지 않지만 회사 결정 · 붙일 서류가 섞여 있다(2.8.0 B3 — 대부분이 게이트 밖이었다)
        found.append(_finding("REVIEW_BLANKS", "MINOR", "검토용 「담당자가 채울 항목」이 남음",
                              "회사가 정할 값 · 본문에서 뺀 문장 · 붙일 서류가 검토용 파일 끝 「담당자가 채울 항목」에 있습니다",
                              count=len(blanks), location="검토용 파일 「담당자가 채울 항목」"))
    if bid.papers_unread(view):
        # 보통 · 사실 확인 — 상태(차단 · 검토 필요)도 자동 작성 검사도 바꾸지 않는다(제출서류는 판정 밖 · 2.10.0 D10)
        found.append(_finding("PAPERS_UNREAD", "MINOR", "입찰공고문 제출서류 목록을 읽지 못함", bid.PAPERS_UNREAD_NOTE,
                              location=f"검토용 파일 「담당자가 채울 항목」 › {bid.SUPPLEMENT_SECTION}"))

    # --- 참고 --------------------------------------------------------------------------------------------
    quant = _eval_none(view)
    if quant:
        found.append(_finding("EVAL_MAP_BLANK", "INFO", "조견표 정량 항목은 「—」로 둠",
                              "「" + "」 · 「".join(quant[:5]) + "」" + (" 외" if len(quant) > 5 else "")
                              + " — 정량 항목은 제출 서류로 평가합니다. 해당 서류 목차를 적거나 「—」 그대로 두세요",
                              section=bid.EVAL_TITLE, count=len(quant), location=f"{bid.EVAL_TITLE} 「제안서 해당 목차」",
                              action="정량 항목은 받은 파일의 조견표에 해당 서류 목차를 적거나 「—」 그대로 두세요", axis="input"))
    if notice is None:
        found.append(_finding("NOTICE_UNCHECKED", "INFO", "공고 기본정보 대조를 못 함",
                              "받아 둔 공고 목록(최근 공고)에서 이 공고를 찾지 못해 사업명 · 발주기관 대조를 건너뛰었습니다"))
    if skip:
        found.append(_finding("NUMBER_SKIP", "INFO", f"원문 대항목 번호가 건너뜀({skip}) — 원문대로 옮김",
                              "평가위원에게 빠진 장처럼 보일 수 있습니다 — 원문 목차를 확인하세요"))
    for fix in form.get("renumbered") or []:
        found.append(_finding("NUMBER_FIXED", "INFO", f"원문 대항목 번호 {fix.get('from')}({fix.get('title')})를 {fix.get('to')} 로 고쳐 붙임 — 원문 오타로 보임",
                              "제안요청서 목차에 같은 번호가 두 번(또는 거꾸로) 나와 뒤 대항목 번호를 올렸습니다 — 원문 목차와 대조하세요"))
    if fmt.get("blind_only"):
        # 원본 · 사본 구분이 없는 규정 — 평가본이 곧 제출 파일(「제출용」 이름 · 2.10.0 D8)
        found.append(_finding("BLIND_RULE", "INFO", "원문이 제출 제안서에 회사 식별 정보를 막음 — 평가본을 냄",
                              f"원문: 「{_snip(fmt.get('blind_note'))}」 — 원본 · 사본 구분이 없어 평가본이 제출 파일입니다"
                              "(「제출용」 이름 · 회사명 포함본은 내지 않음)",
                              action="「제출용」 이름의 평가본(회사명 없는 판)을 내고, 영문 이름 · 로고는 직접 확인하세요"))
    elif fmt.get("blind"):
        found.append(_finding("BLIND_RULE", "INFO", "원문이 평가본에 회사명 표기를 막음",
                              f"원문: 「{_snip(fmt.get('blind_note'))}」 — 평가본으로도 받으세요(영문 이름 · 로고는 직접 확인)"))
    documents = [view.get("rfp_document"), *((view.get(key) or {}).get("document") for key in ("outline_where", "evaluation_where")),
                 (fmt.get("where") or {}).get("document")]
    if any(_HWP_RE.search(str(name or "").split(" > ")[-1]) for name in documents):
        found.append(_finding("PAGES_APPROX", "INFO", "원문 쪽 번호는 한글 문서 근사치",
                              "한글(HWP · HWPX) 원문은 실제 쪽이 아니라 문단 묶음으로 센 쪽입니다 — 원문 위치는 직접 확인하세요"))
    return _sorted(found), staffing_unconfirmed


def _sorted(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    order = {severity: n for n, severity in enumerate(SEVERITIES)}
    return sorted(findings, key=lambda f: order[f["severity"]])  # 같은 심각도 안은 넣은 순서 그대로(안정 정렬)


def _approver(approval: dict[str, Any]) -> dict[str, Any]:
    from app.services import user_service

    by = str(approval.get("by") or "")
    name = user_service.display_name_of(by)
    return {"by": by, "by_name": name if name and name != by else None, "at": approval.get("at"), "note": approval.get("note") or None}


def _when(at: Any) -> str:
    try:
        return datetime.fromisoformat(str(at)).astimezone(plan_export_service.KST).strftime("%m/%d %H:%M")
    except ValueError:
        return str(at or "")


def generation_of(findings: list[dict[str, Any]]) -> dict[str, Any]:
    """자동 작성 검사(3차 지시서 §12) — 앱이 고칠 것(갈래 auto)만 본다. 검증 실패면 ERROR · 차단이나 AI 가 못 쓴 소항목이 있으면
    FAIL · 중요 · 보통 경고가 있으면 REVIEW · 없으면 PASS. 담당자 입력 · 증빙 · 사실 확인은 제출 상태(`status`)만 막는다."""
    auto = [f for f in findings if f.get("axis") == "auto"]
    if any(f.get("code") == "GATE_ERROR" for f in findings):
        status = "ERROR"
    elif any(f.get("severity") == "BLOCKER" or f.get("code") in ("LLM_FAILED", *VOID_CODES) for f in auto):
        status = "FAIL"
    elif any(f.get("severity") in ("MAJOR", "MINOR") for f in auto):
        status = "REVIEW"
    else:
        status = "PASS"
    return {"status": status, "label": GENERATION_LABELS[status],
            "counts": {severity: sum(1 for f in auto if f.get("severity") == severity) for severity in SEVERITIES}}


def axis_counts(findings: list[dict[str, Any]]) -> dict[str, int]:
    """갈래마다 참고(INFO)를 뺀 항목 수 — 화면 여섯 상태(§9 · 자동 작성 완료 · 수정 필요 · 담당자 입력 필요 · 증빙 필요 · 사실 확인 필요 · 검증 완료)."""
    return {axis: sum(1 for f in findings if f.get("axis") == axis and f.get("severity") != "INFO") for axis in AXES}


def _result(view: dict[str, Any], findings: list[dict[str, Any]], *, draft_hash: str, staffing_unconfirmed: bool,
            approval: dict[str, Any] | None, submit_blanks: int | None, coverage: list[dict[str, Any]] | None = None,
            evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    """`quality` 칸(API 약속) — 상태는 차단 → 승인(살아 있으면) → 중요 순(제출 준비 축). `generation` 은 자동 작성 축(게이트 판 3).
    `hwpx_check` 는 `read_view` 가 채운다."""
    terms = view.get("terms") or {}
    counts = {severity: sum(1 for f in findings if f["severity"] == severity) for severity in SEVERITIES}
    if counts["BLOCKER"]:
        status = "BLOCKED"
    elif approval:
        status = "READY_TO_SUBMIT"
    elif counts["MAJOR"]:
        status = "NEEDS_REVIEW"
    else:
        status = "VERIFIED_DRAFT"
    return {
        "status": status,
        "status_label": STATUS_LABELS[status],
        "counts": counts,
        "generation": generation_of(findings),
        "axes": axis_counts(findings),
        "findings": findings,
        "staffing_unconfirmed": staffing_unconfirmed,
        "approval": _approver(approval) if approval else None,
        "draft_hash": draft_hash,
        "file_label": "제출용" if status == "READY_TO_SUBMIT" else "초안",
        "gate_version": GATE_VERSION,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "submit_blanks": submit_blanks,
        "review_blanks": len(view.get("blanks") or []),
        "hwpx_check": None,
        "pdf_check": None,  # 마지막 「한글에서 저장한 PDF 검사」(`read_view` 가 채움 · 판정 밖 · 2.10.0 D10)
        "evaluation_coverage": coverage or [],
        "evidence_status": evidence,
        "terms": {key: terms.get(key) for key in ("period", "end", "budget")},
    }


def evaluate(view: dict[str, Any], *, meta: dict[str, Any], draft_hash: str, notice: dict[str, Any] | None = None,
             approval: dict[str, Any] | None = None, evidence: dict[str, Any] | None = None,
             identity: list[tuple[str, str]] | None = None, eligibility: Any = None) -> dict[str, Any]:
    """품질 게이트 결과(화면 `quality` 칸 · API 약속 그대로). 승인은 지금 초안 해시와 같을 때만 살아 있고, 승인을 무효로 하는 검사
    (`VOID_CODES` — 낡음 · 공고 불일치 …)가 있으면 「제출 준비」가 아니라 APPROVAL_VOID(2.8.0 B2). evidence 는 `evidence_status`
    (회사 자료를 읽는 `read_view` 가 계산해 넘긴다 · 없으면 근거 상태 검사를 건너뛰고 `evidence_status` 칸은 None) · identity 는
    `identity_words`(평가본 공고만 · 결과 칸에는 싣지 않는다)."""
    scan = _scan_submit(view, meta)
    coverage = evaluation_coverage(view)
    findings, staffing_unconfirmed = findings_of(view, meta=meta, notice=notice, scan=scan, evidence=evidence, coverage=coverage,
                                                 identity=identity, eligibility=eligibility)
    live = approval if approval and approval.get("draft_hash") == draft_hash else None
    void = [f["title"] for f in findings if f["code"] in VOID_CODES]
    if live and void:
        who = _approver(live)
        findings = _sorted([*findings, _finding(
            "APPROVAL_VOID", "MAJOR", "승인 뒤 공고 · 요구사항이 바뀜 — 다시 읽고 승인",
            f"{_when(who['at'])} {who['by_name'] or who['by']} 님의 승인을 쓰지 않습니다 — " + " · ".join(f"「{t}」" for t in void[:3]))])
        live = None
    return _result(view, findings, draft_hash=draft_hash, staffing_unconfirmed=staffing_unconfirmed, approval=live,
                   submit_blanks=scan["total"], coverage=coverage, evidence=evidence)


def error_quality(view: dict[str, Any], *, draft_hash: str) -> dict[str, Any]:
    """검증을 못 했을 때의 `quality` — 통과가 아니라 차단(GATE_ERROR · 승인 409 · 파일 이름 「초안」 · 2.8.0 B1)."""
    finding = _finding("GATE_ERROR", "BLOCKER", "검증을 실행하지 못했습니다 — 다시 시도 · 관리자에게",
                       "제출 상태를 확인하지 못해 차단으로 둡니다. 파일은 「초안」 이름으로 받을 수 있습니다")
    return _result(view, [finding], draft_hash=draft_hash, staffing_unconfirmed=False, approval=None,
                   submit_blanks=view.get("submit_blanks"))


# ---------------------------------------------------------------------------
# 공고 저장본 · 승인 기록 · 품질 보고서
# ---------------------------------------------------------------------------


def stored_notice(procurement_id: str) -> dict[str, Any] | None:
    """받아 둔 공고 목록에서 그 공고(네트워크 없음) — {notice_no, title, agency(화면 표시값), url(공고 상세 주소 · 표지 링크 2.9.1)}.
    목록에 없거나 못 읽으면 None."""
    from app.services import home_agencies, procurement_service

    try:
        cached = procurement_service.load_cache(with_schedule=False)
    except Exception:  # noqa: BLE001 — 공고 목록을 못 읽어도 초안 화면 · 내려받기는 막지 않는다(대조만 건너뜀)
        logger.warning("공고 저장본을 읽지 못해 공고 기본정보 대조를 건너뜁니다", exc_info=True)
        return None
    for entry in cached.notices if cached else []:
        notice = entry.notice
        if notice.id == procurement_id:
            demand = (notice.raw_data or {}).get("demand_institution")
            return {"notice_no": notice.notice_no, "title": notice.title, "agency": home_agencies.display_agency(notice.agency, demand),
                    "url": notice.source_url,
                    "attachments": [str(a.get("name")) for a in (notice.raw_data or {}).get("attachments") or []
                                    if isinstance(a, dict) and a.get("name") and a.get("url")]}
    return None


def _where(procurement_id: str, file_name: str) -> dict[str, Any]:
    from app.services import proposal_service

    return {"public_path": proposal_service.PROPOSALS_DIR / f"{procurement_id}.{file_name}", "file_name": file_name}


def load_approval(context: AnalysisContext | None, procurement_id: str) -> dict[str, Any] | None:
    """저장된 승인 기록(해시가 지금 초안과 다르면 `evaluate` 가 버린다). 없거나 못 읽으면 None."""
    try:
        payload, _legacy = analysis_store.load_json(context, procurement_id, **_where(procurement_id, APPROVAL_FILE))
    except Exception:  # noqa: BLE001 — 승인 기록을 못 읽으면 승인 없음으로(화면은 그대로 열린다)
        logger.warning("승인 기록을 읽지 못했습니다 (procurement_id=%s)", procurement_id, exc_info=True)
        return None
    return payload


def save_approval(context: AnalysisContext | None, procurement_id: str, *, draft_hash: str, note: str | None) -> dict[str, Any]:
    """사람 승인 — 지금 초안 해시 · 누가(요청자 신원) · 언제 · 메모. 미들웨어가 인증이 꺼진 PC 에서 넣는 신원은 「local-admin」 그대로다."""
    from app.core import requester

    record = {
        "procurement_id": procurement_id,
        "draft_hash": draft_hash,
        # 요청 밖(스크립트 · 시험)에는 신원이 없다 — 인증이 꺼진 PC 의 미들웨어 신원과 같은 이름으로 남긴다(core/requester 설명)
        "by": requester.current_recorded_by() or "local-admin",
        "at": datetime.now(timezone.utc).isoformat(),
        "note": (note or "").strip()[:200] or None,
    }
    analysis_store.write_json(context, procurement_id, record, **_where(procurement_id, APPROVAL_FILE))
    return record


def revoke_approval(context: AnalysisContext | None, procurement_id: str) -> None:
    """승인 취소 — 기록 파일을 지운다(없으면 그대로)."""
    analysis_store.guard_public_demo_write(context)
    where = _where(procurement_id, APPROVAL_FILE)
    analysis_store.resolve_path(context, procurement_id, **where).unlink(missing_ok=True)


#: 기록 파일에서 돌려줄 최근 줄 수(보고서 받기 API).
LOG_LIMIT = 500


def _pdf_line(pdf: dict[str, Any] | None) -> dict[str, Any] | None:
    """기록 줄의 PDF 검사 요약 — 상태 · 쪽수 · 검사 코드만(올린 파일 이름 · 식별 낱말 값은 남기지 않는다 · D7)."""
    if not pdf:
        return None
    return {"state": pdf.get("state"), "pages": pdf.get("pages"),
            "findings": [{"code": f.get("code"), "severity": f.get("severity"), "count": f.get("count")} for f in pdf.get("findings") or []]}


def _log_line(procurement_id: str, view: dict[str, Any], *, event: str, fmt: str | None, variant: str | None,
              hwpx: dict[str, Any] | None, error: str | None, pdf: dict[str, Any] | None = None) -> dict[str, Any]:
    quality = view.get("quality") or {}
    return {
        "at": datetime.now(timezone.utc).isoformat(), "event": event, "procurement_id": procurement_id,
        "notice_no": view.get("notice_no"), "executed_at": view.get("executed_at"), "draft_hash": quality.get("draft_hash"),
        "gate_version": quality.get("gate_version", GATE_VERSION), "status": quality.get("status"), "counts": quality.get("counts"),
        "generation": (quality.get("generation") or {}).get("status"), "axes": quality.get("axes"),
        "file_label": quality.get("file_label"), "format": fmt, "variant": variant,
        "findings": [{"code": f.get("code"), "severity": f.get("severity"), "count": f.get("count"), "location": f.get("location"),
                      "axis": f.get("axis")} for f in quality.get("findings") or []],
        "hwpx": hwpx, "error": error, **({"pdf": _pdf_line(pdf)} if pdf else {}),
    }


def log_event(context: AnalysisContext | None, procurement_id: str, view: dict[str, Any], *, event: str, fmt: str | None = None,
              variant: str | None = None, hwpx: dict[str, Any] | None = None, error: str | None = None,
              pdf: dict[str, Any] | None = None) -> None:
    """기록 한 줄(`bid_quality_log.jsonl` · write · export · approve · revoke · error · pdf_check · 2.8.0 B9) — 사내 범위만. 남기지 못해도 막지 않는다."""
    if not analysis_store.is_private(context):
        return
    assert context is not None
    line = _log_line(procurement_id, view, event=event, fmt=fmt, variant=variant, hwpx=hwpx, error=error, pdf=pdf)
    try:
        path = analysis_store.private_dir(context, procurement_id) / LOG_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
    except Exception:  # noqa: BLE001 — 기록은 기록일 뿐이다
        logger.warning("품질 기록을 남기지 못했습니다 (procurement_id=%s)", procurement_id, exc_info=True)


def _load_report(context: AnalysisContext | None, procurement_id: str) -> dict[str, Any] | None:
    if not analysis_store.is_private(context):
        return None
    try:
        payload, _legacy = analysis_store.load_json(context, procurement_id, **_where(procurement_id, REPORT_FILE))
    except Exception:  # noqa: BLE001 — 보고서를 못 읽으면 없음으로
        logger.warning("품질 보고서를 읽지 못했습니다 (procurement_id=%s)", procurement_id, exc_info=True)
        return None
    return payload


def save_report(context: AnalysisContext | None, procurement_id: str, view: dict[str, Any], *, event: str,
                fmt: str | None = None, variant: str | None = None, hwpx: dict[str, Any] | None = None,
                pdf: dict[str, Any] | None = None) -> None:
    """품질 보고서(최신 · `bid_quality.json`) + 기록 한 줄 — 쓰기 · 내려받기 · 승인 · 취소 · PDF 검사 때(사내 범위만 · 공용 데모 파일은 건드리지 않는다).
    마지막 한글 다시 읽기(`last_hwpx` — 제출용 · 평가본 한글 내려받기) · 마지막 PDF 검사(`last_pdf` · 2.10.0 T8)는 다른 사건으로 지우지 않는다.
    남기지 못해도 막지 않는다."""
    if not analysis_store.is_private(context):
        return
    quality = view.get("quality") or {}
    rechecked = hwpx if hwpx and "match" in hwpx else None
    try:
        previous = _load_report(context, procurement_id) or {}
        payload = {"procurement_id": procurement_id, "notice_no": view.get("notice_no"), "executed_at": view.get("executed_at"),
                   "draft_hash": quality.get("draft_hash"), "gate_version": quality.get("gate_version", GATE_VERSION),
                   "saved_at": datetime.now(timezone.utc).isoformat(), "event": event, "format": fmt, "variant": variant,
                   "quality": quality, "hwpx": hwpx, "last_hwpx": rechecked or previous.get("last_hwpx"),
                   "last_pdf": pdf or previous.get("last_pdf")}
        analysis_store.write_json(context, procurement_id, payload, **_where(procurement_id, REPORT_FILE))
    except Exception:  # noqa: BLE001 — 보고서는 기록일 뿐이다
        logger.warning("품질 보고서를 남기지 못했습니다 (procurement_id=%s)", procurement_id, exc_info=True)
    log_event(context, procurement_id, view, event=event, fmt=fmt, variant=variant, hwpx=hwpx, pdf=pdf)


def last_hwpx(context: AnalysisContext | None, procurement_id: str, draft_hash: str) -> dict[str, Any] | None:
    """마지막 한글(제출용 · 평가본) 다시 읽기 결과 — 지금 초안을 받은 것만(다시 쓰면 「아직 안 받음」 · `quality.hwpx_check`)."""
    check = (_load_report(context, procurement_id) or {}).get("last_hwpx")
    return check if isinstance(check, dict) and check.get("draft_hash") == draft_hash else None


def last_pdf(context: AnalysisContext | None, procurement_id: str, draft_hash: str) -> dict[str, Any] | None:
    """마지막 「한글에서 저장한 PDF 검사」 — 지금 초안으로 검사한 것만(다시 쓰면 「아직 안 함」 · `quality.pdf_check`)."""
    check = (_load_report(context, procurement_id) or {}).get("last_pdf")
    return check if isinstance(check, dict) and check.get("draft_hash") == draft_hash else None


def quality_report(context: AnalysisContext | None, procurement_id: str) -> dict[str, Any]:
    """검증 보고서 받기(`GET …/plan-draft/quality-report`) — 최신 보고서 + 이 공고 기록 줄(최근 `LOG_LIMIT` 줄 · 깨진 줄은 뺌)."""
    lines: list[dict[str, Any]] = []
    if analysis_store.is_private(context):
        assert context is not None
        path = analysis_store.private_dir(context, procurement_id) / LOG_FILE
        try:
            raw = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        except OSError:
            logger.warning("품질 기록을 읽지 못했습니다 (procurement_id=%s)", procurement_id, exc_info=True)
            raw = []
        for text in raw[-LOG_LIMIT:]:
            try:
                line = json.loads(text)
            except ValueError:
                continue
            if isinstance(line, dict):
                lines.append(line)
    return {"procurement_id": procurement_id, "gate_version": GATE_VERSION, "report": _load_report(context, procurement_id), "log": lines}


#: 다시 읽은 한글 문단의 대항목 머리(「Ⅵ. 결과 활용성 부문」).
_MAJOR_HEAD_RE = re.compile(r"^([ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]{1,4})\s*\.")
#: 목차 쪽 제목(앱 목차 블록 · 사람이 넣은 「< 목 차 >」 — 견주기 꼴에서 꺾쇠를 뗀 글).
_TOC_TITLES = ("목차", "차례")


def _without_toc(paragraphs: list[str]) -> list[str]:
    """앱이 넣은 목차(「목차」 문단 다음 ~ 목차 첫 줄 글이 본문 머리로 다시 나오기 전)를 뺀 문단(2.11.0 D2) — 목차 줄은 본문 머리를
    옮겨 적은 것이라 대항목 겹침 · 미작성 셈에 넣지 않는다(게이트 셈 `_block_text` 도 목차를 세지 않는다). 첫 줄이 다시 나오지 않으면 그대로."""
    if "목차" not in paragraphs:
        return paragraphs
    start = paragraphs.index("목차")
    first = paragraphs[start + 1] if start + 1 < len(paragraphs) else None
    end = next((i for i in range(start + 2, len(paragraphs)) if paragraphs[i] == first), None)
    return paragraphs if end is None else paragraphs[:start] + paragraphs[end:]


def recheck_hwpx(payload: bytes, *, expected: int) -> dict[str, Any]:
    """만든 한글 파일을 다시 읽어 센다(2.8.0 B9) — 미작성 꼴 수(문단마다 자기 글 · 표 칸 따로 · `unwritten_count`)와 대항목 머리 번호 겹침.
    expected 는 같은 판 블록에서 센 수(`plan_export_service.blank_total`). 다시 읽지 못하면 reextract_ok False · match False."""
    from app.services import document_extractor

    try:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "recheck.hwpx"
            path.write_bytes(payload)
            paragraphs = document_extractor.hwpx_paragraphs(path, own=True)
    except Exception:  # noqa: BLE001 — 다시 읽기 실패는 「다름」으로(파일은 「초안」 이름)
        logger.warning("만든 한글 파일을 다시 읽지 못했습니다", exc_info=True)
        return {"reextract_ok": False, "placeholders": None, "gate_spots": expected, "match": False, "duplicate_majors": []}
    paragraphs = _without_toc(paragraphs)
    count = sum(unwritten_count(text) for text in paragraphs)
    if count != expected:
        logger.warning("만든 한글 파일을 다시 읽은 미작성 칸 수가 게이트와 다릅니다 (다시 읽음 %s · 게이트 %s)", count, expected)
    heads = [m.group(1) for text in paragraphs if (m := _MAJOR_HEAD_RE.match(text))]
    duplicates = list(dict.fromkeys(head for head in heads if heads.count(head) > 1))
    return {"reextract_ok": True, "placeholders": count, "gate_spots": expected, "match": count == expected, "duplicate_majors": duplicates}


# ---------------------------------------------------------------------------
# 평가본 식별 낱말 — 회사 자료에서(한글에서 저장한 PDF 검사 · 제출 전 점검 업로드가 함께 · 2.10.0 T8 · blind6)
# ---------------------------------------------------------------------------


def identity_for(view: dict[str, Any], context: AnalysisContext) -> list[tuple[str, str]] | None:
    """원문이 평가본을 요구하는 초안(`format.blind`)이면 회사 식별 낱말(`read_view` 와 같은 재료 — 회사 값 · 실적 원장 기관 · 이번 공고 글 뺌) · 아니면 None."""
    if not (view.get("format") or {}).get("blind"):
        return None
    from app.services import plan_fill_service

    values = plan_fill_service.company_values(context.organization_id, context.evidence_scope)
    return identity_words(values, bid._company_evidence(context)["ledger_rows"], exclude=notice_text(view))


def draft_identity(procurement_id: str, context: AnalysisContext | None) -> tuple[list[tuple[str, str]], bool] | None:
    """저장된 입찰 제안서 초안이 평가본 공고면 (식별 낱말, 평가본만 내는가) — 초안이 없거나 평가본 공고가 아니면 None(제출 전 점검 업로드)."""
    if context is None:
        return None
    try:
        draft = bid.load(procurement_id, context=context)
    except bid.BidPlanNotGeneratedError:
        return None
    words = identity_for(draft, context)
    return (words, bool((draft.get("format") or {}).get("blind_only"))) if words else None


def draft_budget_cap(procurement_id: str, context: AnalysisContext | None) -> int | None:
    """저장된 입찰 제안서 초안의 사업금액(원 · 예산 표 「합계 ≤ 사업금액」) — 초안이 없으면 None(제출 전 점검 업로드 · budget2)."""
    if context is None:
        return None
    try:
        draft = bid.load(procurement_id, context=context)
    except bid.BidPlanNotGeneratedError:
        return None
    return bid.draft_terms(draft).get("budget_won")


# ---------------------------------------------------------------------------
# 한글에서 저장한 PDF 검사(2.10.0 T8 · D9 · D10 — 사람이 고친 최종 파일을 읽어 알리기만 · 판정 · 승인은 바꾸지 않는다)
# ---------------------------------------------------------------------------

SEVERITY_LABELS = {"BLOCKER": "차단", "MAJOR": "중요", "MINOR": "보통", "INFO": "참고"}
#: A4(pt) · 허용 차(한글 PDF 595 × 841.89 실측 · ±2pt).
A4_PT = (595.3, 841.9)
A4_TOLERANCE = 2.0
PDF_STATES = {"unreadable": "검사 못 함", "issues": "고칠 곳 있음", "ok": "통과"}
#: 예산 배분안 제목 줄 뒤에서 합계 줄을 찾는 줄 수 상한(PDF 한 줄 글 · 칸 줄바꿈 포함).
PDF_BUDGET_LINES = 60
#: 조견표에 사람이 적은 쪽 — 「Ⅲ-1(5쪽)」 · 「Ⅲ-1 (5쪽)」 · 「1.1(5쪽)」.
_WRITTEN_PAGE_RE = re.compile(r"([ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]{1,4}(?:\s*-\s*\d{1,2})?|\d{1,2}\.\d{1,2})\s*[(（]\s*(\d{1,3})\s*쪽\s*[)）]")


#: PDF 검사가 글을 읽는 쪽 · 시간 상한(11-13 독립 검토 — 7만 쪽 · 스트림을 함께 쓰는 작은 파일이 작업자를 수십 분 묶었다). 넘으면 앞쪽만 읽고
#: 쪽수는 전체로 센다(「앞 n쪽만 검사」).
PDF_READ_PAGES = 300
PDF_READ_SECONDS = 60.0


def read_pdf(payload: bytes, *, max_pages: int = PDF_READ_PAGES) -> dict[str, Any]:
    """올린 PDF(pdfplumber · 새 의존성 없음) → {ok, reason, pages(쪽 글), cells(쪽마다 표 칸 글 — 한 줄에 한 칸 · 칸 안 줄바꿈은 빈칸 없이 이음),
    outside(쪽마다 표 밖 글), overlaps(쪽마다 겹친 낱말 쌍 수), total(전체 쪽수), partial(앞쪽만 읽음), sizes(pt), links(URI),
    info(문서 정보 제목 · 지은이 · 주제 · 낱말)}.
    열지 못하거나(깨짐 · 암호 · 비정상 압축 — `document_extractor._check_pdf_streams`) 글이 한 줄도 없으면(그림으로 저장) ok False.
    글은 앞 `max_pages` 쪽 · `PDF_READ_SECONDS` 안에서만 읽는다."""
    import time

    import pdfplumber

    from app.services import document_extractor

    empty: dict[str, Any] = {"ok": False, "reason": None, "pages": [], "cells": [], "outside": [], "overlaps": [], "total": 0, "partial": False,
                             "sizes": [], "links": [], "info": ""}
    try:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "check.pdf"
            path.write_bytes(payload)
            document_extractor._check_pdf_streams(path)
            with pdfplumber.open(str(path)) as pdf:
                total = len(pdf.pages)
                started = time.monotonic()
                pages: list[str] = []
                cells: list[str] = []
                outside: list[str] = []
                overlaps: list[int] = []
                for page in pdf.pages[:max_pages]:
                    if time.monotonic() - started > PDF_READ_SECONDS:
                        break
                    pages.append(page.extract_text() or "")
                    # 좁은 표 칸(참여인력 「성명」)의 「(담당자 입력)」 · 식별 낱말은 쪽 글에서 옆 칸 글과 섞여 갈린다 — 칸 글로도 본다(11-13 독립 검토).
                    # 칸 안 줄바꿈은 빈칸 없이 잇는다 — 「(담당⏎자 입⏎력)」이 빈칸으로 이으면 「(담당 자 입 력)」이라 미작성 꼴에 안 맞았다(2.11.0 T5b ·
                    # 11-14 완성본 07위 91 · 게이트 105). 표 밖 글은 칸 글과 따로 세려고 표 상자 밖만(`_page_unwritten`).
                    tables = page.find_tables()
                    cells.append("\n".join(re.sub(r"\s*\n\s*", "", str(cell)) for table in tables for row in table.extract() for cell in row if cell))
                    rest = page
                    for table in tables:
                        rest = rest.outside_bbox(table.bbox, strict=False)
                    outside.append(rest.extract_text() or "")
                    overlaps.append(_overlap_pairs(page.extract_words()))
                read = pdf.pages[:len(pages)]
                sizes = [(float(page.width), float(page.height)) for page in read]
                links = [str(link["uri"]) for page in read for link in page.hyperlinks if link.get("uri")]
                info = " ".join(str(pdf.metadata.get(key) or "") for key in ("Title", "Author", "Subject", "Keywords"))
    except Exception:  # noqa: BLE001 — 못 읽은 파일은 통과가 아니라 「검사 못 함」
        logger.warning("올린 PDF 를 읽지 못했습니다", exc_info=True)
        return {**empty, "reason": "PDF 를 열지 못했습니다 — 깨진 파일 · 암호 · 비정상 압축일 수 있습니다"}
    if not pages:
        return {**empty, "total": total, "reason": "PDF 에 쪽이 없습니다" if not total else "PDF 를 읽는 데 시간이 너무 걸려 멈췄습니다"}
    partial = len(pages) < total
    read_parts = {"pages": pages, "cells": cells, "outside": outside, "overlaps": overlaps, "total": total, "partial": partial, "sizes": sizes,
                  "links": links, "info": info}
    if not any(text.strip() for text in pages):
        return {**empty, **read_parts,
                "reason": "PDF 에서 글을 읽지 못했습니다 — 그림(스캔)으로 저장한 PDF 는 미작성 · 식별 낱말 검사를 할 수 없습니다"}
    return {"ok": True, "reason": None, **read_parts}


#: 겹쳤다고 보는 낱말 상자 겹침(pt · 가로 · 세로 모두 넘을 때 · 2.11.0 T5d) — 한글이 쪽 끝 긴 표를 다음 쪽으로 밀며 뒤 글을 앞 쪽에 겹쳐 찍었다
#: (11-14 09위 17쪽 28쌍 · 빈 문단을 넣은 판 0 · 다른 한글 PDF 63개 1,355쪽 0).
OVERLAP_PT = 3.0


def _overlap_pairs(words: list[dict[str, Any]]) -> int:
    """쪽 낱말 상자(`extract_words`) 중 가로 · 세로 모두 `OVERLAP_PT` 넘게 겹친 쌍 수 — top 순으로 쓸어 앞 낱말 아래 끝에 닿기 전까지만 견준다.
    top 차가 3pt 안인 두 글줄은 pdfplumber 가 한 줄 낱말로 섞어 못 센다(근사)."""
    boxes = sorted(words, key=lambda word: float(word["top"]))
    pairs = 0
    for index, a in enumerate(boxes):
        for b in boxes[index + 1:]:
            if float(b["top"]) >= float(a["bottom"]) - OVERLAP_PT:
                break
            wide = min(float(a["x1"]), float(b["x1"])) - max(float(a["x0"]), float(b["x0"]))
            tall = min(float(a["bottom"]), float(b["bottom"])) - float(b["top"])
            pairs += wide > OVERLAP_PT and tall > OVERLAP_PT
    return pairs


#: 좁은 표 칸에서 갈린 「(담당자」 조각 — 온전한 표시를 지운 뒤, 같은 줄에 닫는 괄호가 없는 것만(옆 칸 글이 같은 줄에 붙어도 ·
#: 「(담당자 확인 후 결정)」 같은 괄호 글은 아님 · 같은 칸을 두 번 세지 않는다 · 11-13 독립 검토).
_DANGLING_HUMAN_RE = re.compile(r"[(（\[]\s*담당자(?![^\n)）\]]*[)）\]])")


def _pdf_unwritten(text: str) -> int:
    """PDF 쪽 글의 미작성 칸 — `unwritten_count`(한 규칙) + 칸 줄바꿈으로 갈린 「(담당자」 조각."""
    from app.services.plan_form_service import HUMAN_INPUT_RE

    return unwritten_count(text) + len(_DANGLING_HUMAN_RE.findall(HUMAN_INPUT_RE.sub(" ", text)))


def _page_unwritten(text: str, cells: str, outside: str | None) -> int:
    """한 쪽의 미작성 칸 — 표 밖 글 + 칸마다(`unwritten_count` · 칸 안 줄바꿈을 빈칸 없이 이은 글)와 쪽 글 셈 중 큰 쪽(2.11.0 T5b).
    쪽 글에서는 옆 칸과 섞여 「(담당 (담당」으로 갈린 칸을 놓쳤다(11-14 02위 0 · 칸에는 49). 큰 쪽을 쓰는 까닭 — 표를 덜 잡았거나 칸 안
    줄바꿈 뒤 한글이 붙은 칸(「확인 필요⏎교육」)에서 지금보다 적게 세지 않게. 표 밖 글이 없는 옛 결과(`outside` None)는 쪽 글만."""
    page = _pdf_unwritten(text)
    if outside is None:
        return page
    return max(page, _pdf_unwritten(outside) + sum(unwritten_count(cell) for cell in cells.splitlines()))


#: 쪽 번호 줄(「- 3 -」 · 「3」 · 「3 / 40」) · 표 제목 줄(앱 꼴 「< 제목 >」 — 꺾쇠 뒤 빈칸 · 「<참고>」처럼 붙여 쓴 글은 아님 · 2.11.0 T5e).
_PAGE_NO_RE = re.compile(r"^[\s\-–—]*\d{1,3}(?:\s*/\s*\d{1,3})?[\s\-–—]*$")
_CAPTION_RE = re.compile(r"^\s*[<〈＜]\s")


def _orphan_titles(pages: list[str]) -> list[int]:
    """다음 쪽이 있는 쪽 중 마지막 두 줄(빈 줄 · 쪽 번호 줄 뺌)에 표 제목 줄이 든 쪽(1부터) — 한글이 긴 표 제목 · 칸 이름 줄만 쪽 끝에 남긴 꼴
    (`plan_hwpx_service._data_table` 의 ponytail 한계 · 11-14 01 · 07 · 08위). 근사 — 두 줄로 갈린 긴 제목 · 꼬리말 글이 찍힌 쪽은 놓친다."""
    out = []
    for number, text in enumerate(pages[:-1], start=1):
        tail = [line for line in text.splitlines() if line.strip() and not _PAGE_NO_RE.match(line)][-2:]
        if any(_CAPTION_RE.match(line) for line in tail):
            out.append(number)
    return out


def _find_page(texts: list[str], needle: str, start: int) -> int | None:
    return next((i for i in range(start, len(texts)) if needle and needle in texts[i]), None)


def _heading_page(lines: list[list[str]], needle: str, start: int) -> int | None:
    """머리 글(견주기 꼴)로 시작하는 줄이 처음 나오는 쪽(start 쪽부터) — 뒤가 쪽 번호뿐인 줄(사람이 넣은 목차 「Ⅰ. 제안개요 4」)은 뺀다."""
    for index in range(start, len(lines)):
        for line in lines[index]:
            if needle and line.startswith(needle) and not line[len(needle):].isdigit():
                return index
    return None


def _pages_text(numbers: list[int]) -> str:
    return " · ".join(f"{n}쪽" for n in numbers[:8]) + (f" 외 {len(numbers) - 8}곳" if len(numbers) > 8 else "")


def eval_pages(view: dict[str, Any], pages: list[str]) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """조견표 행마다 인용한 목차의 실제 PDF 쪽(표지 = 1쪽 · submit7 · D9) → (행 [{name, mapped, pages}], 검사 줄).
    조견표 머리가 있는 쪽(못 찾으면 첫 쪽)부터 대항목 · 소항목 머리 글(번호 포함)로 시작하는 줄이 처음 나오는 쪽을 차례로 찾는다(앞 머리보다
    뒤에서만 · 사람이 넣은 목차 줄 「Ⅰ. 제안개요 4」 뺌 — 조견표 칸 글 · 목차 쪽에 걸리지 않게) · 소항목 머리를 못 찾으면 그 대항목 쪽
    (「(대항목 쪽)」 · 적은 쪽과 견주지 않음). 조견표 칸에
    사람이 「Ⅲ-1(5쪽)」처럼 적었으면 실제 쪽과 견준다(근사 — 칸 안에서 줄이 갈린 「Ⅰ-2(4 … 쪽)」은 못 읽는다 · 머리 글을 사람이 바꿨으면 「찾지 못함」 ·
    조견표가 없는 초안은 없음)."""
    table = next((t for t in view.get("tables") or [] if t.get("key") == bid.EVAL_TABLE_KEY), None)
    form = view.get("form") or {}
    if not table or not form.get("sections"):
        return [], []
    texts = [_compact(text) for text in pages]
    lines = [[_compact(line) for line in text.splitlines()] for text in pages]
    # 목차 쪽(첫 두 줄 — 빈 줄 뺌 — 이 「목차」 · 「< 목 차 >」 · 「차례」)은 조견표 머리 · 목차 머리 찾기에서 뺀다 — 쪽 번호 없는 목차(앱 제출용 목차 ·
    # 2.11.0 D2)는 머리 줄이 본문과 같아 조견표 행이 모두 목차 쪽으로 대어졌다(11-14 완성본 01 · 03 · 04 · 07 · 08위). 적은 쪽 대조는 원래 쪽 글을 읽는다.
    toc = {i for i, page in enumerate(lines) if any(line.strip("<>〈〉＜＞") in _TOC_TITLES for line in [x for x in page if x][:2])}
    texts = ["" if i in toc else text for i, text in enumerate(texts)]
    lines = [[] if i in toc else page for i, page in enumerate(lines)]
    start = _find_page(texts, _compact(bid.EVAL_TITLE), 0) or 0
    found: dict[str, int] = {}
    guessed: set[str] = set()  # 소항목 머리를 못 찾아 대항목 쪽으로 둔 번호 — 적은 쪽과 견주지 않는다(T8 검토)
    known: set[str] = set()
    cursor, first = start, None
    for section in form.get("sections") or []:
        if not section.get("no") or not section.get("key"):  # 11-03 옛 초안 목차에는 번호 칸이 없다(`_unit_keys` 와 같은 막음 · 11-13 독립 검토 — 500)
            continue
        major = str(section.get("no") or "")
        known.add(major)
        hit = _heading_page(lines, _compact(plan_export_service._heading(section.get("title"))), cursor)
        if hit is not None:
            cursor, first = hit, hit if first is None else first
            found[major] = hit + 1
        for item in section.get("items") or []:
            number = bid.unit_number(form, item["key"])
            known.add(number)
            spot = _heading_page(lines, _compact(plan_export_service._heading(item.get("title"))), cursor)
            if spot is not None:
                cursor = spot
                found[number] = spot + 1
            elif major in found:
                found[number] = found[major]
                guessed.add(number)
    rows = []
    for row in table.get("rows") or []:
        numbers = [token.strip() for token in str(row[3] if len(row) > 3 else "").split(",") if token.strip() in known]
        if numbers:
            rows.append({"name": str(row[1]), "mapped": ", ".join(numbers),
                         "pages": " · ".join(f"{no} {found[no]}쪽" + ("(대항목 쪽)" if no in guessed else "") if no in found else f"{no} 찾지 못함"
                                             for no in numbers)})
    end = first if first is not None else start
    written = [(re.sub(r"\s+", "", m.group(1)), int(m.group(2))) for text in pages[start:end + 1] for m in _WRITTEN_PAGE_RE.finditer(text)]
    off = [f"{no} — 적은 쪽 {page} · 실제 {found[no]}쪽" for no, page in dict.fromkeys(written)
           if no in found and no not in guessed and found[no] != page]
    out = []
    if off:
        out.append(_finding("PDF_EVAL_PAGE", "MAJOR", "조견표에 적은 쪽 번호가 실제 PDF 쪽과 다름",
                            " · ".join(off[:8]) + (" 외" if len(off) > 8 else "") + " (표지 = 1쪽)", section=bid.EVAL_TITLE, count=len(off),
                            location=f"PDF {start + 1}쪽 · {bid.EVAL_TITLE}"))
    if rows:
        out.append(_finding("PDF_EVAL_PAGES", "INFO", "조견표 목차의 실제 PDF 쪽(표지 = 1쪽)", " · ".join(f"「{r['name']}」 {r['pages']}" for r in rows),
                            section=bid.EVAL_TITLE, count=len(rows), location=f"PDF · {bid.EVAL_TITLE}"))
    return rows, out


def _a4(size: tuple[float, float], landscape: bool) -> bool:
    """A4 세로(±2pt) — 가로 A4 는 원문이 가로로 쓰라고 할 때만."""
    width, height = size
    portrait = abs(width - A4_PT[0]) <= A4_TOLERANCE and abs(height - A4_PT[1]) <= A4_TOLERANCE
    flipped = abs(width - A4_PT[1]) <= A4_TOLERANCE and abs(height - A4_PT[0]) <= A4_TOLERANCE
    return portrait or (landscape and flipped)


def _notice_keys(url: str) -> tuple[str, ...]:
    """나라장터 공고 주소의 공고번호 · 차수(`bidPbancNo` · `bidPbancOrd`) — XML 이스케이프(`&amp;`)가 남은 링크 주소도(T8 검토)."""
    import html
    from urllib.parse import parse_qs, urlsplit

    query = parse_qs(html.unescape(urlsplit(url).query))
    return tuple(query.get(key, [""])[0] for key in ("bidPbancNo", "bidPbancOrd"))


def pdf_findings(pdf: dict[str, Any], view: dict[str, Any], *, identity: list[tuple[str, str]] | None,
                 expected_blanks: int | None = None) -> list[dict[str, Any]]:
    """`read_pdf` 결과 → 검사 줄(심각도 순) — 쪽수(원문 상한) · A4(가로는 원문이 가로일 때만) · 미작성(`unwritten_count` 한 규칙 · 표 칸 단위
    `_page_unwritten`) · 그 수가 앱 초안 빈칸(`expected_blanks`)보다 적음(참고) · 평가본 공고면 식별 낱말(본문 + 문서 정보 · 원본 · 사본을 함께
    내는 공고는 중요까지) · 표지 나라장터 링크(공고번호 · 차수) · 예산 배분안 산수(`plan_validation.budget_breaks` — 표 제목 줄 ~ 합계 줄) ·
    조견표 목차의 실제 쪽(`eval_pages`) · 글자 겹침(`overlaps`) · 쪽 끝에 남은 표 제목(`_orphan_titles`). 글을 못 읽으면 「검사 못 함」 한 줄 +
    쪽수 · 크기만. 새 칸(cells · outside · overlaps)이 없는 옛 결과는 그 검사를 지금처럼 건너뛴다."""
    fmt = view.get("format") or {}
    pages = list(pdf.get("pages") or [])
    found: list[dict[str, Any]] = []
    if not pdf.get("ok"):
        found.append(_finding("PDF_UNREADABLE", "BLOCKER", "PDF 를 읽지 못해 검사하지 못함 — 통과가 아님", str(pdf.get("reason") or "")))
    limit = fmt.get("page_limit")
    note = f" — 원문: 「{_snip(fmt.get('page_note'))}」" if fmt.get("page_note") else ""
    total = int(pdf.get("total") or len(pages))
    partial = f" · 앞 {len(pages)}쪽만 검사했습니다(쪽 · 시간 상한)" if pdf.get("partial") else ""
    if total and limit and total > int(limit):
        found.append(_finding("PDF_PAGES_OVER", "BLOCKER", "PDF 쪽수가 원문 상한을 넘음", f"PDF {total}쪽 · 원문 상한 {limit}쪽{note}{partial}"))
    elif total:
        found.append(_finding("PDF_PAGES", "INFO", f"PDF {total}쪽",
                              (f"원문 상한 {limit}쪽{note}" if limit else "원문 쪽수 상한을 읽지 못했습니다 — 원문을 직접 확인하세요") + partial))
    sizes = list(pdf.get("sizes") or [])
    odd = [n for n, size in enumerate(sizes, start=1) if not _a4(size, bool(fmt.get("landscape")))]
    if odd:
        width, height = sizes[odd[0] - 1]
        found.append(_finding("PDF_NOT_A4", "MAJOR", "A4 가 아닌 쪽이 있음" if fmt.get("landscape") else "A4 세로가 아닌 쪽이 있음",
                              f"{_pages_text(odd)} — {width:.0f} × {height:.0f}pt(A4 = 595 × 842pt)", count=len(odd), location=f"PDF {odd[0]}쪽"))
    if not pdf.get("ok"):
        return _sorted(found)
    cells = [*(pdf.get("cells") or []), *[""] * len(pages)]
    outside = list(pdf.get("outside") or [])  # 비면(옛 결과 · 시험 가짜) 쪽 글만 센다
    blanks = [(n, count) for n, text in enumerate(pages, start=1)
              if (count := _page_unwritten(text, cells[n - 1], outside[n - 1] if n <= len(outside) else None))]
    written = sum(c for _n, c in blanks)
    if blanks:
        found.append(_finding("PDF_UNWRITTEN", "BLOCKER", "PDF 에 미작성 칸 「(담당자 입력)」 등이 남음",
                              f"{_pages_text([n for n, _count in blanks])} — 제출 전에 채우거나 지우세요", count=written,
                              location=f"PDF {blanks[0][0]}쪽"))
    # 앞쪽만 읽었으면 당연히 적다 — 견주지 않는다(2.11.0 T5c · 채운 칸과 못 읽은 칸을 앱이 가르지 못해 참고만)
    if expected_blanks and not pdf.get("partial") and written < expected_blanks:
        found.append(_finding("PDF_BLANKS_FEWER", "INFO", "PDF 에서 읽은 미작성 칸이 앱 초안보다 적음",
                              f"앱 초안 {expected_blanks}칸 · PDF {written}칸 — 그사이 채운 칸이 {expected_blanks - written}개보다 적다면 "
                              "PDF 에서 못 읽은 칸이 있습니다(같은 초안으로 만든 PDF 일 때만 견줄 수 있음)", count=expected_blanks - written))
    if fmt.get("blind") and identity:
        pairs = [*((f"{n}쪽", f"{text}\n{cells[n - 1]}") for n, text in enumerate(pages, start=1)), ("문서 정보", str(pdf.get("info") or ""))]
        for finding in identity_findings(pairs, identity):
            if not fmt.get("blind_only"):  # 회사명 포함본도 내는 공고 — 올린 파일이 그 판일 수 있다
                finding = {**finding, "severity": "MAJOR", "title": f"평가본 파일이면 — {finding['title']}"}
            found.append(finding)
    want = plan_export_service.official_link(view.get("notice_url"))
    g2b = [url for url in pdf.get("links") or [] if "g2b.go.kr" in url]
    if want and g2b:
        keys = _notice_keys(want)
        cut = [url for url in g2b if (_notice_keys(url) != keys if any(keys) else url.rstrip("/") != want.rstrip("/"))]
        if cut:
            found.append(_finding("PDF_LINK_CUT", "MAJOR", "표지 「공고 원문」 링크에 공고번호 · 차수가 없거나 다름",
                                  f"PDF 링크 「{_snip(cut[0])}」 · 공고 「{_snip(want)}」 — 한글이 주소를 자른 판일 수 있습니다", count=len(cut)))
    if any(t.get("key") == bid.BUDGET_TABLE["key"] for t in view.get("tables") or []):
        lines = [(n, line) for n, text in enumerate(pages, start=1) for line in text.splitlines()]
        budget = budget_lines([line for _n, line in lines])
        if budget is None:
            found.append(_finding("PDF_BUDGET_UNREAD", "INFO", "PDF 에서 예산 배분안을 찾지 못해 산수 검산을 못 함",
                                  f"표 제목 「{bid.BUDGET_TABLE['title']}」 줄을 찾지 못했습니다"))
        else:
            terms = view.get("terms") or bid.draft_terms(view)
            if breaks := plan_validation.budget_breaks(budget[1], terms.get("budget_won")):
                found.append(_finding("BUDGET_MATH", "MAJOR", "예산 배분안 산수가 맞지 않음(PDF)", " · ".join(breaks[:3]) + (" 외" if len(breaks) > 3 else ""),
                                      count=len(breaks), location=f"PDF {lines[budget[0]][0]}쪽 · 표 「{bid.BUDGET_TABLE['title']}」"))
    found += eval_pages(view, pages)[1]
    if overlapped := [(n, k) for n, k in enumerate(pdf.get("overlaps") or [], start=1) if k]:
        found.append(_finding("PDF_OVERLAP", "MAJOR", "글자가 겹친 쪽이 있음",
                              f"{_pages_text([n for n, _k in overlapped])} — 겹친 낱말 {sum(k for _n, k in overlapped)}쌍 · "
                              "쪽 끝 긴 표 뒤 글이 앞 쪽으로 흘러 겹친 꼴일 수 있습니다", count=len(overlapped), location=f"PDF {overlapped[0][0]}쪽"))
    if orphans := _orphan_titles(pages):
        found.append(_finding("PDF_TABLE_ORPHAN", "MINOR", "쪽 끝에 표 제목 · 칸 이름 줄만 남음(근사)",
                              f"{_pages_text(orphans)} — 표 내용은 다음 쪽부터", count=len(orphans), location=f"PDF {orphans[0]}쪽"))
    if pages:  # 표 잘림 · 칸 넘침은 글로 알 수 없다(submit5 — 사람이 쪽 그림으로)
        found.append(_finding("PDF_TABLE_LOOK", "INFO", "표 잘림 · 칸 넘침은 앱이 보지 못함 — 쪽 그림으로 확인",
                              "PDF 화면에서 표가 쪽 끝에서 잘리거나 칸 글이 넘친 곳이 없는지 담당자가 직접 봅니다"
                              "(글자 겹침 · 쪽 끝에 남은 표 제목은 앱이 근사로 봅니다)"))
    return _sorted(found)


def budget_lines(lines: list[str]) -> tuple[int, list[Any]] | None:
    """글 줄에서 예산 배분안 행 — (찾은 줄 번호, 그 뒤 ~ 합계 줄 행 · 「a | b」 줄은 칸 목록). 표 머리줄(과업 · 항목 · 산출 · 금액)을 먼저 찾고
    (워드 추출은 표 줄을 본문 뒤에 몰아 붙여 제목 줄과 떨어진다) 없으면 표 제목 줄. 둘 다 없으면 None — 한글 PDF 검사 · 제출 전 점검 업로드가
    `plan_validation.budget_breaks` 에 넘긴다(2.10.0 T8 · budget2)."""
    flat = [_compact(line.replace("|", "")) for line in lines]
    at = next((i for key in (_compact("".join(bid.BUDGET_TABLE["columns"])), _compact(bid.BUDGET_TABLE["title"]))
               for i, line in enumerate(flat) if key in line), None)
    if at is None:
        return None
    rows: list[Any] = []
    for line in lines[at + 1:at + 1 + PDF_BUDGET_LINES]:
        row: Any = [cell.strip() for cell in line.split("|")] if "|" in line else line
        rows.append(row)
        if plan_validation.is_budget_total(row):
            break
    return at, rows


def check_pdf(payload: bytes, view: dict[str, Any], *, identity: list[tuple[str, str]] | None, draft_hash: str) -> dict[str, Any]:
    """한글에서 저장한 PDF 검사(`POST …/plan-draft/check-pdf`) — 상태(검사 못 함 · 고칠 곳 있음(차단 · 중요) · 통과) · 쪽수 · 검사 줄.
    올린 파일 이름 · 식별 낱말 값은 싣지 않는다(D7). 품질 게이트 판정 · 승인과 따로다(D10)."""
    fmt = view.get("format") or {}
    limit = fmt.get("page_limit")
    # 원문 상한을 넘는지는 전체 쪽수로 아니, 글은 상한 + 5쪽(작으면 PDF_READ_PAGES)까지만 읽는다
    read = read_pdf(payload, max_pages=min(PDF_READ_PAGES, int(limit) + 5) if limit else PDF_READ_PAGES)
    # 앱 초안 빈칸(`submit_variant` 판) — 평가본 · 회사명 판을 함께 받는 공고는 어느 판을 올렸는지 몰라 견주지 않는다(2.11.0 T5c)
    expected = None if fmt.get("blind") and not fmt.get("blind_only") else (view.get("quality") or {}).get("submit_blanks")
    findings = pdf_findings(read, view, identity=identity, expected_blanks=expected)
    state = "unreadable" if not read["ok"] else "issues" if any(f["severity"] in ("BLOCKER", "MAJOR") for f in findings) else "ok"
    return {"at": datetime.now(timezone.utc).isoformat(), "draft_hash": draft_hash, "state": state, "state_label": PDF_STATES[state],
            "pages": read.get("total") or len(read["pages"]) or None, "page_limit": limit,
            "counts": {severity: sum(1 for f in findings if f["severity"] == severity) for severity in SEVERITIES}, "findings": findings}


# ---------------------------------------------------------------------------
# 검증 보고서 엑셀(2.10.0 T8 · submit4 — JSON 보고서와 같은 재료 · 대표 · 담당자가 열어 보는 판)
# ---------------------------------------------------------------------------


def quality_workbook(view: dict[str, Any]) -> bytes:
    """`GET …/quality-report?format=xlsx` — 시트 셋. 「검사 항목」(수정 위치 · 검사 항목 · 근거 · 심각도 · 상태(갈래) · 남은 조치 + 마지막 PDF 검사 줄 +
    맨 아래 제출 준비 상태) · 「담당자 확인 사항」(반영 위치 · 항목 · 확인할 값 · 필요한 자료) · 「제출 서류」(입찰공고문 서류 · 제출 파일 구분 · 요건 ·
    유효기간 · 입찰 마감 · 참가자격등록 마감). 새 판정 없이 `read_view` 값을 옮긴다 · 「=」로 시작하는 칸은 글(수식 주입 막음 · `opportunity_workbook._append`)."""
    import io

    from openpyxl import Workbook

    from app.services import opportunity_workbook as kit

    quality = view.get("quality") or {}
    book = Workbook()
    checks = book.active
    checks.title = "검사 항목"
    kit._write_header(checks, ["수정 위치", "검사 항목", "근거", "심각도", "상태", "남은 조치"])
    pdf = quality.get("pdf_check") or {}
    for head, finding in [*(("", f) for f in quality.get("findings") or []), *(("PDF 검사 › ", f) for f in pdf.get("findings") or [])]:
        kit._append(checks, [head + str(finding.get("location") or finding.get("section") or ""), finding.get("title") or "",
                             finding.get("detail") or "", SEVERITY_LABELS.get(str(finding.get("severity")), ""),
                             AXIS_LABELS.get(str(finding.get("axis")), ""), finding.get("action") or ""])
    counts = " · ".join(f"{SEVERITY_LABELS[s]} {(quality.get('counts') or {}).get(s, 0)}" for s in SEVERITIES)
    approval = quality.get("approval") or {}
    kit._append(checks, ["제출 준비 상태", quality.get("status_label") or "", counts,
                         f"PDF 검사 {pdf.get('state_label')}" if pdf else "PDF 검사 안 함", "",
                         f"{approval.get('by_name') or approval.get('by')} 승인 {_when(approval.get('at'))}" if approval else "승인 전"])
    inputs = book.create_sheet("담당자 확인 사항")
    kit._write_header(inputs, ["반영 위치", "항목", "확인할 값", "필요한 자료"])
    for blank in view.get("blanks") or []:
        kit._append(inputs, [blank.get("section") or "", blank.get("field") or "", blank.get("why") or "", blank.get("proof") or ""])
    papers = book.create_sheet("제출 서류")
    # 참가자격등록 마감 칸(나라장터 `bidQlfctRgstDt` · 옛 초안은 빈칸 — 실제 마감은 더 이른 쪽 · 43차 결정 1)
    kit._write_header(papers, ["번호", "서류", "제출 파일 구분", "요건(원문)", "유효기간", "입찰 마감", "참가자격등록 마감"])
    found = view.get("submission_papers") or {}

    def kst(value: Any) -> str:
        try:
            return datetime.fromisoformat(str(value)).astimezone(plan_export_service.KST).strftime("%Y-%m-%d %H:%M") if value else ""
        except ValueError:
            return str(value)

    terms = view.get("terms") or {}
    due, qualify = kst(terms.get("deadline")), kst(terms.get("qualification_deadline"))
    for row in found.get("rows") or []:
        kit._append(papers, [row.get("no"), row.get("name"), row.get("file"), row.get("need"), row.get("valid"), due, qualify])
    for note in found.get("notes") or []:
        kit._append(papers, ["※", "제출 방법", "", note.get("text"), "", due, qualify])
    if bid.papers_unread(view):
        kit._append(papers, ["", bid.PAPERS_UNREAD_NOTE])  # 새 초안인데 0건(2.11.0 T6b)
    elif not found.get("rows") and not found.get("notes"):
        kit._append(papers, ["", "공고문 제출서류를 읽지 못했습니다 — 초안을 다시 쓰면 입찰공고문에서 읽습니다(옛 초안 · 입찰공고문을 받지 못한 공고)"])
    for sheet in book.worksheets:
        kit._autosize(sheet)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()
