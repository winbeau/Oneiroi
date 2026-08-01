import { Cpu, LoaderCircle } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ComputeSessionPanel } from "@/features/compute/compute-session-panel";
import {
  useComputeSession,
  useComputeSessionEvents,
} from "@/features/compute/hooks";
import { GpuSelectorPopover } from "@/features/compute/gpu-selector-popover";
import { ReleaseComputeDialog } from "@/features/compute/release-compute-dialog";
import { demoMode } from "@/lib/api-client";

export function ComputeControl({ activeJobs }: { activeJobs: number }) {
  const [selectorOpen, setSelectorOpen] = useState(false);
  const [releaseOpen, setReleaseOpen] = useState(false);
  const sessionQuery = useComputeSession();
  const session = sessionQuery.data;
  useComputeSessionEvents(session);

  return (
    <div className="border-b border-[var(--color-border)] bg-white/55 px-4 py-2.5 md:px-6">
      <div className="flex flex-wrap items-center gap-3">
        <span className="grid size-8 place-items-center rounded-lg bg-[var(--color-accent-soft)] text-[var(--color-accent)]">
          <Cpu className="size-4" />
        </span>
        {!session ? (
          <>
            <div className="min-w-0 flex-1">
              <p className="text-xs font-semibold">GPU 资源未加载</p>
              <p className="text-[10px] text-[var(--color-text-faint)]">
                显式热加载后才能提交真实任务
              </p>
            </div>
            <Button onClick={() => setSelectorOpen(true)} size="sm" variant="primary">
              热加载
            </Button>
          </>
        ) : (
          <>
            <div className="min-w-0 flex-1">
              <p className="flex items-center gap-2 text-xs font-semibold">
                {["allocating", "loading"].includes(session.state) && (
                  <LoaderCircle className="size-3.5 animate-spin text-[var(--color-accent)]" />
                )}
                {session.allocatedGpuCount} 张 H100 · Fast {session.profilePlan.fast} · HQ{" "}
                {session.profilePlan.hq}
              </p>
              <p className="text-[10px] uppercase tracking-wide text-[var(--color-text-faint)]">
                {session.state}
                {session.errorCode ? ` · ${session.errorCode}` : ""}
              </p>
            </div>
            <Button onClick={() => setReleaseOpen(true)} size="sm" variant="secondary">
              释放资源
            </Button>
          </>
        )}
        {demoMode && (
          <span className="rounded-full bg-[rgb(214_154_87_/_14%)] px-2 py-1 text-[10px] font-semibold text-[var(--color-warning)]">
            DEMO MODE
          </span>
        )}
      </div>
      {session && ["allocating", "loading", "degraded", "failed"].includes(session.state) && (
        <div className="mt-2">
          <ComputeSessionPanel session={session} />
        </div>
      )}
      {sessionQuery.isError && (
        <p className="mt-2 text-xs text-[var(--color-danger)]">
          BFF/Gateway 不可用，生产模式不会创建模拟任务。
        </p>
      )}
      <GpuSelectorPopover onOpenChange={setSelectorOpen} open={selectorOpen} />
      {session && (
        <ReleaseComputeDialog
          activeJobs={activeJobs}
          onOpenChange={setReleaseOpen}
          open={releaseOpen}
          session={session}
        />
      )}
    </div>
  );
}
