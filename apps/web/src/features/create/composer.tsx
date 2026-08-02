import {
  Check,
  Plus,
  Sparkles,
  WandSparkles,
  X,
} from "lucide-react";
import { useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { DurationSliderPopover } from "@/features/create/duration-slider-popover";
import { FrameSizePopover } from "@/features/create/frame-size-popover";
import { GenerationTypePopover } from "@/features/create/generation-type-popover";
import { ModelSelectorPopover } from "@/features/create/model-selector-popover";
import { useComputeCapabilities, useComputeSession } from "@/features/compute/hooks";
import {
  useCreateConversation,
  useCreateJob,
  useUploadImage,
} from "@/features/studio/hooks";
import type {
  GenerationDraft,
  MediaReference,
  ProfileCapability,
} from "@/features/studio/types";
import { cn } from "@/lib/utils";
import { useStudioStore } from "@/store/studio-store";

function ReferenceSlot({
  label,
  reference,
  onChange,
  onClear,
  className,
}: {
  label: string;
  reference: MediaReference | null;
  onChange: (file: File) => Promise<void>;
  onClear: () => void;
  className?: string;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  return (
    <div
      className={cn(
        "group relative h-[82px] w-[62px] shrink-0 transition-transform duration-200 ease-out hover:z-30 hover:scale-[1.1]",
        className,
      )}
    >
      <button
        aria-label={reference ? `更换${label}` : `上传${label}`}
        className="relative grid size-full place-items-center overflow-hidden rounded-[5px] border border-[var(--color-border-strong)] bg-[var(--color-surface-muted)] text-[var(--color-text-faint)] shadow-[0_2px_6px_rgba(48,46,42,0.08)] transition-colors hover:border-[var(--color-accent)]/35 hover:bg-[var(--color-surface-hover)]"
        onClick={() => inputRef.current?.click()}
        type="button"
      >
        {reference ? (
          <>
            <img
              alt=""
              className="size-full object-cover transition-transform duration-300 ease-out group-hover:scale-[1.04]"
              src={reference.url}
            />
            <span className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/60 to-transparent px-1.5 pb-1.5 pt-5 text-center text-[9px] font-medium text-white">
              {label}
            </span>
          </>
        ) : (
          <span className="flex flex-col items-center gap-1.5">
            <Plus className="size-5" strokeWidth={1.6} />
            <span className="text-[9px] font-medium">{label}</span>
          </span>
        )}
      </button>
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
      {reference && (
        <button
          aria-label={`移除${label}`}
          className="absolute -right-1.5 -top-1.5 z-10 grid size-5 place-items-center rounded-full border bg-white text-[var(--color-text-muted)] shadow-sm transition-colors hover:text-[var(--color-danger)]"
          onClick={onClear}
          type="button"
        >
          <X className="size-2.5" />
        </button>
      )}
    </div>
  );
}

export function Composer() {
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

  const profiles = useMemo(
    () => capabilities.data?.profiles ?? [],
    [capabilities.data?.profiles],
  );
  const profile = useMemo(
    () => profiles.find((item) => item.tier === draft.profile),
    [draft.profile, profiles],
  );
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

  const selectProfile = (next: ProfileCapability) => {
    const resolutions = next.resolutions ?? [];
    const resolution = resolutions.includes(draft.resolution)
      ? draft.resolution
      : (resolutions[0] as GenerationDraft["resolution"] | undefined) ?? draft.resolution;
    updateDraft({
      quality: next.tier === "hq" ? "高质量" : "快速",
      queue: next.tier,
      profile: next.tier,
      resolution,
    });
  };

  return (
    <div className="w-full">
      <form
        aria-label="视频生成创作器"
        className={cn(
          "rounded-[10px] border bg-white/92 p-2.5 backdrop-blur-xl transition-[border-color,box-shadow] duration-150",
          focused
            ? "border-[var(--color-accent)]/28 shadow-[0_0_0_3px_var(--color-accent-faint)]"
            : "border-[var(--color-border-strong)] shadow-[var(--shadow-card)]",
        )}
        onBlur={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget)) setFocused(false);
        }}
        onFocus={() => setFocused(true)}
        onSubmit={submit}
      >
        <div className="flex flex-col gap-2.5 md:flex-row">
          <div className="flex min-h-[112px] shrink-0 items-center justify-center px-3 pb-1 pt-3 md:w-[132px] md:self-stretch md:px-1 md:py-0">
            <ReferenceSlot
              className="z-0 -rotate-[9deg] translate-x-2 translate-y-1"
              label="首帧"
              onChange={(file) => uploadReference(file, "firstFrame")}
              onClear={() => updateDraft({ firstFrame: null })}
              reference={draft.firstFrame}
            />
            <ReferenceSlot
              className="z-10 -ml-4 rotate-[8deg] translate-y-2"
              label="尾帧"
              onChange={(file) => uploadReference(file, "lastFrame")}
              onClear={() => updateDraft({ lastFrame: null })}
              reference={draft.lastFrame}
            />
          </div>
          <label className="relative min-w-0 flex-1 rounded-[7px] bg-[var(--color-canvas)]/72 px-3 pb-7 pt-2.5 ring-1 ring-inset ring-[var(--color-border)]">
            <span className="sr-only">生成提示词</span>
            <textarea
              className="min-h-[94px] w-full resize-none bg-transparent text-sm leading-6 outline-none"
              onChange={(event) => updateDraft({ prompt: event.target.value })}
              placeholder="描述主体动作、镜头变化、光线与声音……"
              rows={3}
              value={draft.prompt}
            />
            <span className="absolute bottom-2.5 right-3 text-[9px] text-[var(--color-text-faint)]">
              {draft.prompt.length} / 4000
            </span>
          </label>
        </div>

        <div className="mt-2.5 flex flex-wrap items-center gap-1.5 border-t border-[var(--color-border)] pt-2.5">
          <GenerationTypePopover />
          <ModelSelectorPopover
            onChange={selectProfile}
            profiles={profiles}
            value={draft.profile}
          />
          <FrameSizePopover
            onRatioChange={(ratio) => updateDraft({ ratio })}
            onResolutionChange={(resolution) => updateDraft({ resolution })}
            ratio={draft.ratio}
            resolution={draft.resolution}
            resolutions={profile?.resolutions ?? ["720p", "1080p"]}
          />
          <DurationSliderPopover
            onChange={(duration) => updateDraft({ duration })}
            value={draft.duration}
          />
          <button
            aria-pressed={draft.enhancePrompt}
            className={cn(
              "ml-auto inline-flex h-9 items-center gap-1.5 rounded-[5px] px-2.5 text-xs transition",
              draft.enhancePrompt
                ? "bg-[var(--color-accent-soft)] font-medium text-[var(--color-accent)]"
                : "text-[var(--color-text-muted)] hover:bg-[var(--color-surface-muted)]",
            )}
            onClick={() => updateDraft({ enhancePrompt: !draft.enhancePrompt })}
            type="button"
          >
            <WandSparkles className="size-3.5" /> Prompt 增强
          </button>
          <Button
            disabled={!canSubmit}
            size="md"
            title={!sessionReady ? "请先前往算力页热加载 GPU" : undefined}
            type="submit"
            variant="primary"
          >
            <span className="flex items-center gap-1.5">
              {submitted ? <Check className="size-4" /> : <Sparkles className="size-4" />}
              {submitted ? "已提交" : "生成"}
            </span>
          </Button>
        </div>
        {error && <p className="mt-2 text-xs text-[var(--color-danger)]">{error}</p>}
      </form>
    </div>
  );
}
