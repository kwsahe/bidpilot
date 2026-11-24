"use client";

import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { safeNextPath } from "@/lib/authPolicy";

/**
 * 로그인 화면의 안내 문구는 **실제 런타임 모드**에서 나온다.
 *
 * 예전에는 「심사·팀 공유용 데모」·「읽기 전용」·「로컬에서 백엔드를 켜야 동작합니다」가
 * 하드코딩돼 있었다. 실백엔드가 붙은 사내 배포에서는 셋 다 사실이 아니다.
 * 모드는 서버 컴포넌트(page.tsx)가 읽어 prop 으로 넘긴다 — 여기서 다시 판정하지 않는다.
 *
 * 계정은 이제 **직원별 계정**이다 (계정·권한 계약서). 「팀 공용 접근계정 하나이며
 * 직원별 계정·권한은 아직 없습니다」라고 적혀 있던 문장은 사실이 아니게 됐다.
 * 다만 공용 접근계정(DEMO_USER)도 호환을 위해 계속 받으므로, 「개인 계정만 된다」고도
 * 적지 않는다 — 화면은 둘 중 무엇을 받았는지 알 수 없다.
 */
export function LoginForm({ realBackend }: { realBackend: boolean }) {
  const router = useRouter();
  const params = useSearchParams();
  // 이 사이트 안의 주소만 따라간다 (CMN-03).
  const next = safeNextPath(params.get("next"));

  const [user, setUser] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user, password }),
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => ({}))) as { error?: string };
        /**
         * 자격증명이 틀린 경우(401)에는 **서버가 뭐라고 하든** 같은 문장만 띄운다.
         * 「없는 아이디입니다」와 「비밀번호가 틀렸습니다」를 나눠 보여주면, 아이디 하나만
         * 찍어 보고도 그 계정이 있는지 알 수 있다. 계정 목록을 공짜로 알려주는 셈이다.
         * 그 밖의 실패(게이트 미설정 503, 요청 형식 400 등)는 사유를 알아야 고칠 수 있으므로
         * 서버 문장을 그대로 쓴다. 잠금(「로그인 시도가 너무 많습니다」)은 401 이어도 그대로 보인다 — 계정 존재를
         * 드러내지 않는 문장이고, 가리면 담당자가 비밀번호를 의심하며 계속 다시 친다 (CMN-04).
         */
        const locked = typeof body.error === "string" && body.error.includes("너무 많습니다");
        setError(
          response.status === 401 && !locked
            ? "아이디 또는 비밀번호가 맞지 않습니다."
            : (body.error ?? "로그인하지 못했습니다."),
        );
        return;
      }
      router.replace(next);
      router.refresh();
    } catch {
      setError("서버에 연결하지 못했습니다.");
    } finally {
      setBusy(false);
    }
  }

  const field =
    "w-full rounded-lg border border-cosmos-border bg-cosmos-bg px-4 py-3 text-[15px] " +
    "text-cosmos-text outline-none transition focus:border-cosmos-cyan";

  return (
    <form onSubmit={submit} className="flex w-full max-w-[380px] flex-col gap-5">
      <div className="flex flex-col gap-2">
        {/* 머리 로고 윗줄과 같은 표어 · 같은 대소문자 (CMN-16) */}
        <p className="text-[12px] font-bold tracking-[0.14em] text-cosmos-cyan">
          근거 기반 AI 수주 도우미
        </p>
        <h1 className="text-[30px] font-bold leading-tight text-cosmos-text">
          BidPilot AI
        </h1>
        <p className="text-[13.5px] leading-relaxed text-cosmos-secondary">
          {realBackend
            ? "사내 전용 시스템입니다. 본인에게 발급된 계정으로 들어오세요."
            : "심사·팀 공유용 데모입니다. 본인에게 발급된 계정으로 들어오세요."}
        </p>
      </div>

      <div className="flex flex-col gap-3">
        <label className="flex flex-col gap-2">
          <span className="text-[12.5px] font-semibold text-cosmos-secondary">아이디</span>
          <input
            className={field}
            value={user}
            onChange={(e) => setUser(e.target.value)}
            autoComplete="username"
            autoFocus
            required
          />
        </label>
        <label className="flex flex-col gap-2">
          <span className="text-[12.5px] font-semibold text-cosmos-secondary">비밀번호</span>
          <input
            className={field}
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
      </div>

      {error ? (
        <p
          role="alert"
          className="rounded-lg border border-cosmos-red/40 bg-cosmos-red/10 px-4 py-3 text-[13px] text-cosmos-red"
        >
          {error}
        </p>
      ) : null}

      <button
        type="submit"
        disabled={busy}
        className="rounded-lg bg-cosmos-blue-strong px-4 py-3 text-[15px] font-bold text-white transition hover:brightness-110 disabled:opacity-50"
      >
        {busy ? "확인하는 중…" : "들어가기"}
      </button>

      {realBackend ? (
        <p className="text-[12px] leading-relaxed text-cosmos-muted">
          로그인하면 <span className="text-cosmos-secondary">공고 조회</span>, 분석 실행,
          회사자료 관리, 제안서 작성 지원, 제출 전 점검을 사용할 수 있습니다.
          계정마다 할 수 있는 일이 다릅니다 — <span className="text-cosmos-secondary">열람자</span>는
          보기만, <span className="text-cosmos-secondary">편집자</span>는 분석·작성까지,{" "}
          <span className="text-cosmos-secondary">관리자</span>는 회사 관리까지 합니다.
          계정은 관리자가 서버에서 만듭니다(비밀번호를 잊었으면 관리자에게). 다른 사람과 나눠 쓰지 마세요 — 저장·승인 기록에 로그인한 사람으로 남습니다.
        </p>
      ) : (
        <p className="text-[12px] leading-relaxed text-cosmos-muted">
          이 배포본은 <span className="text-cosmos-secondary">읽기 전용</span>입니다. 저장된 분석
          결과를 보여주며 검사 실행·제안서 생성·문서 내보내기는 동작하지 않습니다.
        </p>
      )}
    </form>
  );
}

