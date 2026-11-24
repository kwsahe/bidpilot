"use client";

/**
 * 사업기회 레이더 범례.
 *
 * 기본 화면에는 **한 줄**만 둔다: 출처 두 개(위/아래) + 거리 의미.
 * 나머지 설명(노드 크기·링 경계·점수 미확인·마감 테두리·산정 방식·확률 아님)은 지우지 않고
 * 「읽는 법」 팝오버(RadarReadingGuide)로 옮겼다 — 같은 문장을 화면 여러 곳에 반복하지 않는다.
 *
 * 색만으로 정보를 전달하지 않는다: 섹터 위치(위/아래) + 출처 이름 텍스트를 함께 둔다.
 * 접점 모양은 출처와 무관하게 하나다 — 같은 종류의 대상이기 때문이다.
 * 여기 적힌 문장과 layout.ts 의 계산 규칙은 반드시 일치해야 한다.
 */

import { PlaneTargetIcon } from "@/components/icons/aviation";
import { REVIEW_PRIORITY } from "@/lib/scoreNames";
import { UNSCORED } from "@/lib/terms";
import { COSMOS_COLORS } from "@/lib/cosmos/theme";
import { URGENCY_DAYS } from "@/lib/deadline";
import { RING_DAY_CANDIDATES } from "@/lib/radar/layout";

/** 「D-3 · D-7」 — 링 후보에서 만든다. 손으로 적지 않는다 (0921 §4-E). */
const RING_DAYS_TEXT = RING_DAY_CANDIDATES.slice(0, 2)
  .map((ring) => ring.label)
  .join(" · ");

/**
 * 범례용 견본 — 스코프의 접점과 **같은 실루엣**을 쓴다.
 * 출처마다 모양을 바꾸지 않는다. 출처는 섹터 위치(위/아래)와 색이 나르고, 모양은 하나다.
 */
function ContactSwatch({ color, size = 15 }: { color: string; size?: number }) {
  return <PlaneTargetIcon filled size={size} className="shrink-0" style={{ color }} />;
}

/** 기본 화면용 한 줄 범례. */
export default function RadarLegend({ className = "" }: { className?: string }) {
  return (
    <p className={`flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] leading-5 text-cosmos-secondary ${className}`}>
      <span className="inline-flex items-center gap-1.5">
        <ContactSwatch color={COSMOS_COLORS.cyan} />
        위쪽 = 나라장터 입찰
      </span>
      <span className="inline-flex items-center gap-1.5">
        <ContactSwatch color={COSMOS_COLORS.violet} />
        아래쪽 = 기업마당 지원사업
      </span>
      <span aria-hidden="true" className="text-cosmos-muted">
        ·
      </span>
      {/*
        **마감은 점수에 들어가지 않는다** (0922 §4-B-0 · 0923 §3-2 · ISSUE-092).
        예전 문구 「클수록 우선순위 점수가 높다」는 그 사실을 말하지 않아, 안쪽에 있는 큰
        노드를 보고 「마감이 가까워서 점수가 높다」고 읽게 했다. 두 축은 서로 다른 것이다.
      */}
      {/* 크기의 이름은 목록 · 상세와 같은 「검토 우선순위」 — 「적합도」는 기업마당 원본 점수(지원 적합도)와 헷갈렸다 (27차 RDR-22). */}
      <span className="text-cosmos-muted">
        가운데 = 우리 회사 · 가운데일수록 마감이 빠름 · 클수록 {REVIEW_PRIORITY.label}가 높음
      </span>
      <span aria-hidden="true" className="text-cosmos-muted">
        ·
      </span>
      {/* 불가 판정은 서버가 숨긴 목록이라 그림에 거의 나오지 않는다 — 숨긴다는 사실과 되돌리는 곳을 적는다 (27차 RDR-05).
          시연용 고정 공고는 불가여도 서버가 남기므로 「숨김」이 늘 참은 아니다 — 예외를 함께 적는다. */}
      <span className="text-cosmos-red">참가할 수 없는 공고는 그림에서 뺐습니다 — 「전체 목록」에서 「불가 포함」을 켜면 보입니다</span>
    </p>
  );
}

function GuideRow({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <li className="min-w-0">
      <span className="block text-[12px] font-semibold text-cosmos-text">{title}</span>
      <span className="mt-0.5 block text-[12px] leading-5 text-cosmos-secondary">{children}</span>
    </li>
  );
}

/**
 * 「읽는 법」 팝오버 내용 — 기본 화면에서 뺀 설명을 전부 여기 모아 둔다.
 * 삭제한 문장은 없다. 위치만 옮겼다.
 */
