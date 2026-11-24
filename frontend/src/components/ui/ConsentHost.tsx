"use client";

import { useEffect, useSyncExternalStore } from "react";

import { Modal } from "@/components/ui/overlays";
import { Button } from "@/components/ui/primitives";
import { answerConsent, readConsent, registerConsentHost, subscribeConsent } from "@/lib/consentPrompt";

const readServer = () => null;

/** 화면 안 확인 창 — `lib/consentPrompt` 의 질문을 `Modal` 로 받는다. Esc · 바깥 누름 = 취소 (28차 §A-6). */
export function ConsentHost() {
  const request = useSyncExternalStore(subscribeConsent, readConsent, readServer);
  useEffect(() => registerConsentHost(), []);
  const cancel = () => answerConsent(false);
  return (
    <Modal open={request !== null} onClose={cancel} title={request?.title ?? ""}>
      {request && (
        <div className="flex flex-col gap-3" data-consent-dialog>
          <p className="text-[13px] leading-5 text-cosmos-secondary">{request.body}</p>
          {request.fileName && (
            <p className="break-all rounded-md border border-cosmos-border bg-cosmos-panel px-2.5 py-1.5 text-[13px] text-cosmos-text">
              {request.fileName}
              {request.size && <span className="text-cosmos-muted">{request.size}</span>}
            </p>
          )}
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="secondary" onClick={cancel}>
              {request.cancelLabel ?? "취소"}
            </Button>
            <Button variant="primary" onClick={() => answerConsent(true)}>
              {request.confirmLabel}
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
