import {
  AlertTriangle,
  CheckCircle2,
  Clipboard,
  Download,
  RefreshCw,
  RotateCcw,
  Square,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { JobTimeline } from "@/features/create/job-timeline";
import type { JobStage, StudioJob } from "@/features/studio/types";
import { cn } from "@/lib/utils";
import { useStudioStore } from "@/store/studio-store";

const stageMeta: Record<
  JobStage,
  { label: string; description: string; tone: "neutral" | "active" | "success" | "danger" }
> = {
  draft: { label: "草稿", description: "正在整理任务参数", tone: "neutral" },
  uploaded: { label: "已上传", description: "参考素材已进入任务目录", tone: "active" },
  queued: { label: "排队中", description: "等待可用 GPU Runner", tone: "active" },
  assigned: { label: "已分配", description: "任务已绑定固定 GPU", tone: "active" },
  preparing: { label: "准备模型", description: "正在加载模型和编码 Prompt", tone: "active" },
  generating: { label: "生成中", description: "正在执行视频扩散采样", tone: "active" },
  encoding: { label: "编码中", description: "正在封装视频和音频", tone: "active" },
  succeeded: { label: "已完成", description: "结果已加入资产库", tone: "success" },
  failed: { label: "失败", description: "任务可以修正后重试", tone: "danger" },
  cancelled: { label: "已取消", description: "任务未继续占用队列", tone: "neutral" },
};

const toneClasses = {
  neutral: "bg-[var(--color-surface-muted)] text-[var(--color-text-muted)]",
  active: "bg-[var(--color-accent-soft)] text-[var(--color-accent)]",
  success: "bg-[var(--color-success-soft)] text-[var(--color-success)]",
  danger: "bg-[rgb(184_74_74_/_10%)] text-[var(--color-danger)]",
};

const downloadParameters = (job: StudioJob) => {
  const blob = new Blob([JSON.stringify(job.draft, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${job.id}-parameters.json`;
  anchor.click();
  URL.revokeObjectURL(url);
};

function RunningPreview({ job }: { job: StudioJob }) {
  return (
    <div className="relative min-h-[210px] overflow-hidden rounded-[var(--radius-lg)] bg-[var(--color-preview)] sm:min-h-[250px]">
      <div className="absolute inset-0 grid grid-cols-2">
        <div className="relative overflow-hidden">
          {job.draft.firstFrame ? (
            <img
              alt="任务首帧"
              className="size-full object-cover opacity-80 blur-[0.3px]"
              src={job.draft.firstFrame.url}
            />
          ) : (
            <div className="size-full bg-[#312f2d]" />
          )}
          <div className="absolute inset-0 bg-gradient-to-r from-transparent to-[#272523]/55" />
        </div>
        <div className="relative overflow-hidden">
          {job.draft.lastFrame ? (
            <img
              alt="任务尾帧"
              className="size-full object-cover opacity-80 blur-[0.3px]"
              src={job.draft.lastFrame.url}
            />
          ) : (
            <div className="size-full bg-[#312f2d]" />
          )}
          <div className="absolute inset-0 bg-gradient-to-l from-transparent to-[#272523]/55" />
        </div>
      </div>
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(102,92,207,0.12),transparent_42%)]" />
      <div className="absolute left-1/2 top-1/2 h-px w-36 -translate-x-1/2 -translate-y-1/2 bg-white/20">
        <div className="frame-flow absolute inset-0" />
      </div>
      <div className="absolute left-1/2 top-1/2 grid size-12 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full border border-white/20 bg-black/25 text-white backdrop-blur-md">
        <span className="soft-pulse size-2 rounded-full bg-[#c7c0ff]" />
      </div>
      <div className="absolute inset-x-0 bottom-0 flex items-end justify-between bg-gradient-to-t from-black/65 to-transparent px-4 pb-4 pt-16 text-white">
        <div>
          <p className="text-xs font-medium">{stageMeta[job.stage].description}</p>
          <p className="mt-1 text-[10px] uppercase tracking-[0.12em] text-white/55">
            {job.draft.queue} pipeline
          </p>
        </div>
        <span className="font-mono text-xs tabular-nums">{job.progress}%</span>
      </div>
    </div>
  );
}

export function JobCard({ job }: { job: StudioJob }) {
  const cancelJob = useStudioStore((state) => state.cancelJob);
  const retryJob = useStudioStore((state) => state.retryJob);
  const reuseJob = useStudioStore((state) => state.reuseJob);
  const meta = stageMeta[job.stage];
  const isRunning = !["succeeded", "failed", "cancelled"].includes(job.stage);

  return (
    <article className="overflow-hidden rounded-[18px] border border-[var(--color-border)] bg-white/88 shadow-[0_10px_34px_rgba(48,46,42,0.055)] backdrop-blur-sm">
      <div className="flex flex-wrap items-start justify-between gap-3 px-4 pb-3 pt-4 md:px-5">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold",
                toneClasses[meta.tone],
              )}
            >
              {isRunning && <span className="soft-pulse size-1.5 rounded-full bg-current" />}
              {job.stage === "succeeded" && (
                <CheckCircle2 aria-hidden="true" className="size-3" />
              )}
              {job.stage === "failed" && (
                <AlertTriangle aria-hidden="true" className="size-3" />
              )}
              {meta.label}
            </span>
            <span className="text-xs text-[var(--color-text-faint)]">
              {job.draft.quality} · {job.draft.ratio} · {job.draft.resolution} · {job.draft.duration} 秒
            </span>
          </div>
          <p className="mt-2 text-sm text-[var(--color-text-muted)]">{meta.description}</p>
        </div>
        <code className="font-mono rounded-md bg-[var(--color-surface-muted)] px-2 py-1 text-[10px] text-[var(--color-text-faint)]">
          {job.id}
        </code>
      </div>

      <div className="border-y border-[var(--color-border)] px-4 py-3 md:px-5">
        <JobTimeline stage={job.stage} />
      </div>

      <div className="grid gap-4 p-4 md:grid-cols-[minmax(0,1.45fr)_minmax(250px,0.75fr)] md:p-5">
        <div>
          {isRunning && <RunningPreview job={job} />}

          {job.stage === "succeeded" && job.previewUrl && (
            <div className="relative overflow-hidden rounded-[var(--radius-lg)] bg-[var(--color-preview)]">
              <img
                alt="生成结果预览帧"
                className="aspect-video w-full object-cover"
                src={job.previewUrl}
              />
              <div className="absolute inset-x-0 bottom-0 flex items-center justify-between bg-gradient-to-t from-black/65 to-transparent px-4 pb-3 pt-12 text-xs text-white">
                <span>结果预览 · 接入 Runner 后替换为 MP4</span>
                <span>{job.draft.duration}s</span>
              </div>
            </div>
          )}

          {job.stage === "failed" && (
            <div className="rounded-[var(--radius-lg)] border border-[rgb(184_74_74_/_18%)] bg-[rgb(184_74_74_/_7%)] px-4 py-4">
              <div className="flex items-start gap-3">
                <span className="grid size-8 shrink-0 place-items-center rounded-full bg-[rgb(184_74_74_/_10%)] text-[var(--color-danger)]">
                  <AlertTriangle aria-hidden="true" className="size-4" />
                </span>
                <div>
                  <p className="text-sm font-semibold text-[var(--color-danger)]">任务没有完成</p>
                  <p className="mt-1 text-sm leading-6 text-[var(--color-text-muted)]">
                    {job.errorMessage ?? "检查提示词和素材后，可以保留当前设置重新提交。"}
                  </p>
                </div>
              </div>
            </div>
          )}

          {job.stage === "cancelled" && (
            <div className="rounded-[var(--radius-lg)] bg-[var(--color-surface-muted)] px-4 py-6 text-center text-sm text-[var(--color-text-muted)]">
              任务已取消，参数仍然保留。
            </div>
          )}
        </div>

        <div className="flex min-w-0 flex-col rounded-[var(--radius-lg)] bg-[var(--color-canvas)] p-4 ring-1 ring-inset ring-[var(--color-border)]">
          <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[var(--color-text-faint)]">
            Prompt
          </p>
          <p className="mt-2 line-clamp-6 text-sm leading-6 text-[var(--color-text)]">
            {job.draft.prompt}
          </p>
          <dl className="mt-4 grid grid-cols-2 gap-x-3 gap-y-2 border-t border-[var(--color-border)] pt-3 text-xs">
            <div>
              <dt className="text-[var(--color-text-faint)]">Seed</dt>
              <dd className="font-mono mt-0.5 text-[var(--color-text-muted)]">{job.draft.seed}</dd>
            </div>
            <div>
              <dt className="text-[var(--color-text-faint)]">队列</dt>
              <dd className="mt-0.5 uppercase text-[var(--color-text-muted)]">{job.draft.queue}</dd>
            </div>
          </dl>
          <div className="mt-auto flex flex-wrap gap-1.5 pt-5">
            {isRunning && (
              <Button onClick={() => cancelJob(job.id)} size="sm" variant="secondary">
                <Square aria-hidden="true" className="size-3.5" />
                取消
              </Button>
            )}
            {["failed", "cancelled"].includes(job.stage) && (
              <Button onClick={() => retryJob(job.id)} size="sm" variant="primary">
                <RefreshCw aria-hidden="true" className="size-3.5" />
                重试
              </Button>
            )}
            {job.stage === "succeeded" && (
              <>
                <Button onClick={() => reuseJob(job.id)} size="sm" variant="secondary">
                  <RotateCcw aria-hidden="true" className="size-3.5" />
                  复用设置
                </Button>
                <Button
                  aria-label="复制 Prompt"
                  onClick={() => void navigator.clipboard.writeText(job.draft.prompt)}
                  size="icon"
                  variant="ghost"
                >
                  <Clipboard aria-hidden="true" className="size-3.5" />
                </Button>
                <Button
                  aria-label="下载参数"
                  onClick={() => downloadParameters(job)}
                  size="icon"
                  variant="ghost"
                >
                  <Download aria-hidden="true" className="size-3.5" />
                </Button>
              </>
            )}
          </div>
        </div>
      </div>
    </article>
  );
}
