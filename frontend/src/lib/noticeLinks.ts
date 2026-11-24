/**
 * 입찰 분석의 「나라장터 공고 원문 ↗ · 제안요청서 내려받기 ↗」(2.9.1 · 대표 11-13 「입찰분석에서도 공고 링크랑 제안요청서 다운받을수 있도록」).
 *
 * 링크는 원본(나라장터) 주소만 건다 — 앱이 받아 둔 사본은 내보내지 않는다(20차 §4-E-1 · `lib/attachments`).
 * 제안요청서는 첨부 목록 API(`/api/procurements/{id}/attachments`)가 고른 것 — 본공고 첨부가 공고서뿐이면 연결된
 * 사전규격 규격서(제안요청서)까지 붙여 고른다(11-03). 공고문으로 골라졌으면(제안요청서가 없음) 제안요청서라고 부르지 않는다.
 */
import { attachmentLinkOf, isAllowedAttachmentUrl, type AttachmentLink } from "@/lib/attachments";
import type { NoticeAttachmentList } from "@/lib/api";

/** 공고 원문 링크 — 나라장터 https 주소만(첨부 링크와 같은 규칙). 아니면 null. */
export function noticeSourceHref(url: string | null | undefined): string | null {
  return url && isAllowedAttachmentUrl(url) ? url.trim() : null;
}

export interface RfpLink extends AttachmentLink {
  href: string;
  /** 본공고가 아니라 연결된 사전규격에 붙은 문서(「사전규격 규격서 n(번호)」)인가 */
  fromPrespec: boolean;
}

/** 첨부 목록 → 내려받을 제안요청서 하나. 고른 첨부가 없거나 · 공고문이거나 · 링크로 걸 수 없는 주소면 null. */
export function rfpLinkOf(list: NoticeAttachmentList | null | undefined): RfpLink | null {
  if (!list || list.rfp_index === null) return null;
  const file = list.attachments.find((item) => item.index === list.rfp_index);
  if (!file || file.document_role === "notice" || list.rfp_index === list.notice_index) return null;
  // 압축은 안을 열어야 안다(document_role null) — 이름에 제안요청 · 과업 · 사전규격이 없으면 공고 묶음일 수 있어 부르지 않는다(2.9.1 검토)
  if (file.document_role == null && !/제안요청|과업|사전규격/.test(file.name.replace(/\s+/g, ""))) return null;
  const link = attachmentLinkOf(file);
  if (!link.href) return null;
  return { ...link, href: link.href, fromPrespec: /^사전규격\s*규격서/.test(file.name.trim()) };
}
