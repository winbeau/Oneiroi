import {
  Activity,
  CheckCircle2,
  Cpu,
  Gauge,
  LoaderCircle,
  Power,
  Server,
  Zap,
} from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ComputeSessionPanel } from "@/features/compute/compute-session-panel";
import { GpuInventoryPanel } from "@/features/compute/gpu-inventory-panel";
import { GpuSelectorPopover } from "@/features/compute/gpu-selector-popover";
import {
  useComputeCapabilities,
  useComputeGpus,
  useComputeSession,
} from "@/features/compute/hooks";
import { ReleaseComputeDialog } from "@/features/compute/release-compute-dialog";
import { useJobs } from "@/features/studio/hooks";
import type { ProfileCapability } from "@/features/studio/types";
import { cn } from "@/lib/utils";

const sessionLabels: Record<string, string> = {
  requested: "等待分配",
  allocating: "正在分配",
  loading: "正在加载模型",
  ready: "算力已就绪",
  degraded: "部分算力已就绪",
  failed: "加载失败",
  draining: "等待任务结束",
  releasing: "正在释放",
  released: "已释放",
};

function MetricCard({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Cpu;
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-[var(--radius-lg)] border bg-white/82 p-4 shadow-[var(--shadow-card)]">
      <div className="flex items-center gap-2 text-[var(--color-text-muted)]">
        <Icon className="size-3.5" />
        <span className="text-[11px] font-medium">{label}</span>
      </div>
      <p className="mt-2.5 text-xl font-semibold tracking-[-0.03em]">{value}</p>
    </div>
  );
}

function CapabilityCard({
  profile,
  hasSession,
}: {
  profile: ProfileCapability;
  hasSession: boolean;
}) {
  const fast = profile.tier === "fast";
  const resolutions = profile.resolutions ?? [];
  const durations = profile.durations ?? [];
  const durationLabel = durations.length
    ? durations.length > 2
      ? `${Math.min(...durations)}–${Math.max(...durations)} 秒`
      : `${durations.join(" / ")} 秒`
    : "—";
  return (
    <article className="rounded-[var(--radius-lg)] border bg-white/82 p-4 shadow-[var(--shadow-card)]">
      <div className="flex items-start gap-3">
        <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-[var(--color-accent-soft)] text-[var(--color-accent)]">
          {fast ? <Zap className="size-4" /> : <Gauge className="size-4" />}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold">LTX 2.3 {fast ? "快速" : "高质量"}</h3>
            <span
              className={cn(
                "rounded-full px-2 py-0.5 text-[9px] font-semibold",
                profile.available
                  ? "bg-[var(--color-success-soft)] text-[var(--color-success)]"
                  : "bg-[var(--color-surface-muted)] text-[var(--color-text-faint)]",
              )}
            >
              {profile.available ? (hasSession ? "READY" : "INSTALLED") : "UNAVAILABLE"}
            </span>
          </div>
          <p className="mt-1 truncate font-mono text-[9px] text-[var(--color-text-faint)]">
            {profile.id}
          </p>
        </div>
      </div>
      <dl className="mt-4 grid grid-cols-2 gap-3 border-t pt-3 text-[11px]">
        <div>
          <dt className="text-[var(--color-text-faint)]">分辨率</dt>
          <dd className="mt-1 font-medium">{resolutions.join(" / ") || "—"}</dd>
        </div>
        <div>
          <dt className="text-[var(--color-text-faint)]">时长</dt>
          <dd className="mt-1 font-medium">{durationLabel}</dd>
        </div>
      </dl>
      {!profile.available && profile.unavailableReason && (
        <p className="mt-3 text-[10px] text-[var(--color-warning)]">
          {profile.unavailableReason}
        </p>
      )}
    </article>
  );
}

