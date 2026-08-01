import {
  Bot,
  Check,
  ChevronDown,
  ImageIcon,
  ImagePlus,
  SlidersHorizontal,
  Sparkles,
  Video,
  WandSparkles,
  X,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useComputeCapabilities, useComputeSession } from "@/features/compute/hooks";
import {
  useCreateConversation,
  useCreateJob,
  useUploadImage,
} from "@/features/studio/hooks";
import type {
  GenerationDraft,
  MediaReference,
  OffloadMode,
} from "@/features/studio/types";
import { cn } from "@/lib/utils";
import { useStudioStore } from "@/store/studio-store";

function ReferenceSlot({
  label,
  reference,
  onChange,
  onClear,
}: {
  label: string;
  reference: MediaReference | null;
  onChange: (file: File) => Promise<void>;
  onClear: () => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  return (
    <div className="group relative flex h-11 min-w-0 items-center gap-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-muted)]/65 p-1 pr-2 sm:w-[142px]">
      <button
        aria-label={reference ? `更换${label}` : `上传${label}`}
        className="relative grid size-9 shrink-0 place-items-center overflow-hidden rounded-md bg-white text-[var(--color-text-faint)] ring-1 ring-[var(--color-border)]"
        onClick={() => inputRef.current?.click()}
        type="button"
      >
        {reference ? (
          <img alt="" className="size-full object-cover" src={reference.url} />
        ) : (
          <ImagePlus className="size-3.5" />
        )}
        <input
          ref={inputRef}
          accept="image/png,image/jpeg,image/webp"
          className="sr-only"
          onChange={async (event) => {
            const file = event.target.files?.[0];
            if (file) await onChange(file);
            event.target.value = "";
          }}
          type="file"
        />
      </button>
      <div className="min-w-0 flex-1">
        <p className="text-[10px] font-semibold uppercase text-[var(--color-text-faint)]">{label}</p>
        <p className="truncate text-[11px] text-[var(--color-text-muted)]">
          {reference?.name ?? "点击上传"}
        </p>
      </div>
      {reference && (
        <button aria-label={`移除${label}`} onClick={onClear} type="button">
          <X className="size-3" />
        </button>
      )}
    </div>
  );
}

function SelectChip({
  ariaLabel,
  children,
  onChange,
  value,
}: {
  ariaLabel: string;
  children: React.ReactNode;
  onChange: (value: string) => void;
  value: string | number;
}) {
  return (
    <label className="relative inline-flex h-8 items-center rounded-md bg-[var(--color-surface-muted)] px-2.5 text-xs">
      <span className="sr-only">{ariaLabel}</span>
      <select
        aria-label={ariaLabel}
        className="appearance-none bg-transparent pr-4 outline-none"
        onChange={(event) => onChange(event.target.value)}
        value={value}
      >
        {children}
      </select>
      <ChevronDown className="pointer-events-none absolute right-2 size-3" />
    </label>
  );
}

type ComposerProps = { agentOpen?: boolean; onAgentToggle?: () => void };

export function Composer({ agentOpen = false, onAgentToggle }: ComposerProps) {
  const draft = useStudioStore((state) => state.draft);
  const updateDraft = useStudioStore((state) => state.updateDraft);
  const activeConversationId = useStudioStore((state) => state.activeConversationId);
  const setActiveConversation = useStudioStore((state) => state.setActiveConversation);
  const compute = useComputeSession();
  const capabilities = useComputeCapabilities(compute.data?.id ?? "");
  const createConversation = useCreateConversation();
  const createJob = useCreateJob();
  const upload = useUploadImage();
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState("");
  const [focused, setFocused] = useState(false);
  const promptRef = useRef<HTMLTextAreaElement>(null);
  const quickImageInputRef = useRef<HTMLInputElement>(null);

  const profile = useMemo(
    () => capabilities.data?.profiles.find((item) => item.tier === draft.profile),
    [capabilities.data, draft.profile],
  );
  const hq = capabilities.data?.profiles.find((item) => item.tier === "hq");
  const sessionReady = Boolean(
    compute.data && ["ready", "degraded"].includes(compute.data.state),
  );
  const canSubmit =
    Boolean(draft.prompt.trim()) &&
    sessionReady &&
    profile?.available === true &&
    !createJob.isPending &&
    !createConversation.isPending;

  const uploadReference = async (file: File, field: "firstFrame" | "lastFrame") => {
    setError("");
    try {
      const asset = await upload.mutateAsync({ file, title: file.name });
      updateDraft({
        [field]: { name: file.name, url: asset.previewUrl, assetId: asset.id },
      });
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "上传失败");
    }
  };

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSubmit || !compute.data) return;
    setError("");
    try {
      let conversationId = activeConversationId;
      if (!conversationId) {
        const conversation = await createConversation.mutateAsync(
          draft.prompt.slice(0, 18) || "未命名创作",
        );
        conversationId = conversation.id;
        setActiveConversation(conversation.id);
      }
      await createJob.mutateAsync({
        conversationId,
        computeSessionId: compute.data.id,
        draft,
      });
      setSubmitted(true);
      window.setTimeout(() => setSubmitted(false), 2_000);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "任务提交失败");
    }
  };

  const setQuality = (quality: GenerationDraft["quality"]) => {
    if (quality === "高质量" && !hq?.available) return;
    updateDraft(
      quality === "高质量"
        ? { quality, queue: "hq", profile: "hq", resolution: "1080p" }
        : { quality, queue: "fast", profile: "fast", resolution: "720p" },
    );
  };

  return (
    <div className="w-full">
      <motion.form
        animate={{ y: focused ? -2 : 0 }}
        aria-label="视频生成创作器"
        className={cn(
          "rounded-[18px] border bg-white/92 p-2.5 backdrop-blur-xl",
          focused
            ? "border-[var(--color-accent)]/35 shadow-[0_24px_70px_rgba(73,66,135,0.15)]"
            : "border-[var(--color-border-strong)] shadow-[var(--shadow-float)]",
        )}
        onBlur={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget)) setFocused(false);
        }}
        onFocus={() => setFocused(true)}
        onSubmit={submit}
      >
        <div className="flex flex-col gap-2.5 md:flex-row">
          <div className="flex min-w-0 gap-2 md:w-[142px] md:flex-col">
            <ReferenceSlot
              label="首帧"
              onChange={(file) => uploadReference(file, "firstFrame")}
              onClear={() => updateDraft({ firstFrame: null })}
              reference={draft.firstFrame}
            />
            <ReferenceSlot
              label="尾帧"
              onChange={(file) => uploadReference(file, "lastFrame")}
              onClear={() => updateDraft({ lastFrame: null })}
              reference={draft.lastFrame}
            />
          </div>
          <label className="relative min-w-0 flex-1 rounded-lg bg-[var(--color-canvas)]/70 px-3 pb-6 pt-2 ring-1 ring-inset ring-[var(--color-border)]">
            <span className="sr-only">生成提示词</span>
            <textarea
              ref={promptRef}
              className="min-h-[92px] w-full resize-none bg-transparent text-sm leading-6 outline-none"
              onChange={(event) => updateDraft({ prompt: event.target.value })}
              placeholder="描述主体动作、镜头变化、光线与声音……"
              rows={3}
              value={draft.prompt}
            />
            <span className="absolute bottom-2 right-3 text-[10px] text-[var(--color-text-faint)]">
              {draft.prompt.length} / 4000
            </span>
          </label>
        </div>

        <div className="mt-2.5 flex flex-wrap items-center gap-1.5 border-t border-[var(--color-border)] pt-2.5">
          <div aria-label="生成质量" className="inline-flex h-8 rounded-md bg-[var(--color-surface-muted)] p-0.5">
            {(["快速", "高质量"] as const).map((quality) => {
              const disabled = quality === "高质量" && !hq?.available;
              return (
                <button
                  aria-disabled={disabled}
                  className={cn(
                    "rounded px-2.5 text-xs font-medium",
                    draft.quality === quality && "bg-white shadow-[var(--shadow-card)]",
                    disabled && "cursor-not-allowed opacity-45",
                  )}
                  key={quality}
                  onClick={() => setQuality(quality)}
                  title={disabled ? hq?.unavailableReason ?? "HQ 当前不可用" : undefined}
                  type="button"
                >
                  {quality}
                </button>
              );
            })}
          </div>
          <SelectChip
            ariaLabel="画面比例"
            onChange={(value) => updateDraft({ ratio: value as GenerationDraft["ratio"] })}
            value={draft.ratio}
          >
            <option>16:9</option>
            <option>9:16</option>
            <option>1:1</option>
          </SelectChip>
          <SelectChip
            ariaLabel="分辨率"
            onChange={(value) =>
              updateDraft({ resolution: value as GenerationDraft["resolution"] })
            }
            value={draft.resolution}
          >
            {(profile?.resolutions ?? ["720p", "1080p"]).map((resolution) => (
              <option key={resolution}>{resolution}</option>
            ))}
          </SelectChip>
          <SelectChip
            ariaLabel="时长"
            onChange={(value) =>
              updateDraft({ duration: Number(value) as GenerationDraft["duration"] })
            }
            value={draft.duration}
          >
            {(profile?.durations ?? [5, 8, 10]).map((duration) => (
              <option key={duration} value={duration}>
                {duration} 秒
              </option>
            ))}
          </SelectChip>
          <Popover>
            <PopoverTrigger asChild>
              <button aria-label="打开高级参数" className="grid size-8 place-items-center" type="button">
                <SlidersHorizontal className="size-3.5" />
              </button>
            </PopoverTrigger>
            <PopoverContent align="start" className="w-[min(540px,calc(100vw-2rem))]">
              <p className="text-sm font-semibold">高级参数</p>
              <p className="mt-1 text-xs text-[var(--color-text-muted)]">
                精确控制随机性、关键帧约束与显存策略。
              </p>
              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                <label className="text-xs font-medium">
                  Seed
                  <input
                    className="mt-1.5 h-9 w-full rounded-md border px-2.5"
                    onChange={(event) => updateDraft({ seed: Number(event.target.value) || 0 })}
                    type="number"
                    value={draft.seed}
                  />
                </label>
                <label className="text-xs font-medium">
                  Offload
                  <select
                    className="mt-1.5 h-9 w-full rounded-md border bg-white px-2.5"
                    onChange={(event) =>
                      updateDraft({ offload: event.target.value as OffloadMode })
                    }
                    value={draft.offload}
                  >
                    <option value="none">GPU 优先</option>
                    <option value="cpu">CPU Offload</option>
                  </select>
                </label>
                <label className="text-xs font-medium sm:col-span-2">
                  负面提示词
                  <textarea
                    className="mt-1.5 min-h-20 w-full rounded-md border p-2"
                    onChange={(event) => updateDraft({ negativePrompt: event.target.value })}
                    value={draft.negativePrompt}
                  />
                </label>
              </div>
            </PopoverContent>
          </Popover>
          <button
            aria-pressed={draft.enhancePrompt}
            className="inline-flex h-8 items-center gap-1.5 rounded-md px-2.5 text-xs"
            onClick={() => updateDraft({ enhancePrompt: !draft.enhancePrompt })}
            type="button"
          >
            <WandSparkles className="size-3.5" /> Prompt 增强
          </button>
          <span className="ml-auto text-[10px] uppercase text-[var(--color-text-faint)]">
            {sessionReady ? `${draft.queue} · ${draft.resolution} · READY` : "COMPUTE REQUIRED"}
          </span>
          <Button disabled={!canSubmit} size="md" type="submit" variant="primary">
            <AnimatePresence initial={false} mode="wait">
              {submitted ? (
                <motion.span className="flex items-center gap-1.5" key="submitted">
                  <Check className="size-4" /> 已提交
                </motion.span>
              ) : (
                <motion.span className="flex items-center gap-1.5" key="ready">
                  <Sparkles className="size-4" /> 生成
                </motion.span>
              )}
            </AnimatePresence>
          </Button>
        </div>
        {!sessionReady && (
          <p className="mt-2 text-xs text-[var(--color-text-muted)]">请先热加载 GPU 资源。</p>
        )}
        {draft.profile === "hq" && !hq?.available && (
          <p className="mt-1 text-xs text-[var(--color-warning)]">
            {hq?.unavailableReason ?? "HQ 当前不可用"}
          </p>
        )}
        {error && <p className="mt-2 text-xs text-[var(--color-danger)]">{error}</p>}
      </motion.form>

      <div aria-label="创作入口" className="mt-4 flex items-center justify-center gap-2" role="group">
        <button
          aria-label="图片"
          className="inline-flex h-10 items-center gap-2 rounded-xl border bg-white/72 px-4 text-sm"
          onClick={() => quickImageInputRef.current?.click()}
          type="button"
        >
          <ImageIcon className="size-3.5" /> 图片
        </button>
        <input
          ref={quickImageInputRef}
          accept="image/png,image/jpeg,image/webp"
          className="sr-only"
          onChange={async (event) => {
            const file = event.target.files?.[0];
            if (file) await uploadReference(file, "firstFrame");
            event.target.value = "";
          }}
          type="file"
        />
        <button
          aria-label="视频"
          className="inline-flex h-10 items-center gap-2 rounded-xl border border-[var(--color-accent)]/20 bg-[var(--color-accent-soft)] px-4 text-sm font-semibold text-[var(--color-accent)]"
          onClick={() => promptRef.current?.focus()}
          type="button"
        >
          <Video className="size-3.5" /> 视频
        </button>
        <button
          aria-label="Agent"
          aria-pressed={agentOpen}
          className="inline-flex h-10 items-center gap-2 rounded-xl border bg-white/72 px-4 text-sm"
          onClick={onAgentToggle}
          type="button"
        >
          <Bot className="size-3.5" /> Agent
        </button>
      </div>
    </div>
  );
}
