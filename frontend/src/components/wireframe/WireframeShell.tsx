"use client";

/**
 * 와이어프레임 대시보드 셸.
 *
 * Evidence Cosmos("/")와 같은 backend 데이터를 쓰지만, 화면은 "설계 단계 목업"으로 그린다.
 * 목적은 예쁘게 보이는 것이 아니라 아래 세 가지를 한 화면에서 드러내는 것이다.
 *   1. 각 패널이 어떤 API로 채워지는가
 *   2. 지금 실제로 구현된 부분이 어디까지인가 (실데이터 / 데모 시나리오 / 미구현)
 *   3. 아직 화면이 없는 영역은 어디인가 (회색 자리표시)
 */

import { SYNTHETIC_NOTICE } from "@/lib/terms";
import {
  limitNoticeOptions,
  pickerHiddenLabel,
} from "@/lib/cosmos/noticePicker";
import Link from "next/link";

import { formatDateTime } from "@/lib/cosmos/format";
import { useWireframeData } from "@/lib/wireframe/useWireframeData";

import {
  AuditorPanel,
  BacklogPanel,
  EligibilityPanel,
  EvidencePanel,
  FitPanel,
  NoticePanel,
  ProposalPanel,
  RequirementPanel,
  ReviewPanel,
} from "./panels";
import {
  Bar,
  Chip,
  SketchButton,
  Stamp,
  WireframeStyles,
  XBox,
  type StampKind,
} from "./primitives";
// 영문 등급을 화면에 내지 않는다 — 사전은 하나다 (규칙 11 · ISSUE-074-e · 0921 §4-E).
import { CANDIDATE_TIER_LABELS } from "@/lib/cosmos/format";


/** 좌측 목차. state는 실행 결과에 따라 셸에서 채운다. */
const NAV_ITEMS: { id: number; label: string }[] = [
  { id: 1, label: "공고 수집" },
  { id: 2, label: "우리 회사 적합도" },
  { id: 3, label: "참가자격 판정" },
  { id: 4, label: "요구사항 정리표" },
  { id: 5, label: "회사 Evidence" },
  { id: 6, label: "제안서 초안" },
  { id: 7, label: "AI Auditor" },
  { id: 8, label: "최종 검토" },
  { id: 9, label: "확장 백로그" },
];

const NAV_MARK: Record<StampKind, string> = {
  live: "●",
  demo: "◐",
  partial: "◐",
  todo: "○",
};

