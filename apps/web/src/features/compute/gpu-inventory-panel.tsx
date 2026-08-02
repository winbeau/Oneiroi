import {
  Activity,
  Pause,
  Play,
  RefreshCw,
  Thermometer,
  Workflow,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import type { GpuInfo, StudioJob } from "@/features/studio/types";
import { cn } from "@/lib/utils";

const gpuStateLabels: Record<string, string> = {
  offline: "离线",
  empty: "空闲",
  reserved: "已预留",
  loading: "加载中",
  ready: "已就绪",
  busy: "任务运行中",
  draining: "等待释放",
  unloading: "释放中",
  error: "异常",
  foreign_busy: "外部进程占用",
};

const activeToneStates = new Set(["reserved", "loading", "ready", "busy", "draining"]);

function stateTone(gpu: GpuInfo) {
  if (gpu.state === "error" || gpu.state === "offline") return "danger";
  if (gpu.state === "foreign_busy") return "warning";
  if (gpu.eligible || activeToneStates.has(gpu.state)) return "success";
  return "neutral";
}

const toneClasses = {
  danger: "bg-[rgb(184_74_74_/_10%)] text-[var(--color-danger)]",
  warning: "bg-[rgb(214_154_87_/_12%)] text-[var(--color-warning)]",
  success: "bg-[var(--color-success-soft)] text-[var(--color-success)]",
  neutral: "bg-[var(--color-surface-muted)] text-[var(--color-text-muted)]",
};

function formatGiB(mib: number) {
  return `${(mib / 1024).toFixed(1)} GiB`;
}

function ResourceBar({ value }: { value: number }) {
  const bounded = Math.min(100, Math.max(0, value));
  return (
    <div className="h-1.5 min-w-10 flex-1 overflow-hidden rounded-full bg-[var(--color-surface-muted)]">
      <div
        className={cn(
          "h-full rounded-full transition-[width] duration-300",
          bounded >= 90
            ? "bg-[var(--color-danger)]"
            : bounded >= 65
              ? "bg-[var(--color-warning)]"
              : "bg-[var(--color-accent)]",
        )}
        style={{ width: `${bounded}%` }}
      />
    </div>
  );
}

function StateBadge({ gpu }: { gpu: GpuInfo }) {
  const tone = stateTone(gpu);
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-[4px] px-2 py-1 text-[10px] font-semibold",
        toneClasses[tone],
      )}
    >
      <span
        className={cn(
          "size-1.5 rounded-full",
          tone === "danger"
            ? "bg-[var(--color-danger)]"
            : tone === "warning"
              ? "bg-[var(--color-warning)]"
              : tone === "success"
                ? "bg-[var(--color-success)]"
                : "bg-[var(--color-text-faint)]",
        )}
      />
      {gpuStateLabels[gpu.state] ?? gpu.state}
    </span>
  );
}

function GpuIdentity({ gpu }: { gpu: GpuInfo }) {
  return (
    <div className="min-w-0">
      <div className="flex min-w-0 items-center gap-2">
        <span className="shrink-0 font-mono text-[15px] font-semibold tabular-nums">
          GPU {gpu.physicalIndex}
        </span>
        <span className="min-w-0 truncate text-sm font-semibold text-[var(--color-text)] md:text-[15px]">
          {gpu.name}
        </span>
        {gpu.eligible && (
          <span className="shrink-0 rounded-[3px] bg-[var(--color-accent-soft)] px-1.5 py-0.5 text-[9px] font-semibold text-[var(--color-accent)]">
            ELIGIBLE
          </span>
        )}
      </div>
    </div>
  );
}

function MetricCell({
  label,
  value,
  percent,
}: {
  label: string;
  value: string;
  percent: number;
}) {
  return (
    <div className="flex min-w-0 items-center gap-2 text-xs md:text-[15px]">
      <span className="min-w-7 shrink-0 font-semibold text-[var(--color-text)]">{label}</span>
      <ResourceBar value={percent} />
      <span className="shrink-0 font-mono font-semibold tabular-nums text-[var(--color-text)]">
        {value}
      </span>
    </div>
  );
}