export function RadarReadingGuide() {
  return (
    <div className="flex flex-col gap-3">
      <ul className="flex flex-col gap-2.5">
        <GuideRow title="가운데 = 현재 회사 · 거리 = 마감(긴급도)">
          안쪽에 있을수록 마감이 이릅니다. 다만 거리는 «남은 날짜 수»가 아니라{" "}
          <strong className="font-semibold text-cosmos-secondary">이 화면에 있는 마감일들의 순서</strong>입니다 —
          D-1과 D-4 사이가 D-28과 D-37 사이와 같은 간격으로 보일 수 있습니다. 대신 두 가지는 언제나 맞습니다:
          안쪽이면 반드시 마감이 더 이르고, 거리가 같으면 반드시 마감일이 같습니다.
        </GuideRow>
        <GuideRow title="방향 = 출처">
          위쪽 절반은 나라장터 입찰(용역 수주, 청록색), 아래쪽 절반은 기업마당 지원사업(지원금·바우처 신청,
          보라색)입니다. 접점 모양은 둘 다 같습니다 — 같은 종류의 대상이고, 출처는 위치와 색이 나릅니다. 같은 출처끼리 한쪽에 모이므로 방향만 봐도 어디서 온 사업인지 알 수 있습니다.
          섹터 <strong className="font-semibold text-cosmos-secondary">안에서의</strong> 각도는 겹치지 않게 나눈
          자리일 뿐이라 따로 뜻이 없고, 그래서 방위 숫자를 적지 않습니다.
        </GuideRow>
        <GuideRow title="점선 링 = 마감 경계">
          {/* 숫자는 `lib/radar/layout` 의 링 후보에서 읽는다 — 손으로 적으면 후보가 바뀔 때
              설명만 거짓말이 된다 (6차 보고 §3 끝의 미착수 · 0921 §4-E). */}
          점선 원 위의 「{RING_DAYS_TEXT}」(2D는 D-3 · D-7도 함께)이 그 원까지 남은 날짜입니다. 「D-
          {RING_DAY_CANDIDATES[1].days} 이라 적힌 원 안쪽 = {RING_DAY_CANDIDATES[1].days}일 이내」가 언제나
          참입니다. 화면에 그 날짜대의 사업이 없으면 링을 그리지 않습니다 — 없는 눈금은 적지 않습니다.
        </GuideRow>
        {/* 이름은 「검토 우선순위」 하나(27차 RDR-22) · 점선 테두리는 그리지 않는다 — 있는 표시만 적는다(RDR-23) ·
            정렬을 바꾸면 그림의 N건이 바뀌어 상대 크기도 다시 잰다(RDR-04). */}
        <GuideRow title={`노드 크기 = ${REVIEW_PRIORITY.label}(마감 무관) · 거리 = 마감`}>
          점수가 높을수록 큽니다. 크기는{" "}
          <strong className="font-semibold text-cosmos-secondary">이 화면 안에서의 상대 크기</strong>라, 점수 폭이
          좁아도 차이를 알아볼 수 있습니다. 정렬을 바꿔 그림에 오른 사업이 달라지면 같은 사업도 크기가 달라질 수
          있습니다. 점수를 계산할 수 없는 항목은 중간 크기로 그리고 라벨 · 목록 · 상세에{" "}
          <strong className="font-semibold text-cosmos-amber">{UNSCORED}</strong>으로 적습니다 — 크기로 점수를 흉내
          내지 않습니다. 0점이 아닙니다.
        </GuideRow>
        <GuideRow title="축 밖 = 마감일 없음 · 마감된 건">
          상시 접수처럼 마감일이 없는 사업은 시간축에 올릴 수 없어 축 바깥에 따로 세웁니다. 「마감이 아주 멀다」는
          뜻이 아닙니다. 이미 마감된 건은 그보다 더 바깥입니다.
        </GuideRow>
        <GuideRow title="바깥 테두리 = 마감 임박도">
          거리가 «순서»를 나르는 대신, 테두리가 «절대 임박도»를 나릅니다. 굵고 밝을수록 마감이 가깝습니다
          (D-{URGENCY_DAYS.urgent} 이하가 가장 강함). 마감일이 없는 사업에는 테두리를 그리지 않고 원문 문구를
          그대로 씁니다.
        </GuideRow>
        <GuideRow title="크기가 커도 「불가」일 수 있습니다">
          불가 판정은 기본으로 그림에서 숨깁니다(예시 공고는 남김) — 몇 건을 숨겼는지는 위 계기 줄에 적고, 전체 목록에서 「불가 포함」을
          켜면 보입니다. 노드 크기는 업무 적합도까지 합친 검토 우선순위일 뿐, 신청 자격 판정이 아닙니다. 회사 활동
          지역 밖이거나 업종·신청 대상이 맞지 않으면 점수가 높아도{" "}
          <strong className="font-semibold text-cosmos-red">불가</strong>로 표시하고 추천 위쪽에 올리지
          않습니다. 예외 자격(지점·사업장 증빙 등)이 있으면 담당자가 다시 판단합니다. 자격 판정은 상세 패널 맨 위에
          사유와 함께 있습니다.
        </GuideRow>
        <GuideRow title="그림과 목록은 같은 데이터입니다">
          평면도 · 순위 목록 · 추적 목록이 모두 같은 계산 결과를 그립니다. 보기를 바꿔도 순위나 판정이 달라지지
          않습니다 — 그림이 보기 어려우면 「순위 목록」으로 바꿔 같은 내용을 표로 읽으면 됩니다.
        </GuideRow>
        {/* 라벨은 이제 모든 노드에 뜬다(ISSUE-109) · 1024px 미만은 상세가 시트다 — 옛 규칙 문장을 고쳤다 (27차 RDR-24). */}
        <GuideRow title="라벨은 모든 노드에">
          모든 노드에 같은 출처 안 순위와 D-day, 검토 우선순위를 띄우고, 고르거나 마우스를 올리면 넓게 펼칩니다. 전체 제목과 산정 근거는 상세(넓은 화면은 오른쪽, 좁은 화면은 아래에서 올라오는 시트)에서,
          전체 목록은 「순위 목록」이나 사업기회 목록 화면에서 봅니다.
        </GuideRow>
      </ul>
      <p className="border-t border-cosmos-border pt-2.5 text-[12px] leading-5 text-cosmos-muted">
        이 화면의 점수는 <strong className="font-semibold text-cosmos-secondary">회사 기준 검토 우선순위</strong>이며
        낙찰·선정 확률이 아닙니다. 나라장터의 추천등급과 기업마당의 지원 적합도는 원본 그대로 상세에 남기고 서로
        합치지 않습니다. 계산할 수 있는 항목만으로 100점 만점으로 환산하며, 미확인 항목은 0점으로 세지 않습니다. 최종 판단은
        사람이 합니다.
      </p>
    </div>
  );
}
