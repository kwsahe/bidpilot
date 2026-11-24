"use client";

/**
 * 와이어프레임 대시보드의 모듈 패널들.
 *
 * 각 패널은 (1) 어떤 backend 엔드포인트가 채우는지, (2) 지금 실제로 구현된 부분이 어디까지인지를
 * 머리말과 하단 주석에 그대로 적는다. 값이 없으면 회색 자리표시로 두고 숫자를 지어내지 않는다.
 */

import { useEffect, useState } from "react";

import {
  getReview,
  proposalExportUrl,
  proposalFullExportUrl,
  saveReview,
} from "@/lib/api";
import { DownloadLink } from "@/components/ui/DownloadLink";
import { findingTypeLabel } from "@/lib/cosmos/graph";
import { describeFailure } from "@/lib/errors";
import {
  CANDIDATE_TIER_LABELS,
  ELIGIBILITY_LABELS,
  GROUNDING_LABELS,
  METHOD_LABELS,
  REQUIREMENT_STATUS_LABELS,
  REQUIREMENT_TYPE_LABELS,
  SEVERITY_LABELS,
  daysUntil,
  formatBudgetCompact,
  formatDDay,
  formatDateTime,
  formatPage,
  formatSimilarity,
  truncate,
} from "@/lib/cosmos/format";
import { isDemoProcurementId } from "@/lib/cosmos/demoNotice";
import { formatDeadlineDateTime } from "@/lib/deadline";
import { useNowMs } from "@/lib/cosmos/useCosmosDashboard";
import type { WireframeData } from "@/lib/wireframe/useWireframeData";
import type {
  ReviewChecklist,
  ReviewDecision,
  ReviewStatus,
} from "@/types/analysis";
import type { EligibilityStatus, Severity } from "@/types/cosmos";
import { noticeAttachments } from "@/types/procurement";

import {
  Bar,
  BarLines,
  Chip,
  Field,
  Gauge,
  Hatch,
  NotRun,
  Panel,
  XBox,
} from "./primitives";

/** 요구사항 표에 한 번에 보여줄 행 수. 나머지는 자리표시로 남긴다. */
const REQUIREMENT_ROWS = 8;
/** 목록형 패널에서 보여줄 항목 수. */
const LIST_ROWS = 5;

/**
 * 검토 우선순위 배점 — **백엔드 `opportunity_priority.PRIORITY_WEIGHTS` 와 같은 값**이다
 * (CLAUDE.md §12 · 0922 §4-B). 마감(「일정 여유」)은 8차에서 배점에서 빠졌다.
 */
const PRIORITY_WEIGHT_ROWS: ReadonlyArray<readonly [string, string]> = [
  ["회사 사업영역 적합도", "35%"],
  ["참여·신청자격 적합도", "25%"],
  ["수행근거·보유역량", "20%"],
  ["규모 적합도", "10%"],
  ["전략적 가치", "10%"],
];

function verdictTone(status: EligibilityStatus): "blue" | "ink" | "red" {
  if (status === "PASS") return "blue";
  if (status === "CHECK") return "ink";
  return "red";
}

function severityTone(severity: Severity): "red" | "ink" | "default" {
  if (severity === "high") return "red";
  if (severity === "medium") return "ink";
  return "default";
}

/** 2단계 로딩 중이면 회색 막대, 아니면 "미실행". */
function Pending({ loading, lines = 3 }: { loading: boolean; lines?: number }) {
  if (loading) return <BarLines lines={lines} pulse />;
  return <NotRun />;
}

// ---------------------------------------------------------------------------
// ① 공고 수집
// ---------------------------------------------------------------------------

