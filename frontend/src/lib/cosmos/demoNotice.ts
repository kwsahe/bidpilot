/**
 * 데모 시나리오 전용 합성 공고.
 *
 * `/api/procurements`는 이제 나라장터 실공고만 내려주므로(docs/real_data_migration.md §1),
 * 합성 RFP 공고(synthetic-rfp-0001)의 메타데이터는 여기서만 관리한다.
 * 값은 합성 RFP fixture(`data/public/sample_rfp/synthetic_ai_training_rfp.pdf`)에 맞춘 것이며,
 * 예전에 있던 `data/public/sample_procurements/sample_procurement.json` 더미는 삭제되었다.
 * UI에서는 항상 「합성 데모 공고」로 표기한다 (실제 공고인 것처럼 보이면 안 된다).
 */

import { SYNTHETIC_NOTICE } from "@/lib/terms";
import type { ProcurementNotice } from "@/types/procurement";

/** 데모 시나리오 공고 ID (RFP fixture · demo_cosmos_scenario와 같은 키). */
export const DEMO_PROCUREMENT_ID = "synthetic-rfp-0001";

export const DEMO_NOTICE_LABEL = SYNTHETIC_NOTICE;

/**
 * 데모 공고 날짜는 **화면을 연 시각 기준**이다 (ISSUE-160 · 27차 §3-F).
 * 예전에는 마감이 2026-09-25 로 박혀 있어 그날이 지나자 첫 화면이 「입찰 종료 · 참여할 수 없습니다」로 열렸다.
 * 공고일 = 연 날 −7일 09:00 · 마감 = 연 날 +21일 18:00 (KST). RFP 원문 속 날짜(교육 일정 등)는 그대로다.
 * `scripts/demo_preflight.py` 가 아래 두 수를 읽어 「데모 공고 마감 D-n」을 알린다 — 규칙은 여기 한 곳.
 */
export const DEMO_PUBLISHED_DAYS_AGO = 7;
export const DEMO_DEADLINE_DAYS = 21;

const KST_MS = 9 * 3600_000;
const DAY_MS = 86_400_000;

/** `nowMs` 의 KST 날짜에서 `dayOffset` 일 뒤 `hour` 시 (+09:00 표기). */
function kstIso(nowMs: number, dayOffset: number, hour: number): string {
  const d = new Date(nowMs + KST_MS + dayOffset * DAY_MS);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}T${pad(hour)}:00:00+09:00`;
}

export function buildDemoNotice(nowMs: number): ProcurementNotice {
  return {
    id: DEMO_PROCUREMENT_ID,
    notice_no: "SYN-2026-0915-01",
    title: "[가상 예시] 2026 생성형 AI 실무역량 강화 교육 운영 용역",
    agency: "광주미래학습진흥원(가상기관)",
    published_at: kstIso(nowMs, -DEMO_PUBLISHED_DAYS_AGO, 9),
    deadline_at: kstIso(nowMs, DEMO_DEADLINE_DAYS, 18),
    budget: 60000000,
    region: "광주광역시",
    description: "생성형 AI 실무교육 12회 운영 및 성과관리 통합 테스트용 가상 예시 공고",
    source_url: null,
    raw_data: { synthetic: true },
  };
}

/** 모듈을 읽은 시각(= 브라우저에서 화면을 연 시각) 기준. 데이터는 모두 effect 에서 불러와 서버 렌더에 쓰이지 않는다. */
export const DEMO_NOTICE: ProcurementNotice = buildDemoNotice(Date.now());

export function isDemoProcurementId(id: string | null): boolean {
  return id === DEMO_PROCUREMENT_ID;
}

/** 서버가 요구사항을 뽑을 수 있는 공고 id 모양 — 합성 fixture 또는 `g2b-<공고번호>-<차수>` (backend rfp_parser REAL_NOTICE_ID_RE). 정리표 · 제안서 작성이 함께 쓴다(2.1.2). */
const REAL_NOTICE_ID = /^g2b-[A-Za-z0-9]{1,40}-[A-Za-z0-9]{1,8}$/;
export function isParsableNoticeId(id: string): boolean {
  return isDemoProcurementId(id) || REAL_NOTICE_ID.test(id);
}
