"use client";

/**
 * 데이터 상태 팝오버.
 *
 * 기본 화면에서 뺀 것(출처별 상태 · 캐시 상세 · 조회 시각 · 새로고침 · 응답 안내 문구)을
 * **지우지 않고** 여기 모았다. 트리거 칩에는 두 출처 중 가장 약한 상태 한 단어를 적어,
 * 실데이터인지 캐시인지 합성 샘플인지 팝오버를 열지 않아도 알 수 있게 한다.
 */

import { Button } from "@/components/ui/primitives";
import { Popover } from "@/components/ui/overlays";
import { DATA_STATUS_MARK, DataStatusLabel, SourceBadge, type DataStatus } from "@/components/ui/SourceBadge";
import { FrozenNotice, FROZEN_RELOAD_REASON } from "@/components/ui/FrozenNotice";
import { formatDateTime } from "@/lib/cosmos/format";
import { sourceBadgeOf } from "@/lib/radar/layout";
import { RELOAD_TERM, collectTerm } from "@/lib/terms";
import type { UnifiedOpportunityListResponse } from "@/types/opportunity";

/**
 * 두 출처 중 가장 약한 상태. 기호 · 색 · 말은 사업기회 머리 칩과 같은 `DATA_STATUS_MARK` (27차 §3-E · UNI-18).
 * 시연 고정 모드에서는 「캐시」가 사고가 아니라 의도라 「시연 고정」으로 적는다 — 오류 · 합성 샘플은 그보다 먼저 말한다.
 */
function worstStatus(data: UnifiedOpportunityListResponse | null, hasError: boolean): DataStatus {
  if (hasError) return "error";
  if (!data) return "cached";
  const values = Object.values(data.source_status);
  if (Object.values(data.source_errors).some(Boolean)) return "error";
  if (values.includes("sample")) return "sample";
  if (data.frozen) return "frozen";
  if (values.includes("cached")) return "cached";
  return "live";
}

export interface RadarDataStatusProps {
  data: UnifiedOpportunityListResponse | null;
  loading: boolean;
  error: string | null;
  /** 출처를 다시 호출한다 (캐시를 건너뛴다). */
  onReload: () => void;
}

export default function RadarDataStatus({ data, loading, error, onReload }: RadarDataStatusProps) {
  const status: DataStatus = loading ? "loading" : worstStatus(data, Boolean(error));
  const frozen = Boolean(data?.frozen);
  // 읽어 주는 이름도 칩 글자와 같은 함수(FRONTEND-07 · 39차 §3-F-2) — 「새 공고 받기 꺼짐」만 읽던 것을 자동 받기 한 줄로
  const word = status === "frozen" ? collectTerm(data?.collect_state) : DATA_STATUS_MARK[status].word;

  return (
    <Popover
      align="end"
      width="320px"
      title="자료 상태"
      triggerLabel={`자료 상태: ${word}. 출처별 상태와 조회 시각을 봅니다`}
      // 40차 FRONT-01 — 단추 글자는 짧게(긴 받은 때 글은 팝오버 안 안내에) · 그래도 좁으면 줄바꿈(사업기회와 같은 단추 꼴)
      triggerClassName="max-w-full text-left whitespace-normal!"
      trigger={<DataStatusLabel status={status} collectState={data?.collect_state ?? null} short />}
    >
      {frozen && <FrozenNotice className="mb-1" collectState={data?.collect_state ?? null} />}
      {data ? (
        <>
          {/* 출처를 하나로 좁히면 반대쪽은 부르지 않는다(null) — 「상태 미상」 · 「0건」은 고장처럼 읽혀 그 쪽은 적지 않는다 (27차 RDR-15). */}
          <div className="flex flex-wrap items-center gap-1.5">
            {data.source_status.g2b != null && (
              <SourceBadge {...sourceBadgeOf(data.source_status.g2b, "g2b")} fetchedAt={data.fetched_at} />
            )}
            {data.source_status.bizinfo != null && (
              <SourceBadge {...sourceBadgeOf(data.source_status.bizinfo, "bizinfo")} fetchedAt={data.fetched_at} />
            )}
          </div>
          <p className="text-cosmos-muted">
            조회 시각 {formatDateTime(data.fetched_at)}
            {data.source_status.g2b != null ? ` · 나라장터 ${data.g2b_count.toLocaleString("ko-KR")}건` : ""}
            {data.source_status.bizinfo != null ? ` · 기업마당 ${data.bizinfo_count.toLocaleString("ko-KR")}건` : ""}
            {data.source_status.g2b == null || data.source_status.bizinfo == null ? " · 다른 출처는 이번 조회에서 뺐습니다" : ""}
            {data.closed_count > 0 ? ` · 마감 ${data.closed_count.toLocaleString("ko-KR")}건 제외 가능` : ""}
          </p>
          {/* 「어떻게 받았는가」 (0920 §4-A-3). 목록 화면과 같은 문장을 쓴다. */}
          {data.collected_by && (
            <p className="text-cosmos-muted">
              수집 방식 {data.collected_by}
              {typeof data.collect_calls === "number" && ` · 호출 ${data.collect_calls}회`}
            </p>
          )}
          {Object.entries(data.source_errors)
            .filter(([, message]) => Boolean(message))
            .map(([key, message]) => (
              <p key={key} className="text-cosmos-red">
                {key === "g2b" ? "나라장터" : "기업마당"} 오류 — {message}
              </p>
            ))}
          {!data.field_mapping_verified && (
            <p className="text-cosmos-amber">
              기업마당 응답 필드 대응을 아직 확인하지 못했습니다 — 지원사업 값은 원문에서 다시 확인하세요.
            </p>
          )}
          <p className="text-cosmos-muted">{data.note}</p>
        </>
      ) : error ? (
        <p className="text-cosmos-red">{error}</p>
      ) : (
        <p className="text-cosmos-muted">아직 응답을 받지 못했습니다.</p>
      )}
      <div className="pt-1">
        <Button
          size="sm"
          variant="secondary"
          onClick={onReload}
          disabled={loading || frozen}
          title={frozen ? FROZEN_RELOAD_REASON : undefined}
        >
          {frozen ? `${RELOAD_TERM} 잠김` : loading ? "불러오는 중…" : RELOAD_TERM}
        </Button>
        {frozen && <p className="pt-1 text-cosmos-muted">{FROZEN_RELOAD_REASON}.</p>}
      </div>
    </Popover>
  );
}
