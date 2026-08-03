import {
  AlertTriangle,
  CheckCircle2,
  Download,
  MoreHorizontal,
  Play,
  RefreshCw,
  RotateCcw,
  Square,
  Video,
} from "lucide-react";
import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  useAssets,
  useCancelJob,
  useRetryJob,
} from "@/features/studio/hooks";
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
  queued: { label: "排队中", description: "等待可用的 LTX 2.3 Slot", tone: "active" },
  assigned: { label: "已分配", description: "任务已绑定 H100", tone: "active" },
  loading_model: { label: "加载模型", description: "正在恢复匹配的模型", tone: "active" },
  preparing: { label: "准备中", description: "正在处理素材和编码 Prompt", tone: "active" },
  generating: { label: "正在生成视频", description: "LTX 2.3 正在执行扩散采样", tone: "active" },
  encoding: { label: "正在编码", description: "正在封装视频文件", tone: "active" },
  cancel_requested: { label: "取消中", description: "等待安全停止点", tone: "neutral" },
  succeeded: { label: "已完成", description: "视频已加入资产库", tone: "success" },
  failed: { label: "生成失败", description: "本次任务未能完成", tone: "danger" },
  cancelled: { label: "已取消", description: "任务已停止", tone: "neutral" },
};

const toneClasses = {
  neutral: "bg-[var(--color-surface-muted)] text-[var(--color-text-muted)]",
  active: "bg-[var(--color-accent-soft)] text-[var(--color-accent)]",
  success: "bg-[var(--color-success-soft)] text-[var(--color-success)]",
  danger: "bg-[rgb(184_74_74_/_10%)] text-[var(--color-danger)]",
};

const ratioClasses: Record<GenerationDraft["ratio"], string> = {
  "21:9": "mx-auto aspect-[21/9] max-w-[960px]",
  "16:9": "aspect-video",
  "4:3": "mx-auto aspect-[4/3] max-w-[820px]",
  "1:1": "mx-auto aspect-square max-w-[720px]",
  "3:4": "mx-auto aspect-[3/4] max-h-[680px] max-w-[540px]",
  "9:16": "mx-auto aspect-[9/16] max-h-[680px] max-w-[440px]",
};

