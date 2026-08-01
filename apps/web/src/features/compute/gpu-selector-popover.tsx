import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { useComputeGpus, useCreateComputeSession } from "@/features/compute/hooks";
import { cn } from "@/lib/utils";

export function GpuSelectorPopover({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const inventory = useComputeGpus();
  const createSession = useCreateComputeSession();
  const [mode, setMode] = useState<"auto" | "manual">("auto");
  const [requested, setRequested] = useState(4);
  const [selected, setSelected] = useState<string[]>([]);
  const [allowPartial, setAllowPartial] = useState(true);

  const plannedCount = mode === "manual" ? selected.length : requested;
  const plan = useMemo(() => {
    const count = Math.min(4, plannedCount);
    return count === 1
      ? { fast: 1, hq: 0 }
      : count === 2
        ? { fast: 1, hq: 1 }
        : count === 3
          ? { fast: 2, hq: 1 }
          : count >= 4
            ? { fast: 2, hq: 2 }
            : { fast: 0, hq: 0 };
  }, [plannedCount]);

  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogContent className="max-w-2xl p-6">
        <DialogTitle className="font-display text-2xl font-semibold">热加载 H100 资源</DialogTitle>
        <DialogDescription className="mt-2 text-sm text-[var(--color-text-muted)]">
          只会租约当前 eligible 的 GPU；不会终止或抢占外部 CUDA 进程。
        </DialogDescription>

        <div className="mt-5 flex gap-2">
          {(["auto", "manual"] as const).map((value) => (
            <button
              className={cn(
                "rounded-lg border px-3 py-2 text-sm",
                mode === value
                  ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)] text-[var(--color-accent)]"
                  : "border-[var(--color-border)] bg-white",
              )}
              key={value}
              onClick={() => setMode(value)}
              type="button"
            >
              {value === "auto" ? "自动选卡" : "手动选卡"}
            </button>
          ))}
          <label className="ml-auto text-xs text-[var(--color-text-muted)]">
            请求卡数
            <select
              aria-label="请求 GPU 数量"
              className="ml-2 rounded-md border border-[var(--color-border)] bg-white px-2 py-1.5"
              onChange={(event) => setRequested(Number(event.target.value))}
              value={requested}
            >
              {Array.from(
                { length: inventory.data?.maximumSelectable ?? 4 },
                (_, index) => index + 1,
              ).map((count) => (
                <option key={count} value={count}>
                  {count}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="scrollbar-notion mt-4 max-h-64 space-y-2 overflow-y-auto">
          {inventory.isLoading && <p className="text-sm">正在读取 GPU inventory…</p>}
          {inventory.isError && (
            <p className="text-sm text-[var(--color-danger)]">无法读取 GPU inventory。</p>
          )}
          {inventory.data?.gpus.map((gpu) => {
            const checked = selected.includes(gpu.id);
            return (
              <label
                className={cn(
                  "flex items-center gap-3 rounded-lg border px-3 py-2.5",
                  gpu.eligible
                    ? "border-[var(--color-border)] bg-white"
                    : "border-[var(--color-border)] bg-[var(--color-surface-muted)] opacity-60",
                )}
                key={gpu.id}
              >
                {mode === "manual" && (
                  <input
                    checked={checked}
                    disabled={!gpu.eligible}
                    onChange={(event) =>
                      setSelected((items) =>
                        event.target.checked
                          ? [...items, gpu.id].slice(0, 4)
                          : items.filter((id) => id !== gpu.id),
                      )
                    }
                    type="checkbox"
                  />
                )}
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">
                    GPU {gpu.physicalIndex} · {gpu.name}
                  </p>
                  <p className="mt-0.5 text-[11px] text-[var(--color-text-muted)]">
                    {gpu.vramUsedMiB} / {gpu.vramTotalMiB} MiB · {gpu.utilizationPercent}%
                  </p>
                </div>
                <span className="text-[10px] text-[var(--color-text-faint)]">
                  {gpu.eligible ? "ELIGIBLE" : gpu.unavailableReason}
                </span>
              </label>
            );
          })}
        </div>

        <label className="mt-4 flex items-center gap-2 text-sm">
          <input
            checked={allowPartial}
            onChange={(event) => setAllowPartial(event.target.checked)}
            type="checkbox"
          />
          空闲卡不足时允许 partial allocation
        </label>
        <p className="mt-3 rounded-lg bg-[var(--color-surface-muted)] px-3 py-2 text-xs">
          预计 profile：Fast {plan.fast} · HQ {plan.hq}
        </p>
        {createSession.error && (
          <p className="mt-3 text-sm text-[var(--color-danger)]">{createSession.error.message}</p>
        )}
        <div className="mt-5 flex justify-end gap-2">
          <Button onClick={() => onOpenChange(false)} variant="ghost">
            取消
          </Button>
          <Button
            disabled={
              createSession.isPending ||
              (mode === "manual" && selected.length === 0) ||
              !inventory.data
            }
            onClick={() =>
              createSession.mutate(
                {
                  requestedGpuCount: requested,
                  selectionMode: mode,
                  gpuIds: mode === "manual" ? selected : [],
                  allowPartial,
                },
                { onSuccess: () => onOpenChange(false) },
              )
            }
            variant="primary"
          >
            {createSession.isPending ? "正在申请…" : "开始热加载"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
