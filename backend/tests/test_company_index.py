"""회사자료 임베딩 인덱스 생성 규칙 테스트 (scripts/build_company_index.py).

핵심 계약
    - "확인되지 않은 사항" 문단은 **근거가 아니라 공백**이므로 인덱스에 넣지 않는다.
      실측 사고: "증빙 서류 목록은 공개 자료에서 확인되지 않았습니다"가 유사도 0.608로
      요구사항의 충족 근거로 채택되었다. 못 찾은 것을 찾았다고 인용하는 셈이다.
    - front matter의 synthetic / anonymized 값을 하드코딩하지 않고 그대로 읽는다.

네트워크를 쓰지 않는다 (임베딩 호출부는 건드리지 않고 순수 함수만 검증).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "build_company_index.py"


def load_module():
    spec = importlib.util.spec_from_file_location("build_company_index", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bci = load_module()


# --------------------------------------------------------------------------
# 근거가 아닌 문단 제외
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "chunk",
    [
        "확인되지 않은 사항: 연도별 누적 교육생 수는 공개 자료에서 확인되지 않았습니다.",
        "# 확인되지 않은 사항\n강사 수와 경력은 공개 자료로 확인할 수 없습니다.",
        "미확인 항목: 정보보호 관리체계 인증 보유 여부",
        "실제 교안과 산출물 원본은 공개되어 있지 않습니다.",
        "전담 관리자 지정 여부는 공개 자료에서 확인되지 않았습니다.",
    ],
)
def test_확인되지_않은_사항은_근거로_넣지_않는다(chunk: str) -> None:
    assert bci.is_gap_chunk(chunk) is True


@pytest.mark.parametrize(
    "chunk",
    [
        "교육용 계정 운영·관리: 수강생별 교육용 계정을 일괄 생성하고 회수합니다.",
        "생성형 AI 활용 실무 모듈을 보유하고 있습니다.",
        "고용보험 가입 기업 재직자를 대상으로 환급 과정을 운영합니다.",
        "가상 과정은 대면 교육으로 6시간 단위로 운영됩니다.",
    ],
)
def test_실제_수행근거는_그대로_넣는다(chunk: str) -> None:
    assert bci.is_gap_chunk(chunk) is False


def test_공백_문단_제외가_회사_역량_서술을_지우지_않는다() -> None:
    """'확인' 이라는 낱말이 들어가도 긍정 서술이면 남긴다."""
    chunk = "출결은 서명부와 전자출결로 확인하며 결석 인원을 별도로 표시합니다."
    assert bci.is_gap_chunk(chunk) is False


# --------------------------------------------------------------------------
# front matter 플래그
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [({"synthetic": "true"}, True), ({"synthetic": "false"}, False), ({}, True)],
)
def test_synthetic_플래그를_문서에서_읽는다(raw: dict, expected: bool) -> None:
    assert bci._flag(raw, "synthetic", default=True) is expected


def test_anonymized는_기본이_거짓이다() -> None:
    assert bci._flag({}, "anonymized", default=False) is False
    assert bci._flag({"anonymized": "true"}, "anonymized", default=False) is True


def test_front_matter를_본문과_분리한다() -> None:
    text = "---\ndocument_name: 회사소개서\nsynthetic: false\n---\n\n# 개요\n\n본문입니다.\n"
    meta, body = bci.parse_front_matter(text)
    assert meta["document_name"] == "회사소개서"
    assert meta["synthetic"] == "false"
    assert "본문입니다" in body
    assert "document_name" not in body


# --------------------------------------------------------------------------
# 실제 문서 상태 (회귀 방지)
# --------------------------------------------------------------------------


def test_저장된_문서에_확인되지_않은_사항이_남아있어도_인덱스에는_없다() -> None:
    """문서에는 남기되(사람이 읽을 가치가 있다) 인덱스에서만 뺀다."""
    docs = REPO_ROOT / "data" / "synthetic_company" / "docs"
    if not docs.is_dir():  # pragma: no cover
        pytest.skip("회사자료 폴더가 없다")

    gap_docs = [
        p for p in docs.glob("*.md") if "확인되지 않은 사항" in p.read_text(encoding="utf-8")
    ]
    if not gap_docs:  # pragma: no cover
        pytest.skip("확인되지 않은 사항 절을 가진 문서가 없다")

    import json

    index = REPO_ROOT / "data" / "synthetic_company" / "index" / "company_index.json"
    if not index.exists():  # pragma: no cover
        pytest.skip("인덱스가 없다")
    chunks = json.loads(index.read_text(encoding="utf-8"))["chunks"]
    assert not [c for c in chunks if bci.is_gap_chunk(c["source_text"])]
