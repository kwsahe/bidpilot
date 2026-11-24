/**
 * 지원사업 3D 어휘·경계 가드 — 「입찰의 말」과 「입찰의 부품」이 지원사업 화면으로 새지 않는지.
 *
 * 프론트엔드에는 테스트 러너가 없다(선례: `scripts/check_radar_axis.mjs`). 그렇다고 이 셋을
 * 눈으로만 붙잡고 둘 수는 없어서, 소스를 직접 읽어 세 가지를 기계로 검사한다.
 *
 *   A 금칙어 — 지원사업 어휘 파일의 **문자열 리터럴**에 입찰 용어가 0회
 *   B import 경계 — 지원사업 그래프가 `graph.ts` 의 파생 뷰 타입·입찰 빌더를 끌어오지 않는다
 *   C 부품 경계 — 지원사업 화면이 입찰 전용 컴포넌트를 끌어오지 않는다
 *
 * **왜 B 가 필요한가.** 지원사업 그래프는 `requirements`·`evidence`·`findings` 를 언제나 비운다.
 * 원본인 `SupportRequirementItem` 에는 `page`·`source_text`·`displayStatus`·`sentences` 가 없어서
 * `RequirementView` 를 채우면 «전부 지어낸 값»이 되기 때문이다. 그런데 이 규칙은 사람의 선의에만
 * 기대고 있다 — 나중에 누가 「이왕이면 displayStatus 도 채우자」고 손을 대면 조용히 무너진다.
 * `RequirementView`/`EvidenceView`/`FindingView`/`buildCosmosGraph` 를 import 하지 못하게 막으면
 * 그 순간 **빌드가 먼저 멈춘다.** 이것이 정직성 경계선의 자물쇠다.
 *
 * **왜 C 가 필요한가.** WebGL 이 없을 때 `CosmosStage.tsx` 는 `Cosmos2D` 로 떨어지고,
 * `Cosmos2D.tsx` 의 `CLUSTER_META` 는 「참가 가능 여부 / Requirement Matrix / 제안서 초안 / AI Audit」다.
 * 지원사업 화면이 그 부품을 한 번이라도 거치면 **지원사업 공고에 입찰 용어가 그대로 뜬다.**
 *
 * **주석은 검사하지 않는다.** 「이 말은 쓰지 않는다」를 설명하는 주석(바로 이 주석 같은)이
 * 스스로를 죽이면 안 되기 때문이다. 그래서 A 는 주석을 걷어낸 뒤 문자열 리터럴만 본다.
 *
 * 실행:  node scripts/check_support_vocabulary.mjs
 *        node scripts/check_support_vocabulary.mjs --verbose
 *
 * 종료코드:  0 통과 · 1 위반 발견 · 2 실행 환경 문제(저장소 경로를 못 찾음)
 *
 * 검사 대상이 아직 없으면(다른 작업자가 만드는 중이면) 「검사 대상 없음」으로 **통과**시키되
 * 그 사실을 반드시 출력한다 — 조용히 0 을 돌려주면 가드가 도는 줄 알고 방심하게 된다.
 */

import { readdirSync, readFileSync, existsSync, statSync } from "node:fs";
import { join, relative, resolve, dirname, basename, extname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, "..");
const VERBOSE = process.argv.includes("--verbose");

if (!existsSync(join(REPO_ROOT, "frontend", "src"))) {
  console.error(`frontend/src 를 찾을 수 없습니다 — 저장소 루트에서 실행하세요 (${REPO_ROOT})`);
  process.exit(2);
}

/** A — 지원사업 화면에 쓰지 않는 말. 계약서 C-7 의 목록 그대로. */
const FORBIDDEN_WORDS = [
  "입찰",
  "낙찰",
  "투찰",
  "RFP",
  "제안서",
  "수주",
  "평가항목",
  "발주기관",
  "나라장터",
  "Auditor",
  "참가자격",
  "참가 차단",
  "요구사항",
  "증빙",
];

/** B — `graph.ts` 에서 끌어오면 안 되는 이름. 파생 뷰 3개 + 입찰 빌더. */
const FORBIDDEN_GRAPH_IMPORTS = ["buildCosmosGraph", "RequirementView", "EvidenceView", "FindingView"];

/** C — 지원사업 화면이 끌어오면 안 되는 입찰 전용 컴포넌트. */
const BID_ONLY_COMPONENTS = [
  "Cosmos2D",
  "NodeList",
  "CosmosStage",
  "MissionStrip",
  "DetailPanel",
  "BottomStrip",
  "TodayPanel",
  "WorkflowRail",
  "CosmosLegend",
];

const SOURCE_EXTENSIONS = new Set([".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs"]);

