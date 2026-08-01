import {
  AlertTriangle,
  CheckCircle2,
  Download,
  RefreshCw,
  RotateCcw,
  Square,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { JobTimeline } from "@/features/create/job-timeline";
import { useCancelJob, useRetryJob } from "@/features/studio/hooks";
import type { GenerationDraft, JobStage, StudioJob } from "@/features/studio/types";
import { apiUrl } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import { useStudioStore } from "@/store/studio-store";

const stageMeta: Record<
  JobStage,
  { label: string; description: string; tone: "neutral" | "active" | "success" | "danger" }
> = {
  draft: { label: "草稿", description: "正在整理任务参数", tone: "neutral" },
  uploaded: { label: "已上传", description: "参考素材已进入任务目录", tone: "active" },
  queued: { label: "排队中", description: "等待 ready GPU slot", tone: "active" },
  assigned: { label: "已分配", description: "任务已绑定定向 GPU slot", tone: "active" },
  loading_model: { label: "恢复模型", description: "正在恢复匹配的 PipelineSpec", tone: "active" },
  preparing: { label: "准备中", description: "正在处理素材和编码 Prompt", tone: "active" },
  generating: { label: "生成中", description: "正在执行视频扩散采样", tone: "active" },
  encoding: { label: "编码中", description: "正在封装真实 MP4", tone: "active" },
  cancel_requested: { label: "取消中", description: "等待安全停止点", tone: "neutral" },
  succeeded: { label: "已完成", description: "真实结果已加入资产库", tone: "success" },
  failed: { label: "失败", description: "保留历史 attempt，可重新提交", tone: "danger" },
  cancelled: { label: "已取消", description: "后端已确认任务停止", tone: "neutral" },
};

const toneClasses = {
  neutral: "bg-[var(--color-surface-muted)] text-[var(--color-text-muted)]",
  active: "bg-[var(--color-accent-soft)] text-[var(--color-accent)]",
  success: "bg-[var(--color-success-soft)] text-[var(--color-success)]",
  danger: "bg-[rgb(184_74_74_/_10%)] text-[var(--color-danger)]",
};

export function JobCard({ job }: { job: StudioJob }) {
  const cancel = useCancelJob();
  const retry = useRetryJob();
  const updateDraft = useStudioStore((state) => state.updateDraft);
  const meta = stageMeta[job.stage];
  const isRunning = !["succeeded", "failed", "cancelled"].includes(job.stage);
  const quality = job.draft.profile === "hq" ? "高质量" : "快速";

  const reuse = () => {
    updateDraft({
      ...(job.draft as Partial<GenerationDraft>),
      quality,
      firstFrame: null,
      lastFrame: null,
    });
  };

  return (
    <article className="overflow-hidden rounded-[18px] border border-[var(--color-border)] bg-white/88 shadow-[var(--shadow-card)]">
      <div className="flex flex-wrap items-start justify-between gap-3 px-4 pb-3 pt-4 md:px-5">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className={cn("rounded-full px-2.5 py-1 text-xs font-semibold", toneClasses[meta.tone])}>
              {job.stage === "succeeded" && <CheckCircle2 className="mr-1 inline size-3" />}
              {job.stage === "failed" && <AlertTriangle className="mr-1 inline size-3" />}
              {meta.label}
            </span>
            <span className="text-xs text-[var(--color-text-faint)]">
              {quality} · {job.draft.ratio} · {job.draft.resolution} · {job.draft.duration} 秒
            </span>
          </div>
          <p className="mt-2 text-sm text-[var(--color-text-muted)]">{meta.description}</p>
        </div>
        <code className="rounded-md bg-[var(--color-surface-muted)] px-2 py-1 text-[10px]">
          {job.id}
        </code>
      </div>

      <div className="border-y border-[var(--color-border)] px-4 py-3 md:px-5">
        <JobTimeline
          currentStep={job.currentStep}
          phase={job.phase}
          stage={job.stage}
          totalSteps={job.totalSteps}
        />
      </div>

      <div className="grid gap-4 p-4 md:grid-cols-[minmax(0,1.4fr)_minmax(250px,0.8fr)] md:p-5">
        <div>
          {job.stage === "succeeded" && job.output ? (
            <video
              className="aspect-video w-full rounded-[var(--radius-lg)] bg-black"
              controls
              preload="metadata"
              src={apiUrl(job.output.fileUrl)}
            />
          ) : (
            <div className="relative grid min-h-[220px] place-items-center rounded-[var(--radius-lg)] bg-[var(--color-preview)] text-white">
              <div className="text-center">
                <p className="text-sm font-medium">{meta.description}</p>
                <p className="mt-2 font-mono text-xs">{job.progress}%</p>
              </div>
            </div>
          )}
          {job.error && (
            <div className="mt-3 rounded-lg border border-[rgb(184_74_74_/_18%)] bg-[rgb(184_74_74_/_7%)] p-4">
              <p className="text-sm font-semibold text-[var(--color-danger)]">{job.error.code}</p>
              <p className="mt-1 text-sm text-[var(--color-text-muted)]">{job.error.message}</p>
            </div>
          )}
        </div>

        <div className="flex flex-col rounded-[var(--radius-lg)] bg-[var(--color-canvas)] p-4 ring-1 ring-inset ring-[var(--color-border)]">
          <p className="text-[10px] font-semibold uppercase text-[var(--color-text-faint)]">Prompt</p>
          <p className="mt-2 line-clamp-6 text-sm leading-6">{job.draft.prompt}</p>
          <dl className="mt-4 grid grid-cols-2 gap-3 border-t border-[var(--color-border)] pt-3 text-xs">
            <div>
              <dt className="text-[var(--color-text-faint)]">GPU</dt>
              <dd className="mt-1">{job.gpu ? `GPU ${job.gpu.physicalIndex}` : "等待分配"}</dd>
            </div>
            <div>
              <dt className="text-[var(--color-text-faint)]">Attempt</dt>
              <dd className="mt-1">{job.attempt}</dd>
            </div>
            <div>
              <dt className="text-[var(--color-text-faint)]">Profile</dt>
              <dd className="mt-1 truncate">{job.profileId ?? job.draft.profile}</dd>
            </div>
            <div>
              <dt className="text-[var(--color-text-faint)]">启动</dt>
              <dd className="mt-1">{job.warmStart == null ? "—" : job.warmStart ? "Warm" : "Cold"}</dd>
            </div>
          </dl>
          <div className="mt-auto flex flex-wrap gap-1.5 pt-5">
            {isRunning && job.stage !== "cancel_requested" && (
              <Button onClick={() => cancel.mutate(job.id)} size="sm" variant="secondary">
                <Square className="size-3.5" /> 取消
              </Button>
            )}
            {["failed", "cancelled"].includes(job.stage) && (
              <Button onClick={() => retry.mutate(job.id)} size="sm" variant="primary">
                <RefreshCw className="size-3.5" /> 重试
              </Button>
            )}
            {job.stage === "succeeded" && job.output && (
              <>
                <Button onClick={reuse} size="sm" variant="secondary">
                  <RotateCcw className="size-3.5" /> 复用设置
                </Button>
                <Button asChild size="icon" variant="ghost">
                  <a aria-label="下载视频" href={apiUrl(job.output.fileUrl)}>
                    <Download className="size-3.5" />
                  </a>
                </Button>
              </>
            )}
          </div>
        </div>
      </div>
    </article>
  );
}
