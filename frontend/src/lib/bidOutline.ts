/**
 * 입찰 제안서 「이 양식으로 씁니다」(11-06 갈래 B-2) — 미리 보기 · 초안 머리 줄의 문장 만들기 · 경고 고르기.
 *
 * 화면(/plan `BidWriter`)은 이 함수 결과만 그린다. 값은 서버(`outline_preview` · 저장된 초안)가 원문에서 읽은 것 그대로이고
 * 여기서 새 판단을 하지 않는다 — 문장으로 옮기고, 앱이 맞추는 것과 사람이 직접 맞출 것을 가를 뿐이다.
 */

import { ApiError, type BidFormatRules, type BidOutlinePreview, type BidOutlineRejected, type BidOutlineWhere, type BidPlanView } from "@/lib/api";
import { describeFailure } from "@/lib/errors";

export type ExportVariant = "submit" | "review" | "blind";

/** 한 줄 + 경고 색으로 그릴지. */
export interface OutlineLine {
  text: string;
  warn: boolean;
}

/** 형식 규정 한 줄 — `manual` 이면 앱이 만들지 못해 사람이 직접 맞춘다. */
export interface FormatLine {
  text: string;
  manual: boolean;
}

export const OLD_DRAFT_NOTE = "예전 방식으로 쓴 초안 — 다시 쓰면 공고 양식으로 씁니다";
export const OUTLINE_SESSION = "세션이 끝났습니다 — 새 탭에서 다시 로그인한 뒤 「다시 읽기」를 누르세요";
export const NO_FORMAT_RULES = "원문에서 쪽수 · 회사명 표기 같은 형식 규정을 찾지 못했습니다";

/** 「1_제안요청서(KISA).hwpx」 · 「첨부.zip > 2_과업지시서.pdf」 → 「제안요청서(KISA)」 · 「과업지시서」. */
export function documentLabel(name: string | null | undefined): string {
  const last = (name ?? "").split(" > ").pop() ?? "";
  return last.replace(/\.(hwpx|hwp|pdf|docx|doc|zip|txt)$/i, "").replace(/^\d{1,2}[_.\s-]+/, "").trim() || "원문";
}

/** 「제안요청서 31쪽」 · 쪽을 모르면 「제안요청서」. */
export function whereText(where: BidOutlineWhere | null | undefined): string {
  if (!where) return "원문";
  const doc = documentLabel(where.document);
  return where.page ? `${doc} ${where.page}쪽` : doc;
}

/** 목차 한 줄 — 「Ⅰ. 제안개요」 · 번호 없는 대항목(「제안사」)은 제목만 · 「1)」 「가.」처럼 끝맺은 번호는 그대로. */
export function entryLabel(no: string | null | undefined, title: string): string {
  const mark = (no ?? "").trim();
  if (!mark) return title;
  return /[.)]$/.test(mark) ? `${mark} ${title}` : `${mark}. ${title}`;
}

export function outlineCounts(outline: BidOutlinePreview["outline"]): { majors: number; minors: number } {
  return { majors: outline.length, minors: outline.reduce((sum, major) => sum + (major.items?.length ?? 0), 0) };
}

/** 목차 줄 — 어디서 읽은 목차로 쓰나(표준 목차면 경고 색). */
export function outlineLine(preview: Pick<BidOutlinePreview, "outline_source" | "outline" | "outline_where" | "outline_found_at">): OutlineLine {
  const { majors, minors } = outlineCounts(preview.outline);
  const count = `대항목 ${majors} · 소항목 ${minors}`;
  if (preview.outline_source === "rfp") {
    const where = preview.outline_where;
    const head = where?.head ? ` 「${where.head}」의 목차로` : "의 제안서 목차로";
    return { text: `${where ? whereText(where) : "제안요청서"}${head} 씁니다 — ${count}`, warn: false };
  }
  if (preview.outline_source === "unread") {
    return { text: `${unreadOutline(preview.outline_found_at)} 표준 목차로 씁니다(${count}) — 원문 목차와 맞춰 보세요`, warn: true };
  }
  return { text: `원문에 제안서 목차가 없어 표준 목차로 씁니다(${count})`, warn: true };
}

/** 「제안요청서 31쪽의 제안서 목차를 읽지 못해」 — 머리는 찾았는데 읽지 못한 곳(서버 `outline_found_at`). */
function unreadOutline(foundAt: BidOutlineWhere | null | undefined): string {
  return foundAt?.page ? `${whereText(foundAt)}의 제안서 목차를 읽지 못해` : "원문의 제안서 목차를 읽지 못해";
}

/** 평가표 줄 — 「기술평가 n항목 · m점 — 조견표로 넣습니다」 · 못 읽었으면 경고. */
export function evaluationLine(evaluation: BidOutlinePreview["evaluation"]): OutlineLine {
  const items = evaluation.items ?? [];
  if (items.length === 0) {
    const where = evaluation.where ? `${whereText(evaluation.where)} 평가표` : "원문의 평가표";
    return { text: `평가표를 읽지 못했습니다 — ${where}를 확인하세요`, warn: true };
  }
  const quantitative = items.filter((item) => item.kind === "정량").length;
  const points = evaluation.total != null ? ` · ${evaluation.total}점` : "";
  const label = quantitative ? `평가 ${items.length}항목(정성 ${items.length - quantitative} · 정량 ${quantitative})` : `기술평가 ${items.length}항목`;
  return { text: `${label}${points} — 조견표로 넣습니다`, warn: false };
}