export default function WireframeShell() {
  const data = useWireframeData();

  // 목차 표시용 상태 — 패널이 실제로 무엇을 그리고 있는지와 같은 기준을 쓴다.
  const navState: Record<number, StampKind> = {
    1: data.list ? "live" : "todo",
    2: data.scenario ? "demo" : "todo",
    3: data.eligibility ? "live" : "todo",
    4: data.parse ? "live" : "todo",
    5: data.scenario ? "demo" : "todo",
    6: data.proposal ? "live" : "todo",
    7: data.audit ? "live" : "todo",
    8: "todo",
    9: "todo",
  };

  const demoOptions = data.options.filter((o) => o.demo);
  const allRealOptions = data.options.filter((o) => !o.demo);
  // 드롭다운이 길어지면 시연 중 찾기 어렵다. 상위 N개만 보여준다 (선택된 공고는 항상 남긴다).
  const realOptions = limitNoticeOptions(allRealOptions, data.selectedId);
  const hiddenLabel = pickerHiddenLabel(allRealOptions.length, realOptions.length);

  // 첫 로드 동안에는 공고 선택기를 그리지 않는다.
  // 선택된 공고는 URL(?notice=)에서 오는데 서버 렌더는 그 값을 모르므로
  // 여기서 select를 그리면 hydration이 어긋난다 (목록도 아직 비어 있다).
  const firstLoad = data.status === "loading" && data.list === null;

  return (
    <div className="wf-root min-h-dvh">
      <WireframeStyles />

      {/* ---------------------------------------------------------------- */}
      {/* 문서 머리말                                                        */}
      {/* ---------------------------------------------------------------- */}
      <header className="border-b border-[var(--wf-line-strong)] px-5 py-3">
        <div className="mx-auto flex max-w-[1400px] flex-col gap-3">
          <div className="wf-label flex flex-wrap items-center gap-x-5 gap-y-1">
            <span>문서 · BIDPILOT-UI-WF-01</span>
            <span>판 · 0.1</span>
            <span>상태 · 초안</span>
            <span>
              자료 ·{" "}
              {data.list ? formatDateTime(data.list.fetched_at) : "미연결"}
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <div className="w-9 shrink-0">
              <XBox height={36} />
            </div>
            <div className="min-w-[220px] flex-1">
              <h1 className="text-[17px] font-bold leading-tight">
                BidPilot AI — 대시보드 와이어프레임
              </h1>
              <p className="wf-label mt-1 tracking-normal">
                공고 → 자격 → 요구사항 → 증빙 → 제안서 → 역검증 전체 화면 설계
              </p>
            </div>

            <div className="flex w-full flex-wrap items-center gap-2 lg:w-auto">
              <Chip tone={data.health ? "blue" : "red"}>
                서버 {data.health ? "연결됨" : "연결 안 됨"}
              </Chip>
              <Link
                href="/cosmos"
                className="wf-chip wf-chip--ink hover:bg-[var(--wf-fill)]"
              >
                Evidence Cosmos ↗
              </Link>
              <Link
                href="/opportunities"
                className="wf-chip wf-chip--ink hover:bg-[var(--wf-fill)]"
              >
                공고 목록 ↗
              </Link>
            </div>
          </div>

          <p className="wf-note">
            이 화면은 디자인 확정 전 <strong>저충실도 목업</strong>입니다. 회색 블록·빗금은 아직
            만들지 않은 영역이고, 파란 값은 실제 서버 응답이며, 빨간 글씨는 검토 주석입니다.
            여기 보이는 수치는 어느 것도 성과 지표가 아닙니다.
          </p>
        </div>
      </header>

      {/* ---------------------------------------------------------------- */}
      {/* 본문                                                              */}
      {/* ---------------------------------------------------------------- */}
      <div className="mx-auto flex max-w-[1400px] flex-col gap-4 px-5 py-4 lg:flex-row">
        {/* 좌측 목차 */}
        <nav
          aria-label="화면 목차"
          className="shrink-0 lg:sticky lg:top-4 lg:h-fit lg:w-[210px]"
        >
          <div className="wf-box p-3">
            <p className="wf-label mb-2">화면 목차</p>
            <ul className="flex flex-col gap-0.5">
              {NAV_ITEMS.map((item) => (
                <li key={item.id}>
                  <a
                    href={`#wf-panel-${item.id}`}
                    className="flex items-center gap-2 px-1 py-1 text-[12px] text-[var(--wf-ink-2)] hover:bg-[var(--wf-fill)]"
                  >
                    <span
                      aria-hidden="true"
                      className="wf-mono w-3 shrink-0 text-[12px] text-[var(--wf-ink-3)]"
                    >
                      {NAV_MARK[navState[item.id]]}
                    </span>
                    <span className="wf-mono w-3 shrink-0 text-[12px]">
                      {item.id}
                    </span>
                    <span className="min-w-0 flex-1 truncate">{item.label}</span>
                  </a>
                </li>
              ))}
            </ul>
            <p className="wf-label mt-3 tracking-normal leading-5">
              ● 실데이터 &nbsp; ◐ 가상 예시 공고 &nbsp; ○ 미구현
            </p>
          </div>

          <div className="wf-box wf-box--dashed mt-3 p-3">
            <p className="wf-label mb-1">미포함 화면</p>
            <p className="text-[12px] leading-5 text-[var(--wf-ink-3)]">
              {/* 로그인 · 권한 · 조직(회사) 설정은 이제 있다 — 목록에서 뺐다 (CMN-24). */}
              알림함 · 사용자 프로필 · 검색 — MVP 범위 밖이라 이 목업에도 없습니다.
            </p>
          </div>
        </nav>

        {/* 우측 본문 */}
        <main className="flex min-w-0 flex-1 flex-col gap-4">
          {/* 도구 막대 */}
          <div className="wf-box sticky top-0 z-10 flex flex-wrap items-center gap-2 p-3">
            <div className="wf-box wf-box--thin wf-box--b min-w-[260px] flex-1">
              {firstLoad ? (
                <div className="px-3 py-2.5">
                  <Bar width="64%" />
                </div>
              ) : (
                <>
                  <label className="sr-only" htmlFor="wf-notice-picker">
                    분석 대상 공고 선택
                  </label>
                  <select
                    id="wf-notice-picker"
                    className="wf-select"
                    value={data.selectedId}
                    disabled={data.parsing}
                    onChange={(event) => data.selectNotice(event.target.value)}
                  >
                    <optgroup label={SYNTHETIC_NOTICE}>
                      {demoOptions.map((option) => (
                        <option key={option.id} value={option.id}>
                          {option.title}
                        </option>
                      ))}
                    </optgroup>
                    <optgroup
                      label={
                        hiddenLabel
                          ? `나라장터 실공고 후보 — ${hiddenLabel}`
                          : `나라장터 실공고 후보 (${realOptions.length})`
                      }
                    >
                      {realOptions.map((option) => (
                        <option key={option.id} value={option.id}>
                          {option.rank != null ? `${option.rank}. ` : ""}
                          {option.grade
                            ? `[${option.grade === "NO_GO" ? "마감" : option.grade}] `
                            : option.tier
                              ? `[${CANDIDATE_TIER_LABELS[option.tier] ?? "확인 필요"}] `
                              : ""}
                          {option.title} · {option.agency}
                        </option>
                      ))}
                    </optgroup>
                  </select>
                </>
              )}
            </div>

            <SketchButton onClick={data.reload} disabled={data.parsing}>
              새로고침
            </SketchButton>
            <SketchButton onClick={data.runParse} disabled={data.parsing}>
              {data.parsing ? "파싱 중…" : "RFP 파싱 실행"}
            </SketchButton>

            <span className="wf-label ml-auto">
              {data.status === "loading"
                ? "불러오는 중"
                : data.analysisLoading
                  ? "분석 결과 수신 중"
                  : "대기"}
            </span>
          </div>

          {data.error ? (
            <p role="alert" className="wf-box wf-box--dashed p-3 wf-note">
              {data.error}
            </p>
          ) : null}
          {data.listError ? (
            <p className="wf-box wf-box--dashed p-3 wf-note">
              공고 목록 경고: {data.listError}
            </p>
          ) : null}
          {data.parseError ? (
            <p role="alert" className="wf-box wf-box--dashed p-3 wf-note">
              {data.parseError}
            </p>
          ) : null}

          {/* 패널 그리드 */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
            <NoticePanel data={data} />
            <FitPanel data={data} />
            <EligibilityPanel data={data} />
            <RequirementPanel data={data} />
            <EvidencePanel data={data} />
            <ProposalPanel data={data} />
            <AuditorPanel data={data} />
            {/* 공고가 바뀌면 리마운트해 이전 공고의 체크리스트·검토자·오류가 남지 않게 한다. */}
            <ReviewPanel key={data.selectedId} data={data} />
            <BacklogPanel />
          </div>

          {/* 범례 */}
          <footer className="wf-box p-4">
            <p className="wf-label mb-2">표기 범례</p>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <div className="flex flex-col gap-1.5">
                <span className="wf-bar" style={{ width: "70%" }} />
                <span className="text-[12px] text-[var(--wf-ink-2)]">
                  회색 막대 — 아직 만들지 않은 영역
                </span>
              </div>
              <div className="flex flex-col gap-1.5">
                <span className="wf-live text-[12px]">나라장터 캐시</span>
                <span className="text-[12px] text-[var(--wf-ink-2)]">
                  파란 값 — 실제 서버 응답
                </span>
              </div>
              <div className="flex flex-col gap-1.5">
                <span className="wf-note">↳ 검토 주석</span>
                <span className="text-[12px] text-[var(--wf-ink-2)]">
                  빨간 글씨 — 구현 상태·주의사항
                </span>
              </div>
              <div className="flex flex-wrap items-start gap-1.5">
                <Stamp kind="live" />
                <Stamp kind="demo" />
                <Stamp kind="todo" />
              </div>
            </div>
            <p className="wf-label mt-4 tracking-normal leading-5">
              같은 데이터를 완성된 화면으로 보려면{" "}
              <Link href="/cosmos" className="underline">
                Evidence Cosmos 대시보드
              </Link>
              를 여세요. 두 화면은 같은 API(procurements · rfp · eligibility · proposal ·
              auditor)를 호출합니다.
            </p>
          </footer>
        </main>
      </div>
    </div>
  );
}
