import {
  ChevronDown,
  ImagePlus,
  Maximize2,
  Minus,
  Plus,
  SlidersHorizontal,
  Sparkles,
  X,
} from "lucide-react";
import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import type {
  GenerationDraft,
  MediaReference,
  OffloadMode,
} from "@/features/studio/types";
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
    <div className="flex items-center gap-2">
      <button
        aria-label={reference ? `更换${label}` : `上传${label}`}
        className="group relative grid size-12 shrink-0 place-items-center overflow-hidden rounded-md border border-dashed border-[var(--color-border-strong)] bg-[var(--color-surface-muted)] text-[var(--color-text-faint)] transition hover:border-[var(--color-accent)] hover:text-[var(--color-accent)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)]"
        onClick={() => inputRef.current?.click()}
        type="button"
      >
        {reference ? (
          <img alt="" className="size-full object-cover" src={reference.url} />
        ) : (
          <ImagePlus aria-hidden="true" className="size-4" />
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
      <div className="min-w-0">
        <p className="text-xs font-medium text-[var(--color-text-muted)]">{label}</p>
        <p className="max-w-28 truncate text-[11px] text-[var(--color-text-faint)]">
          {reference?.name ?? "点击上传"}
        </p>
      </div>
      {reference && (
        <button
          aria-label={`移除${label}`}
          className="ml-auto rounded p-1 text-[var(--color-text-faint)] hover:bg-[var(--color-surface-muted)] hover:text-[var(--color-text)]"
          onClick={onClear}
          type="button"
        >
          <X aria-hidden="true" className="size-3.5" />
        </button>
      )}
    </div>
  );
}