// ---------------------------------------------------------------------------
// 소스 훑기
// ---------------------------------------------------------------------------

/** 디렉터리 아래 소스 파일 전부. 없는 디렉터리는 빈 배열(호출부가 「대상 없음」으로 처리한다). */
function sourceFilesUnder(dir) {
  if (!existsSync(dir) || !statSync(dir).isDirectory()) return [];
  const found = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      found.push(...sourceFilesUnder(full));
    } else if (SOURCE_EXTENSIONS.has(extname(entry.name))) {
      found.push(full);
    }
  }
  return found.sort();
}

const rel = (file) => relative(REPO_ROOT, file).split("\\").join("/");

// ---------------------------------------------------------------------------
// 아주 작은 스캐너 — 주석을 걷어내고 문자열 리터럴만 남긴다
// ---------------------------------------------------------------------------

/** `/` 가 나눗셈이 아니라 정규식의 시작일 수 있는 자리. (직전 의미 있는 글자로 판별) */
const REGEX_CAN_FOLLOW = new Set(["(", ",", "=", ":", "[", "!", "&", "|", "?", "{", "}", ";", "+", "-", "*", "%", "~", "^", "<", ">", "\n"]);

/**
 * 소스에서 **문자열 리터럴만** 뽑는다. 줄 주석 `//` · 블록 주석 `/* *\/` · JSDoc 의 ` * ` 줄은
 * 통째로 버린다. 템플릿 리터럴은 `${…}` 안을 코드로 되돌려 중첩까지 따라간다
 * (`` `앞 ${`뒤`}` `` 같은 중첩에서 따옴표 짝이 어긋나 뒤쪽 코드를 통째로 문자열로 오인하던 것을 막는다).
 *
 * @returns {{value: string, line: number}[]}
 */
function stringLiterals(source) {
  const out = [];
  const n = source.length;
  let i = 0;
  let line = 1;
  let mode = "code"; // "code" | "template"
  let buffer = "";
  let startLine = 1;
  let braceDepth = 0;
  let lastSignificant = "\n";
  /** `${…}` 로 잠시 코드로 나갈 때 템플릿 상태를 쌓아 둔다. */
  const stack = [];

  while (i < n) {
    const c = source[i];

    if (mode === "template") {
      if (c === "\\") {
        buffer += source[i + 1] ?? "";
        if (source[i + 1] === "\n") line += 1;
        i += 2;
        continue;
      }
      if (c === "`") {
        out.push({ value: buffer, line: startLine });
        mode = "code";
        lastSignificant = "`";
        i += 1;
        continue;
      }
      if (c === "$" && source[i + 1] === "{") {
        stack.push({ buffer, startLine, braceDepth });
        mode = "code";
        lastSignificant = "{";
        i += 2;
        continue;
      }
      if (c === "\n") line += 1;
      buffer += c;
      i += 1;
      continue;
    }

    // --- code ---
    if (c === "\n") {
      line += 1;
      lastSignificant = "\n";
      i += 1;
      continue;
    }
    if (c === "/" && source[i + 1] === "/") {
      while (i < n && source[i] !== "\n") i += 1;
      continue;
    }
    if (c === "/" && source[i + 1] === "*") {
      i += 2;
      while (i < n && !(source[i] === "*" && source[i + 1] === "/")) {
        if (source[i] === "\n") line += 1;
        i += 1;
      }
      i += 2;
      continue;
    }
    if (c === "/" && REGEX_CAN_FOLLOW.has(lastSignificant)) {
      // 정규식 리터럴. 안에 따옴표가 있어도 문자열로 오인하지 않도록 통째로 건너뛴다.
      i += 1;
      let inClass = false;
      while (i < n) {
        const d = source[i];
        if (d === "\\") { i += 2; continue; }
        if (d === "\n") break;
        if (d === "[") inClass = true;
        else if (d === "]") inClass = false;
        else if (d === "/" && !inClass) { i += 1; break; }
        i += 1;
      }
      lastSignificant = "/";
      continue;
    }
    if (c === '"' || c === "'") {
      const quote = c;
      const opened = line;
      let value = "";
      i += 1;
      while (i < n) {
        const d = source[i];
        if (d === "\\") { value += source[i + 1] ?? ""; i += 2; continue; }
        if (d === quote) { i += 1; break; }
        if (d === "\n") { line += 1; break; } // 닫히지 않은 따옴표 — 줄에서 끊는다
        value += d;
        i += 1;
      }
      out.push({ value, line: opened });
      lastSignificant = quote;
      continue;
    }
    if (c === "`") {
      mode = "template";
      buffer = "";
      startLine = line;
      i += 1;
      continue;
    }
    if (c === "{") {
      braceDepth += 1;
      lastSignificant = "{";
      i += 1;
      continue;
    }
    if (c === "}") {
      const top = stack[stack.length - 1];
      if (top && braceDepth === top.braceDepth) {
        stack.pop();
        buffer = top.buffer;
        startLine = top.startLine;
        braceDepth = top.braceDepth;
        mode = "template";
        i += 1;
        continue;
      }
      braceDepth = Math.max(0, braceDepth - 1);
      lastSignificant = "}";
      i += 1;
      continue;
    }
    if (!/\s/.test(c)) lastSignificant = c;
    i += 1;
  }
  return out;
}