export function ComputePage() {
  const [selectorOpen, setSelectorOpen] = useState(false);
  const [releaseOpen, setReleaseOpen] = useState(false);
  const [liveInventory, setLiveInventory] = useState(true);
  const inventory = useComputeGpus(liveInventory ? 3_000 : false);
  const sessionQuery = useComputeSession();
  const session = sessionQuery.data;
  const capabilities = useComputeCapabilities(session?.id ?? "");
  const jobs = useJobs().data ?? [];
  const activeJobs = jobs.filter(
    (job) => !["succeeded", "failed", "cancelled"].includes(job.stage),
  );
  const ready = Boolean(session && ["ready", "degraded"].includes(session.state));

  return (
    <main className="scrollbar-notion min-h-[calc(100vh-60px)] overflow-y-auto px-4 py-7 md:px-7 md:py-10">
      <div className="mx-auto w-full max-w-[1180px]">
        <header className="flex flex-col gap-5 border-b pb-5 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="flex items-center gap-2 text-xs font-medium text-[var(--color-accent)]">
              <Server className="size-3.5" /> COMPUTE WORKSPACE
            </p>
            <h1 className="font-display mt-2 text-3xl font-semibold tracking-[-0.035em] md:text-4xl">
              算力
            </h1>
          </div>
          <div className="flex items-center gap-2">
            {session ? (
              <Button onClick={() => setReleaseOpen(true)} variant="secondary">
                <Power className="size-3.5" /> 释放资源
              </Button>
            ) : (
              <Button onClick={() => setSelectorOpen(true)} variant="primary">
                <Zap className="size-3.5" /> 热加载算力
              </Button>
            )}
          </div>
        </header>

        <section aria-label="算力概览" className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard
            icon={ready ? CheckCircle2 : LoaderCircle}
            label="当前状态"
            value={session ? sessionLabels[session.state] ?? session.state : "算力未加载"}
          />
          <MetricCard
            icon={Cpu}
            label="H100"
            value={`${session?.allocatedGpuCount ?? 0} 张`}
          />
          <MetricCard
            icon={Zap}
            label="Profile 分配"
            value={`Fast ${session?.profilePlan.fast ?? 0} / HQ ${session?.profilePlan.hq ?? 0}`}
          />
          <MetricCard
            icon={Activity}
            label="活跃任务"
            value={`${activeJobs.length} 个`}
          />
        </section>

        {session && (
          <section className="mt-7 rounded-[var(--radius-xl)] border bg-[var(--color-surface-muted)]/45 p-4 md:p-5">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-base font-semibold">当前热加载 Session</h2>
              <span
                className={cn(
                  "rounded-[4px] px-2.5 py-1 text-xs font-semibold",
                  ready
                    ? "bg-[var(--color-success-soft)] text-[var(--color-success)]"
                    : "bg-[var(--color-accent-soft)] text-[var(--color-accent)]",
                )}
              >
                {sessionLabels[session.state] ?? session.state}
              </span>
            </div>
            <ComputeSessionPanel session={session} />
          </section>
        )}

        <GpuInventoryPanel
          activeJobs={activeJobs}
          error={inventory.isError}
          gpus={inventory.data?.gpus ?? []}
          live={liveInventory}
          loading={inventory.isLoading}
          onRefresh={() => void inventory.refetch()}
          onToggleLive={() => setLiveInventory((value) => !value)}
          refreshing={inventory.isFetching}
          updatedAt={inventory.dataUpdatedAt}
        />

        <section className="mt-8">
          <h2 className="font-display mb-4 text-2xl font-semibold">LTX 2.3 模型能力</h2>
          <div className="grid gap-3 md:grid-cols-2">
            {capabilities.data?.profiles.map((profile) => (
              <CapabilityCard hasSession={Boolean(session)} key={profile.id} profile={profile} />
            ))}
          </div>
        </section>
      </div>

      <GpuSelectorPopover onOpenChange={setSelectorOpen} open={selectorOpen} />
      {session && (
        <ReleaseComputeDialog
          activeJobs={activeJobs.length}
          onOpenChange={setReleaseOpen}
          open={releaseOpen}
          session={session}
        />
      )}
    </main>
  );
}
