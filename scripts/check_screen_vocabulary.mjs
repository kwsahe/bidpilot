/**
 * 화면 어휘 검사 — **영문 판정값이 화면에 새어 나오지 않는다** (0921 §3-11 · 0922 §4-D-6).
 *
 * ## 무엇을 막는가
 *
 * 저장 값은 영문 enum 이다(`PASS`·`CHECK`·`FAIL`·`GO`·`HOLD`·`NO_GO`·`high`). 그것을 그대로
 * 화면에 적으면 담당자가 읽을 수 없는 말이 된다. 회차마다 같은 자리에서 다시 샜다 —
 *
 *   5차 ISSUE-074-e  상세 패널 「등급 high」
 *   5차 ISSUE-074-f  KPI 「GO/HOLD/NO_GO」 원문
 *   8차 ISSUE-089    그래프 노드 「PASS 7/10 · 지역제한」
 *   8차 §4-D-6       버튼 툴팁 「이 사업에 참여하기로 결정한다 (GO)」·와이어프레임 「HIGH」
 *
 * 사전은 있었다(`lib/scoreNames`·`lib/cosmos/format`). 없던 것은 **새는 것을 잡는 그물**이다.
 *
 * ## 어떻게 찾는가
 *
 * **한국어가 섞인 문자열 안에 영문 판정값이 있으면** 화면 문장으로 본다. 비교식
 * (`status === "PASS"`)·사전 조회(`LABELS.PASS`·`LABELS["PASS"]`)·타입·import 는 세지 않는다 —
 * 그것들은 저장 값을 다루는 코드이지 화면 글자가 아니다.
 *
 * 완벽한 파서가 아니다. 놓치는 모양이 있으면 여기에 규칙을 더한다.
 *
 * 실행:  node scripts/check_screen_vocabulary.mjs
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("../frontend/src", import.meta.url));

/** 검사할 폴더 — 화면을 그리는 곳만 본다. */
const SCAN_DIRS = ["app", "components", "lib"];

/**
 * 화면에 보이면 안 되는 저장 값.
 *
 * `GO` 는 두 글자라 「GO」가 든 영단어(`GOOD`·`CARGO`)에 걸릴 수 있어 낱말 경계로 찾는다.
 */
const FORBIDDEN = ["PASS", "CHECK", "FAIL", "NO_GO", "NO-GO", "GO", "HOLD", "HIGH", "MEDIUM", "LOW", "NONE", "SCORE"];

/**
 * 예외 — 화면 글자가 아닌 것.
 *
 * `lib/scoreNames`·`lib/cosmos/format` 는 **사전 자체**라 영문 키가 있어야 한다.
 * 테스트 파일도 저장 값을 그대로 다룬다.
 */
const ALLOWED_FILES = [
  "lib/scoreNames.ts",
  "lib/cosmos/format.ts",
  "lib/cosmos/theme.ts",
  "types/",
];

/**
 * 화면 글자에 쓰면 안 되는 말 — 파일 범위별 (27차).
 *
 * 따옴표 문자열만이 아니라 JSX 글자 줄도 본다(주석 줄은 뺀다). `files` 는 `frontend/src` 기준 앞부분.
 */
