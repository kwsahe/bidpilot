"""AI Auditor 성능 측정 — 정답을 아는 합성 RFP에 결함을 주입해 탐지 여부를 잰다.

사용:
    python scripts/evaluate_auditor.py
    python scripts/evaluate_auditor.py --json out.json
    python scripts/evaluate_auditor.py --llm      # LLM 2차 판단까지 포함(키 필요, 비결정적)
    python scripts/evaluate_auditor.py --print-draft                            # 결함 초안을 화면에
    python scripts/evaluate_auditor.py --print-draft docs/demo_defective_draft.txt  # 파일로 (UTF-8)

`--print-draft` 는 **시연 7단계에 붙여넣는 결함 초안의 단일 출처**다 (ISSUE-136 · 18차 §4-B).
리허설 캡처(`capture_rehearsal.mjs`)와 체크리스트가 모두 이것을 부른다 — 손으로 만든 메모장
텍스트가 측정한 것과 달라지는 일이 없게. 측정은 하지 않고 텍스트만 낸다.

방식 (docs/auditor_spec.md 5장, CLAUDE.md 17장)
1. synthetic-rfp-0001의 필수 요구사항 전부를 반영한 **정상 초안**을 만든다.
2. 의도적으로 3가지 결함을 주입한다.
   D1. 만족도 조사 요구사항(REQ-015) 대응 문장 삭제
   D2. 교육 횟수 수치 변경 (12회 -> 10회)
   D3. 근거 없는 주장 삽입 ("만족도 95% 이상을 보장합니다")
3. Auditor를 돌려 각 결함의 탐지 여부, 오탐 수, Coverage를 출력한다.

모든 수치는 실행 시점에 계산한다. 하드코딩된 탐지율은 없다.
기본값은 규칙 계층만 사용해 **같은 입력이면 항상 같은 결과**가 나오게 한다.
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.schemas.audit import AuditFinding, AuditRun  # noqa: E402
from app.services import auditor_service, rfp_parser  # noqa: E402

PROCUREMENT_ID = "synthetic-rfp-0001"

# 요구사항별 정상 초안 문장. 담당자가 쓸 법한 표현으로 작성했다(원문 복사가 아니다).
BASELINE_SENTENCES: list[tuple[str, str]] = [
    ("REQ-001", "본 사업은 2026년 10월 1일부터 2026년 12월 15일까지 모든 과업을 완료하는 일정으로 수행한다."),
    ("REQ-002", "교육은 총 12회 운영하며 회차당 교육시간은 3시간으로 편성한다."),
    ("REQ-003", "전체 교육대상은 누적 240명 이상으로 계획하고 회차별 명단과 실제 참석인원을 구분해 관리한다."),
    ("REQ-004", "총 12회 중 10회는 광주광역시 내 지정 교육장에서 대면으로 운영하고 2회는 실시간 온라인 방식으로 운영한다."),
    ("REQ-005", "교육과정은 생성형 AI와 LLM 기본 이해, 프롬프트 작성, 데이터·보안 유의사항, 문서작성 및 업무자동화 실습을 모두 포함해 구성한다."),
    ("REQ-006", "첫 교육일 10일 전까지 세부 커리큘럼과 교안, 실습파일을 제출해 발주기관의 승인을 받는다."),
    ("REQ-007", "모든 실습은 가상 또는 비식별 데이터로 진행하며, 교육생이 개인정보와 기관 비공개자료를 외부 생성형 AI 서비스에 입력하지 않도록 사전에 안내한다."),
    ("REQ-008", "회차별 참석 예정 인원이 25명 이상인 회차에는 주강사 외에 실습 보조인력 2명을 배치한다."),
    ("REQ-009", "당사는 사업자등록을 완료한 사업자이며 공공계약 관련 법령상 입찰참가 제한을 받지 않는다."),
    ("REQ-010", "공동수급 없이 단독으로 수행하며 핵심 교육과업은 발주기관의 사전 서면승인 없이 재위탁하지 않는다."),
    ("REQ-011", "총괄책임자는 관련 분야 경력 3년 이상이며 최근 3년 이내 공공기관 AI 교육 유사사업 3건 이상 수행 경험을 보유한다."),
    ("REQ-012", "일정과 교육생, 산출물을 관리하는 전담 프로젝트 관리자 1명을 지정하며 사업기간 중 발주기관 승인 없이 교체하지 않는다."),
    ("REQ-013", "경력과 수행실적은 계약서, 실적증명서, 재직증명서 등 객관적 증빙으로 확인할 수 있도록 제출한다."),
    ("REQ-014", "매 회차 교육생 서명부와 전자출결 기록을 작성하고 결석·중도이탈 인원을 별도로 표시한다."),
    ("REQ-015", "매 회차 종료 직후 만족도 조사를 실시하고 전체 참석자 대비 응답률 80% 이상을 확보한다."),
    ("REQ-016", "교육이 진행되는 주에는 매주 금요일 17시까지 진행현황과 이슈, 다음 주 계획을 포함한 주간보고를 제출한다."),
    ("REQ-017", "최종 교육일로부터 7일 이내에 전체 운영실적과 출결, 만족도, 개선의견을 포함한 최종결과보고서를 제출한다."),
    ("REQ-018", "편집 가능한 원본파일과 PDF 파일을 함께 제출하고 파일명에 산출물명과 제출일자를 표시한다."),
    ("REQ-019", "사업 종료 후 30일 이내에 교육생 명단과 연락처, 출결 원본 등 개인정보를 파기하고 파기확인서를 제출한다."),
    ("REQ-020", "외부 AI 또는 클라우드 서비스를 사용할 경우 개인정보와 기관 비공개자료를 전송하지 않으며 사용 서비스와 데이터 처리방식을 사전에 설명한다."),
    ("REQ-021", "제안서에는 사업수행계획, 투입인력표, 유사사업 실적증명, 보안·개인정보 보호계획, 가격제안서를 모두 포함하여 제출한다."),
    ("REQ-022", "필수 요구사항의 반영 여부는 제안서와 RFP 원문을 대조해 확인하며 누락·수치 불일치·근거 없는 주장은 보완대상으로 관리한다."),
    ("REQ-023", "AI 분석결과는 참고자료로만 활용하며 자격판정과 Evidence 채택, 제안서 확정 및 제출 여부는 담당자가 최종 승인한다."),
]

# 주입할 결함 정의
DEFECT_DELETED_REQ = "REQ-015"
DEFECT_NUMBER_REQ = "REQ-002"
DEFECT_NUMBER_FROM = "12회"
DEFECT_NUMBER_TO = "10회"
DEFECT_CLAIM_SENTENCE = "당사는 교육 만족도 95% 이상을 보장합니다."


class InjectionError(RuntimeError):
    """결함 주입에 실패했다 (초안 문장이 바뀐 경우). 측정을 진행하지 않는다."""


@dataclass
class Defect:
    code: str
    description: str
    expected_finding_type: str
    matched: list[AuditFinding] = field(default_factory=list)

    @property
    def detected(self) -> bool:
        return bool(self.matched)


def build_draft(*, inject: bool) -> str:
    """정상 초안(또는 결함 3건을 주입한 초안) 텍스트."""
    sentences: list[str] = []
    replaced_number = False
    for requirement_id, sentence in BASELINE_SENTENCES:
        if inject and requirement_id == DEFECT_DELETED_REQ:
            continue  # D1: 만족도 조사 대응 문장 삭제
        if inject and requirement_id == DEFECT_NUMBER_REQ:
            if DEFECT_NUMBER_FROM not in sentence:
                raise InjectionError(f"{DEFECT_NUMBER_REQ} 문장에 {DEFECT_NUMBER_FROM}이(가) 없습니다")
            sentence = sentence.replace(DEFECT_NUMBER_FROM, DEFECT_NUMBER_TO, 1)  # D2
            replaced_number = True
        sentences.append(sentence)

    if inject:
        if not replaced_number:
            raise InjectionError(f"{DEFECT_NUMBER_REQ} 문장을 찾지 못했습니다")
        sentences.append(DEFECT_CLAIM_SENTENCE)  # D3
    return "\n".join(sentences)


def classify(run: AuditRun) -> list[Defect]:
    """주입한 결함별로 대응하는 finding을 찾는다."""
    defects = [
        Defect(
            code="D1",
            description=f"{DEFECT_DELETED_REQ} 만족도 조사 대응 문장 삭제",
            expected_finding_type="missing_requirement",
        ),
        Defect(
            code="D2",
            description=f"교육 횟수 수치 변경 ({DEFECT_NUMBER_FROM} -> {DEFECT_NUMBER_TO})",
            expected_finding_type="number_mismatch",
        ),
        Defect(
            code="D3",
            description="근거 없는 주장 삽입 (만족도 95% 보장)",
            expected_finding_type="unsupported_claim",
        ),
    ]
    by_code = {defect.code: defect for defect in defects}

    for finding in run.findings:
        if (
            finding.finding_type == "missing_requirement"
            and finding.requirement_id == DEFECT_DELETED_REQ
            and finding.severity == "high"
        ):
            by_code["D1"].matched.append(finding)
        elif finding.finding_type == "number_mismatch" and DEFECT_NUMBER_FROM in (
            finding.recommendation or ""
        ):
            by_code["D2"].matched.append(finding)
        elif finding.finding_type == "unsupported_claim" and "95%" in (
            finding.proposal_text or ""
        ):
            by_code["D3"].matched.append(finding)
    return defects


def other_findings(run: AuditRun, defects: list[Defect]) -> list[AuditFinding]:
    attributed = {finding.id for defect in defects for finding in defect.matched}
    return [finding for finding in run.findings if finding.id not in attributed]


def _check_requirement_ids() -> set[str]:
    """원래 status가 check인 요구사항 — 사람 확인용 finding은 설계상 정상이다."""
    parsed = rfp_parser.load_generated(PROCUREMENT_ID)
    return {req.requirement_id for req in parsed.requirements if req.status == "check"}


def _display_width(text: str) -> int:
    """한글·전각 문자를 2칸으로 세어 표 정렬을 맞춘다."""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _display_width(text))


def _page(finding: AuditFinding) -> str:
    return f"p.{finding.source_page}" if finding.source_page else "페이지 없음"


def _cut(text: str | None, limit: int = 72) -> str:
    if not text:
        return "-"
    compact = " ".join(text.split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


def print_run_summary(title: str, run: AuditRun) -> None:
    coverage = run.coverage
    rate = coverage.covered / coverage.total * 100 if coverage.total else 0.0
    print(f"\n[{title}]")
    print(f"  초안 문장 수      : {run.sentence_count}")
    print(f"  필수 요구사항     : {coverage.total}건")
    print(f"  Coverage          : {coverage.covered} / {coverage.total} ({rate:.1f}%)")
    print(f"  부분대응/미반영   : {coverage.partial} / {coverage.missing}")
    if coverage.missing_requirement_ids:
        print(f"  미반영 요구사항   : {', '.join(coverage.missing_requirement_ids)}")
    print(f"  발견 항목         : {len(run.findings)}건 {run.counts or '{}'}")
    print(f"  LLM 2차 판단      : {'사용' if run.llm_used else '미사용(규칙만)'}")


def print_defect_table(defects: list[Defect]) -> None:
    print("\n[주입 결함 탐지 결과]")
    columns = (4, 42, 6, 30, 10, 14)
    labels = ("ID", "주입한 결함", "탐지", "finding", "severity", "탐지계층")
    header = "  " + "".join(_pad(label, width) for label, width in zip(labels, columns))
    print(header)
    print("  " + "-" * (_display_width(header) - 2))
    for defect in defects:
        if defect.detected:
            first = defect.matched[0]
            cells = (
                defect.code,
                defect.description,
                "O",
                f"{first.id} {first.finding_type}",
                first.severity,
                first.detected_by,
            )
        else:
            cells = (
                defect.code,
                defect.description,
                "X",
                f"(기대: {defect.expected_finding_type})",
                "-",
                "-",
            )
        print("  " + "".join(_pad(cell, width) for cell, width in zip(cells, columns)))
        for finding in defect.matched:
            print(f"        - RFP {_page(finding)} / {_cut(finding.recommendation)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="AI Auditor 결함 탐지 성능 측정")
    parser.add_argument("--json", type=Path, default=None, help="측정 결과 JSON 저장 경로")
    parser.add_argument(
        "--llm",
        action="store_true",
        help="LLM 2차 판단 포함 (기본은 규칙만 사용해 결정론적으로 측정)",
    )
    parser.add_argument(
        "--print-draft",
        nargs="?",
        const="-",
        metavar="PATH",
        help="측정하지 않고 결함 초안(build_draft(inject=True))만 낸다. PATH 를 주면 UTF-8 파일로 쓴다",
    )
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

    if args.print_draft is not None:
        draft = build_draft(inject=True)
        if args.print_draft == "-":
            print(draft)
        else:
            # 셸의 `>` 는 PowerShell 5.1 에서 UTF-16 으로 바꿔 쓴다 — 파일은 여기서 직접 쓴다.
            Path(args.print_draft).write_text(draft + "\n", encoding="utf-8")
            print(f"결함 초안 {len(draft)}자 → {args.print_draft}")
        return 0

    use_llm = bool(args.llm)
    parsed = rfp_parser.load_generated(PROCUREMENT_ID)
    covered_ids = {requirement_id for requirement_id, _ in BASELINE_SENTENCES}
    mandatory_ids = {
        req.requirement_id for req in parsed.requirements if req.requirement_type == "mandatory"
    }
    missing_from_baseline = sorted(mandatory_ids - covered_ids)

    print("=" * 96)
    print("AI Auditor 평가 — synthetic-rfp-0001 (정답을 아는 합성 RFP)")
    print("=" * 96)
    print(f"  RFP 문서          : {parsed.document} (요구사항 {parsed.count}건)")
    print(f"  정상 초안 문장    : 필수 요구사항 {len(mandatory_ids)}건 중 {len(covered_ids & mandatory_ids)}건 대응")
    if missing_from_baseline:
        print(f"  (초안 미작성 요구사항: {', '.join(missing_from_baseline)})")

    clean_run = auditor_service.run_audit(PROCUREMENT_ID, build_draft(inject=False), use_llm=use_llm)
    print_run_summary("결함 없는 정상 초안", clean_run)

    injected_run = auditor_service.run_audit(
        PROCUREMENT_ID, build_draft(inject=True), use_llm=use_llm
    )
    print_run_summary("결함 3건을 주입한 초안", injected_run)

    defects = classify(injected_run)
    print_defect_table(defects)

    check_ids = _check_requirement_ids()
    others = other_findings(injected_run, defects)
    by_design = [
        finding
        for finding in others
        if finding.finding_type == "unchecked_condition" and finding.requirement_id in check_ids
    ]
    false_positives = [finding for finding in others if finding not in by_design]

    print("\n[주입 결함 외 발견 항목]")
    print(f"  총 {len(others)}건 — 그중 CHECK 요구사항 사람확인 {len(by_design)}건(설계상 정상), "
          f"오탐 후보 {len(false_positives)}건")
    for finding in others:
        tag = "사람확인" if finding in by_design else "오탐후보"
        print(
            f"  - [{tag}] {finding.id} {finding.finding_type}({finding.severity}) "
            f"{finding.requirement_id or '-'} : {_cut(finding.recommendation, 60)}"
        )

    detected = sum(1 for defect in defects if defect.detected)
    coverage = injected_run.coverage
    rate = coverage.covered / coverage.total * 100 if coverage.total else 0.0

    print("\n" + "=" * 96)
    print(f"Coverage(결함 주입 초안): {coverage.covered} / {coverage.total} ({rate:.1f}%)")
    print(f"오탐 후보: {len(false_positives)}건 / 전체 발견 {len(injected_run.findings)}건")
    print(f"주입 결함 {len(defects)}건 중 {detected}건 탐지")
    print("=" * 96)

    if args.json:
        payload: dict[str, Any] = {
            "procurement_id": PROCUREMENT_ID,
            "use_llm": use_llm,
            "clean_run": clean_run.model_dump(mode="json"),
            "injected_run": injected_run.model_dump(mode="json"),
            "defects": [
                {
                    "code": defect.code,
                    "description": defect.description,
                    "expected_finding_type": defect.expected_finding_type,
                    "detected": defect.detected,
                    "finding_ids": [finding.id for finding in defect.matched],
                }
                for defect in defects
            ],
            "detected_count": detected,
            "defect_count": len(defects),
            "false_positive_count": len(false_positives),
            "by_design_count": len(by_design),
        }
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"결과 JSON 저장: {args.json}")

    return 0 if detected == len(defects) else 1


if __name__ == "__main__":
    raise SystemExit(main())
