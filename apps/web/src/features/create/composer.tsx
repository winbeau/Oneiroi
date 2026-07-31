import {
  Check,
  ChevronDown,
  ImagePlus,
  SlidersHorizontal,
  Sparkles,
  WandSparkles,
  X,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import type {
  GenerationDraft,
  MediaReference,
  OffloadMode,
} from "@/features/studio/types";
import { cn } from "@/lib/utils";
import { useStudioStore } from "@/store/studio-store";

const readImage = (file: File): Promise<MediaReference> =>
  new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => {
      if (typeof reader.result === "string") {
        resolve({ name: file.name, url: reader.result });
      } else {
        reject(new Error("无法读取图片"));
      }
    });
    reader.addEventListener("error", () => reject(reader.error));
    reader.readAsDataURL(file);
  });

function ReferenceSlot({
  label,
  reference,
  onChange,
  onClear,
}: {
  label: string;
  reference: MediaReference | null;
  onChange: (reference: MediaReference) => void;
  onClear: () => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);

  return (
    <div className="group relative flex h-11 min-w-0 items-center gap-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-muted)]/65 p-1 pr-2 transition hover:border-[var(--color-border-strong)] hover:bg-[var(--color-surface-muted)] sm:w-[142px]">
      <button
        aria-label={reference ? `更换${label}` : `上传${label}`}
        className="relative grid size-9 shrink-0 place-items-center overflow-hidden rounded-md bg-white text-[var(--color-text-faint)] shadow-[var(--shadow-card)] outline-none ring-1 ring-[var(--color-border)] transition group-hover:text-[var(--color-accent)] focus-visible:ring-2 focus-visible:ring-[var(--color-accent)]/40"
        onClick={() => inputRef.current?.click()}
        type="button"
      >
        {reference ? (
          <img alt="" className="size-full object-cover" src={reference.url} />
        ) : (
          <ImagePlus aria-hidden="true" className="size-3.5" />
        )}
        <input
          ref={inputRef}
          accept="image/*"
          className="sr-only"
          onChange={async (event) => {
            const file = event.target.files?.[0];
            if (file) onChange(await readImage(file));
            event.target.value = "";
          }}
          type="file"
        />
      </button>
      <div className="min-w-0 flex-1">
        <p className="text-[10px] font-semibold uppercase tracking-[0.06em] text-[var(--color-text-faint)]">
          {label}
        </p>
        <p className="truncate text-[11px] text-[var(--color-text-muted)]">
          {reference?.name ?? "点击上传"}
        </p>
      </div>
      {reference && (
        <button
          aria-label={`移除${label}`}
          className="grid size-6 shrink-0 place-items-center rounded text-[var(--color-text-faint)] transition hover:bg-white hover:text-[var(--color-text)]"
          onClick={onClear}
          type="button"
        >
          <X aria-hidden="true" className="size-3" />
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
    <label className="relative inline-flex h-8 items-center rounded-md bg-[var(--color-surface-muted)] px-2.5 text-xs text-[var(--color-text-muted)] transition hover:bg-[var(--color-surface-hover)] hover:text-[var(--color-text)]">
      <span className="sr-only">{ariaLabel}</span>
      <select
        aria-label={ariaLabel}
        className="appearance-none bg-transparent pr-4 outline-none"
        onChange={(event) => onChange(event.target.value)}
        value={value}
      >
        {children}
      </select>
      <ChevronDown aria-hidden="true" className="pointer-events-none absolute right-2 size-3" />
    </label>
  );
}

export function Composer() {
  const draft = useStudioStore((state) => state.draft);
  const updateDraft = useStudioStore((state) => state.updateDraft);
  const submitDraft = useStudioStore((state) => state.submitDraft);
  const [submitted, setSubmitted] = useState(false);
  const [focused, setFocused] = useState(false);

  const setQuality = (quality: GenerationDraft["quality"]) => {
    updateDraft(
      quality === "高质量"
        ? { quality, queue: "hq", resolution: "1080p" }
        : { quality, queue: "fast", resolution: "720p" },
    );
  };

  const submit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!draft.prompt.trim()) return;
    submitDraft();
    setSubmitted(true);
    window.setTimeout(() => setSubmitted(false), 2_200);
  };

  return (
    <motion.form
      animate={{ y: focused ? -2 : 0 }}
      aria-label="视频生成创作器"
      className={cn(
        "rounded-[18px] border bg-white/92 p-2.5 backdrop-blur-xl transition-[border-color,box-shadow] duration-300",
        focused
          ? "border-[var(--color-accent)]/35 shadow-[0_24px_70px_rgba(73,66,135,0.15),0_3px_10px_rgba(48,46,42,0.06)]"
          : "border-[var(--color-border-strong)] shadow-[var(--shadow-float)]",
      )}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setFocused(false);
      }}
      onFocus={() => setFocused(true)}
      onSubmit={submit}
      transition={{ duration: 0.24, ease: [0.2, 0.8, 0.2, 1] }}
    >
      <div className="flex flex-col gap-2.5 md:flex-row">
        <div className="flex min-w-0 gap-2 md:w-[142px] md:flex-col">
          <ReferenceSlot
            label="首帧"
            onChange={(firstFrame) => updateDraft({ firstFrame })}
            onClear={() => updateDraft({ firstFrame: null })}
            reference={draft.firstFrame}
          />
          <ReferenceSlot
            label="尾帧"
            onChange={(lastFrame) => updateDraft({ lastFrame })}
            onClear={() => updateDraft({ lastFrame: null })}
            reference={draft.lastFrame}
          />
        </div>

        <label className="relative min-w-0 flex-1 rounded-lg bg-[var(--color-canvas)]/70 px-3 pb-6 pt-2 ring-1 ring-inset ring-[var(--color-border)] transition focus-within:bg-white focus-within:ring-[var(--color-accent)]/25">
          <span className="sr-only">生成提示词</span>
          <textarea
            className="scrollbar-notion min-h-[68px] w-full resize-none bg-transparent text-sm leading-6 outline-none placeholder:text-[var(--color-text-faint)] md:min-h-[92px]"
            onChange={(event) => updateDraft({ prompt: event.target.value })}
            placeholder="描述主体动作、镜头变化、光线与声音……"
            rows={3}
            value={draft.prompt}
          />
          <span className="absolute bottom-2 right-3 text-[10px] tabular-nums text-[var(--color-text-faint)]">
            {draft.prompt.length} / 2000
          </span>
        </label>
      </div>

      <div className="mt-2.5 flex flex-wrap items-center gap-1.5 border-t border-[var(--color-border)] px-0.5 pt-2.5">
        <div
          aria-label="生成质量"
          className="inline-flex h-8 rounded-md bg-[var(--color-surface-muted)] p-0.5"
          role="group"
        >
          {(["快速", "高质量"] as const).map((quality) => (
            <button
              className={cn(
                "relative isolate rounded px-2.5 text-xs font-medium transition-colors",
                draft.quality === quality
                  ? "text-[var(--color-text)]"
                  : "text-[var(--color-text-muted)] hover:text-[var(--color-text)]",
              )}
              key={quality}
              onClick={() => setQuality(quality)}
              type="button"
            >
              {draft.quality === quality && (
                <motion.span
                  aria-hidden="true"
                  className="absolute inset-0 -z-10 rounded bg-white shadow-[var(--shadow-card)] ring-1 ring-[var(--color-border)]"
                  layoutId="quality-pill"
                  transition={{ duration: 0.25, ease: [0.2, 0.8, 0.2, 1] }}
                />
              )}
              {quality}
            </button>
          ))}
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
          <option>720p</option>
          <option>1080p</option>
        </SelectChip>

        <SelectChip
          ariaLabel="时长"
          onChange={(value) =>
            updateDraft({ duration: Number(value) as GenerationDraft["duration"] })
          }
          value={draft.duration}
        >
          <option value={5}>5 秒</option>
          <option value={8}>8 秒</option>
          <option value={10}>10 秒</option>
        </SelectChip>

        <Popover>
          <PopoverTrigger asChild>
            <button
              aria-label="打开高级参数"
              className="grid size-8 place-items-center rounded-md text-[var(--color-text-muted)] transition hover:bg-[var(--color-surface-muted)] hover:text-[var(--color-text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)]/30"
              title="高级参数"
              type="button"
            >
              <SlidersHorizontal aria-hidden="true" className="size-3.5" />
            </button>
          </PopoverTrigger>
          <PopoverContent align="start" className="w-[min(540px,calc(100vw-2rem))]">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-sm font-semibold">高级参数</p>
                <p className="mt-1 text-xs text-[var(--color-text-muted)]">
                  精确控制随机性、关键帧约束与显存策略。
                </p>
              </div>
              <span className="rounded-full bg-[var(--color-accent-soft)] px-2 py-1 text-[10px] font-medium text-[var(--color-accent)]">
                {draft.queue.toUpperCase()}
              </span>
            </div>
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <label className="text-xs font-medium text-[var(--color-text-muted)]">
                Seed
                <input
                  className="mt-1.5 h-9 w-full rounded-md border border-[var(--color-border-strong)] bg-white px-2.5 text-sm tabular-nums outline-none transition focus:border-[var(--color-accent)] focus:shadow-[0_0_0_3px_var(--color-accent-soft)]"
                  min={0}
                  onChange={(event) => updateDraft({ seed: Number(event.target.value) || 0 })}
                  type="number"
                  value={draft.seed}
                />
              </label>
              <label className="text-xs font-medium text-[var(--color-text-muted)]">
                Offload
                <select
                  className="mt-1.5 h-9 w-full rounded-md border border-[var(--color-border-strong)] bg-white px-2.5 text-sm outline-none focus:border-[var(--color-accent)]"
                  onChange={(event) =>
                    updateDraft({ offload: event.target.value as OffloadMode })
                  }
                  value={draft.offload}
                >
                  <option value="none">GPU 优先</option>
                  <option value="cpu">CPU Offload</option>
                </select>
              </label>
              <label className="text-xs font-medium text-[var(--color-text-muted)]">
                <span className="flex justify-between">
                  首帧强度
                  <span className="font-mono text-[var(--color-text-faint)]">
                    {draft.firstStrength.toFixed(2)}
                  </span>
                </span>
                <input
                  className="mt-2 h-2 w-full accent-[var(--color-accent)]"
                  max={1}
                  min={0}
                  onChange={(event) =>
                    updateDraft({ firstStrength: Number(event.target.value) })
                  }
                  step={0.05}
                  type="range"
                  value={draft.firstStrength}
                />
              </label>
              <label className="text-xs font-medium text-[var(--color-text-muted)]">
                <span className="flex justify-between">
                  尾帧强度
                  <span className="font-mono text-[var(--color-text-faint)]">
                    {draft.lastStrength.toFixed(2)}
                  </span>
                </span>
                <input
                  className="mt-2 h-2 w-full accent-[var(--color-accent)]"
                  max={1}
                  min={0}
                  onChange={(event) =>
                    updateDraft({ lastStrength: Number(event.target.value) })
                  }
                  step={0.05}
                  type="range"
                  value={draft.lastStrength}
                />
              </label>
              <label className="text-xs font-medium text-[var(--color-text-muted)] sm:col-span-2">
                负面提示词
                <textarea
                  className="mt-1.5 min-h-20 w-full resize-y rounded-md border border-[var(--color-border-strong)] bg-white px-2.5 py-2 text-sm leading-5 outline-none transition focus:border-[var(--color-accent)] focus:shadow-[0_0_0_3px_var(--color-accent-soft)]"
                  onChange={(event) => updateDraft({ negativePrompt: event.target.value })}
                  placeholder="例如：身份漂移、镜头抖动、额外肢体……"
                  value={draft.negativePrompt}
                />
              </label>
            </div>
          </PopoverContent>
        </Popover>

        <button
          aria-pressed={draft.enhancePrompt}
          className={cn(
            "inline-flex h-8 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium transition",
            draft.enhancePrompt
              ? "bg-[var(--color-accent-soft)] text-[var(--color-accent)]"
              : "text-[var(--color-text-muted)] hover:bg-[var(--color-surface-muted)] hover:text-[var(--color-text)]",
          )}
          onClick={() => updateDraft({ enhancePrompt: !draft.enhancePrompt })}
          type="button"
        >
          <WandSparkles aria-hidden="true" className="size-3.5" />
          <span className="hidden sm:inline">Prompt 增强</span>
        </button>

        <span className="ml-auto hidden text-[10px] uppercase tracking-[0.08em] text-[var(--color-text-faint)] lg:inline">
          {draft.queue} · {draft.resolution} · READY
        </span>
        <Button className="min-w-[92px]" disabled={!draft.prompt.trim()} size="md" type="submit" variant="primary">
          <AnimatePresence initial={false} mode="wait">
            {submitted ? (
              <motion.span
                animate={{ opacity: 1, y: 0 }}
                className="flex items-center gap-1.5"
                exit={{ opacity: 0, y: -4 }}
                initial={{ opacity: 0, y: 4 }}
                key="submitted"
              >
                <Check aria-hidden="true" className="size-4" />
                已提交
              </motion.span>
            ) : (
              <motion.span
                animate={{ opacity: 1, y: 0 }}
                className="flex items-center gap-1.5"
                exit={{ opacity: 0, y: -4 }}
                initial={{ opacity: 0, y: 4 }}
                key="ready"
              >
                <Sparkles aria-hidden="true" className="size-4" />
                生成
              </motion.span>
            )}
          </AnimatePresence>
        </Button>
      </div>
    </motion.form>
  );
}