const BANNED_PHRASES = [
  // ISSUE-158 — 요구사항 정리표는 규칙으로만 뽑는다. 같은 화면 배지가 「규칙」인데 머리 · 열 이름이 「AI 추출」이었다.
  // 28차 §3-C — 옛 /rfp 페이지가 사업기회 안의 탭 부품으로 옮겨졌다.
  { files: ["components/opportunities/RequirementSheet", "components/opportunities/requirementEvidenceView"], pattern: /AI\s*추출/, reason: "규칙 추출을 「AI 추출」이라고 부르지 않는다 (ISSUE-158)" },
  // 27차 §3-D-8 — 입찰 지도 위 숫자는 정거장 번호 1~8 하나의 뜻만. 안내 · 튜토리얼 · 발표 · 범례 문구가 ①~⑳ 을 다른 뜻
  // (번호 칩 · 안내 단계 · 핵심 라벨)으로 썼다. 지원사업 지도의 번호 칩(`three/labels.tsx`)은 규칙 그대로라 뺀다.
  {
    files: [
      "lib/cosmos/vocabulary.ts",
      "lib/cosmos/tutorial.ts",
      "lib/cosmos/quickTour.ts",
      "lib/cosmos/presentation.ts",
      "lib/cosmos/guidedFlow.ts",
      "components/cosmos/GuidedFlowBar.tsx",
      "components/cosmos/GuidedDetail.tsx",
      "components/cosmos/LegendSheet.tsx",
      "components/cosmos/CosmosLegend.tsx",
      "components/cosmos/WorkflowRail.tsx",
      "components/cosmos/Cosmos2D.tsx",
      "components/cosmos/three/stations.tsx",
    ],
    pattern: /[①-⑳]/,
    reason: "입찰 지도 · 안내 문구에 원문자(①~⑳)를 쓰지 않는다 — 지도 숫자는 정거장 번호뿐 (27차 §3-D-8)",
  },
];

/**
 * 한국어 화면 문장 안에 쓰면 안 되는 모양 — 모든 파일 (27차 §3-H).
 *
 * 코드(주소 · 설정 읽기)는 한국어가 없으니 걸리지 않는다. 담당자가 읽는 문장에 설정 이름 · API 주소 · 개발 말이 새면 걸린다.
 * `§3-E` 의 옛 말은 `OLD_TERMS` 에 더한다.
 */
