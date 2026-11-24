"use client";

/**
 * 지원사업 신청 계획표 — 신청자격 / 필수·우대조건 / 신청기간 / 제출서류.
 *
 * 원칙 (backend `support_application_service` 와 같다):
 * - 기업마당 목록 원문에 없는 조건은 **지어내지 않는다**. `status="unknown"` 은 값 대신
 *   「원문 상세 확인 필요」로 남긴다.
 * - 값이 어느 원문 필드에서 왔는지(`source_field`)는 지우지 않고 헤더의 「원문 필드」 팝오버로 모은다.
 * - 입찰 용어(입찰자격·낙찰·투찰·RFP·제안서)를 쓰지 않는다.
 *
 * 정보량 규칙
 * - 한 번에 **한 단계**만 그린다 (`step` 으로 받은 묶음). 4묶음을 동시에 펼치지 않는다.
 * - 「원문 상세 확인 필요 — …」 같은 공통 문장은 항목마다 반복하지 않는다. 상단 경고에서 한 번만
 *   말하고, 항목에는 작은 `확인 필요` 상태 표시만 둔다(자세한 문장은 배지 툴팁).
 */

import { SUPPORT_SECTION_SCROLL_MT, supportSectionId } from "@/components/support/SupportStepBar";
import { Popover } from "@/components/ui/overlays";
import AnnexFetch from "@/components/support/AnnexFetch";
import AttachmentLinks from "@/components/ui/AttachmentLinks";
import { Badge, Panel, SectionHeader } from "@/components/ui/primitives";
import { tintStyle } from "@/lib/cosmos/format";
import { TONE_COLORS } from "@/lib/cosmos/theme";
import { FIRST_SUPPORT_LINE, SUPPORT_DEADLINE_LINE } from "@/lib/terms";
import type {
  SupportApplicationResult,
  SupportAttachment,
  SupportRequirementItem,
  SupportStepKey,
} from "@/types/opportunity";

/** 계획표의 네 묶음. key 는 plan 의 키이자 진행 바 단계 key 와 같다. */
export type PlanGroupKey = "eligibility" | "conditions" | "schedule" | "documents";

const PLAN_GROUPS: Array<{ key: PlanGroupKey; title: string; description: string }> = [
  {
    key: "eligibility",
    title: "신청자격",
    // 공고문을 읽은 사업에도 맞는 말로 — 「목록 정보에 없는 조건」은 공고문 조항을 읽은 사업에서 틀린 말이었다 (27차 SUP-22).
    description: `지원 대상·신청 가능 기업 유형·지역과 공고문 조항. 원문에서 확인하지 못한 조건은 채우지 않고 확인 대상으로 남깁니다. ${FIRST_SUPPORT_LINE}`,
  },
  {
    key: "conditions",
    title: "필수·우대조건",
    description: "지원 분야와 사업 개요는 원문에서, 지원 방식·규모·자부담·우대조건은 기업마당 목록에 없으므로 공고 원문에서 확인해야 합니다.",
  },
  {
    key: "schedule",
    title: "신청기간",
    description: `접수 기간과 접수 방법. 「상시 접수」·「예산 소진시까지」처럼 날짜가 없는 표기도 원문 그대로 남깁니다. ${SUPPORT_DEADLINE_LINE}`,
  },
  {
    key: "documents",
    title: "제출서류",
    description: "신청 서식·공고문·문의처. 제출서류는 신청방법 원문에 적힌 문장만 옮긴 것이며 전체 목록은 공고문에서 확인해야 합니다.",
  },
];

const PLAN_GROUP_KEYS: PlanGroupKey[] = PLAN_GROUPS.map((group) => group.key);

export function isPlanGroupKey(step: SupportStepKey): step is PlanGroupKey {
  return (PLAN_GROUP_KEYS as SupportStepKey[]).includes(step);
}

/** backend 가 미확인 항목마다 붙이는 공통 문장 — 화면에서 반복하지 않는다. */
const GENERIC_UNKNOWN_NOTE = /^원문 상세 확인 필요/;

const UNKNOWN_HINT =
  "원문 상세 확인 필요 — 현재 기업마당 목록 정보만으로는 판정할 수 없습니다. 공고 원문·첨부 공고문에서 확인하세요.";

/** 공고문 조항(`clause_*`)은 공고문을 읽고도 못 찾은 것이다 — 「목록 정보만으로는」이라고 하지 않는다 (27차 SUP-22). */
const CLAUSE_UNKNOWN_HINT = "원문 상세 확인 필요 — 공고문에서 이 조항을 찾지 못했습니다. 공고 원문·첨부 공고문에서 직접 확인하세요.";

function unknownHint(item: SupportRequirementItem): string {
  return item.key.startsWith("clause_") ? CLAUSE_UNKNOWN_HINT : UNKNOWN_HINT;
}

const HTTP_URL = /^https?:\/\/\S+$/i;