function GpuMobileCard({ gpu, jobs }: { gpu: GpuInfo; jobs: StudioJob[] }) {
  const memoryPercent = gpu.vramTotalMiB
    ? Math.round((gpu.vramUsedMiB / gpu.vramTotalMiB) * 100)
    : 0;
  return (
    <article className="border-t px-3 py-2.5 first:border-t-0">
      <div className="flex items-start justify-between gap-3">
        <GpuIdentity gpu={gpu} />
        <StateBadge gpu={gpu} />
      </div>
      <div className="mt-2.5 grid gap-2.5">
        <MetricCell
          label="显存"
          percent={memoryPercent}
          value={`${formatGiB(gpu.vramUsedMiB)} / ${formatGiB(gpu.vramTotalMiB)}`}
        />
        <MetricCell
          label="GPU 利用率"
          percent={gpu.utilizationPercent}
          value={`${Math.round(gpu.utilizationPercent)}%`}
        />
      </div>
      <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1 border-t pt-2 text-[10px] text-[var(--color-text-muted)]">
        <span className="flex items-center gap-1">
          <Thermometer className="size-3" /> {Math.round(gpu.temperatureCelsius)}°C
        </span>
        <span>{jobs.length} 个 Oneiroi 任务</span>
        <span>{gpu.externalProcessCount} 个外部进程</span>
      </div>
      {!gpu.eligible && gpu.unavailableReason && (
        <p className="mt-2 text-[9px] text-[var(--color-warning)]">{gpu.unavailableReason}</p>
      )}
    </article>
  );
}