const SCREEN_TEXT_BANS = [
  { pattern: /[A-Z][A-Z_]{4,}=/, reason: "환경변수 꼴(NAME=)을 화면 문장에 쓰지 않는다 (27차 §3-H)" },
  { pattern: /\/api\//, reason: "API 주소를 화면 문장에 쓰지 않는다 (27차 §3-H)" },
  { pattern: /fixture/i, reason: "개발 말 「fixture」를 화면 문장에 쓰지 않는다 (27차 §3-H)" },
];

/**
 * 옛 말 — 27차 §3-E 「말 한 벌」에서 **실제로 바꾼 말**만 (새 말은 `frontend/src/lib/terms.ts`).
 *
 * 따옴표 문자열 · JSX 글자 모두 본다(주석은 지운 뒤에 본다 — 주석은 옛 말을 인용해 이유를 적어도 된다).
 * `ALLOWED_FILES`(사전 파일)도 본다 — 옛 말이 사전에 남아 있던 것이 뿌리였다.
 * `except` 는 이번 묶음이 손대지 않는 지도 파일(주 에이전트 담당) — 그쪽이 고치면 뺀다.
 */
const OLD_TERMS = [
  { term: "사람 확인 필요", use: "확인 필요" },
  { term: "결정 미정", use: "결정 전" },
  { term: "미결정", use: "결정 전" },
  { term: "결정 대기", use: "결정 전" },
  { term: "증빙 없음", use: "근거 없음" },
  { term: "회사 증빙", use: "회사 근거" },
  { term: "RFP 분석", use: "요구사항 정리표" },
  { term: "매트릭스 화면", use: "요구사항 정리표" },
  { term: "요구사항 매트릭스", use: "요구사항 정리표" },
  // 「데모 시나리오 · 합성 공고」 · 「데모 시나리오 — …」를 함께 막는다.
  { term: "데모 시나리오", use: "가상 예시 공고(SYNTHETIC_NOTICE)" },
  { term: "데모 화면입니다", use: "가상 예시 공고입니다" },
  { term: "데모 자료입니다", use: "가상 예시 공고입니다" },
  // 31차 §3-C 「합성 → 가상 예시」(담당자 결정) — 「합성 데모 공고 · 합성 회사자료 · 합성 RFP · (합성) · 합성 기본값」 모두.
  // 「적합성 · 종합성」 같은 낱말 속 「합성」은 옛 말이 아니다.
  { pattern: /(?<![적종복결화])합성/, term: "합성", use: "가상 예시(SYNTHETIC_NOTICE · SYNTHETIC_COMPANY) · 예시 값" },
  { term: "일 내 마감", use: "일 안 마감" },
  // 27차 §3-E 검수 R27U-MSC-05 · MSC-11 · HD-09 — 바꾼 말이 되살아나지 않게
  { term: "참여 곤란", use: "불가" },
  { term: "회사정보·수행근거", use: "회사자료" },
  { term: "접수 마감", use: "신청 마감(deadlineTerm)" },
  { term: "예산 미정", use: "예산 미공개" },
  { term: "점수 미확인", use: "미산정" },
  { term: "우선순위 미확인", use: "검토 우선순위 점수 없음" },
  // 30차 §3-F 화면 글 쉽게 — 바꾼 옛 말(docs/reports/2026-10-17_screen_wording_list.md §2 · §3)
  { term: "후보 판정", use: "우리 회사 적합도" },
  { term: "풀리는 조건", use: "갖추면 가능" },
  { term: "열리는 조건", use: "갖추면 가능" },
  { term: "갖추면 열린다", use: "갖추면 가능" },
  { term: "회사에 뜻하는 것", use: "우리 회사 입장에서" },
  { term: "실분석", use: "AI 분석 결과" },
  { term: "매핑 미검증", use: "값 점검 전" },
  { term: "Evidence-based", use: "근거 기반 AI 수주 도우미" },
  { term: "통합 점수", use: "회사 기준 검토 우선순위" },
  { term: "관제 중심", use: "우리 회사 (가운데 기준)" },
  { term: "탐지 대상", use: "그림에 올린 건" },
  { term: "참가 차단 미해결", use: "탈락 위험(안 고침)" },
  { term: "미해결 발견", use: "점검에서 고칠 것" },
  { term: "사람이 채울 칸", use: "담당자가 채울 칸" },
  { term: "사흘 안", use: "3일 안" },
  { term: "이달 안", use: "30일 안" },
  { term: "규모 상단", use: "규모 큼" },
  { term: "홈그라운드", use: "광주·전남 기관 발주" },
  { term: "구체해집니다", use: "더 구체적으로 씁니다" },
  { term: "회사 쪽 확인", use: "회사 정보 필요" },
  { term: "역대조", use: "맞춰 보기" },
  { term: "재수집", use: "새로 받기(RECOLLECT_TERM)" },
  { term: "평가위원 채점", use: "AI 모의 채점" },
  { term: "파싱 미실행", use: "아직 안 읽음" },
  { term: "섹션 생성", use: "제안서 초안 만들기" },
  { term: "행동 필요", use: "할 일 있음" },
  { term: "색인 갱신", use: "AI 검색 다시 준비" },
  { term: "제안서 반영 상태", use: "필수 요구사항 반영" },
  { term: "규칙 초안", use: "기본 초안" },
  { term: "시연용 고정", use: "예시 공고(마감)" },
  { term: "사람의 최종 결정", use: "담당자 최종 결정" },
  // 31차 §3-G (recheck23 R30-29 · 33)
  { term: "기업마당 캐시", use: "기업마당 저장본(CACHE_TERM)" },
  { term: "안 본 조항", use: "확정 안 한 조항(보류 포함)" },
  { term: "조항 다 봄", use: "조항 다 확정" },
  { term: "규칙 재판정", use: "다시 판정" },
  { term: "검증 역량", use: "해 본 일" },
  { term: "우리 갈래", use: "회사가 하는 종류의 일" },
  { term: "시연 고정", use: "새 공고 받기 꺼짐(FROZEN_TERM)" },
  { term: "필드 매핑", use: "값 점검" },
  { term: "캐시 사용 중", use: "저장본 사용 중" },
  // 33차 R32-14 — 의미 유사도 이름 하나(백엔드 FIT_METHOD_LABELS 「AI 의미 매칭」)
  { term: "AI 내용 비교", use: "AI 의미 매칭" },
  { term: "AI 유사도", use: "AI 의미 매칭" },
  // 40차 FRONT-03 — 수집 · 후보는 회사 사업영역 기준(38차 · 39차 이름) — 「?」 대화상자에 옛 이름이 남아 있었다
  { term: "AI·AI교육 공고 후보", use: "회사 사업영역(AI · 교육 · 컨설팅 · ESG 등) 공고 후보" },
  { term: "AI·AI교육 후보", use: "회사 사업영역 후보" },
  { term: "의미 유사도(AI)", use: "AI 의미 매칭" }, // 34차 R33-07
];

/** 주석을 지운 본문 — 줄 수는 그대로 둔다(보고할 줄 번호가 맞아야 한다). `http://` 의 `//` 는 주석이 아니다. */
function stripComments(source) {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, (block) => block.replace(/[^\n]/g, " "))
    .replace(/(^|[^:\\])\/\/[^\n]*/gm, "$1");
}

