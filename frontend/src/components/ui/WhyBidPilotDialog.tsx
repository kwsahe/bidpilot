"use client";

/**
 * 「왜 BidPilot인가」 — 제품 정의를 설명하는 **단 하나의** 안내 대화상자.
 * 모든 화면(대시보드 상단·AppShell 헤더)의 「?」가 같은 내용을 연다. 수치는 넣지 않는다 (측정 전 성과 주장 금지).
 *
 * 여기에 «처음 순서 5단계»와 «GPT로 직접 할 때와의 차이»를 함께 둔 이유:
 * 안내가 다섯 갈래(환영 대화상자 / 30초 안내 / 상세 튜토리얼 / 화면 위 5단계 바 / 이 대화상자)로
 * 흩어져 있어서, 처음 온 담당자가 «어떤 안내를 볼까»부터 정해야 했다.
 * 새 안내를 또 만들지 않고 이 하나를 «먼저 읽는 곳»으로 삼는다.
 */

import Link from "next/link";
import { useId, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { useDismissable, useFocusTrap } from "@/components/ui/overlays";
import { Badge, Button } from "@/components/ui/primitives";
import { SourceBadge, type SourceKind } from "@/components/ui/SourceBadge";
import {
  FIRST_TIME_END,
  GUIDE_OPEN_LINK,
  FIRST_TIME_G2B,
  FIRST_TIME_G2B_TITLE,
  FIRST_TIME_SUPPORT,
  FIRST_TIME_SUPPORT_TITLE,
  FIRST_TIME_TITLE,
} from "@/lib/terms";
import { GUIDE_LINKS } from "@/lib/guide";
import { useDisplayMode } from "@/lib/viewMode";

/** 처음 온 사람이 60초 안에 알아야 하는 순서. 화면 위 5단계 바(guidedFlow.ts)와 같은 뼈대다. */
const START_STEPS: Array<{ title: string; detail: string }> = [
  { title: "우리 회사정보 확인", detail: "회사자료를 한 번 등록·승인해 두면 이후 모든 공고에서 그대로 근거로 쓰입니다." },
  { title: "검토할 공고 선택", detail: "나라장터·기업마당을 한 목록에서 보고 회사 기준 검토 우선순위로 정렬합니다." },
  { title: "참가 가능 여부 확인", detail: "지역·업종·현장설명 필참처럼 참가 자체를 막는 조건을 점수보다 먼저 봅니다." },
  { title: "요구사항과 회사 근거 연결", detail: "제안요청서를 항목 단위로 펼치고 승인된 회사자료 문장을 붙입니다." },
  { title: "제안서 작성 및 최종 검토", detail: "초안을 만든 뒤 원문과 맞춰 보고 빠진 것을 찾습니다. 마지막 판단은 담당자가 합니다." },
];

/** GPT 로 직접 할 때와 무엇이 다른가. 영상 속 담당자가 이미 하고 있는 일을 기준으로 적는다. */
const GPT_COMPARISON: Array<{ gpt: string; bidpilot: string }> = [
  { gpt: "사업마다 회사정보를 다시 입력", bidpilot: "회사자료를 한 번 등록하고 계속 재사용" },
  { gpt: "여러 채팅 결과를 복사해 이어붙임", bidpilot: "공고 하나를 축으로 단계가 이어짐" },
  { gpt: "요구사항이 바뀐 것을 사람이 기억", bidpilot: "이전 기준으로 쓴 제안서를 구버전으로 구분" },
  { gpt: "회사 근거의 출처가 불명확", bidpilot: "담당자가 승인한 회사자료 문장만 연결" },
  { gpt: "자격조건을 대화로 반복 확인", bidpilot: "참가 가능 여부와 참가 차단 조건을 규칙으로 판정" },
  { gpt: "최종 검토 기준이 매번 달라짐", bidpilot: "제안요청서 원문을 기준으로 같은 검사를 반복" },
  { gpt: "개인의 프롬프트 역량에 의존", bidpilot: "팀이 같은 업무 흐름을 공유" },
];

const PROBLEM_STEPS = [
  "나라장터 신규 공고·사전규격 확인",
  "자사 사업영역과 관련 있는 공고 선별",
  "입찰 참가자격 검토",
  "제안요청서의 과업·요구사항·평가항목·일정·제출서류 정리",
  "회사소개서·수행실적·인력·인증자료 탐색",
  "요구사항과 수행근거 매핑",
  "제안서 작성",
  "제출 전 누락·불일치 재검토",
];

const DOES = [
  // 40차 FRONT-03 — 38차부터 수집 낱말이 회사 사업영역(21개)이고 39차 이름이 「회사 사업영역 후보」다(사업기회 자료 상태와 같은 말)
  "나라장터 공식 데이터에서 회사 사업영역(AI · 교육 · 컨설팅 · ESG 등) 공고 후보를 걸러 검토 우선순위를 매긴다 (낙찰확률 아님).",
  "제안요청서를 요약하지 않고 과업 / 필수 요구사항 / 참가자격 / 제출·일정 / 평가기준 / 특이사항 단위로 페이지·원문과 함께 펼친다.",
  "현장설명 필참·지역제한·보증금처럼 참가 자체를 막는 조건을 찾아, 참여 결정 전에 사람이 해결하게 한다.",
  "담당자가 등록·승인한 회사자료만 근거로 연결하고, 근거 없는 문장은 「확인 필요」로 둔다.",
  "제출 전 누락 점검이 초안을 제안요청서 원문과 맞춰 보고 빠진 요구사항 · 틀린 숫자 · 근거 없는 문장을 원문 쪽과 함께 보여 줍니다.",
];

const DOES_NOT = [
  // 저장 값(GO·HOLD·NO_GO)을 괄호에 적어 두던 자리다. 화면에는 사전을 거친 말만 쓴다 (규칙 11).
  "제출 여부를 자동으로 확정하지 않는다 — 「참여」·「보류」·「참여 안 함」은 사람이 사유와 함께 저장한다.",
  "근거 없는 회사정보·수치·자격 판정을 만들지 않는다. 모호하면 「확인 필요」, 근거가 없으면 「근거 없음」으로 남긴다.",
  "실행하지 않은 단계를 완료처럼 보이게 하지 않는다. 아직 안 한 단계 · 가상 예시 · 규칙 판정 · AI 분석 · 담당자 확인을 늘 나눠 표시합니다.",
  "실제 회사 민감자료를 공개 링크에 쓰지 않는다. 공개 배포본은 가상 예시·비식별 자료만 쓰고, 사내 배포는 로그인 게이트 뒤에서만 실제 회사자료를 쓴다.",
];

/**
 * 출처 표시 범례 — 화면의 출처 배지(SourceBadge)를 그대로 그린다. 예전에는 따로 적어서 ✓ 를 「AI 분석」이라 하면서
 * 캐시 ◐ · 시연용 고정 ⚑ · 실패 ! 는 빠져 있었다 (CMN-10). 이름은 뜻으로 적는다(배지 기본 이름 「실분석」 · 「실데이터」 대신).
 */
const SOURCE_LEGEND: Array<{ kind: SourceKind; label: string }> = [
  { kind: "computed", label: "실제 자료" },
  { kind: "rule", label: "규칙으로 판정" },
  { kind: "analysis", label: "AI 분석" },
  { kind: "human", label: "사람 확인" },
  { kind: "g2b", label: "나라장터 실시간" },
  { kind: "cached", label: "저장본(지난번에 받아 둔 목록)" },
  { kind: "pinned", label: "예시 공고(마감)" },
  { kind: "demo", label: "가상 예시" },
  { kind: "not_run", label: "아직 안 함" },
  { kind: "failed", label: "실패" },
];

export interface WhyBidPilotActions {
  /** 화면 위 5단계 안내를 켠다. 대시보드에서만 넘어온다. */
  onStartGuidedFlow?: () => void;
  /** 화면 사용법(상세 튜토리얼)을 켠다. 대시보드에서만 넘어온다. */
  onStartTutorial?: () => void;
  /** 30초 핵심 안내를 켠다 — 쉬운 보기에는 「안내 ▾」 메뉴가 없어 여기서 시작한다 (24차). */
  onStartQuickTour?: () => void;
  /** 발표 모드를 켠다 — 같은 이유 (24차). */
  onStartPresentation?: () => void;
}

export function WhyBidPilotDialog({
  onClose,
  actions,
}: {
  onClose: () => void;
  actions?: WhyBidPilotActions;
}) {
  const headingId = useId();
  // 시트 · 가운데 대화상자와 같은 두 훅 — Esc 로 닫고 · 닫으면 「?」로 초점을 돌려주고 · Tab 을 안에 가둔다 (CMN-21).
  // 첫 초점은 머리의 ✕(대화상자 안 첫 단추)다.
  useDismissable(true, onClose);
  const boxRef = useFocusTrap(true);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6">
      <button type="button" aria-label="닫기" tabIndex={-1} onClick={onClose} className="absolute inset-0 cursor-default bg-cosmos-bg/70" />
      <div
        ref={boxRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={headingId}
        className="mc-scroll relative flex max-h-[88vh] w-full max-w-3xl flex-col gap-5 overflow-y-auto rounded-xl border border-cosmos-border p-5 shadow-[0_18px_48px_var(--cosmos-shadow)] backdrop-blur sm:p-7"
        style={{ backgroundColor: "var(--cosmos-overlay)" }}
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-[12px] font-medium tracking-[0.18em] text-cosmos-cyan">처음 안내</p>
            <h2 id={headingId} className="mt-1 text-[20px] font-semibold leading-tight text-cosmos-text">
              왜 BidPilot인가
            </h2>
            <p className="mt-2 text-[13.5px] leading-6 text-cosmos-secondary">
              나라장터·기업마당 공고에서 해야 할 일을 항목별로 정리하고, 우리 회사 자료를 근거로 제안서 초안을 쓴 뒤, 내기 전에 빠진
              것이 없는지 공고 원문과 맞춰 보는 <strong className="font-semibold text-cosmos-text">AI 도우미</strong>입니다. 마지막
              판단은 사람이 합니다.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="닫기"
            className="mc-focus min-h-8 shrink-0 rounded-lg border border-cosmos-border px-2.5 text-[13px] text-cosmos-secondary transition-colors hover:border-cosmos-border-strong hover:text-cosmos-text"
          >
            ✕
          </button>
        </div>

        <section className="flex flex-col gap-2">
          <h3 className="text-[12px] font-semibold tracking-[0.14em] text-cosmos-muted">처음이라면 이 순서로</h3>
          <ol className="flex flex-col gap-1.5">
            {START_STEPS.map((step, index) => (
              <li
                key={step.title}
                className="flex items-start gap-2.5 rounded-lg border border-cosmos-border bg-cosmos-elevated/60 px-3 py-2"
              >
                <span className="mt-px flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-cosmos-cyan/20 font-mono text-[12px] font-semibold text-cosmos-cyan">
                  {index + 1}
                </span>
                <span className="min-w-0">
                  <span className="block text-[13px] font-semibold text-cosmos-text">{step.title}</span>
                  <span className="block text-[12px] leading-5 text-cosmos-secondary">{step.detail}</span>
                </span>
              </li>
            ))}
          </ol>
          {(actions?.onStartGuidedFlow || actions?.onStartTutorial || actions?.onStartQuickTour || actions?.onStartPresentation) && (
            <div className="flex flex-wrap gap-2 pt-0.5">
              {actions.onStartGuidedFlow && (
                <Button
                  size="sm"
                  onClick={() => {
                    onClose();
                    actions.onStartGuidedFlow?.();
                  }}
                >
                  화면에서 5단계 따라가기
                </Button>
              )}
              {actions.onStartTutorial && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    onClose();
                    actions.onStartTutorial?.();
                  }}
                >
                  {/* 「안내 ▾」 메뉴 · 환영 창과 같은 이름 (EZ-28) */}
                  상세 튜토리얼
                </Button>
              )}
              {actions.onStartQuickTour && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    onClose();
                    actions.onStartQuickTour?.();
                  }}
                >
                  30초 안내
                </Button>
              )}
              {actions.onStartPresentation && (
                <Button
                  size="sm"
                  variant="ghost"
                  data-tour="why-presentation"
                  onClick={() => {
                    onClose();
                    actions.onStartPresentation?.();
                  }}
                >
                  발표 모드
                </Button>
              )}
            </div>
          )}
        </section>

        {/*
          처음 한 번 하는 준비 (31차 §3-B · 제품 반영 안 1-1). 안내 창 · 튜토리얼이 「화면 읽는 법」만 다뤄, 나라장터 등록 ·
          인증서 · 확인서를 어디서도 말하지 않았다. 모양은 아래 「8단계」 목록과 같은 두 칸 격자 — 대화상자 안이라 배치는 그대로다.
        */}
        <section className="flex flex-col gap-2" aria-labelledby={`${headingId}-first`}>
          <h3 id={`${headingId}-first`} className="text-[12px] font-semibold tracking-[0.14em] text-cosmos-muted">
            {FIRST_TIME_TITLE}
          </h3>
          <div className="grid gap-2 sm:grid-cols-2">
            {[
              { title: FIRST_TIME_G2B_TITLE, lines: FIRST_TIME_G2B },
              { title: FIRST_TIME_SUPPORT_TITLE, lines: FIRST_TIME_SUPPORT },
            ].map((group) => (
              <div key={group.title} className="flex min-w-0 flex-col gap-1.5 rounded-lg border border-cosmos-border bg-cosmos-elevated/60 px-3 py-2">
                <p className="text-[13px] font-semibold text-cosmos-text">{group.title}</p>
                <ol className="flex flex-col gap-1">
                  {group.lines.map((line, index) => (
                    <li key={line} className="flex gap-2 text-[12px] leading-5 text-cosmos-secondary">
                      <span className="mt-px flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-cosmos-blue/25 font-mono text-[12px] text-cosmos-text">
                        {index + 1}
                      </span>
                      <span className="min-w-0 break-words">{line}</span>
                    </li>
                  ))}
                </ol>
              </div>
            ))}
          </div>
          <p className="text-[12px] leading-5 text-cosmos-muted">
            {FIRST_TIME_END}{" "}
            <Link href={GUIDE_LINKS.start} onClick={onClose} className="mc-focus font-medium text-cosmos-cyan underline-offset-2 hover:underline">
              {GUIDE_OPEN_LINK}
            </Link>
          </p>
        </section>

        <section className="flex flex-col gap-2">
          <h3 className="text-[12px] font-semibold tracking-[0.14em] text-cosmos-muted">
            GPT로 직접 할 때와 무엇이 다른가
          </h3>
          <div className="mc-scroll overflow-x-auto rounded-xl border border-cosmos-border">
            <table className="w-full min-w-[420px] border-collapse text-left text-[12.5px]">
              <caption className="sr-only">GPT로 직접 할 때와 BidPilot의 차이</caption>
              <thead>
                <tr className="bg-cosmos-elevated/70">
                  <th scope="col" className="w-1/2 px-3 py-2 text-[12px] font-semibold tracking-[0.1em] text-cosmos-muted">
                    GPT에서 직접 할 때
                  </th>
                  <th scope="col" className="w-1/2 px-3 py-2 text-[12px] font-semibold tracking-[0.1em] text-cosmos-cyan">
                    BidPilot
                  </th>
                </tr>
              </thead>
              <tbody>
                {GPT_COMPARISON.map((row) => (
                  <tr key={row.gpt} className="border-t border-cosmos-border align-top">
                    <td className="px-3 py-2 leading-5 text-cosmos-secondary">{row.gpt}</td>
                    <td className="px-3 py-2 leading-5 text-cosmos-text">{row.bidpilot}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-[12px] leading-5 text-cosmos-muted">
            GPT를 대신하지 않습니다. 담당자가 여러 작업창으로 나눠 하던 일을 공고 하나의 상태로 이어 붙일 뿐입니다.
          </p>
        </section>

        <section className="flex flex-col gap-2">
          <h3 className="text-[12px] font-semibold uppercase tracking-[0.14em] text-cosmos-muted">지금 담당자가 손으로 하는 8단계</h3>
          <ol className="grid gap-1.5 sm:grid-cols-2">
            {PROBLEM_STEPS.map((step, index) => (
              <li key={step} className="flex items-center gap-2 rounded-lg border border-cosmos-border bg-cosmos-elevated/60 px-3 py-1.5 text-[12.5px] text-cosmos-secondary">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-cosmos-blue/25 font-mono text-[12px] text-cosmos-text">
                  {index + 1}
                </span>
                {step}
              </li>
            ))}
          </ol>
          <p className="text-[12px] leading-5 text-cosmos-muted">
            어느 단계도 사라지지 않습니다. BidPilot은 각 단계의 근거를 한 화면에 모으고 빠진 곳을 드러내는 도구입니다.
          </p>
        </section>

        <div className="grid gap-4 md:grid-cols-2">
          <section className="flex flex-col gap-2 rounded-xl border border-cosmos-cyan/30 bg-cosmos-cyan/5 p-4">
            <h3 className="flex items-center gap-2 text-[12px] font-semibold text-cosmos-text">
              <Badge tone="ok" glyph>
                하는 것
              </Badge>
            </h3>
            <ul className="flex flex-col gap-1.5 text-[12.5px] leading-5 text-cosmos-secondary">
              {DOES.map((line) => (
                <li key={line} className="flex gap-2">
                  <span aria-hidden="true" className="text-cosmos-cyan">
                    •
                  </span>
                  {line}
                </li>
              ))}
            </ul>
          </section>
          <section className="flex flex-col gap-2 rounded-xl border border-cosmos-amber/30 bg-cosmos-amber/5 p-4">
            <h3 className="flex items-center gap-2 text-[12px] font-semibold text-cosmos-text">
              <Badge tone="warn" glyph>
                하지 않는 것
              </Badge>
            </h3>
            <ul className="flex flex-col gap-1.5 text-[12.5px] leading-5 text-cosmos-secondary">
              {DOES_NOT.map((line) => (
                <li key={line} className="flex gap-2">
                  <span aria-hidden="true" className="text-cosmos-amber">
                    •
                  </span>
                  {line}
                </li>
              ))}
            </ul>
          </section>
        </div>

        <section className="flex flex-col gap-2">
          <h3 className="text-[12px] font-semibold uppercase tracking-[0.14em] text-cosmos-muted">화면의 값은 출처를 함께 표시합니다</h3>
          <div className="flex flex-wrap gap-1.5">
            {SOURCE_LEGEND.map((item) => (
              <SourceBadge key={item.kind} kind={item.kind} label={item.label} />
            ))}
          </div>
          <p className="text-[12px] leading-5 text-cosmos-muted">
            「아직 안 함」은 값이 0이라는 뜻이 아니라 그 단계를 아직 하지 않았다는 뜻입니다. 절감률·정확도 같은 성과 수치는 측정 전에는 표시하지
            않습니다.
          </p>
        </section>
      </div>
    </div>
  );
}

/**
 * 헤더에 두는 「?」 단추 + 대화상자 상태.
 *
 * 대화상자는 `document.body` 로 옮겨 그린다 (ISSUE-165 · CMN-01). 머리(AppShell · 대시보드 TopBar)에는 `backdrop-blur` 가
 * 걸려 있고, 흐림이 걸린 상자는 안의 `fixed` 요소의 기준 상자가 된다(Chrome · Edge · Firefox). 그래서 대화상자가 창이 아니라
 * 머리(높이 56~100px) 가운데에 서서 제목 · ✕ 가 창 위로 잘렸고, 어둡게 하기도 머리만 덮었다.
 * 쉬운 보기 글자 크기 규칙(`[data-view="simple"]` · globals.css)은 단추가 있던 자리의 것을 그대로 가져간다.
 *
 * `variant` 는 옛 호출 호환이다 — 글자 단추 변형은 그려지는 곳이 없어 지웠다(CMN-22). 늘 아이콘이다.
 */
export function WhyBidPilotButton({
  actions,
}: {
  variant?: "icon";
  /** 대시보드에서만 넘긴다. 없으면 대화상자가 안내 시작 버튼을 아예 그리지 않는다. */
  actions?: WhyBidPilotActions;
}) {
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<string | undefined>(undefined);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  // 쉬운 보기는 본문 단추(40~44px)에 맞춰 크게 — 자주 누르는 단추가 32px 였다 (EZ-37).
  const simple = useDisplayMode() === "simple";
  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        onClick={() => {
          setView(buttonRef.current?.closest("[data-view]")?.getAttribute("data-view") ?? undefined);
          setOpen(true);
        }}
        aria-label="처음 안내 — 시작 순서 · 처음 준비 · 하지 않는 것"
        title="처음 안내 — 시작 순서 · 처음 준비 · 하지 않는 것"
        className={`mc-focus flex ${simple ? "h-10 w-10" : "h-8 w-8"} shrink-0 items-center justify-center rounded-full border border-cosmos-border bg-cosmos-panel text-[13px] font-semibold text-cosmos-secondary transition-colors hover:border-cosmos-cyan/60 hover:text-cosmos-text`}
      >
        <span aria-hidden="true">?</span>
      </button>
      {open &&
        createPortal(
          <div data-view={view}>
            <WhyBidPilotDialog onClose={() => setOpen(false)} actions={actions} />
          </div>,
          document.body,
        )}
    </>
  );
}