const HTML_ENTITIES: Record<string, string> = {
  "&nbsp;": " ",
  "&amp;": "&",
  "&lt;": "<",
  "&gt;": ">",
  "&quot;": '"',
  "&#39;": "'",
  "&apos;": "'",
};

/**
 * 기업마당 원문(사업 개요 등)은 HTML 조각으로 온다. 표시할 때만 태그를 걷어내고
 * 줄바꿈으로 바꾼다 — 문장은 그대로 두며, 없는 내용을 만들지 않는다.
 * (HTML을 그대로 삽입하지 않는다 — dangerouslySetInnerHTML 금지.)
 */
export function plainText(value: string): string {
  if (!/<[a-z/!][^>]*>|&[a-z#0-9]+;/i.test(value)) return value;
  return value
    .replace(/<\s*br\s*\/?>/gi, "\n")
    .replace(/<\/\s*(p|div|li|tr|h[1-6]|blockquote)\s*>/gi, "\n")
    .replace(/<[^>]*>/g, "")
    .replace(/&[a-z#0-9]+;/gi, (entity) => HTML_ENTITIES[entity.toLowerCase()] ?? entity)
    .replace(/[ \t ]+/g, " ")
    .split("\n")
    .map((line) => line.trim())
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function ItemValue({ item }: { item: SupportRequirementItem }) {
  if (item.status === "unknown" || !item.value) {
    return (
      <p
        className="inline-flex items-start gap-1.5 rounded-lg border px-2 py-1 text-[12.5px] font-medium leading-5"
        style={tintStyle(TONE_COLORS.warn)}
        title={unknownHint(item)}
      >
        <span aria-hidden="true" className="mt-px text-[12px] leading-4">
          !
        </span>
        확인 필요
      </p>
    );
  }

  if (HTTP_URL.test(item.value)) {
    return (
      <a
        href={item.value}
        target="_blank"
        rel="noreferrer noopener"
        className="mc-focus inline-block max-w-full break-all rounded text-[13px] leading-5 text-cosmos-cyan underline underline-offset-2 hover:brightness-110"
      >
        {item.value}
        <span aria-hidden="true"> ↗</span>
      </a>
    );
  }

  return <p className="whitespace-pre-line break-words text-[13px] leading-5 text-cosmos-text">{plainText(item.value)}</p>;
}

function PlanItem({ item }: { item: SupportRequirementItem }) {
  const confirmed = item.status === "confirmed" && Boolean(item.value);
  // 공통 안내 문장은 상단 경고에서 한 번만 말한다 — 항목마다 되풀이하지 않는다.
  const note = item.note && !GENERIC_UNKNOWN_NOTE.test(item.note) ? item.note : null;

  return (
    <li className="grid gap-1 border-t border-cosmos-border py-2.5 first:border-t-0 first:pt-0 sm:grid-cols-[minmax(120px,170px)_minmax(0,1fr)] sm:gap-x-4">
      <span
        className="text-[12.5px] font-semibold leading-5 text-cosmos-text"
        title={
          confirmed
            ? `기업마당 원문에서 확인된 값${item.source_field ? ` · 값 출처 ${item.source_field}` : ""}`
            : unknownHint(item)
        }
      >
        {item.label}
      </span>
      <div className="flex min-w-0 flex-col gap-1">
        <ItemValue item={item} />
        {note && <p className="break-words text-[12px] leading-5 text-cosmos-muted">{note}</p>}
      </div>
    </li>
  );
}

/**
 * 어느 원문 필드에서 읽은 값인지 — 항목마다 한 줄씩 늘어놓지 않고 여기에 모은다.
 *
 * 여는 단추의 「{}」 글리프는 뺐다 (0925 §4-F-5 · ISSUE-107). 「필드」를 뜻하는
 * 장식이었지만 화면에서는 **값이 새어 나온 것**으로 읽힌다 — 검수자가 실제로 그렇게
 * 읽고 「리터럴 노출」로 적어 왔다. 이름표 「원문 필드」가 같은 말을 이미 한다.
 * `scripts/check_visibility.mjs` 가 `{}`·`[]`·`null`·`undefined` 텍스트 노드를 센다.
 */
function SourceFieldPopover({ items }: { items: SupportRequirementItem[] }) {
  return (
    <Popover
      trigger={<>값 출처</>}
      triggerLabel="이 단계의 값을 읽어 온 기업마당 항목 보기"
      title="기업마당 값 출처"
      align="end"
      width="320px"
    >
      <p className="text-cosmos-muted">각 값을 어느 응답 필드에서 읽었는지입니다. 필드가 없으면 원문에서 직접 확인해야 하는 항목입니다.</p>
      <ul className="flex flex-col gap-1">
        {items.map((item) => (
          <li key={item.key} className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5">
            <span className="text-[12px] font-semibold text-cosmos-text">{item.label}</span>
            <span className="min-w-0 break-all font-mono text-[12px] text-cosmos-muted">
              {item.source_field ?? "항목 없음 — 공고 원문 확인"}
            </span>
          </li>
        ))}
      </ul>
    </Popover>
  );
}

/** 첨부 종류 배지 — 이름으로 단 종류(30차 §3-A · 과제소개서에 「신청 서식」이 붙었다). */
const ATTACHMENT_BADGES: Record<SupportAttachment["kind"], { label: string; tone: "info" | "muted" | "pass" }> = {
  annex: { label: "과제소개서", tone: "pass" },
  manual: { label: "신청 매뉴얼", tone: "muted" },
  form: { label: "신청 서식", tone: "info" },
  notice: { label: "공고문", tone: "muted" },
};

function AttachmentList({ attachments, collapseAfter, programId }: { attachments: SupportAttachment[]; collapseAfter?: number; programId?: string }) {
  if (attachments.length === 0) return null;
  return (
    <div className="mt-3 border-t border-cosmos-border pt-3">
      <p className="text-[12px] font-semibold text-cosmos-text">공고 첨부파일 (기업마당 원문)</p>
      {/* 나라장터 첨부와 **같은 부품**이다 (20차 §4-E-3) — 두 화면의 내려받기 줄이 같은 모양이어야 한다. */}
      <div className="mt-1.5">
        <AttachmentLinks
          collapseAfter={collapseAfter}
          items={attachments.map((file) => ({
            key: `${file.kind}:${file.url}`,
            name: file.name,
            ext: file.ext ?? null,
            href: file.url,
            badge: <Badge tone={(ATTACHMENT_BADGES[file.kind] ?? ATTACHMENT_BADGES.form).tone}>{(ATTACHMENT_BADGES[file.kind] ?? ATTACHMENT_BADGES.form).label}</Badge>,
            // 기업마당이 준 원래 주소는 뷰어다. 내려받기가 막힌 환경을 위해 보조로만 남긴다.
            extra: file.view_url ? (
              <a
                href={file.view_url}
                target="_blank"
                rel="noreferrer noopener"
                className="mc-focus shrink-0 rounded text-[12px] leading-5 text-cosmos-secondary underline underline-offset-2 hover:text-cosmos-text"
                title="기업마당 뷰어로 열기"
              >
                보기
              </a>
            ) : undefined,
          }))}
        />
      </div>
      <p className="mt-2 text-[12px] leading-4 text-cosmos-muted">
        파일 이름을 누르면 기업마당에서 바로 내려받습니다. 「보기」는 기업마당 뷰어로 엽니다. 시스템이 서식을 대신
        작성하거나 제출하지 않습니다.
      </p>
      {programId && attachments.some((file) => file.kind === "annex") && (
        <div className="mt-2">
          <AnnexFetch programId={programId} />
        </div>
      )}
    </div>
  );
}

export default function SupportPlanPanel({
  step,
  plan,
  attachments,
  collapseAttachmentsAfter,
  showSourceFields = true,
  programId,
}: {
  step: SupportStepKey;
  plan: SupportApplicationResult["plan"];
  attachments: SupportAttachment[];
  /** 주면 과제소개서 첨부 옆에 「과제소개서 받기」(30차 §3-A) — 쉬운 보기는 컨트롤 상한 때문에 주지 않는다. */
  programId?: string;
  /** 쉬운 보기(24차): 첨부를 앞 n개만 보이고 나머지는 「첨부 m개 더 ▸」로 접는다. 없으면 전부 */
  collapseAttachmentsAfter?: number;
  /** 「원문 필드」(영문 응답 필드 이름) — 쉬운 보기에서는 숨긴다(전체 보기에 그대로 있다 · 27차 SUP-15). */
  showSourceFields?: boolean;
}) {
  if (!isPlanGroupKey(step)) return null;

  const group = PLAN_GROUPS.find((entry) => entry.key === step);
  if (!group) return null;

  const items = plan[group.key];
  const headingId = `${supportSectionId(group.key)}-title`;

  return (
    <div id={supportSectionId(group.key)} className={`min-w-0 ${SUPPORT_SECTION_SCROLL_MT}`}>
      <Panel ariaLabelledBy={headingId}>
        {/* 「원문 필드」는 줄 오른쪽 끝에 — 좁은 폭에서 줄이 바뀌면 왼쪽 끝으로 내려가 팝오버가 창 왼쪽 밖으로 열렸다 (27차 SUP-05). */}
        <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
          <SectionHeader id={headingId} eyebrow="신청 분석" title={group.title} description={group.description} />
          {showSourceFields && (
            <span className="ml-auto">
              <SourceFieldPopover items={items} />
            </span>
          )}
        </div>
        <ul className="mt-3 flex flex-col">
          {items.map((item) => (
            <PlanItem key={item.key} item={item} />
          ))}
        </ul>
        {group.key === "documents" && <AttachmentList attachments={attachments} collapseAfter={collapseAttachmentsAfter} programId={programId} />}
      </Panel>
    </div>
  );
}
