/**
 * 공고 첨부 내려받기 링크 (20차 §4-E · 담당자 「공고문 hwp, pdf를 직접 다운받을 수 있는 링크도 추가」).
 *
 * 링크는 **원본 주소만** 건다 — 로컬 캐시(`data/public/real_rfp/`)는 내보내지 않는다.
 * 나라장터 첨부는 백엔드 `attachment_service.is_allowed_url` 과 같은 규칙(https + g2b.go.kr)을
 * 통과할 때만 링크가 된다. 거절되면 이름만 적고 그 주소(도메인)는 화면에 적지 않는다.
 */

/** 형식 칩에 적는 확장자 — 무엇으로 열어야 하는 파일인지 이름을 끝까지 읽지 않아도 알게 한다. */
export const ATTACHMENT_EXTS = ["hwpx", "hwp", "pdf", "zip", "docx", "xlsx", "pptx"] as const;

export interface AttachmentLink {
  name: string;
  /** 소문자 확장자(알려진 것만). 모르면 null. */
  ext: string | null;
  /** 내려받기 주소. 허용하지 않는 주소면 null — 이름만 적는다. */
  href: string | null;
}

const G2B_HOST = "g2b.go.kr";

/** 나라장터 첨부 주소가 링크로 걸어도 되는가 — https 이고 g2b.go.kr(또는 그 하위)일 때만. */
export function isAllowedAttachmentUrl(url: string): boolean {
  let parsed: URL;
  try {
    parsed = new URL(url.trim());
  } catch {
    return false;
  }
  if (parsed.protocol !== "https:") return false;
  const host = parsed.hostname.toLowerCase().replace(/\.$/, "");
  return host === G2B_HOST || host.endsWith(`.${G2B_HOST}`);
}

export function attachmentExt(name: string): string | null {
  const match = /\.([A-Za-z0-9]{2,5})\s*$/.exec(name);
  const ext = match ? match[1].toLowerCase() : null;
  return ext && (ATTACHMENT_EXTS as readonly string[]).includes(ext) ? ext : null;
}

/** 나라장터 첨부 하나 → 이름 · 형식 · 링크(허용될 때만). */
export function attachmentLinkOf(file: { name: string; url: string }): AttachmentLink {
  return {
    name: file.name,
    ext: attachmentExt(file.name),
    href: file.url && isAllowedAttachmentUrl(file.url) ? file.url.trim() : null,
  };
}
