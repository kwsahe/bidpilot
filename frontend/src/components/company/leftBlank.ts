import type { BlankFieldsResponse } from "@/lib/api";

/** 저장 응답의 「안 적음」 열쇠를 칸에 바로 반영한다 — 다시 읽기를 기다리는 동안 앞 선택을 잃지 않게(42차 FRONT-R41-01). */
export function applyLeftBlank(data: BlankFieldsResponse, keys: readonly string[]): BlankFieldsResponse {
  const chosen = new Set(keys);
  return { ...data, fields: data.fields.map((field) => ({ ...field, left_blank: chosen.has(field.key) })) };
}
