import { AlertTriangle, CheckCircle2, LoaderCircle } from "lucide-react";

import type { ComputeSlot } from "@/features/studio/types";

export function SlotStatusRow({ slot }: { slot: ComputeSlot }) {
  const ready = slot.state === "ready";
  const error = slot.state === "error";
  return (
    <div className="flex items-center gap-3 rounded-lg border border-[var(--color-border)] bg-white/65 px-3 py-2.5">
      <span className="grid size-7 place-items-center rounded-md bg-[var(--color-surface-muted)]">
        {ready ? (
          <CheckCircle2 className="size-4 text-[var(--color-success)]" />
        ) : error ? (
          <AlertTriangle className="size-4 text-[var(--color-danger)]" />
        ) : (
          <LoaderCircle className="size-4 animate-spin text-[var(--color-accent)]" />
        )}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-xs font-semibold">
          GPU {slot.physicalIndex} · {(slot.profile ?? "waiting").toUpperCase()}
        </p>
        <p className="mt-0.5 truncate text-[11px] text-[var(--color-text-muted)]">
          {slot.lastError ?? slot.loadStage ?? slot.state}
        </p>
      </div>
      <span className="font-mono text-[11px] tabular-nums text-[var(--color-text-faint)]">
        {slot.loadProgress}%
      </span>
    </div>
  );
}
