"use client";

/**
 * 내 비밀번호 바꾸기(44차 S5) — 로그인한 사람이 자기 비밀번호만. 지금 비밀번호 확인 · 규칙(8자 이상)은 관리 명령과 같다.
 * 틀리면 로그인과 같은 연속 실패 잠금 · 활동 기록에는 값 없이 「내 비밀번호 바꿈」만 남는다. 남의 비밀번호 초기화는 관리자 서버 명령.
 */

import { useState, type FormEvent } from "react";

import { Sheet } from "@/components/ui/overlays";
import { Button, InlineAlert } from "@/components/ui/primitives";
import { changeMyPassword } from "@/lib/api";
import { describeFailure } from "@/lib/errors";

const FIELD = "mc-focus min-h-10 w-full rounded-lg border border-cosmos-border bg-cosmos-panel px-3 text-[14px] text-cosmos-text";
const MIN_LENGTH = 8;

export default function PasswordChange({ className = "" }: { className?: string }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ old: "", next: "", again: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const close = () => {
    setOpen(false);
    setForm({ old: "", next: "", again: "" });  // 닫으면 칸을 비운다(화면에 남기지 않음)
    setError(null);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    if (form.next.length < MIN_LENGTH) return setError(`새 비밀번호는 ${MIN_LENGTH}자 이상이어야 합니다.`);
    if (form.next !== form.again) return setError("새 비밀번호 두 칸이 다릅니다.");
    setBusy(true);
    try {
      await changeMyPassword(form.old, form.next);
      setDone(true);
      close();
    } catch (e: unknown) {
      setError(describeFailure(e, "비밀번호를 바꾸지 못했습니다."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={() => {
          setDone(false);
          setOpen(true);
        }}
        className={`mc-focus shrink-0 rounded-md border border-cosmos-border px-2 py-1 text-[12px] text-cosmos-secondary transition-colors hover:bg-cosmos-elevated ${className}`}
      >
        비밀번호
      </button>
      {done && <span role="status" className="text-[14px] font-medium text-cosmos-teal">✓ 비밀번호를 바꿨습니다</span>}
      <Sheet open={open} onClose={close} title="내 비밀번호 바꾸기" description="다음 로그인부터 새 비밀번호를 씁니다. 이미 로그인해 둔 다른 PC · 브라우저는 끊기지 않습니다(최대 12시간) — 비밀번호가 샌 것 같으면 관리자에게 계정 끄기를 부탁하세요. 다른 사람의 비밀번호는 관리자가 서버에서 바꿉니다.">
        <form className="flex flex-col gap-3" onSubmit={(e) => void submit(e)}>
          <label className="flex flex-col gap-1 text-[13px] text-cosmos-secondary">
            지금 비밀번호
            <input className={FIELD} type="password" autoComplete="current-password" value={form.old} onChange={(e) => setForm({ ...form, old: e.target.value })} required />
          </label>
          <label className="flex flex-col gap-1 text-[13px] text-cosmos-secondary">
            새 비밀번호({MIN_LENGTH}자 이상)
            <input className={FIELD} type="password" autoComplete="new-password" value={form.next} onChange={(e) => setForm({ ...form, next: e.target.value })} required />
          </label>
          <label className="flex flex-col gap-1 text-[13px] text-cosmos-secondary">
            새 비밀번호 한 번 더
            <input className={FIELD} type="password" autoComplete="new-password" value={form.again} onChange={(e) => setForm({ ...form, again: e.target.value })} required />
          </label>
          {error && <InlineAlert tone="fail">{error}</InlineAlert>}
          <div className="flex gap-2">
            <Button type="submit" variant="primary" disabled={busy || !form.old || !form.next || !form.again}>
              {busy ? "바꾸는 중…" : "바꾸기"}
            </Button>
            <Button type="button" variant="ghost" onClick={close}>그만두기</Button>
          </div>
        </form>
      </Sheet>
    </>
  );
}
