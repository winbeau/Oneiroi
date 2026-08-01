import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { useReleaseComputeSession } from "@/features/compute/hooks";
import type { ComputeSession } from "@/features/studio/types";

export function ReleaseComputeDialog({
  session,
  activeJobs,
  open,
  onOpenChange,
}: {
  session: ComputeSession;
  activeJobs: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const release = useReleaseComputeSession();
  const [cancelRunning, setCancelRunning] = useState(false);
  const [confirmed, setConfirmed] = useState(false);

  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogContent className="max-w-lg p-6">
        <DialogTitle className="font-display text-2xl font-semibold">释放 GPU 资源</DialogTitle>
        <DialogDescription className="mt-2 text-sm text-[var(--color-text-muted)]">
          默认等待运行任务完成后退出 Model Worker，并验证租约和显存均已释放。
        </DialogDescription>
        {activeJobs > 0 && (
          <div className="mt-5 rounded-lg border border-[var(--color-border)] bg-white p-3 text-sm">
            当前有 {activeJobs} 个活跃任务。
            <label className="mt-3 flex items-center gap-2 text-[var(--color-danger)]">
              <input
                checked={cancelRunning}
                onChange={(event) => {
                  setCancelRunning(event.target.checked);
                  setConfirmed(false);
                }}
                type="checkbox"
              />
              取消任务并释放（危险操作）
            </label>
            {cancelRunning && (
              <label className="mt-2 flex items-center gap-2 text-xs">
                <input
                  checked={confirmed}
                  onChange={(event) => setConfirmed(event.target.checked)}
                  type="checkbox"
                />
                我确认强制取消正在运行的任务
              </label>
            )}
          </div>
        )}
        {release.error && (
          <p className="mt-3 text-sm text-[var(--color-danger)]">{release.error.message}</p>
        )}
        <div className="mt-5 flex justify-end gap-2">
          <Button onClick={() => onOpenChange(false)} variant="ghost">
            返回
          </Button>
          <Button
            disabled={release.isPending || (cancelRunning && !confirmed)}
            onClick={() =>
              release.mutate(
                {
                  sessionId: session.id,
                  policy: cancelRunning ? "cancel_running" : "when_idle",
                  confirmed,
                },
                { onSuccess: () => onOpenChange(false) },
              )
            }
            className={cancelRunning ? "bg-[var(--color-danger)] hover:bg-[var(--color-danger)]" : undefined}
            variant="primary"
          >
            {release.isPending ? "正在释放…" : activeJobs > 0 ? "任务完成后释放" : "确认释放"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
