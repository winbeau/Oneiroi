import { ChevronDown, RectangleHorizontal } from "lucide-react";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import type { GenerationDraft } from "@/features/studio/types";
import { cn } from "@/lib/utils";

type RatioOption = "21:9" | "16:9" | "4:3" | "1:1" | "3:4" | "9:16";

const ratios: RatioOption[] = ["21:9", "16:9", "4:3", "1:1", "3:4", "9:16"];

const ratioShape: Record<RatioOption, string> = {
  "21:9": "h-2.5 w-6",
  "16:9": "h-3 w-5",
  "4:3": "h-4 w-5",
  "1:1": "size-4",
  "3:4": "h-5 w-4",
  "9:16": "h-5 w-3",
};

export function FrameSizePopover({
  ratio,
  resolution,
  resolutions,
  onRatioChange,
  onResolutionChange,
}: {
  ratio: GenerationDraft["ratio"];
  resolution: GenerationDraft["resolution"];
  resolutions: string[];
  onRatioChange: (ratio: GenerationDraft["ratio"]) => void;
  onResolutionChange: (resolution: GenerationDraft["resolution"]) => void;
}) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          aria-label="选择画面比例和分辨率"
          className="inline-flex h-9 items-center gap-2 rounded-[5px] border border-[var(--color-border)] bg-white/78 px-3 text-xs font-medium transition hover:bg-white"
          type="button"
        >
          <RectangleHorizontal className="size-3.5" /> {ratio}
          <span className="text-[var(--color-text-muted)]">{resolution.toUpperCase()}</span>
          <ChevronDown className="size-3" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[min(460px,calc(100vw-2rem))] p-3">
        <p className="text-xs font-semibold">选择比例</p>
        <div className="mt-2 grid grid-cols-3 gap-0.5 rounded-[6px] bg-[var(--color-surface-muted)] p-1 sm:grid-cols-6">
          {ratios.map((item) => {
            const supported = true;
            return (
              <button
                aria-disabled={!supported}
                className={cn(
                  "relative flex min-h-14 flex-col items-center justify-center gap-1.5 rounded-[5px] text-[11px] outline-none transition-colors focus-visible:ring-2 focus-visible:ring-[var(--color-accent)]/20",
                  ratio === item
                    ? "bg-white font-semibold text-[var(--color-text)] shadow-[var(--shadow-card)] ring-1 ring-inset ring-[var(--color-accent)]/16"
                    : "text-[var(--color-text-muted)]",
                  supported
                    ? "hover:bg-white/65 hover:text-[var(--color-text)]"
                    : "cursor-not-allowed opacity-50",
                )}
                disabled={!supported}
                key={item}
                onClick={() => onRatioChange(item as GenerationDraft["ratio"])}
                type="button"
              >
                <span className={cn("rounded-[2px] border-2 border-current", ratioShape[item])} />
                {item}
              </button>
            );
          })}
        </div>

        <p className="mt-4 text-xs font-semibold">选择分辨率</p>
        <div className="mt-2 grid gap-1.5 sm:grid-cols-2">
          {resolutions.map((item) => (
            <button
              className={cn(
                "h-10 rounded-[5px] border text-xs font-semibold transition",
                resolution === item
                  ? "border-[var(--color-accent)]/25 bg-[var(--color-accent-soft)] text-[var(--color-accent)]"
                  : "bg-white hover:bg-[var(--color-surface-muted)]",
              )}
              key={item}
              onClick={() => onResolutionChange(item as GenerationDraft["resolution"])}
              type="button"
            >
              {item.toUpperCase()}
            </button>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}