export function Composer() {
  const draft = useStudioStore((state) => state.draft);
  const updateDraft = useStudioStore((state) => state.updateDraft);
  const submitDraft = useStudioStore((state) => state.submitDraft);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [submitted, setSubmitted] = useState(false);

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
    window.setTimeout(() => setSubmitted(false), 2_500);
  };

  return (
    <form
      aria-label="视频生成创作器"
      className="rounded-xl border border-[var(--color-border-strong)] bg-white p-3 shadow-[0_8px_30px_rgba(55,53,47,0.08)]"
      onSubmit={submit}
    >
      <div className="flex gap-3">
        <div className="flex shrink-0 flex-col gap-2">
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
        <label className="min-w-0 flex-1">
          <span className="sr-only">生成提示词</span>
          <textarea
            className="min-h-28 w-full resize-none bg-transparent px-1 py-1 text-sm leading-6 outline-none placeholder:text-[var(--color-text-faint)]"
            onChange={(event) => updateDraft({ prompt: event.target.value })}
            placeholder="描述画面如何运动，例如：人物打开柜门，伸手拿出一本书，镜头保持固定……"
            rows={4}
            value={draft.prompt}
          />
          <span className="mt-1 block text-right text-[11px] tabular-nums text-[var(--color-text-faint)]">
            {draft.prompt.length} / 2000
          </span>
        </label>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-[var(--color-border)] pt-3">
        <div className="inline-flex h-8 rounded-md bg-[var(--color-surface-muted)] p-0.5" role="group" aria-label="生成质量">
          {(["快速", "高质量"] as const).map((quality) => (
            <button
              className={`rounded px-2.5 text-xs font-medium transition ${
                draft.quality === quality
                  ? "bg-white text-[var(--color-text)] shadow-[var(--shadow-card)]"
                  : "text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
              }`}
              key={quality}
              onClick={() => setQuality(quality)}
              type="button"
            >
              {quality}
            </button>
          ))}
        </div>

        <label className="inline-flex h-8 items-center gap-1 rounded-md bg-[var(--color-surface-muted)] px-2.5 text-xs text-[var(--color-text-muted)]">
          <span className="sr-only">画面比例</span>
          <select
            aria-label="画面比例"
            className="bg-transparent outline-none"
            onChange={(event) =>
              updateDraft({ ratio: event.target.value as GenerationDraft["ratio"] })
            }
            value={draft.ratio}
          >
            <option>16:9</option>
            <option>9:16</option>
            <option>1:1</option>
          </select>
          <ChevronDown aria-hidden="true" className="size-3" />
        </label>

        <label className="inline-flex h-8 items-center gap-1 rounded-md bg-[var(--color-surface-muted)] px-2.5 text-xs text-[var(--color-text-muted)]">
          <span className="sr-only">分辨率</span>
          <select
            aria-label="分辨率"
            className="bg-transparent outline-none"
            onChange={(event) =>
              updateDraft({ resolution: event.target.value as GenerationDraft["resolution"] })
            }
            value={draft.resolution}
          >
            <option>720p</option>
            <option>1080p</option>
          </select>
          <ChevronDown aria-hidden="true" className="size-3" />
        </label>

        <label className="inline-flex h-8 items-center gap-1 rounded-md bg-[var(--color-surface-muted)] px-2.5 text-xs text-[var(--color-text-muted)]">
          <span className="sr-only">时长</span>
          <select
            aria-label="时长"
            className="bg-transparent outline-none"
            onChange={(event) =>
              updateDraft({ duration: Number(event.target.value) as GenerationDraft["duration"] })
            }
            value={draft.duration}
          >
            <option value={5}>5 秒</option>
            <option value={8}>8 秒</option>
            <option value={10}>10 秒</option>
          </select>
          <ChevronDown aria-hidden="true" className="size-3" />
        </label>

        <button
          className={`grid size-8 place-items-center rounded-md transition ${
            advancedOpen
              ? "bg-[var(--color-text)] text-white"
              : "text-[var(--color-text-muted)] hover:bg-[var(--color-surface-muted)] hover:text-[var(--color-text)]"
          }`}
          onClick={() => setAdvancedOpen((value) => !value)}
          title="高级参数"
          type="button"
        >
          <SlidersHorizontal aria-hidden="true" className="size-4" />
        </button>

        <button
          className="inline-flex h-8 items-center gap-1 rounded-md px-2.5 text-xs font-medium text-[var(--color-accent)] hover:bg-blue-50"
          onClick={() => updateDraft({ enhancePrompt: !draft.enhancePrompt })}
          type="button"
        >
          <Sparkles aria-hidden="true" className="size-3.5" />
          {draft.enhancePrompt ? "已增强" : "Prompt 增强"}
        </button>

        <span className="ml-auto hidden text-xs text-[var(--color-text-faint)] lg:inline">
          {draft.queue === "hq" ? "HQ 队列" : "Fast 队列"} · {submitted ? "已提交" : "就绪"}
        </span>
        <Button disabled={!draft.prompt.trim()} size="md" type="submit" variant="primary">
          <Sparkles aria-hidden="true" className="size-4" />
          生成
        </Button>
      </div>

      {advancedOpen && (
        <div className="mt-3 grid gap-3 border-t border-[var(--color-border)] pt-3 sm:grid-cols-2 lg:grid-cols-4">
          <label className="text-xs text-[var(--color-text-muted)]">
            Seed
            <input
              className="mt-1 h-9 w-full rounded-md border border-[var(--color-border-strong)] px-2 text-sm tabular-nums outline-none focus:border-[var(--color-accent)]"
              min={0}
              onChange={(event) => updateDraft({ seed: Number(event.target.value) || 0 })}
              type="number"
              value={draft.seed}
            />
          </label>
          <label className="text-xs text-[var(--color-text-muted)]">
            首帧强度
            <input
              className="mt-1 h-9 w-full accent-[var(--color-accent)]"
              max={1}
              min={0}
              onChange={(event) => updateDraft({ firstStrength: Number(event.target.value) })}
              step={0.05}
              type="range"
              value={draft.firstStrength}
            />
            <span className="tabular-nums">{draft.firstStrength.toFixed(2)}</span>
          </label>
          <label className="text-xs text-[var(--color-text-muted)]">
            尾帧强度
            <input
              className="mt-1 w-full accent-[var(--color-accent)]"
              max={1}
              min={0}
              onChange={(event) => updateDraft({ lastStrength: Number(event.target.value) })}
              step={0.05}
              type="range"
              value={draft.lastStrength}
            />
            <span className="tabular-nums">{draft.lastStrength.toFixed(2)}</span>
          </label>
          <label className="text-xs text-[var(--color-text-muted)]">
            Offload
            <select
              className="mt-1 h-9 w-full rounded-md border border-[var(--color-border-strong)] bg-white px-2 text-sm outline-none focus:border-[var(--color-accent)]"
              onChange={(event) => updateDraft({ offload: event.target.value as OffloadMode })}
              value={draft.offload}
            >
              <option value="none">GPU 优先</option>
              <option value="cpu">CPU Offload</option>
            </select>
          </label>
          <label className="text-xs text-[var(--color-text-muted)] sm:col-span-2 lg:col-span-4">
            负面提示词
            <textarea
              className="mt-1 min-h-16 w-full resize-y rounded-md border border-[var(--color-border-strong)] px-2 py-1.5 text-sm leading-5 outline-none focus:border-[var(--color-accent)]"
              onChange={(event) => updateDraft({ negativePrompt: event.target.value })}
              value={draft.negativePrompt}
            />
          </label>
          <div className="flex items-center gap-2 text-xs text-[var(--color-text-faint)] sm:col-span-2 lg:col-span-4">
            <Maximize2 aria-hidden="true" className="size-3.5" />
            <span>当前规格：{draft.resolution} · {draft.ratio} · {draft.duration} 秒</span>
            <Minus aria-hidden="true" className="ml-auto size-3" />
            <Plus aria-hidden="true" className="size-3" />
          </div>
        </div>
      )}
    </form>
  );
}
