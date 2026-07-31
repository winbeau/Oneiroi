import {
  AlertTriangle,
  CheckCircle2,
  Clipboard,
  Download,
  LoaderCircle,
  RefreshCw,
  RotateCcw,
  Square,
} from "lucide-react";

import { Button } from "@/components/ui/button";
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
  active: "bg-blue-50 text-blue-700",
  success: "bg-emerald-50 text-emerald-700",
  danger: "bg-red-50 text-red-700",
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

export function JobCard({ job }: { job: StudioJob }) {
  const cancelJob = useStudioStore((state) => state.cancelJob);
  const retryJob = useStudioStore((state) => state.retryJob);
  const reuseJob = useStudioStore((state) => state.reuseJob);
  const meta = stageMeta[job.stage];
  const isRunning = !["succeeded", "failed", "cancelled"].includes(job.stage);

  return (
    <article className="overflow-hidden rounded-xl border border-[var(--color-border)] bg-white shadow-[var(--shadow-card)]">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-[var(--color-border)] px-4 py-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium",
                toneClasses[meta.tone],
              )}
            >
              {isRunning && <LoaderCircle aria-hidden="true" className="size-3 animate-spin" />}
              {job.stage === "succeeded" && <CheckCircle2 aria-hidden="true" className="size-3" />}
              {job.stage === "failed" && <AlertTriangle aria-hidden="true" className="size-3" />}
              {meta.label}
            </span>
            <span className="text-xs text-[var(--color-text-faint)]">
              {job.draft.quality} · {job.draft.ratio} · {job.draft.resolution} · {job.draft.duration} 秒
            </span>
          </div>
          <p className="mt-2 text-sm text-[var(--color-text-muted)]">{meta.description}</p>
        </div>
        <code className="rounded bg-[var(--color-surface-muted)] px-2 py-1 text-[11px] text-[var(--color-text-faint)]">
          {job.id}
        </code>
      </div>

      {isRunning && (
        <div className="px-4 py-3" aria-label={`任务进度 ${job.progress}%`}>
          <div className="h-1.5 overflow-hidden rounded-full bg-[var(--color-surface-muted)]">
            <div
              className="h-full rounded-full bg-[var(--color-accent)] transition-[width] duration-500"
              style={{ width: `${job.progress}%` }}
            />
          </div>
          <div className="mt-2 flex justify-between text-xs text-[var(--color-text-faint)]">
            <span>{job.draft.queue === "hq" ? "HQ 队列" : "Fast 队列"}</span>
            <span className="tabular-nums">{job.progress}%</span>
          </div>
        </div>
      )}

      {job.stage === "succeeded" && job.previewUrl && (
        <div className="relative bg-[var(--color-preview)]">
          <img
            alt="生成结果预览帧"
            className="aspect-video w-full object-cover"
            src={job.previewUrl}
          />
          <div className="absolute inset-x-0 bottom-0 flex items-center justify-between bg-gradient-to-t from-black/65 to-transparent px-4 pb-3 pt-8 text-xs text-white">
            <span>模拟结果预览 · 接入 Runner 后替换为 MP4 播放器</span>
            <span>{job.draft.duration}s</span>
          </div>
        </div>
      )}

      {job.stage === "failed" && (
        <div className="mx-4 my-3 rounded-md border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-800">
          {job.errorMessage ?? "任务执行失败，请查看日志详情后重试。"}
        </div>
      )}

      <div className="px-4 py-3">
        <p className="line-clamp-3 text-sm leading-6 text-[var(--color-text)]">{job.draft.prompt}</p>
        <div className="mt-3 flex flex-wrap gap-2">
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
                onClick={() => void navigator.clipboard.writeText(job.draft.prompt)}
                size="sm"
                variant="ghost"
              >
                <Clipboard aria-hidden="true" className="size-3.5" />
                复制 Prompt
              </Button>
              <Button onClick={() => downloadParameters(job)} size="sm" variant="ghost">
                <Download aria-hidden="true" className="size-3.5" />
                下载参数
              </Button>
            </>
          )}
        </div>
      </div>
    </article>
  );
}