export function GpuInventoryPanel({
  gpus,
  activeJobs,
  updatedAt,
  live,
  loading,
  error,
  refreshing,
  onToggleLive,
  onRefresh,
}: {
  gpus: GpuInfo[];
  activeJobs: StudioJob[];
  updatedAt: number;
  live: boolean;
  loading: boolean;
  error: boolean;
  refreshing: boolean;
  onToggleLive: () => void;
  onRefresh: () => void;
}) {
  const totalMemory = gpus.reduce((sum, gpu) => sum + gpu.vramTotalMiB, 0);
  const usedMemory = gpus.reduce((sum, gpu) => sum + gpu.vramUsedMiB, 0);
  const averageUtilization = gpus.length
    ? Math.round(gpus.reduce((sum, gpu) => sum + gpu.utilizationPercent, 0) / gpus.length)
    : 0;
  const maximumTemperature = gpus.length
    ? Math.max(...gpus.map((gpu) => gpu.temperatureCelsius))
    : 0;
  const eligibleCount = gpus.filter((gpu) => gpu.eligible).length;
  const assignedJobs = activeJobs.filter((job) => job.gpu);
  const externalProcessCount = gpus.reduce((sum, gpu) => sum + gpu.externalProcessCount, 0);
  const updatedLabel = updatedAt
    ? new Intl.DateTimeFormat("zh-CN", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      }).format(new Date(updatedAt))
    : "—";

  return (
    <section className="mt-9">
      <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="font-display text-2xl font-semibold">GPU Inventory</h2>
          <span className="rounded-[4px] bg-[var(--color-surface-muted)] px-2 py-1 font-mono text-[8px] text-[var(--color-text-muted)]">
            NVITOP VIEW
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="mr-1 hidden font-mono text-[9px] text-[var(--color-text-faint)] sm:inline">
            UPDATED {updatedLabel}
          </span>
          <Button onClick={onToggleLive} size="sm" variant={live ? "secondary" : "ghost"}>
            {live ? <Pause className="size-3" /> : <Play className="size-3" />}
            {live ? "实时 3s" : "已暂停"}
          </Button>
          <Button aria-label="刷新 GPU inventory" onClick={onRefresh} size="icon" variant="ghost">
            <RefreshCw className={cn("size-3.5", refreshing && "animate-spin")} />
          </Button>
        </div>
      </div>

      <div className="overflow-hidden rounded-[8px] border bg-white/78 shadow-[var(--shadow-card)]">
        <div className="grid grid-cols-2 border-b bg-[var(--color-surface-muted)]/55 sm:grid-cols-4">
          {[
            ["GPU", `${gpus.length} 张 · ${eligibleCount} 可调度`],
            ["显存", `${formatGiB(usedMemory)} / ${formatGiB(totalMemory)}`],
            ["平均利用率", `${averageUtilization}%`],
            ["最高温度", `${Math.round(maximumTemperature)}°C`],
          ].map(([label, value]) => (
            <div className="border-b px-3 py-3 last:border-b-0 sm:border-b-0 sm:border-r sm:last:border-r-0" key={label}>
              <p className="font-mono text-sm font-semibold tabular-nums">{value}</p>
            </div>
          ))}
        </div>

        {loading && (
          <div className="grid min-h-40 place-items-center text-sm text-[var(--color-text-muted)]">
            正在读取 GPU inventory…
          </div>
        )}
        {error && (
          <div className="grid min-h-40 place-items-center px-4 text-sm text-[var(--color-danger)]">
            无法读取 GPU inventory。
          </div>
        )}

        {!loading && !error && (
          <>
            <div className="hidden overflow-x-auto md:block">
              <div className="min-w-[980px]">
                {gpus.map((gpu) => {
                  const gpuJobs = assignedJobs.filter(
                    (job) => job.gpu?.physicalIndex === gpu.physicalIndex,
                  );
                  const memoryPercent = gpu.vramTotalMiB
                    ? Math.round((gpu.vramUsedMiB / gpu.vramTotalMiB) * 100)
                    : 0;
                  return (
                    <article
                      className="grid grid-cols-[minmax(250px,1.45fr)_105px_minmax(230px,1.3fr)_minmax(185px,1fr)_70px_125px] items-center gap-4 border-b px-4 py-2.5 last:border-b-0 hover:bg-[var(--color-surface-muted)]/32"
                      key={gpu.id}
                    >
                      <GpuIdentity gpu={gpu} />
                      <div className="min-w-0">
                        <StateBadge gpu={gpu} />
                        {!gpu.eligible && gpu.unavailableReason && (
                          <p className="mt-1 truncate text-[9px] text-[var(--color-warning)]" title={gpu.unavailableReason}>
                            {gpu.unavailableReason}
                          </p>
                        )}
                      </div>
                      <MetricCell
                        label={`${memoryPercent}%`}
                        percent={memoryPercent}
                        value={`${formatGiB(gpu.vramUsedMiB)} / ${formatGiB(gpu.vramTotalMiB)}`}
                      />
                      <MetricCell
                        label="UTIL"
                        percent={gpu.utilizationPercent}
                        value={`${Math.round(gpu.utilizationPercent)}%`}
                      />
                      <span
                        className={cn(
                          "font-mono text-[15px] font-semibold tabular-nums",
                          gpu.temperatureCelsius >= 75
                            ? "text-[var(--color-danger)]"
                            : gpu.temperatureCelsius >= 60
                              ? "text-[var(--color-warning)]"
                              : "text-[var(--color-success)]",
                        )}
                      >
                        {Math.round(gpu.temperatureCelsius)}°C
                      </span>
                      <div className="text-xs font-medium text-[var(--color-text-muted)]">
                        <p>{gpuJobs.length} Oneiroi jobs</p>
                        <p className="mt-1">{gpu.externalProcessCount} external</p>
                      </div>
                    </article>
                  );
                })}
              </div>
            </div>

            <div className="md:hidden">
              {gpus.map((gpu) => (
                <GpuMobileCard
                  gpu={gpu}
                  jobs={assignedJobs.filter(
                    (job) => job.gpu?.physicalIndex === gpu.physicalIndex,
                  )}
                  key={gpu.id}
                />
              ))}
            </div>
          </>
        )}
      </div>

      <div className="mt-3 overflow-hidden rounded-[8px] border bg-white/65">
        <div className="flex items-center justify-between border-b bg-[var(--color-surface-muted)]/45 px-3 py-2.5">
          <p className="flex items-center gap-2 text-xs font-semibold">
            <Workflow className="size-3.5 text-[var(--color-accent)]" /> GPU Workloads
          </p>
          <p className="font-mono text-[10px] text-[var(--color-text-faint)]">
            {assignedJobs.length} JOBS · {externalProcessCount} EXTERNAL
          </p>
        </div>
        {assignedJobs.length === 0 && externalProcessCount === 0 ? (
          <div className="flex items-center justify-center gap-2 px-4 py-8 text-xs text-[var(--color-text-muted)]">
            <Activity className="size-3.5" /> 当前没有运行中的 GPU workload
          </div>
        ) : (
          <div className="divide-y">
            {assignedJobs.map((job) => (
              <div className="grid gap-2 px-3 py-2.5 text-[11px] sm:grid-cols-[90px_110px_minmax(0,1fr)_100px] sm:items-center" key={job.id}>
                <span className="font-mono font-semibold">GPU {job.gpu?.physicalIndex}</span>
                <span className="text-[var(--color-accent)]">ONEIROI JOB</span>
                <span className="truncate text-[var(--color-text-muted)]">{job.draft.prompt || job.id}</span>
                <span className="font-mono text-[var(--color-text-faint)]">{job.stage.toUpperCase()}</span>
              </div>
            ))}
            {gpus
              .filter((gpu) => gpu.externalProcessCount > 0)
              .map((gpu) => (
                <div className="grid gap-2 px-3 py-2.5 text-[11px] sm:grid-cols-[90px_110px_minmax(0,1fr)_100px] sm:items-center" key={`${gpu.id}-external`}>
                  <span className="font-mono font-semibold">GPU {gpu.physicalIndex}</span>
                  <span className="text-[var(--color-warning)]">EXTERNAL CUDA</span>
                  <span className="text-[var(--color-text-muted)]">
                    Gateway 检测到 {gpu.externalProcessCount} 个外部计算进程
                  </span>
                  <span className="font-mono text-[var(--color-text-faint)]">PROTECTED</span>
                </div>
              ))}
          </div>
        )}
      </div>
    </section>
  );
}