function timeLabel(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export function JobCard({ job }: { job: StudioJob }) {
  const cancel = useCancelJob();
  const retry = useRetryJob();
  const assets = useAssets().data ?? [];
  const updateDraft = useStudioStore((state) => state.updateDraft);
  const meta = stageMeta[job.stage];
  const isRunning = !["succeeded", "failed", "cancelled"].includes(job.stage);
  const quality = job.draft.profile === "hq" ? "高质量" : "快速";
  const firstAsset = assets.find((asset) => asset.id === job.draft.firstFrameAssetId);
  const lastAsset = assets.find((asset) => asset.id === job.draft.lastFrameAssetId);
  const posterUrl = firstAsset?.previewUrl ? apiUrl(firstAsset.previewUrl) : undefined;
  const displayProgress = isRunning ? Math.max(job.progress, 4) : job.progress;
  const title =
    job.draft.prompt.split(/[.!。]/, 1)[0]?.trim().slice(0, 48) || "视频生成任务";

  const reuse = () => {
    updateDraft({
      ...(job.draft as Partial<GenerationDraft>),
      quality,
      firstFrame: firstAsset
        ? { name: firstAsset.title, url: apiUrl(firstAsset.previewUrl), assetId: firstAsset.id }
        : null,
      lastFrame: lastAsset
        ? { name: lastAsset.title, url: apiUrl(lastAsset.previewUrl), assetId: lastAsset.id }
        : null,
    });
  };

  return (
    <article className="group w-full max-w-[620px] border-b border-[var(--color-border)] pb-6 last:border-b-0">
      <div className="mb-3 flex items-start gap-3">
        <span className="grid size-10 shrink-0 place-items-center overflow-hidden rounded-md border bg-[var(--color-surface-muted)] text-[var(--color-text-muted)]">
          {posterUrl ? (
            <img alt="" className="size-full object-cover" src={posterUrl} />
          ) : (
            <Video className="size-4" />
          )}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <h3 className="truncate text-sm font-semibold">{title}</h3>
            <span className={cn("rounded-full px-2 py-0.5 text-[9px] font-semibold", toneClasses[meta.tone])}>
              {job.stage === "succeeded" && <CheckCircle2 className="mr-1 inline size-2.5" />}
              {job.stage === "failed" && <AlertTriangle className="mr-1 inline size-2.5" />}
              {meta.label}
            </span>
          </div>
          <p className="mt-1 text-[11px] text-[var(--color-text-muted)]">
            {quality} · LTX 2.3 · {job.draft.duration} 秒 · {job.draft.ratio} · {job.draft.resolution.toUpperCase()}
          </p>
        </div>
        <span className="shrink-0 text-[10px] text-[var(--color-text-faint)]">
          {timeLabel(job.createdAt)}
        </span>
      </div>

      {isRunning && (
        <div className="mb-2.5 grid grid-cols-[auto_minmax(120px,1fr)_auto] items-center gap-3 text-[11px]">
          <span className="truncate font-medium text-[var(--color-accent)]">{meta.description}</span>
          <div className="h-1.5 overflow-hidden rounded-full bg-[var(--color-surface-hover)]">
            <div
              className="progress-shimmer h-full rounded-full bg-[var(--color-accent)] transition-[width] duration-500"
              style={{ width: `${displayProgress}%` }}
            />
          </div>
          <span className="font-mono tabular-nums text-[var(--color-text-muted)]">
            {displayProgress}%
          </span>
        </div>
      )}

      <div
        className={cn(
          "relative overflow-hidden rounded-[var(--radius-md)] border border-[var(--color-border-strong)] bg-[var(--color-preview)] shadow-[var(--shadow-card)]",
          ratioClasses[job.draft.ratio],
        )}
      >
        {job.stage === "succeeded" && job.output ? (
          <VideoPlayer
            duration={job.draft.duration}
            poster={posterUrl}
            src={apiUrl(job.output.fileUrl)}
          />
        ) : isRunning ? (
          <div className="generation-waiting relative size-full min-h-60 overflow-hidden">
            {posterUrl && (
              <img
                alt="生成中的视频首帧"
                className="generation-waiting-image absolute inset-[-8%] size-[116%] object-cover opacity-55"
                src={posterUrl}
              />
            )}
            <div className="generation-waiting-aurora absolute inset-[-20%]" />
            <div className="generation-waiting-sweep absolute inset-0" />
            <div className="absolute left-3 top-3 z-10 flex items-center gap-2 rounded-[5px] bg-black/28 px-2.5 py-1.5 text-[10px] font-medium text-white backdrop-blur-md">
              <SparkleDot /> {meta.label}
            </div>
            <div className="absolute inset-x-0 bottom-0 z-10 flex items-end justify-between gap-4 bg-gradient-to-t from-black/42 via-black/8 to-transparent px-4 pb-3.5 pt-14 text-white">
              <p className="text-[11px] text-white/78">{meta.description}</p>
              <span className="font-mono text-xs tabular-nums">{displayProgress}%</span>
            </div>
          </div>
        ) : posterUrl ? (
          <>
            <img
              alt="视频任务参考首帧"
              className="size-full object-cover opacity-82"
              src={posterUrl}
            />
            <div className="absolute inset-0 bg-gradient-to-t from-black/55 via-black/5 to-black/10" />
            <div className="absolute inset-x-0 bottom-0 flex items-end justify-between gap-4 p-4 text-white md:p-5">
              <div>
                <p className="flex items-center gap-2 text-sm font-medium">
                  <SparkleDot /> {meta.label}
                </p>
                <p className="mt-1 text-[11px] text-white/65">{meta.description}</p>
              </div>
              <span className="font-mono text-xs tabular-nums">{displayProgress}%</span>
            </div>
          </>
        ) : (
          <div className="grid size-full min-h-64 place-items-center text-white">
            <div className="text-center">
              <span className="mx-auto grid size-11 place-items-center rounded-full bg-white/10">
                {job.stage === "failed" ? <AlertTriangle className="size-5" /> : <Play className="size-5" />}
              </span>
              <p className="mt-3 text-sm font-medium">{meta.description}</p>
              <p className="mt-1 font-mono text-xs text-white/60">{displayProgress}%</p>
            </div>
          </div>
        )}
      </div>

      {job.error && (
        <div className="mt-3 flex items-start gap-2 rounded-lg border border-[rgb(184_74_74_/_18%)] bg-[rgb(184_74_74_/_7%)] px-3 py-2.5">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-[var(--color-danger)]" />
          <div>
            <p className="text-xs font-semibold text-[var(--color-danger)]">{job.error.code}</p>
            <p className="mt-0.5 text-[11px] text-[var(--color-text-muted)]">{job.error.message}</p>
          </div>
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <span className="text-[11px] text-[var(--color-text-muted)]">
          {job.gpu ? `GPU ${job.gpu.physicalIndex}` : "等待 GPU"}
          {job.warmStart != null ? ` · ${job.warmStart ? "Warm" : "Cold"}` : ""}
        </span>
        <div className="ml-auto flex flex-wrap items-center gap-1.5">
          {isRunning && job.stage !== "cancel_requested" && (
            <Button onClick={() => cancel.mutate(job.id)} size="sm" variant="ghost">
              <Square className="size-3" /> 取消
            </Button>
          )}
          {["failed", "cancelled"].includes(job.stage) && (
            <Button onClick={() => retry.mutate(job.id)} size="sm" variant="secondary">
              <RefreshCw className="size-3.5" /> 重试
            </Button>
          )}
          {job.stage === "succeeded" && job.output && (
            <>
              <Button onClick={reuse} size="sm" variant="ghost">
                <RotateCcw className="size-3.5" /> 继续创作
              </Button>
              <Button asChild size="sm" variant="ghost">
                <a download href={apiUrl(job.output.fileUrl)}>
                  <Download className="size-3.5" /> 下载
                </a>
              </Button>
            </>
          )}
        </div>
      </div>

      <details className="mt-2 text-[11px] text-[var(--color-text-muted)]">
        <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 rounded-md py-1 hover:text-[var(--color-text)]">
          <MoreHorizontal className="size-3.5" /> 查看 Prompt 与任务详情
        </summary>
        <div className="mt-2 rounded-md bg-[var(--color-surface-muted)]/65 p-3 leading-5">
          <p>{job.draft.prompt}</p>
          <p className="mt-2 border-t pt-2 font-mono text-[9px] text-[var(--color-text-faint)]">
            {job.id} · {job.profileId ?? job.draft.profile} · Attempt {job.attempt}
          </p>
        </div>
      </details>
    </article>
  );
}

function SparkleDot() {
  return (
    <span className="relative flex size-3">
      <span className="absolute inline-flex size-full animate-ping rounded-full bg-cyan-300/50" />
      <span className="relative inline-flex size-3 rounded-full bg-cyan-300" />
    </span>
  );
}

function VideoPlayer({
  src,
  poster,
  duration,
}: {
  src: string;
  poster?: string;
  duration: number;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);

  const play = async () => {
    setPlaying(true);
    try {
      await videoRef.current?.play();
    } catch {
      setPlaying(false);
    }
  };

  return (
    <div className="relative size-full">
      <video
        ref={videoRef}
        className="size-full object-cover"
        controls={playing}
        onEnded={() => setPlaying(false)}
        playsInline
        poster={poster}
        preload="metadata"
        src={src}
      />
      {!playing && (
        <button
          aria-label="播放生成视频"
          className="absolute inset-0 flex items-end bg-black text-left text-white"
          onClick={play}
          type="button"
        >
          {poster && <img alt="" className="absolute inset-0 size-full object-cover" src={poster} />}
          <span className="absolute inset-0 bg-gradient-to-t from-black/55 via-transparent to-black/5" />
          <span className="relative flex w-full items-center gap-3 p-4 md:p-5">
            <span className="grid size-9 place-items-center rounded-full bg-white text-[var(--color-text)] shadow-lg">
              <Play className="ml-0.5 size-4 fill-current" />
            </span>
            <span className="font-mono text-xs tabular-nums">
              00:00 / 00:{String(duration).padStart(2, "0")}
            </span>
          </span>
        </button>
      )}
    </div>
  );
}
