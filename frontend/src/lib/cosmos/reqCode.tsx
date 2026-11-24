"use client";

import { createContext, useContext, type ReactNode } from "react";

import type { Requirement } from "@/types/rfp";

import { displayCodeOf } from "./itemTypes";

type CodeSource = ReadonlyArray<Pick<Requirement, "display_code" | "item_type" | "requirement_id">>;

const cache = new WeakMap<CodeSource, Map<string, string>>();

/**
 * 저장 id(REQ-026) → 화면 코드(EVL-026) — 정리표와 같은 코드(45차 M7). 대시보드 · 발견 · 근거 줄은 저장 id 를 그려
 * 한 항목이 「EVL-026」 · 「REQ-026」 둘로 보였다. 목록에 없는 id 는 그대로.
 */
export function requirementCode(requirements: CodeSource, id: string): string {
  let codes = cache.get(requirements);
  if (!codes) {
    codes = new Map(requirements.map((req) => [req.requirement_id, displayCodeOf(req)]));
    cache.set(requirements, codes);
  }
  return codes.get(id) ?? id;
}

const ReqCodeContext = createContext<CodeSource>([]);

export function ReqCodeProvider({ requirements, children }: { requirements: CodeSource; children: ReactNode }) {
  return <ReqCodeContext.Provider value={requirements}>{children}</ReqCodeContext.Provider>;
}

/** 공급자 밖(목록 없음)이면 저장 id 그대로 */
export function useReqCode(): (id: string) => string {
  const requirements = useContext(ReqCodeContext);
  return (id) => requirementCode(requirements, id);
}