export function NoticePanel({ data }: { data: WireframeData }) {
  const nowMs = useNowMs();
  const { list, notice } = data;
  const attachments = notice ? noticeAttachments(notice) : [];

  const sourceText =
    list === null
      ? "조회 실패"
      : list.source === "g2b"
        ? "나라장터 실시간"
        : "나라장터 캐시";

  return (
    <Panel
      index={1}
      title="공고 수집"
      source="GET /api/procurements"
      status={list ? "live" : "todo"}
      span={6}
      note="공고 원문(raw_data) 뷰어와 첨부문서 미리보기는 아직 화면이 없다. 목록 정렬·검색·페이지네이션도 미구현."
    >
      <div className="flex flex-col gap-1">
        <Field label="목록 출처" value={sourceText} live={list !== null} />
        <Field
          label="조회 시각"
          value={list ? formatDateTime(list.fetched_at) : <NotRun />}
          live={list !== null}
        />
        <Field
          label="후보 건수"
          value={
            list ? (
              `${list.total_fetched}건 중 ${list.count}건 후보`
            ) : (
              <NotRun />
            )
          }
          live={list !== null}
          mono
        />
        <Field
          label="G2B 키"
          value={
            data.health
              ? data.health.g2b_api_configured
                ? "설정됨"
                : "미설정 (캐시로 동작)"
              : "확인 불가"
          }
        />
      </div>

      <div className="wf-box wf-box--thin p-3">
        {/* 공고 종류 표시는 notice가 도착한 뒤에만 그린다 — 서버 렌더는 URL의 ?notice= 를 모른다. */}
        {notice ? (
          <>
            <div className="mb-1.5 flex items-center gap-1.5">
              <span className="wf-label">선택된 공고</span>
              {isDemoProcurementId(notice.id) ? (
                <Chip tone="fill">가상 예시</Chip>
              ) : (
                <Chip tone="blue">실공고</Chip>
              )}
            </div>
            <p className="text-[12.5px] font-semibold leading-6">{notice.title}</p>
            <div className="mt-2 flex flex-col gap-1">
              <Field label="공고번호" value={notice.notice_no} mono />
              <Field label="발주기관" value={notice.agency} />
              <Field
                label="지역 / 예산"
                value={`${notice.region ?? "확인 필요"} · ${formatBudgetCompact(notice.budget)}`}
              />
              <Field
                label="마감"
                value={
                  nowMs === null
                    ? formatDeadlineDateTime(notice.deadline_at)
                    : `${formatDeadlineDateTime(notice.deadline_at)} (${formatDDay(daysUntil(notice.deadline_at, nowMs))})`
                }
              />
              <Field
                label="첨부"
                value={
                  attachments.length > 0
                    ? `${attachments.length}건`
                    : "없음 / 미확인"
                }
                mono
              />
            </div>
          </>
        ) : (
          <>
            <span className="wf-label mb-1.5 block">선택된 공고</span>
            <BarLines lines={4} />
          </>
        )}
      </div>

      {notice?.candidate ? (
        <div className="flex flex-wrap items-center gap-1.5">
          <Chip tone="blue">
            키워드 등급 {CANDIDATE_TIER_LABELS[notice.candidate.tier] ?? "확인 필요"}
          </Chip>
          {notice.candidate.matched_ai_keywords.slice(0, 3).map((kw) => (
            <Chip key={kw}>AI · {kw}</Chip>
          ))}
          {notice.candidate.matched_work_keywords.slice(0, 3).map((kw) => (
            <Chip key={kw}>업무 · {kw}</Chip>
          ))}
        </div>
      ) : (
        <Hatch height={40} label="키워드 판정 근거 없음 (데모 공고)" />
      )}
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// ② SampleEdu 적합도
// ---------------------------------------------------------------------------

export function FitPanel({ data }: { data: WireframeData }) {
  const match = data.scenario?.semantic_match ?? null;

  return (
    <Panel
      index={2}
      title="우리 회사 적합도 (의미 유사도 + 낱말 기준)"
      source="GET /api/demo/cosmos/{id} · semantic_match"
      status={match ? "demo" : "todo"}
      span={6}
      note="의미 유사도 매칭은 구현돼 있고(recommendation.semantic_used · 화면이 「AI 의미 매칭」으로 표시), 임베딩을 쓸 수 없는 환경에서는 키워드 등급으로 떨어진다. 지금 이 저장소는 AI 검색 크레딧이 소진돼 키워드 경로다. 아래 점수는 가상 예시 공고의 고정값이라 성과 수치로 인용하면 안 된다."
    >
      {match ? (
        <>
          <Gauge
            ratio={match.fit_score}
            caption={`fit_score ${match.fit_score.toFixed(2)} · ${match.label} (가상 예시 공고 값)`}
          />
          <div className="flex flex-wrap gap-1.5">
            {match.matched_domains.map((domain) => (
              <Chip key={domain} tone="fill">
                {domain}
              </Chip>
            ))}
          </div>
          <p className="wf-body">{match.reason}</p>
        </>
      ) : (
        <>
          <Gauge ratio={0} caption="fit_score — 미산출" />
          <Hatch height={64} label="의미 유사도 미산출 (임베딩을 쓸 수 없음)" />
        </>
      )}

      <div className="flex flex-col gap-1.5">
        {/*
          배점은 **백엔드가 쓰는 것과 같아야 한다** (CLAUDE.md §12 · 0922 §4-B).
          여기 적혀 있던 「인력·일정 적합도 20%」는 8차에서 사라진 항목이다 — 마감은 적합도가
          아니라 긴급도라 배점에서 뺐고, 그 자리를 「규모 적합도」가 대신한다.
          숫자는 화면 사전(`lib/scoreNames`)에서 읽는다.
        */}
        <span className="wf-label">검토 우선순위 배점 (CLAUDE.md §12)</span>
        {PRIORITY_WEIGHT_ROWS.map(([label, weight]) => (
          <div key={label} className="flex items-center gap-2">
            <span className="w-[104px] shrink-0 text-[12px] text-[var(--wf-ink-2)]">
              {label}
            </span>
            <span className="flex-1">
              <Bar width={weight} />
            </span>
            <span className="wf-mono w-9 shrink-0 text-right text-[12px] text-[var(--wf-ink-3)]">
              {weight}
            </span>
          </div>
        ))}
      </div>
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// ③ Eligibility Gate
// ---------------------------------------------------------------------------

export function EligibilityPanel({ data }: { data: WireframeData }) {
  const report = data.eligibility;

  return (
    <Panel
      index={3}
      title="참가자격 판정 (Eligibility Gate)"
      source="POST /api/eligibility/evaluate"
      status={report ? "live" : "todo"}
      span={12}
      note="애매한 조건은 자동 통과시키지 않고 「확인 필요」로 남긴다. 담당자가 그것을 해소하는 화면(근거 첨부·수동 판정)은 아직 미구현이다."
    >
      {report ? (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <Chip tone={verdictTone(report.verdict)}>
              종합 {ELIGIBILITY_LABELS[report.verdict]}
            </Chip>
            <Chip tone="fill">
              {/* 영문 판정값을 화면에 내지 않는다 (규칙 11 · 0921 §4-E). */}
              {ELIGIBILITY_LABELS.PASS} {report.counts.passed} · {ELIGIBILITY_LABELS.CHECK}{" "}
              {report.counts.check} · {ELIGIBILITY_LABELS.FAIL} {report.counts.failed} / 총{" "}
              {report.counts.total}
            </Chip>
            <Chip>{report.llm_used ? "LLM 보강 사용" : "규칙 판정만"}</Chip>
            <Chip>
              공고필드 {report.notice_available ? "O" : "X"} · 요구사항{" "}
              {report.requirements_available ? "O" : "X"}
            </Chip>
            <span className="wf-label ml-auto">
              {formatDateTime(report.evaluated_at)}
            </span>
          </div>

          <div className="grid gap-2 md:grid-cols-2">
            {report.results.slice(0, LIST_ROWS * 2).map((result) => (
              <div
                key={result.rule_id}
                className="wf-box wf-box--thin wf-box--b flex flex-col gap-1 p-2.5"
              >
                <div className="flex items-center gap-1.5">
                  <Chip tone={verdictTone(result.status)}>
                    {ELIGIBILITY_LABELS[result.status]}
                  </Chip>
                  <span className="min-w-0 flex-1 truncate text-[12px] font-semibold">
                    {result.label}
                  </span>
                  <Chip>{METHOD_LABELS[result.method]}</Chip>
                </div>
                <p className="wf-body">{truncate(result.reason, 110)}</p>
                <p className="wf-label truncate" title={result.source}>
                  근거: {result.source}
                </p>
              </div>
            ))}
          </div>
        </>
      ) : (
        <div className="grid gap-2 md:grid-cols-2">
          <Pending loading={data.analysisLoading} lines={4} />
          <Hatch height={72} label="판정 결과 없음" />
        </div>
      )}
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// ④ RFP Requirement Matrix
// ---------------------------------------------------------------------------

export function RequirementPanel({ data }: { data: WireframeData }) {
  const parse = data.parse;
  const requirements = parse?.requirements ?? [];
  const remaining = Math.max(0, requirements.length - REQUIREMENT_ROWS);

  return (
    <Panel
      index={4}
      title="요구사항 정리표"
      source="GET /api/rfp/{id}/requirements · POST /api/rfp/parse"
      status={parse ? "live" : "todo"}
      span={12}
      note="정렬·필터·요구사항 편집·Gold Set 비교 화면은 미구현. HWP/HWPX는 페이지 정보가 없어 문단 묶음으로 근사하므로(page_is_approximate) 표기 규칙을 확정해야 한다."
    >
      {parse ? (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <Chip tone="blue">{parse.count}건 추출</Chip>
            <Chip tone="fill">출처 {parse.source}</Chip>
            <Chip>{parse.doc_format ?? "형식 미상"}</Chip>
            <Chip>{parse.page_count}p</Chip>
            {parse.page_is_approximate ? (
              <Chip tone="red">페이지 근사값</Chip>
            ) : null}
            {parse.empty_pages.length > 0 ? (
              <Chip tone="red">빈 페이지 {parse.empty_pages.length}건</Chip>
            ) : null}
            <span
              className="wf-label ml-auto max-w-[280px] truncate"
              title={parse.document}
            >
              {parse.document}
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="wf-table">
              <thead>
                <tr>
                  <th>REQ ID</th>
                  <th>구분</th>
                  <th>요구사항</th>
                  <th>페이지</th>
                  <th>상태</th>
                  <th>추출</th>
                </tr>
              </thead>
              <tbody>
                {requirements.slice(0, REQUIREMENT_ROWS).map((req) => (
                  <tr key={req.id}>
                    <td className="wf-mono whitespace-nowrap text-[var(--wf-blue)]">
                      {req.requirement_id}
                    </td>
                    <td className="whitespace-nowrap">
                      {REQUIREMENT_TYPE_LABELS[req.requirement_type]}
                    </td>
                    <td>
                      <span className="font-semibold text-[var(--wf-ink)]">
                        {req.title}
                      </span>
                      <br />
                      <span>{truncate(req.content, 96)}</span>
                    </td>
                    <td className="wf-mono whitespace-nowrap">
                      {formatPage(req.page)}
                    </td>
                    <td className="whitespace-nowrap">
                      {REQUIREMENT_STATUS_LABELS[req.status]}
                    </td>
                    <td className="whitespace-nowrap">
                      {METHOD_LABELS[req.extraction_method]}
                    </td>
                  </tr>
                ))}
                {remaining > 0 ? (
                  <tr>
                    <td colSpan={6} className="py-2">
                      <div className="flex items-center gap-3">
                        <span className="flex-1">
                          <BarLines lines={2} />
                        </span>
                        <span className="wf-label whitespace-nowrap">
                          이하 {remaining}건 — 스크롤/페이지네이션 미구현
                        </span>
                      </div>
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <XBox
          height={120}
          label={
            data.parseMissing
              ? "요구사항 미추출 — 상단 [RFP 파싱 실행] 필요"
              : "요구사항 없음"
          }
        />
      )}
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// ⑤ 회사 Evidence
// ---------------------------------------------------------------------------

export function EvidencePanel({ data }: { data: WireframeData }) {
  const scenario = data.scenario;
  const documents = scenario?.evidence_documents ?? [];
  const links = scenario?.evidence_links ?? [];

  return (
    <Panel
      index={5}
      title="회사 Evidence 매핑"
      source="GET /api/demo/cosmos/{id} · evidence_*"
      status={scenario ? "demo" : "todo"}
      span={6}
      note="임베딩 인덱스·유사도 검색(RAG)은 미구현이다. 지금 보이는 연결은 가상 예시 회사자료의 고정 매핑이며 모든 문서는 synthetic이다. 문서 업로드·채택 저장 화면도 없다."
    >
      {scenario ? (
        <>
          <div className="flex flex-wrap items-center gap-1.5">
            <Chip tone="fill">문서 {documents.length}건</Chip>
            <Chip tone="fill">연결 {links.length}건</Chip>
            <Chip tone="red">전부 synthetic</Chip>
          </div>

          <div className="flex flex-col gap-1.5">
            {links.slice(0, LIST_ROWS).map((link) => {
              const doc = documents.find((d) => d.id === link.evidence_id);
              return (
                <div
                  key={`${link.requirement_id}-${link.evidence_id}`}
                  className="wf-box wf-box--thin wf-box--b flex flex-col gap-1 p-2.5"
                >
                  <div className="flex items-center gap-1.5">
                    <span className="wf-mono text-[12px] text-[var(--wf-blue)]">
                      {link.requirement_id}
                    </span>
                    <span aria-hidden="true" className="text-[var(--wf-ink-3)]">
                      →
                    </span>
                    <span className="min-w-0 flex-1 truncate text-[12px]">
                      {doc ? doc.document_name : link.evidence_id}
                    </span>
                    <Chip>{formatPage(doc?.page ?? null)}</Chip>
                    <Chip tone={link.selected ? "ink" : "default"}>
                      {link.selected ? "채택" : "후보"}
                    </Chip>
                  </div>
                  <Gauge
                    ratio={link.similarity_score}
                    caption={`유사도 ${formatSimilarity(link.similarity_score)} (고정값)`}
                  />
                  {doc ? (
                    <p className="wf-body">{truncate(doc.source_text, 88)}</p>
                  ) : null}
                </div>
              );
            })}
          </div>
        </>
      ) : (
        <>
          <Hatch height={64} label="Embedding / RAG 인덱스 미구현" />
          <XBox height={72} label="회사자료 업로드 영역" />
        </>
      )}
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// ⑥ 제안서 초안
// ---------------------------------------------------------------------------

export function ProposalPanel({ data }: { data: WireframeData }) {
  const proposal = data.proposal;

  return (
    <Panel
      index={6}
      title="제안서 핵심 섹션 초안"
      source="GET /api/proposal/{id} · POST /api/proposal/generate"
      status={proposal ? "live" : "todo"}
      span={6}
      note="근거 없는 문장은 생성하지 않고 '확인 필요'로 남긴다. DOCX 내보내기는 문장마다 RFP 페이지·원문과 회사 근거를 함께 싣는다. 문장 편집기와 섹션 추가는 미구현이다."
    >
      {proposal ? (
        <>
          <div className="flex flex-wrap items-center gap-1.5">
            <Chip tone="blue">{proposal.generation_method}</Chip>
            <Chip tone="fill">문장 {proposal.sentences.length}개</Chip>
            <Chip tone="fill">
              필수 {proposal.requirements_with_sentence}/{proposal.mandatory_total} 대응
            </Chip>
            {proposal.needs_review_count > 0 ? (
              <Chip tone="red">확인 필요 {proposal.needs_review_count}</Chip>
            ) : null}
            <span className="wf-label ml-auto">
              {proposal.generated_at ? formatDateTime(proposal.generated_at) : "생성시각 없음"}
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <p className="text-[12.5px] font-semibold">{proposal.title}</p>
            {data.selectedId ? (
              <span className="ml-auto flex flex-wrap gap-1.5">
                <DownloadLink
                  className="wf-box px-3 py-1 text-[12px]"
                  href={proposalExportUrl(data.selectedId)}
                  title="핵심 섹션 1개. 문장마다 RFP 페이지·원문과 회사 근거가 함께 실린다"
                >
                  핵심 섹션 DOCX
                </DownloadLink>
                <DownloadLink
                  className="wf-box px-3 py-1 text-[12px]"
                  href={proposalExportUrl(data.selectedId, { format: "pdf", groundedOnly: true })}
                  title="확인 필요 문장을 뺀 PDF. 뺀 문장은 문서 끝 확인 목록에 남는다"
                >
                  근거만 PDF
                </DownloadLink>
                <DownloadLink
                  className="wf-box px-3 py-1 text-[12px]"
                  href={proposalExportUrl(data.selectedId, { format: "txt", groundedOnly: true })}
                  title="확인 필요 문장을 뺀 TXT"
                >
                  근거만 TXT
                </DownloadLink>
                <DownloadLink
                  className="wf-box px-3 py-1 text-[12px]"
                  href={proposalFullExportUrl(data.selectedId)}
                  title="요구사항 카테고리별 섹션으로 구성한 전체 초안. 먼저 생성해야 한다"
                >
                  전체 초안 DOCX
                </DownloadLink>
              </span>
            ) : null}
          </div>

          <div className="flex flex-col gap-1.5">
            {proposal.sentences.slice(0, LIST_ROWS).map((sentence) => (
              <div key={sentence.id} className="flex items-start gap-2">
                <span
                  aria-hidden="true"
                  className="wf-mono mt-1 w-3 shrink-0 text-[12px] text-[var(--wf-ink-3)]"
                >
                  ¶
                </span>
                <span className="min-w-0 flex-1">
                  <span className="text-[12px] leading-6 text-[var(--wf-ink-2)]">
                    {truncate(sentence.text, 130)}
                  </span>
                  <span className="mt-1 flex flex-wrap gap-1">
                    <Chip
                      tone={
                        sentence.grounding_type === "AI_SUGGESTION" ? "red" : "default"
                      }
                    >
                      {GROUNDING_LABELS[sentence.grounding_type]}
                    </Chip>
                    {sentence.requirement_id ? (
                      <Chip tone="blue">{sentence.requirement_id}</Chip>
                    ) : null}
                    {sentence.needs_review ? <Chip tone="red">확인 필요</Chip> : null}
                  </span>
                </span>
              </div>
            ))}
          </div>

          {proposal.requirements_without_sentence.length > 0 ? (
            <p className="wf-note">
              대응 문장이 없는 요구사항:{" "}
              {proposal.requirements_without_sentence.join(", ")}
            </p>
          ) : null}
        </>
      ) : (
        <>
          <Pending loading={data.analysisLoading} lines={4} />
          <XBox height={72} label="제안서 편집 영역" />
        </>
      )}
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// ⑦ AI Auditor
// ---------------------------------------------------------------------------

export function AuditorPanel({ data }: { data: WireframeData }) {
  const audit = data.audit;
  const coverage = audit?.coverage ?? null;

  return (
    <Panel
      index={7}
      title="AI Auditor 역검증"
      source="POST /api/auditor/run"
      status={audit ? "live" : "todo"}
      span={12}
      note="발표의 핵심 화면. 발견 항목 필터·정렬, RFP 원문 하이라이트 뷰어, 수정 반영 후 재검사 루프는 아직 미구현이다."
    >
      {audit && coverage ? (
        <>
          <div className="grid gap-3 md:grid-cols-[240px_1fr]">
            <div className="flex flex-col gap-2">
              <Gauge
                ratio={coverage.total === 0 ? 0 : coverage.covered / coverage.total}
                caption={`Coverage ${coverage.covered} / ${coverage.total}`}
              />
              <div className="flex flex-wrap gap-1.5">
                <Chip tone="fill">부분 {coverage.partial}</Chip>
                <Chip tone={coverage.missing > 0 ? "red" : "fill"}>
                  누락 {coverage.missing}
                </Chip>
                <Chip>문장 {audit.sentence_count}개</Chip>
                <Chip>{audit.llm_used ? "LLM 2차 판단" : "규칙 검사만"}</Chip>
              </div>
              {coverage.truncated ? (
                <p className="wf-note">
                  ⚠ 추출 상한으로 요구사항 후보{" "}
                  {coverage.candidate_count ?? "?"}건 중 {coverage.total}건만
                  검사했습니다. 이 Coverage는 검사한 범위 안에서만 유효합니다.
                </p>
              ) : null}
              {coverage.missing_requirement_ids.length > 0 ? (
                <p className="wf-note">
                  누락 REQ: {coverage.missing_requirement_ids.join(", ")}
                </p>
              ) : null}
              {audit.source_document ? (
                <p className="wf-label truncate" title={audit.source_document}>
                  검사 문서: {audit.source_document}
                </p>
              ) : null}
            </div>

            <div className="flex flex-col gap-2">
              {audit.findings.length === 0 ? (
                <Hatch height={64} label="발견된 문제 없음" />
              ) : (
                audit.findings.slice(0, LIST_ROWS).map((finding) => (
                  <div
                    key={finding.id}
                    className="wf-box wf-box--thin wf-box--b flex flex-col gap-1.5 p-3"
                  >
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Chip tone={severityTone(finding.severity)}>
                        {SEVERITY_LABELS[finding.severity]}
                      </Chip>
                      <span className="text-[12px] font-semibold">
                        {findingTypeLabel(finding.finding_type)}
                      </span>
                      {finding.requirement_id ? (
                        <Chip tone="blue">{finding.requirement_id}</Chip>
                      ) : null}
                      {finding.source_page !== null ? (
                        <Chip>RFP {formatPage(finding.source_page)}</Chip>
                      ) : null}
                      {finding.detected_by ? (
                        <Chip>{METHOD_LABELS[finding.detected_by]}</Chip>
                      ) : null}
                    </div>

                    {finding.source_text ? (
                      <p className="wf-body border-l-2 border-[var(--wf-line)] pl-2">
                        RFP 원문 &ldquo;{truncate(finding.source_text, 120)}&rdquo;
                      </p>
                    ) : null}
                    <p className="wf-body">
                      초안:{" "}
                      {finding.proposal_text
                        ? truncate(finding.proposal_text, 110)
                        : "대응 문장 없음"}
                    </p>
                    <p className="wf-note">조치: {finding.recommendation}</p>
                  </div>
                ))
              )}
              {audit.findings.length > LIST_ROWS ? (
                <span className="wf-label">
                  이하 {audit.findings.length - LIST_ROWS}건 — 목록 뷰 미구현
                </span>
              ) : null}
            </div>
          </div>
          {audit.llm_note ? <p className="wf-label">{audit.llm_note}</p> : null}
        </>
      ) : (
        <div className="grid gap-3 md:grid-cols-[240px_1fr]">
          <div className="flex flex-col gap-2">
            <Gauge ratio={0} caption="Coverage — 미실행" />
            <Pending loading={data.analysisLoading} lines={2} />
          </div>
          <XBox height={110} label="Auditor 발견 목록 영역" />
        </div>
      )}
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// ⑧ Human Final Review
// ---------------------------------------------------------------------------

const REVIEW_CHECKS: { key: keyof ReviewChecklist; label: string }[] = [
  { key: "auditor_findings_reviewed", label: "제출 전 점검에서 발견된 항목을 모두 확인했다" },
  { key: "eligibility_check_resolved", label: "「확인 필요」 자격조건을 담당자가 해소했다" },
  { key: "evidence_confirmed", label: "근거 없는 문장(확인 필요)을 수정했다" },
  { key: "numbers_verified", label: "제출서류 목록과 수치를 대조했다" },
];

const EMPTY_CHECKLIST: ReviewChecklist = {
  auditor_findings_reviewed: false,
  eligibility_check_resolved: false,
  evidence_confirmed: false,
  numbers_verified: false,
};

const REVIEW_STATUS_LABEL: Record<ReviewStatus, string> = {
  pending: "검토 전",
  on_hold: "보류",
  rejected: "불참 (No-Go)",
  approved: "승인 — 제출 가능",
};

export function ReviewPanel({ data }: { data: WireframeData }) {
  const procurementId = data.selectedId;
  const auditRunId = data.audit?.id ?? null;

  const [checklist, setChecklist] = useState<ReviewChecklist>(EMPTY_CHECKLIST);
  const [reviewer, setReviewer] = useState("");
  const [note, setNote] = useState("");
  const [saved, setSaved] = useState<ReviewDecision | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 저장된 결정을 불러온다. 공고가 바뀌면 부모가 key로 이 컴포넌트를 다시 마운트하므로
  // 여기서 이전 공고의 상태를 지울 필요가 없다 — 그래서 effect 본문에서 setState를
  // 동기 호출하지 않는다 (react-hooks/set-state-in-effect).
  useEffect(() => {
    if (!procurementId) return;
    let cancelled = false;
    void getReview(procurementId)
      .then((decision) => {
        if (cancelled || !decision) return;
        setSaved(decision);
        setChecklist(decision.checklist);
        setReviewer(decision.reviewer);
        setNote(decision.note ?? "");
      })
      .catch(() => {
        if (!cancelled) setError("저장된 검토 결과를 불러오지 못했습니다.");
      });
    return () => {
      cancelled = true;
    };
  }, [procurementId]);

  const allChecked = REVIEW_CHECKS.every((item) => checklist[item.key]);

  async function submit(status: ReviewStatus) {
    if (!procurementId) return;
    setBusy(true);
    setError(null);
    try {
      const decision = await saveReview({
        procurement_id: procurementId,
        status,
        checklist,
        reviewer: reviewer.trim() || "담당자 미기입",
        note: note.trim() || null,
        audit_run_id: auditRunId,
      });
      setSaved(decision);
    } catch (err) {
      setError(describeFailure(err, "저장하지 못했습니다."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel
      index={8}
      title="담당자 최종 검토 (Human Review)"
      source="POST /api/review"
      status={saved ? "live" : "todo"}
      span={6}
      note="AI는 제출을 확정하지 않는다. 승인은 확인 항목을 모두 체크해야 저장되며, 결정 시점의 Auditor 실행 id가 근거로 함께 남는다."
    >
      <div className="flex flex-col gap-2">
        {REVIEW_CHECKS.map((item) => (
          <label
            key={item.key}
            className="flex cursor-pointer items-center gap-2 text-[12px]"
          >
            <input
              type="checkbox"
              checked={checklist[item.key]}
              disabled={busy}
              onChange={(event) =>
                setChecklist((current) => ({
                  ...current,
                  [item.key]: event.target.checked,
                }))
              }
            />
            <span>{item.label}</span>
          </label>
        ))}
      </div>

      <div className="flex flex-wrap gap-2">
        <input
          className="wf-box flex-1 px-2 py-1.5 text-[12px]"
          placeholder="검토 담당자"
          value={reviewer}
          disabled={busy}
          onChange={(event) => setReviewer(event.target.value)}
          aria-label="검토 담당자"
        />
        <input
          className="wf-box flex-[2] px-2 py-1.5 text-[12px]"
          placeholder="메모 (선택)"
          value={note}
          disabled={busy}
          onChange={(event) => setNote(event.target.value)}
          aria-label="검토 메모"
        />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          className="wf-box px-4 py-1.5 text-[12px] disabled:cursor-not-allowed disabled:opacity-50"
          disabled={busy || !procurementId || !allChecked}
          onClick={() => void submit("approved")}
          title={allChecked ? "승인" : "확인 항목을 모두 체크해야 승인할 수 있습니다"}
        >
          승인
        </button>
        <button
          type="button"
          className="wf-box px-4 py-1.5 text-[12px] disabled:cursor-not-allowed disabled:opacity-50"
          disabled={busy || !procurementId}
          onClick={() => void submit("on_hold")}
        >
          보류
        </button>
        <button
          type="button"
          className="wf-box px-4 py-1.5 text-[12px] disabled:cursor-not-allowed disabled:opacity-50"
          disabled={busy || !procurementId}
          onClick={() => void submit("rejected")}
        >
          불참
        </button>
        {!allChecked && (
          <span className="wf-label">확인 항목을 모두 체크해야 승인됩니다</span>
        )}
      </div>

      {error && <p className="wf-note">{error}</p>}

      {saved ? (
        <div className="wf-box flex flex-col gap-0.5 px-3 py-2 text-[12px]">
          <span className="font-semibold">
            현재 상태: {REVIEW_STATUS_LABEL[saved.status]}
          </span>
          <span className="wf-label">
            {saved.reviewer} · {new Date(saved.decided_at).toLocaleString("ko-KR")}
          </span>
          {saved.audit_run_id && (
            <span className="wf-label">
              근거 Auditor 실행 {saved.audit_run_id}
              {saved.coverage_total !== null
                ? ` · Coverage ${saved.coverage_covered}/${saved.coverage_total}`
                : ""}
            </span>
          )}
          {saved.note && <span className="wf-label">메모: {saved.note}</span>}
        </div>
      ) : (
        <p className="wf-label">아직 저장된 검토 결과가 없습니다.</p>
      )}
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// ⑨ 확장 백로그
// ---------------------------------------------------------------------------

const BACKLOG: { title: string; detail: string }[] = [
  { title: "견적·원가 Agent", detail: "투입인력·단가 산출" },
  { title: "사전규격 선점 분석", detail: "공고 전 단계 탐지" },
  { title: "공고 변경 감지", detail: "정정공고 diff 알림" },
  { title: "시장 Intelligence", detail: "발주기관·낙찰 이력" },
  { title: "전체 제안서 생성", detail: "PDF / PPT 내보내기" },
  { title: "알림 연동", detail: "메일 · Slack · 카카오" },
];

export function BacklogPanel() {
  return (
    <Panel
      index={9}
      title="확장 예정 화면 (본선 이후)"
      source="해당 없음 — 설계만"
      status="todo"
      span={6}
      note="CLAUDE.md §5의 확장 기능. 핵심 MVP(요구사항 정리표 · Auditor)가 끝나기 전에는 착수하지 않는다."
    >
      <div className="grid grid-cols-2 gap-2">
        {BACKLOG.map((item) => (
          <div
            key={item.title}
            className="wf-hatch flex flex-col justify-center border border-dashed border-[var(--wf-line)] px-2.5 py-2"
          >
            <span className="text-[12px] font-semibold text-[var(--wf-ink-2)]">
              {item.title}
            </span>
            <span className="wf-label mt-0.5 tracking-normal">
              {item.detail}
            </span>
          </div>
        ))}
      </div>
    </Panel>
  );
}