/** 주석이 아닌 줄인가 — 금지어 검사는 JSX 글자까지 본다. */
function isCodeLine(line) {
  return !/^\s*(\*|\/\/|\/\*|\{\s*\/\*)/.test(line);
}

/** 한국어가 한 글자라도 들어 있는가 — 화면 문장인지 가리는 기준이다. */
const HAS_KOREAN = /[가-힣]/;

function walk(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) out.push(...walk(full));
    else if (/\.(tsx|ts)$/.test(name)) out.push(full);
  }
  return out;
}

/**
 * 한 줄에서 «화면 문장»만 뽑는다.
 *
 * 주석·import·타입 선언은 버리고, 비교식과 사전 조회가 들어 있는 줄도 버린다.
 */
function screenStrings(line) {
  const trimmed = line.trim();
  if (/^(\*|\/\/|\/\*|import |export type |type |interface )/.test(trimmed)) return [];
  // 비교식·사전 조회·객체 키는 저장 값을 «다루는» 코드다.
  if (/[=!]==\s*["'`]/.test(trimmed)) return [];
  if (/LABELS[.[]|_LABELS\b|Record<|\?\?\s*["']/.test(trimmed)) return [];
  const found = [];
  // 따옴표 문자열과 백틱 템플릿을 모은다.
  for (const match of trimmed.matchAll(/"([^"\\]*(?:\\.[^"\\]*)*)"|'([^'\\]*(?:\\.[^'\\]*)*)'|`([^`]*)`/g)) {
    const value = match[1] ?? match[2] ?? match[3] ?? "";
    if (value) found.push(value);
  }
  return found;
}

const offenders = [];
for (const dir of SCAN_DIRS) {
  for (const file of walk(join(ROOT, dir))) {
    const rel = relative(ROOT, file).replaceAll("\\", "/");
    const source = readFileSync(file, "utf8");
    stripComments(source)
      .split(/\r?\n/)
      .forEach((line, index) => {
        const old = OLD_TERMS.find(({ term, pattern, except = [] }) => (pattern ? pattern.test(line) : line.includes(term)) && !except.includes(rel));
        if (old) offenders.push({ file: rel, line: index + 1, word: `옛 말 「${old.term}」 → 「${old.use}」 (27차 §3-E)`, text: line.trim().slice(0, 80) });
      });
    if (ALLOWED_FILES.some((allowed) => rel.startsWith(allowed))) continue;
    const lines = source.split(/\r?\n/);
    const bans = BANNED_PHRASES.filter((ban) => ban.files.some((prefix) => rel.startsWith(prefix)));
    lines.forEach((line, index) => {
      if (!isCodeLine(line)) return;
      for (const ban of bans) {
        if (ban.pattern.test(line)) offenders.push({ file: rel, line: index + 1, word: ban.reason, text: line.trim().slice(0, 80) });
      }
    });
    lines.forEach((line, index) => {
      for (const text of screenStrings(line)) {
        if (!HAS_KOREAN.test(text)) continue; // 코드 식별자·클래스 이름은 화면 글자가 아니다
        const banned = SCREEN_TEXT_BANS.find((ban) => ban.pattern.test(text));
        if (banned) {
          offenders.push({ file: rel, line: index + 1, word: banned.reason, text: text.slice(0, 80) });
          return;
        }
        for (const word of FORBIDDEN) {
          const pattern = new RegExp(`(^|[^A-Za-z_])${word}([^A-Za-z_]|$)`);
          if (pattern.test(text)) {
            offenders.push({ file: rel, line: index + 1, word, text: text.slice(0, 80) });
            return;
          }
        }
      }
    });
  }
}

/*
 * 백엔드가 만드는 화면 문장도 본다 (27차 §3-E 검수 R27U-MSC-03) — 「RFP 분석 전에는 미계산 — 요구사항 매트릭스를 …」이
 * 레이더 · 사업기회 「점수 산정 근거」에 그대로 나왔는데 검사는 frontend/src 만 봤다. 파이썬 주석(#)과 삼중 따옴표
 * 문서 문자열은 빼고, 한국어가 든 따옴표 문자열에서 옛 말 · 설정 이름 꼴을 찾는다.
 */
const BACKEND_ROOT = fileURLToPath(new URL("../backend/app", import.meta.url));
const TRIPLE = /"""|'''/g;
function walkPy(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) {
      if (name !== "__pycache__") out.push(...walkPy(full));
    } else if (name.endsWith(".py")) out.push(full);
  }
  return out;
}
for (const file of walkPy(BACKEND_ROOT)) {
  const rel = "backend/app/" + relative(BACKEND_ROOT, file).replaceAll("\\", "/");
  let inDoc = false;
  readFileSync(file, "utf8").split(/\r?\n/).forEach((raw, index) => {
    const quotes = (raw.match(TRIPLE) || []).length;
    const wasDoc = inDoc;
    if (quotes % 2 === 1) inDoc = !inDoc;
    if (wasDoc || quotes > 0) return; // 문서 문자열 줄
    if (raw.includes("화면 문장 아님")) return; // 서버 로그 · 모델 지시문 — 그 줄에 적어 둔다
    const line = raw.replace(/(^|\s)#.*$/, "");
    for (const match of line.matchAll(/"([^"\\]*(?:\\.[^"\\]*)*)"|'([^'\\]*(?:\\.[^'\\]*)*)'/g)) {
      const text = match[1] ?? match[2] ?? "";
      if (!HAS_KOREAN.test(text)) continue;
      const old = OLD_TERMS.find(({ term, pattern }) => (pattern ? pattern.test(text) : text.includes(term)));
      if (old) offenders.push({ file: rel, line: index + 1, word: `옛 말 「${old.term}」 → 「${old.use}」`, text: text.slice(0, 80) });
      const banned = SCREEN_TEXT_BANS.find((ban) => ban.pattern.test(text));
      if (banned) offenders.push({ file: rel, line: index + 1, word: banned.reason, text: text.slice(0, 80) });
    }
  });
}

console.log(`화면 어휘 검사 — frontend/src (${SCAN_DIRS.join(" · ")}) · backend/app 화면 문장`);
if (offenders.length === 0) {
  console.log("  ✓ 한국어 문장 안에 영문 판정값이 없습니다");
} else {
  for (const item of offenders) {
    console.log(`  ✗ ${item.file}:${item.line} — 「${item.word}」`);
    console.log(`      ${item.text}`);
  }
}
console.log(`\n${offenders.length === 0 ? "✓" : "✗"} 화면 어휘 — 새는 곳 ${offenders.length}건`);
process.exit(offenders.length === 0 ? 0 : 1);
