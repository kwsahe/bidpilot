"""Gold 검수 작업지를 브라우저에서 채울 수 있는 단일 HTML로 만든다.

JSON을 손으로 142번 고치는 대신 키보드로 O/X만 누르면 된다.
다 채우면 완성된 worksheet JSON을 내려받아 원래 자리에 덮어쓰면 된다.

사용
    python scripts/gold_review_page.py g2b-R26BK01699556-000
    -> data/public/sample_rfp/worksheets/<id>.review.html 생성 (브라우저로 열기)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSHEET_DIR = REPO_ROOT / "data" / "public" / "sample_rfp" / "worksheets"

PAGE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Gold 검수 — __PID__</title>
<style>
  :root { color-scheme: light dark; --line:#d4d4d8; --muted:#71717a; --bg:#fff; --fg:#18181b;
          --yes:#0f766e; --no:#9f1239; --sel:#fef9c3; --card:#fafafa; }
  @media (prefers-color-scheme: dark) {
    :root { --line:#3f3f46; --muted:#a1a1aa; --bg:#0a0a0a; --fg:#fafafa; --sel:#422006; --card:#18181b; }
  }
  * { box-sizing: border-box; }
  body { margin:0; font:14px/1.6 system-ui, -apple-system, "Segoe UI", sans-serif;
         background:var(--bg); color:var(--fg); }
  header { position:sticky; top:0; background:var(--bg); border-bottom:1px solid var(--line);
           padding:12px 16px; z-index:10; }
  h1 { margin:0 0 4px; font-size:16px; }
  .meta { color:var(--muted); font-size:12px; }
  .bar { height:6px; background:var(--line); border-radius:3px; margin-top:8px; overflow:hidden; }
  .bar > div { height:100%; background:var(--yes); width:0%; transition:width .2s; }
  .actions { margin-top:10px; display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
  button { font:inherit; padding:6px 12px; border:1px solid var(--line); border-radius:6px;
           background:var(--card); color:var(--fg); cursor:pointer; }
  button:disabled { opacity:.45; cursor:not-allowed; }
  main { padding:8px 16px 120px; max-width:1100px; margin:0 auto; }
  .page-head { margin:18px 0 6px; font-size:12px; font-weight:700; color:var(--muted);
               border-bottom:1px solid var(--line); padding-bottom:4px; }
  .row { display:grid; grid-template-columns:64px 92px 1fr; gap:10px; align-items:start;
         padding:7px 8px; border-radius:6px; border:1px solid transparent; }
  .row.cur { background:var(--sel); border-color:var(--line); }
  .row .id { color:var(--muted); font:12px/1.6 ui-monospace, monospace; }
  .mark { display:flex; gap:4px; }
  .mark button { padding:2px 9px; font-size:12px; }
  .mark button.on-yes { background:var(--yes); color:#fff; border-color:var(--yes); }
  .mark button.on-no  { background:var(--no);  color:#fff; border-color:var(--no); }
  .txt { word-break:break-all; }
  .tag { display:inline-block; margin-left:6px; padding:0 6px; border-radius:9px; font-size:11px;
         border:1px solid var(--line); color:var(--muted); vertical-align:1px; }
  footer { position:fixed; bottom:0; left:0; right:0; background:var(--bg);
           border-top:1px solid var(--line); padding:10px 16px; font-size:12px; color:var(--muted); }
  kbd { border:1px solid var(--line); border-radius:4px; padding:0 5px; font:12px ui-monospace, monospace; }
</style>
</head>
<body>
<header>
  <h1>Gold 검수 — __TITLE__</h1>
  <div class="meta">각 줄이 <b>제안서가 대응해야 할 요구사항</b>이면 O, 아니면 X.
    「추출됨」 표시는 프로그램 판정이며 정답이 아닙니다.</div>
  <div class="bar"><div id="bar"></div></div>
  <div class="actions">
    <span id="count" class="meta"></span>
    <button id="jump">남은 첫 줄로</button>
    <button id="save" disabled>완료 JSON 내려받기</button>
    <span id="storage-warn" class="meta" hidden style="color:var(--no)">
      자동 저장이 막혀 있습니다 — 창을 닫으면 진행 상황이 사라집니다. 끝까지 채운 뒤 내려받으세요.
    </span>
  </div>
</header>
<main id="list"></main>
<footer>
  <kbd>O</kbd> 요구사항 · <kbd>X</kbd> 아님 · <kbd>↑</kbd><kbd>↓</kbd> 이동 ·
  판정하면 자동으로 다음 줄로 넘어갑니다. 진행 상황은 브라우저에 자동 저장됩니다(막혀 있으면 위에 안내가 뜹니다).
</footer>
<script>
const SHEET = __DATA__;
const KEY = "gold-review:" + SHEET.procurement_id;
let cur = 0;

// file:// 이나 저장이 막힌 환경에서도 검수 자체는 되어야 한다.
// 저장에 실패했다고 O/X가 멈추면 작업을 아예 못 한다.
let storageOk = true;
function loadSaved() {
  try { return JSON.parse(localStorage.getItem(KEY) || "{}"); }
  catch { storageOk = false; return {}; }
}
function persist(data) {
  if (!storageOk) return;
  try { localStorage.setItem(KEY, JSON.stringify(data)); }
  catch { storageOk = false; }
}
const saved = loadSaved();
SHEET.rows.forEach(r => { if (saved[r.line_id] !== undefined) r.is_requirement = saved[r.line_id]; });

const list = document.getElementById("list");
let lastPage = null;
SHEET.rows.forEach((r, i) => {
  if (r.page !== lastPage) {
    lastPage = r.page;
    const h = document.createElement("div");
    h.className = "page-head";
    h.textContent = "p." + r.page;
    list.appendChild(h);
  }
  const row = document.createElement("div");
  row.className = "row";
  row.id = "row-" + i;
  row.innerHTML =
    '<span class="id">' + r.line_id + "</span>" +
    '<span class="mark">' +
      '<button data-i="' + i + '" data-v="1">O</button>' +
      '<button data-i="' + i + '" data-v="0">X</button>' +
    "</span>" +
    '<span class="txt"></span>';
  row.querySelector(".txt").textContent = r.text;
  if (r.extracted) {
    const tag = document.createElement("span");
    tag.className = "tag";
    tag.textContent = "추출됨";
    row.querySelector(".txt").appendChild(tag);
  }
  list.appendChild(row);
});

function mark(i, value) {
  SHEET.rows[i].is_requirement = value;
  saved[SHEET.rows[i].line_id] = value;
  persist(saved);
  render();
  if (i === cur) { cur = Math.min(cur + 1, SHEET.rows.length - 1); focus(); }
}

function render() {
  SHEET.rows.forEach((r, i) => {
    const row = document.getElementById("row-" + i);
    const [yes, no] = row.querySelectorAll(".mark button");
    yes.className = r.is_requirement === true ? "on-yes" : "";
    no.className = r.is_requirement === false ? "on-no" : "";
    row.classList.toggle("cur", i === cur);
  });
  const done = SHEET.rows.filter(r => r.is_requirement !== null).length;
  const total = SHEET.rows.length;
  const yes = SHEET.rows.filter(r => r.is_requirement === true).length;
  document.getElementById("count").textContent =
    done + " / " + total + " 판정 (요구사항 " + yes + "건, 남음 " + (total - done) + ")";
  document.getElementById("bar").style.width = (done / total * 100) + "%";
  document.getElementById("save").disabled = done !== total;
  const warn = document.getElementById("storage-warn");
  if (warn) warn.hidden = storageOk;
}

function focus() {
  render();
  document.getElementById("row-" + cur).scrollIntoView({ block: "center", behavior: "smooth" });
}

list.addEventListener("click", e => {
  const b = e.target.closest("button[data-i]");
  if (b) { cur = +b.dataset.i; mark(+b.dataset.i, b.dataset.v === "1"); }
});

document.addEventListener("keydown", e => {
  const k = e.key.toLowerCase();
  if (k === "o" || k === "1") { mark(cur, true); e.preventDefault(); }
  else if (k === "x" || k === "0") { mark(cur, false); e.preventDefault(); }
  else if (e.key === "ArrowDown" || k === "j") { cur = Math.min(cur + 1, SHEET.rows.length - 1); focus(); e.preventDefault(); }
  else if (e.key === "ArrowUp" || k === "k") { cur = Math.max(cur - 1, 0); focus(); e.preventDefault(); }
});

document.getElementById("jump").onclick = () => {
  const i = SHEET.rows.findIndex(r => r.is_requirement === null);
  if (i >= 0) { cur = i; focus(); }
};

document.getElementById("save").onclick = () => {
  const out = JSON.parse(JSON.stringify(SHEET));
  const blob = new Blob([JSON.stringify(out, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = SHEET.procurement_id + ".worksheet.json";
  a.click();
};

focus();
</script>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("procurement_id")
    args = parser.parse_args()

    source = WORKSHEET_DIR / f"{args.procurement_id}.worksheet.json"
    if not source.exists():
        raise SystemExit(
            f"작업지가 없습니다: {source}\n"
            f"먼저 실행: python scripts/build_gold_worksheet.py {args.procurement_id}"
        )
    sheet = json.loads(source.read_text(encoding="utf-8"))

    html = (
        PAGE.replace("__PID__", args.procurement_id)
        .replace("__TITLE__", sheet.get("document", args.procurement_id))
        .replace("__DATA__", json.dumps(sheet, ensure_ascii=False))
    )
    target = WORKSHEET_DIR / f"{args.procurement_id}.review.html"
    target.write_text(html, encoding="utf-8")

    done = sum(1 for r in sheet["rows"] if r.get("is_requirement") is not None)
    print(f"검수 페이지: {target}")
    print(f"  후보 {len(sheet['rows'])}줄 (추출기 판정 {sum(1 for r in sheet['rows'] if r['extracted'])}건) · 이미 판정 {done}건")
    print("  브라우저로 열어 O/X 키로 채운 뒤 '완료 JSON 내려받기' → 아래 경로에 덮어쓰세요:")
    print(f"    {source}")


if __name__ == "__main__":
    main()