/** 이미 쓴 초안이 2.11.0 형식 칸(원본 · 사본 · 목차 요구) 전에 쓰였을 때 — 내려받는 파일은 초안을 쓸 때 저장한 형식을 따른다. */
export const BEFORE_RULE_NOTE = "지금 초안은 이 규칙 전에 써서 받는 파일에 아직 없을 수 있습니다(다시 쓰면 들어갑니다)";

/** 형식 규정 줄 — 앱이 맞추는 것(쪽수 · 평가본)과 직접 맞춰야 할 것(가로 · PPT · 두 권).
 *  `saved` = 이미 쓴 초안의 저장 형식(초안이 없으면 undefined) — 원본 · 사본 칸이 없으면 2.11.0 전 초안이라 두 「앱이 넣는다」 줄에 그 말을 붙인다. */
export function formatLines(format: BidFormatRules | null | undefined, saved?: Partial<BidFormatRules> | null): FormatLine[] {
  if (!format) return [];
  const lines: FormatLine[] = [];
  const before = saved != null && saved.original_copy === undefined ? ` · ${BEFORE_RULE_NOTE}` : "";
  if (format.page_limit) lines.push({ text: `${format.page_limit}쪽 이내로 냅니다 — 소항목 분량을 그에 맞춥니다`, manual: false });
  if (format.blind) {
    lines.push(
      isBlindOnly(format)
        ? { text: "이 공고는 회사명 없는 평가본만 냅니다 — 「제출용」 파일이 평가본이고 회사명 포함본은 내지 않습니다", manual: false }
        : { text: "평가본에는 회사명 · 대표자를 넣지 않습니다 — 「평가본」 파일을 따로 받으세요", manual: false },
    );
    // 원문 규정(연혁 · 실적 · 회사소개까지 막기도 함)은 앱이 다 맞추지 못한다 — 원문을 그대로 보여 사람이 맞춘다(11-06 검토 #17)
    const note = format.blind_note?.trim();
    // 자르지 않는다 — 끝에 무엇을 금지하는지가 온다(서버가 이미 120자로 자름 · 검토 11-06 round3 #8)
    if (note) lines.push({ text: `원문: ${note}`, manual: true });
    // 설립일 · 연혁은 앱이 빼고(2.10.0 D5) 회사 이름 · 연락처 · 번호 · 실적 기관 이름은 품질 검사가 찾는다(D7)
    lines.push({
      text: "평가본에 영문 회사 이름 · 로고 · 인증 이름 속 회사 표기가 남지 않았는지 직접 확인하세요 — 회사 이름 · 대표자 · 연락처 · 번호 · 실적 기관 이름은 앱이 찾아 품질 검사에 알립니다",
      manual: true,
    });
  }
  // 2.11.0 T3 · D2 — 원본 · 사본 표시와 목차 쪽은 앱이 넣는다(서버 `plan_export_service.document_blocks`)
  if (format.original_copy) {
    lines.push({ text: `표지에 원본 · 사본을 적습니다 — 「제출용」은 「제안서(원본)」, 「평가본」은 「제안서(사본)」${before}`, manual: false });
  }
  if (format.toc_required) lines.push({ text: `원문이 목차를 요구합니다 — 제출용 · 평가본 표지 다음에 목차 쪽(쪽 번호 없이)을 넣습니다${before}`, manual: false });
  if (format.landscape) lines.push({ text: "A4 가로로 내야 합니다 — 받은 파일은 세로라 한글 · 워드에서 쪽 방향을 바꾸세요", manual: true });
  if (format.ppt) lines.push({ text: "발표 자료(PPT) 꼴로 내야 합니다 — 이 초안을 바탕으로 발표 자료를 직접 만드세요", manual: true });
  if (format.two_volume) {
    const volumes = format.volumes?.length ? `(${format.volumes.join(" · ")})` : "";
    lines.push({ text: `정량 · 정성 제안서를 따로 냅니다${volumes} — 이 초안은 정성(사업내용) 제안서입니다`, manual: true });
  }
  const cover = format.cover_form;
  if (cover?.line?.trim()) {
    // 2.11.0 T3b — 앱 표지는 앱 꼴이다(검토 목록 「표지 서식」 줄과 같은 말)
    const where = cover.document && cover.page ? ` · ${documentLabel(cover.document)} ${cover.page}쪽` : "";
    lines.push({ text: `원문이 제안서 표지 서식을 정했습니다(「${cover.line.trim()}」${where}) — 한글에서 그 서식의 칸 · 순서로 표지를 바꾸세요(앱 표지는 앱 꼴)`, manual: true });
  }
  return lines;
}

