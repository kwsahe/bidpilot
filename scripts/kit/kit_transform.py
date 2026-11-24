"""범용 설치 키트 — 풀어 둔 키트 폴더를 바꿔 넣고 「샘플에듀 자료 없음」 검사 다섯을 돈다 (30차 §3-G).

`scripts/build_kit.ps1` 이 `git archive` 로 풀어 둔 폴더에 대해 부른다. 검사가 하나라도 실패하면 0 이 아닌 값으로 끝나고,
build_kit 은 압축 파일을 만들지 않는다. 실명 목록(`data/private/pii_names.txt`)은 저장소에서 읽기만 하고 키트에 넣지 않으며
찾은 이름도 화면에 찍지 않는다(몇 건인지만).

    python scripts/kit/kit_transform.py <키트 폴더> --repo <저장소 루트>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

KIT_ORG = "org-main"
#: 코드 · 자료에서 바꿔 넣는 이름 — 회사 코드와 상호(키트 첫 실행이 진짜 회사 이름을 넣는다).
CODE_REPLACE = (
    ("org-sample", KIT_ORG),
    ("주식회사 샘플에듀", "우리 회사"),
    # 꺼짐 사유가 키트에 없는 파일(start_demo_claude.bat · start_dev.bat)을 가리켰다(31차 R30-07 · 36차) — 파이썬 소스 글자라 백슬래시 둘
    ("먼저 scripts\\\\stop_dev.ps1 로 끈 뒤 start_dev.bat 로 다시 켜세요", "설치 안내(KIT_README.md)의 「Claude · Codex 켜기」를 보세요"),
    # 끄기(stop_dev) 끝 문장도 키트에 없는 start_dev.bat · start_wireframe.bat 을 가리켰다(31차 키트 두 번 실행 확인)
    ("다시 띄우려면 scripts\\start_dev.bat (3110) 또는 scripts\\start_wireframe.bat (4120) 을 더블클릭하세요.",
     "다시 띄우려면 start_kit.bat 을 더블클릭하세요."),
    ("start_dev.ps1 / start_wireframe.ps1 로 띄운 서버가 없거나", "켜 둔 서버가 없거나"),
    # 켜기 요약 줄이 키트에 없는 start_dev.bat 을 가리켰다 — 키트는 실호출로 켠다(36차 마지막 검토 SC-2)
    ("실호출 모드 (개발용 · 매일 쓸 때는 start_dev.bat)", "실호출 모드 (키트 기본 — 나라장터 · 기업마당을 직접 받음)"),
    # 실전 가이드 7장 「BidPilot 매일 쓰는 순서」 켜기 줄(36차 §4) — 키트는 start_kit.bat 으로 켠다
    ("켜기는 `scripts\\start_dev.bat` 더블클릭", "켜기는 `start_kit.bat` 더블클릭"),
    # 45차 M20 — 가이드의 로컬 켜기 줄을 「(개발자용 — …)」으로 접었다. 키트에서는 그 PC 가 키트 PC 다
    ("(개발자용 — 개발 · 시험 PC 에서는 `scripts\\start_dev.bat` 로 켜고 서버 창 두 개를 닫아 끕니다.)",
     "이 PC(설치 키트)에서는 켜기는 `start_kit.bat` 더블클릭, 끄기는 BidPilot 서버 창 두 개 닫기입니다."),
    # 「?」 끝 문장은 32차부터 앱 안 「실전 가이드」 화면(/guide)을 가리킨다 — 키트에도 그 화면이 있어 바꿔 넣지 않는다.
    # 가이드 6-4 출처의 docs 경로는 키트에 없다(R31-30) — 키트에 있는 것으로.
    ("- BidPilot 사용 안내: `docs/user_guide.md`", "- BidPilot 화면: 맨 위 「?」 처음 안내 · 이 가이드 6장 표"),
    ("- BidPilot 화면 설명서: `docs/screen_guide.md`", "- 설치 안내: 이 폴더의 `KIT_README.md`"),
    # 45차 M20 — 저장소 경로 출처에 「(개발자용 · 저장소 안 파일)」 머리를 붙였다
    ("- (개발자용 · 저장소 안 파일) BidPilot 사용 안내: `docs/user_guide.md`", "- BidPilot 화면: 맨 위 「?」 처음 안내 · 이 가이드 6장 표"),
    ("- (개발자용 · 저장소 안 파일) BidPilot 화면 설명서: `docs/screen_guide.md`", "- 설치 안내: 이 폴더의 `KIT_README.md`"),
)
#: 키트 `.env.example` 의 켜는 길 안내(32차 R31-29) — 저장소 판은 start_demo_*.bat 을 가리킨다. 키트에는 start_kit.bat 하나다.
ENV_KIT_LINES = (
    ("# .env 를 고치지 않고 켜려면 scripts/start_demo_claude.bat (start_dev.ps1 -Ai -Provider claude_cli).",
     "# 키트는 start_kit.bat 하나로 켭니다 — 사업계획서를 Claude · Codex 로 쓰려면 아래 KIT_PLAN_WRITER(설치 안내 4-1)."),
    ("#            켜는 자리는 `scripts/start_dev.ps1 -Ai`(= `scripts/start_demo_ai.bat`)뿐이다.",
     "#            키트(start_kit.bat)는 이것을 켜지 않는다."),
    ("# 보통은 여기 적지 않고 scripts\\start_demo_claude.bat(= start_dev.ps1 -Frozen -PlanWriter)로 켠다.",
     "# 키트에서는 여기 적지 않고 아래 KIT_PLAN_WRITER 로 켠다(start_kit.bat 첫 실행 때 묻는다 · 설치 안내 4-1)."),
)
#: 검사 6 — 키트 안내가 키트에 없는 켜기 파일을 가리키면 안 된다(32차 R31-29)
MISSING_LAUNCHERS = re.compile(r"start_demo\w*\.bat|start_dev\.bat|start_wireframe\.bat")
LAUNCHER_GUIDE_FILES = (".env.example", "KIT_README.md", "GUIDE.md", "scripts/stop_dev.ps1", "scripts/start_dev.ps1",
                        "backend/app/services/llm_client.py")
#: 자료 · 문서(json/md/csv/txt/html)는 회사 이름(한글)만 중립으로. 주소 · 전화 · 누리집 · 메일(sampleedu …)은
#: 바꾸지 않는다 — 바꾸면 검사가 새는 것을 못 잡는다(30차 §4 마지막 검토). 그런 글이 남으면 검사 2 · 3 이 실패한다.
DATA_REPLACE = (*CODE_REPLACE, ("샘플에듀", "예시 회사"))
TEXT_SUFFIXES = {".json", ".md", ".csv", ".txt", ".html", ".css", ".svg"}
#: 글자를 바꿔 넣지 않고 **검사만** 하는 꾸러미 파일 — PDF 는 글자를 뽑아 · DOCX 는 zip 속 xml 을 본다(31차 R30-14).
PACKED_SUFFIXES = {".pdf", ".docx"}
CODE_SUFFIXES = {".py", ".ts", ".tsx", ".mjs", ".js", ".ps1", ".bat", ".toml"}
#: 검사 1 — 키트에 있으면 안 되는 경로
BANNED_PARTS = ("data/private", "data/company", ".git/", "node_modules", ".venv", ".next", "docs/reports", "docs/screenshots",
                "docs/presentation", "docs/SampleEdu", "deploy/")
BANNED_NAMES = re.compile(r"^(\.env|\.env\.local|CLAUDE\.md|AGENTS\.md|prompt_.*\.md|09\d\d(-\d)?\.md)$")
#: 검사 2 — 자료 · 문서에 남으면 안 되는 말
DATA_BANNED = re.compile(r"샘플에듀|sampleedu|org-sample", re.IGNORECASE)
#: 검사 3 — 코드에 남으면 안 되는 말(주석의 「샘플에듀」 · 「SampleEdu」 이름은 허용). 회사 코드 · 상호는 바꿔 넣으므로
#: 여기서는 바꿔 넣지 않는 회사 사실(누리집 · 메일 · 주소 · 전화)을 본다.
CODE_BANNED = re.compile(r"주식회사 샘플에듀|org-sample|sampleedu", re.IGNORECASE)


def _read(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def _write(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))  # BOM 없이(파이썬 json 이 BOM 을 못 읽는다)


def _front_matter_synthetic(text: str) -> bool:
    head = text.split("---", 2)[1] if text.startswith("---") else ""
    return bool(re.search(r"^synthetic:\s*true\s*$", head, re.MULTILINE))


def transform(kit: Path) -> list[str]:
    notes: list[str] = []
    snap = kit / "frontend/src/data/demo-snapshot.json"
    if snap.exists():
        _write(snap, "{}\n")
        notes.append("demo-snapshot.json → {}")
    pinned = kit / "data/public/sample_procurements/pinned_notices.json"
    if pinned.exists():
        data = json.loads(_read(pinned))
        data["notices"] = []
        _write(pinned, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        notes.append("pinned_notices.json → 빈 목록")
    docs = kit / "data/synthetic_company/docs"
    removed = 0
    for doc in sorted(docs.glob("*.md")) if docs.exists() else []:
        if not _front_matter_synthetic(_read(doc)):
            doc.unlink()
            removed += 1
    notes.append(f"synthetic_company/docs — 합성 아닌 문서 {removed}개 뺌")
    index = kit / "data/synthetic_company/index/company_index.json"
    if index.exists():
        data = json.loads(_read(index))
        before = len(data.get("chunks") or [])
        data["chunks"] = [c for c in data.get("chunks") or [] if c.get("synthetic") is True]
        data["chunk_count"] = len(data["chunks"])
        data["document_count"] = len({c.get("document_name") for c in data["chunks"]})
        _write(index, json.dumps(data, ensure_ascii=False) + "\n")
        notes.append(f"company_index.json — 문단 {before} → {len(data['chunks'])}(합성만)")
    env = kit / ".env.example"
    if env.exists():
        text = _read(env)
        text = re.sub(r"^DEFAULT_ORGANIZATION_ID=.*$", f"DEFAULT_ORGANIZATION_ID={KIT_ORG}", text, flags=re.MULTILINE)
        # 키트에 없는 켜기 파일(start_demo_*.bat)을 가리키는 줄 — 키트에서 켜는 길로(32차 R31-29)
        for old, rep in ENV_KIT_LINES:
            text = text.replace(old, rep)
        text += ("\n# --- 범용 설치 키트 (kit_setup.ps1 이 첫 실행 때 채운다) ---\n"
                 "DEFAULT_ORGANIZATION_NAME=\n"
                 "NEUTRAL_COMPANY_DEFAULTS=1\n"
                 "# Claude · Codex 로 사업계획서 쓰기(1 = 켬) · 바꾼 포트 — 다시 켤 때도 같게(31차 R30-07 · R30-11)\n"
                 "KIT_PLAN_WRITER=\n"
                 "KIT_FRONTEND_PORT=\n"
                 "KIT_BACKEND_PORT=\n")
        _write(env, text)
        notes.append(".env.example — 기본 회사 org-main · 중립 기본값")
    changed = 0
    for path in kit.rglob("*"):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix not in TEXT_SUFFIXES | CODE_SUFFIXES or path.name == "demo-snapshot.json":
            continue
        text = _read(path)
        pairs = DATA_REPLACE if suffix in TEXT_SUFFIXES else CODE_REPLACE
        new = text
        for old, rep in pairs:
            new = new.replace(old, rep)
        if path.name == "pyproject.toml":
            new = new.replace("BidPilot AI", "BidPilot AI")
        if new != text:
            _write(path, new)
            changed += 1
    notes.append(f"이름 바꿔 넣기 — 파일 {changed}개")
    return notes


def _packed_text(path: Path) -> str:
    """PDF · DOCX 속 글자 — 검사용. PDF 는 pdfplumber(저장소 venv), DOCX 는 zip 속 xml(stdlib)."""
    if path.suffix.lower() == ".docx":
        with zipfile.ZipFile(path) as z:
            return "\n".join(z.read(n).decode("utf-8", "ignore") for n in z.namelist() if n.endswith(".xml"))
    import pdfplumber  # 저장소 venv 에만 있다 — 키트를 묶는 쪽에서만 부른다

    with pdfplumber.open(str(path)) as pdf:
        meta = " ".join(str(v) for v in (pdf.metadata or {}).values())
        return meta + "\n" + "\n".join((page.extract_text() or "") for page in pdf.pages)


def _is_text(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES or path.name == ".env.example"


def checks(kit: Path, repo: Path) -> list[tuple[str, bool, str]]:
    rel = [p.relative_to(kit).as_posix() for p in kit.rglob("*") if p.is_file()]
    bad_paths = [r for r in rel if any(part in f"{r}/" for part in BANNED_PARTS) or BANNED_NAMES.match(Path(r).name)]
    results = [("1 경로 금지 목록", not bad_paths, f"{len(bad_paths)}개" + (f" — {bad_paths[:3]}" if bad_paths else ""))]

    names: list[str] = []
    pii = repo / "data/private/pii_names.txt"
    if pii.exists():
        names = [n.strip() for n in _read(pii).splitlines() if n.strip() and not n.startswith("#")]
    data_hits, name_hits = [], 0
    for r in rel:
        path = kit / r
        if path.name == "demo-snapshot.json" or not (_is_text(path) or path.suffix.lower() in PACKED_SUFFIXES):
            continue
        text = _packed_text(path) if path.suffix.lower() in PACKED_SUFFIXES else _read(path)
        if DATA_BANNED.search(text):
            data_hits.append(r)
        name_hits += sum(1 for n in names if n in text)
    results.append(("2 자료 · 문서 글자", not data_hits and name_hits == 0,
                    f"이름 말 {len(data_hits)}파일 · 실명 {name_hits}건(목록 {len(names)}개로 검사)" + (f" — {data_hits[:3]}" if data_hits else "")))

    code_hits, code_names = [], 0
    for r in rel:
        if (kit / r).suffix.lower() not in CODE_SUFFIXES:
            continue
        text = _read(kit / r)
        if CODE_BANNED.search(text):
            code_hits.append(r)
        code_names += sum(1 for n in names if n in text)
    results.append(("3 코드 글자", not code_hits and code_names == 0,
                    f"{len(code_hits)}파일 · 실명 {code_names}건" + (f" — {code_hits[:3]}" if code_hits else "")))

    docs = kit / "data/synthetic_company/docs"
    not_synth = [d.name for d in docs.glob("*.md") if not _front_matter_synthetic(_read(d))] if docs.exists() else []
    index = kit / "data/synthetic_company/index/company_index.json"
    chunks = json.loads(_read(index)).get("chunks") or [] if index.exists() else []
    bad_chunks = sum(1 for c in chunks if c.get("synthetic") is not True)
    results.append(("4 합성 여부", not not_synth and bad_chunks == 0, f"합성 아닌 문서 {len(not_synth)} · 합성 아닌 문단 {bad_chunks} · 남은 문단 {len(chunks)}"))

    snap = kit / "frontend/src/data/demo-snapshot.json"
    snap_ok = snap.exists() and json.loads(_read(snap)) == {}
    results.append(("5 스냅샷 {}", snap_ok, "비어 있음" if snap_ok else "비어 있지 않음"))

    # 화면 · 안내 글만 본다 — 코드 주석(start_dev.ps1 의 「예: start_demo_claude.bat」 · 맨 위 <# … #> 도움말)은 키트 사용자에게 보이지 않는다
    launcher_hits = [
        f for f in LAUNCHER_GUIDE_FILES
        if (kit / f).exists() and any(MISSING_LAUNCHERS.search(line) for line in _visible_lines(f, _read(kit / f)))
    ]
    results.append(("6 켜기 안내", not launcher_hits, f"키트에 없는 켜기 파일을 가리키는 곳 {len(launcher_hits)}" + (f" — {launcher_hits}" if launcher_hits else "")))
    return results


def _visible_lines(name: str, text: str) -> list[str]:
    """사용자에게 보이는 줄 — PowerShell 파일은 `#` 주석 줄과 `<# … #>` 블록 주석을 뺀다."""
    if not name.endswith(".ps1"):
        return text.splitlines()
    out: list[str] = []
    in_block = False
    for line in text.splitlines():
        stripped = line.strip().lstrip("﻿")  # 파일 맨 앞 BOM
        if in_block:
            in_block = "#>" not in stripped
            continue
        if stripped.startswith("<#"):
            in_block = "#>" not in stripped[2:]
            continue
        if not stripped.startswith("#"):
            out.append(line)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("kit")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    kit, repo = Path(args.kit), Path(args.repo)
    if not args.check_only:
        for note in transform(kit):
            print(f"  [바꿈] {note}")
    failed = 0
    for name, ok, detail in checks(kit, repo):
        print(f"  [{'통과' if ok else '실패'}] 검사 {name} — {detail}")
        failed += not ok
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