/** 주석을 공백으로 바꾼 소스. 줄 번호가 어긋나지 않게 줄바꿈은 남긴다. */
function stripComments(source) {
  let out = "";
  const n = source.length;
  let i = 0;
  let lastSignificant = "\n";
  while (i < n) {
    const c = source[i];
    if (c === "/" && source[i + 1] === "/") {
      while (i < n && source[i] !== "\n") i += 1;
      continue;
    }
    if (c === "/" && source[i + 1] === "*") {
      i += 2;
      while (i < n && !(source[i] === "*" && source[i + 1] === "/")) {
        out += source[i] === "\n" ? "\n" : " ";
        i += 1;
      }
      i += 2;
      continue;
    }
    if (c === '"' || c === "'" || c === "`") {
      const quote = c;
      out += c;
      i += 1;
      while (i < n) {
        const d = source[i];
        out += d;
        if (d === "\\") { out += source[i + 1] ?? ""; i += 2; continue; }
        i += 1;
        if (d === quote) break;
      }
      lastSignificant = quote;
      continue;
    }
    if (!/\s/.test(c)) lastSignificant = c;
    out += c;
    i += 1;
  }
  return out;
}

/**
 * import / export-from / 동적 import 를 훑는다.
 * @returns {{specifier: string, names: string[], line: number}[]}
 */
function importsOf(source) {
  const code = stripComments(source);
  const found = [];
  const lineOf = (index) => code.slice(0, index).split("\n").length;

  const staticRe = /\b(?:import|export)\s+((?:type\s+)?[^;]*?)\s+from\s*["']([^"']+)["']/g;
  for (const m of code.matchAll(staticRe)) {
    found.push({ specifier: m[2], names: bindingNames(m[1]), line: lineOf(m.index) });
  }
  const sideEffectRe = /\bimport\s*["']([^"']+)["']/g;
  for (const m of code.matchAll(sideEffectRe)) {
    found.push({ specifier: m[1], names: [], line: lineOf(m.index) });
  }
  const dynamicRe = /\bimport\s*\(\s*["']([^"']+)["']\s*\)/g;
  for (const m of code.matchAll(dynamicRe)) {
    found.push({ specifier: m[1], names: [], line: lineOf(m.index) });
  }
  return found;
}

/** `type { A, B as c }` · `Default, { A }` · `* as ns` 에서 **원래 이름**만 뽑는다. */
function bindingNames(clause) {
  const names = [];
  const text = clause.replace(/^\s*type\s+/, "");
  const braced = text.match(/\{([\s\S]*)\}/);
  if (braced) {
    for (const part of braced[1].split(",")) {
      const name = part.trim().replace(/^type\s+/, "").split(/\s+as\s+/)[0].trim();
      if (name) names.push(name);
    }
  }
  const head = text.split("{")[0].replace(/\*\s+as\s+\S+/, "").trim().replace(/,$/, "").trim();
  if (head && /^[A-Za-z_$][\w$]*$/.test(head)) names.push(head);
  return names;
}

/** 모듈 지정자의 마지막 조각 (확장자 제거). `@/components/cosmos/CosmosStage` → `CosmosStage` */
const moduleTail = (specifier) => basename(specifier).replace(/\.(tsx?|jsx?|mjs|mts)$/, "");

/** `graph.ts` 를 가리키는 지정자인가. */
const pointsAtGraph = (specifier) => /(^|\/)graph$/.test(specifier.replace(/\.(tsx?|jsx?)$/, ""));

// ---------------------------------------------------------------------------
// 검사
// ---------------------------------------------------------------------------

const SUPPORT_LIB_DIR = join(REPO_ROOT, "frontend", "src", "lib", "cosmos", "support");
const SUPPORT_COMPONENT_DIR = join(REPO_ROOT, "frontend", "src", "components", "support");
const COSMOS_COMPONENT_DIR = join(REPO_ROOT, "frontend", "src", "components", "cosmos");

const failures = [];
const notes = [];
const fail = (message) => {
  console.error(`✗ ${message}`);
  failures.push(message);
};

// --- A · 금칙어 ------------------------------------------------------------