/** 쓰지 않은 목차 후보 한 줄 — 머리 줄이 문서 목차 한 줄 통째(백 자 넘음)일 수 있어 앞 40자만. */
export function rejectedLine(rejected: BidOutlineRejected): string {
  const head = rejected.head.length > 40 ? `${rejected.head.slice(0, 40)}…` : rejected.head;
  return `${rejected.page ? `${rejected.page}쪽 ` : ""}「${head}」 — ${rejected.reason}`;
}

/** 「읽은 원문: 사전규격 규격서 1 전체 22쪽 · 공고서 전체 10쪽」. */
export function documentsLine(documents: BidOutlinePreview["documents"]): string {
  return `읽은 원문: ${documents.map((doc) => `${documentLabel(doc.name)}${doc.pages ? ` 전체 ${doc.pages}쪽` : ""}`).join(" · ")}`;
}

/** 이미 쓴 초안의 머리 줄 — 저장된 양식 값으로. 이 칸이 없는 초안은 예전 방식이라 다시 쓰라고 한다. */
export function draftOutlineLine(
  doc: Pick<BidPlanView, "outline_source" | "evaluation_total" | "rfp_document" | "outline_where" | "outline_found_at" | "format">,
): OutlineLine {
  if (doc.outline_where === undefined && doc.format === undefined) return { text: OLD_DRAFT_NOTE, warn: true };
  const where = doc.outline_where;
  const outline =
    doc.outline_source === "rfp"
      ? `${where ? whereText(where) : "제안요청서"}${where?.head ? ` 「${where.head}」의` : "의 제안서"} 목차대로 썼습니다`
      : doc.outline_source === "unread"
        ? `${unreadOutline(doc.outline_found_at)} 표준 목차로 썼습니다 — 원문 목차와 맞춰 보세요`
        : "원문에 제안서 목차가 없어 표준 목차로 썼습니다";
  const parts = [outline];
  if (doc.evaluation_total) parts.push(`기술능력 평가 기준 ${doc.evaluation_total}점 반영`);
  if (doc.format?.page_limit) parts.push(`${doc.format.page_limit}쪽 이내에 맞춤`);
  if (!where && doc.rfp_document) parts.push(`원문 ${doc.rfp_document}`);
  return { text: parts.join(" · "), warn: doc.outline_source !== "rfp" };
}

/** (2.10.0 D8) 회사명 판 이름 — 원문이 평가본만 받는 공고에서 내지 않는 판(서버 `plan_export_service.WITH_NAME_LABEL` 과 같은 글). */
export const WITH_NAME_LABEL = "회사명 포함본";
export const WITH_NAME_TITLE = "회사명이 든 판 — 이 공고는 제출 제안서에 회사 식별 정보를 막아 이 판은 내지 않습니다(내부 보관용)";
export const BLIND_SUBMIT_TITLE =
  "제출할 판 — 회사 이름 · 대표자 · 연락처 · 설립일 · 연혁을 뺀 평가본입니다(이 공고는 원본 · 사본 구분 없이 평가본만 받습니다)";

/** 원문이 평가본만 받는가(평가본 규정에 원본 · 사본 구분 없음 · 서버 `format.blind_only`) — 칸이 없는 옛 초안은 아니다. */
export function isBlindOnly(format: BidFormatRules | null | undefined): boolean {
  return Boolean(format?.blind && format.blind_only);
}

/** 내려받기 판 — 원문이 평가본에 회사명 표기를 막으면 「평가본」을 더한다 · 평가본만 받는 공고는 평가본이 첫 단추(D8). */
export function downloadVariants(format: BidFormatRules | null | undefined): readonly ExportVariant[] {
  if (isBlindOnly(format)) return ["blind", "review", "submit"];
  return format?.blind ? ["submit", "review", "blind"] : ["submit", "review"];
}

/** 판 이름(받는 파일 이름 머리) — 서버 `plan_export_service.variant_label` 과 같은 규칙. fileLabel = 품질 게이트 「초안」 · 「제출용」.
 *  평가본만 받는 공고(`only`)는 평가본이 「제출용」 · 「초안」이고 회사명 판은 「회사명 포함본」. */
export function variantName(variant: ExportVariant, fileLabel: "초안" | "제출용", only: boolean): string {
  if (variant === "review") return "검토용";
  if (only) return variant === "submit" ? WITH_NAME_LABEL : fileLabel;
  return variant === "blind" ? "평가본" : fileLabel;
}

/** 단추 옆 판 이름 — 평가본은 「(회사명 없음)」을 붙인다. */
export function variantButtonLabel(variant: ExportVariant, fileLabel: "초안" | "제출용", only: boolean): string {
  if (variant === "blind") return `${only ? fileLabel : "평가본"}(회사명 없음)`;
  return variantName(variant, fileLabel, only);
}

/** 미리 보기를 못 읽은 까닭 — 401 은 저장하지 않는 이 칸에 맞는 문장으로(공통 문장은 「저장하지 못했습니다」로 시작함). */
export function outlineFailureText(error: unknown): string {
  if (error instanceof ApiError && error.status === 401 && !error.detail?.startsWith("계정이 꺼졌습니다")) return OUTLINE_SESSION;
  return describeFailure(error, "제안서 양식을 읽지 못했습니다.");
}