const libFiles = sourceFilesUnder(SUPPORT_LIB_DIR);
console.log(`A · 금칙어 — frontend/src/lib/cosmos/support/** (${libFiles.length}개 파일)`);
if (libFiles.length === 0) {
  notes.push("A: 검사 대상 없음 — frontend/src/lib/cosmos/support/ 에 소스가 아직 없습니다 (만들어지면 자동으로 검사합니다)");
  console.log("  검사 대상 없음 — 디렉터리가 아직 비어 있거나 없습니다.");
} else {
  let hits = 0;
  for (const file of libFiles) {
    const literals = stringLiterals(readFileSync(file, "utf8"));
    if (VERBOSE) console.log(`  ${rel(file)} — 문자열 ${literals.length}개`);
    for (const { value, line } of literals) {
      for (const word of FORBIDDEN_WORDS) {
        if (value.includes(word)) {
          fail(`금칙어 「${word}」 — ${rel(file)}:${line}  "${value.slice(0, 60)}"`);
          hits += 1;
        }
      }
    }
  }
  if (hits === 0) console.log("  ✓ 문자열 리터럴에 입찰 용어 0회 (주석은 검사하지 않습니다)");
}

// --- B · import 경계 -------------------------------------------------------

console.log("");
console.log(`B · import 경계 — 지원사업 그래프가 graph.ts 의 파생 뷰를 끌어오지 않는다`);
if (libFiles.length === 0) {
  notes.push("B: 검사 대상 없음 — frontend/src/lib/cosmos/support/ 에 소스가 아직 없습니다");
  console.log("  검사 대상 없음.");
} else {
  let hits = 0;
  for (const file of libFiles) {
    for (const imported of importsOf(readFileSync(file, "utf8"))) {
      for (const name of imported.names) {
        if (FORBIDDEN_GRAPH_IMPORTS.includes(name)) {
          const where = pointsAtGraph(imported.specifier) ? "graph.ts" : imported.specifier;
          fail(`금지된 import 「${name}」 from "${where}" — ${rel(file)}:${imported.line}\n    지원사업 그래프는 파생 뷰를 채우지 않습니다. 원본에 page·source_text 가 없어 채우면 지어낸 값이 됩니다.`);
          hits += 1;
        }
      }
    }
  }
  if (hits === 0) console.log(`  ✓ ${FORBIDDEN_GRAPH_IMPORTS.join(" · ")} 를 끌어온 곳 없음`);
}

// --- C · 부품 경계 ---------------------------------------------------------

console.log("");
console.log("C · 부품 경계 — 지원사업 화면이 입찰 전용 컴포넌트를 끌어오지 않는다");
const supportComponentFiles = [
  ...sourceFilesUnder(SUPPORT_COMPONENT_DIR),
  // 아직 이름이 정해지지 않은 파일까지 잡으려고 **패턴**으로 본다: components/cosmos 아래의 「…Support…」
  ...sourceFilesUnder(COSMOS_COMPONENT_DIR).filter((f) => basename(f).includes("Support")),
];
if (supportComponentFiles.length === 0) {
  notes.push("C: 검사 대상 없음 — components/support/** 도 components/cosmos/**Support** 도 없습니다");
  console.log("  검사 대상 없음.");
} else {
  console.log(`  대상 ${supportComponentFiles.length}개 파일`);
  let hits = 0;
  for (const file of supportComponentFiles) {
    for (const imported of importsOf(readFileSync(file, "utf8"))) {
      const tail = moduleTail(imported.specifier);
      const viaPath = BID_ONLY_COMPONENTS.includes(tail) ? tail : null;
      const viaName = imported.names.find((n) => BID_ONLY_COMPONENTS.includes(n)) ?? null;
      const culprit = viaPath ?? viaName;
      if (culprit) {
        fail(`입찰 전용 컴포넌트 「${culprit}」 — ${rel(file)}:${imported.line} ("${imported.specifier}")\n    WebGL 이 없을 때 Cosmos2D 의 클러스터 이름이 그대로 화면에 뜹니다.`);
        hits += 1;
      }
    }
    if (VERBOSE) console.log(`  ${rel(file)}`);
  }
  if (hits === 0) console.log(`  ✓ ${BID_ONLY_COMPONENTS.join(" · ")} 를 끌어온 곳 없음`);
}

// ---------------------------------------------------------------------------

console.log("");
for (const note of notes) console.log(`· ${note}`);
if (failures.length > 0) {
  console.error("");
  console.error(`✗ 위반 ${failures.length}건`);
  process.exit(1);
}
console.log(notes.length > 0 ? "✓ 통과 (일부는 검사 대상 없음 — 위 목록 확인)" : "✓ 금칙어 · import 경계 · 부품 경계 모두 통과");
