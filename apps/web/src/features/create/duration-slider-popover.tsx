import { ChevronDown, Clock3 } from "lucide-react";
import type { CSSProperties } from "react";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import type { GenerationDraft } from "@/features/studio/types";

export function DurationSliderPopover({
  value,
  onChange,
}: {
  value: GenerationDraft["duration"];
  onChange: (duration: GenerationDraft["duration"]) => void;
}) {
  const minimum = 1;
  const maximum = 15;
  const normalizedValue = Math.min(maximum, Math.max(minimum, Number(value)));
  const progress = ((normalizedValue - minimum) / (maximum - minimum)) * 100;

  const commitManualValue = (input: HTMLInputElement) => {
    const parsed = Number.parseInt(input.value, 10);
    const next = Number.isFinite(parsed)
      ? Math.min(maximum, Math.max(minimum, parsed))
      : normalizedValue;
    input.value = String(next);
    onChange(next as GenerationDraft["duration"]);
  };

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          aria-label="选择视频生成时长"
          className="inline-flex h-9 items-center gap-2 rounded-[5px] border border-[var(--color-border)] bg-white/78 px-3 text-xs font-medium transition hover:bg-white"
          type="button"
        >
          <Clock3 className="size-3.5" /> {value} 秒 <ChevronDown className="size-3" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[min(460px,calc(100vw-2rem))] p-4">
        <p className="text-xs font-semibold">选择视频生成时长</p>
        <div className="mt-4 grid grid-cols-[minmax(0,1fr)_82px] items-center gap-4">
          <div>
            <input
              aria-label="视频时长"
              className="duration-range w-full"
              max={maximum}
              min={minimum}
              onChange={(event) => onChange(Number(event.target.value) as GenerationDraft["duration"])}
              step={1}
              style={{ "--duration-progress": `${progress}%` } as CSSProperties}
              type="range"
              value={normalizedValue}
            />
            <div className="mt-2 flex justify-between font-mono text-[10px] text-[var(--color-text-muted)]">
              <span>1</span>
              <span>5</span>
              <span>10</span>
              <span>15</span>
            </div>
          </div>
          <label className="flex h-12 items-center rounded-[5px] bg-[var(--color-surface-muted)] px-2.5 focus-within:ring-2 focus-within:ring-[var(--color-accent)]/20">
            <input
              aria-label="手动输入视频时长"
              className="min-w-0 flex-1 bg-transparent text-center text-base font-semibold tabular-nums outline-none"
              defaultValue={normalizedValue}
              inputMode="numeric"
              key={normalizedValue}
              max={maximum}
              min={minimum}
              onBlur={(event) => commitManualValue(event.currentTarget)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  event.currentTarget.blur();
                }
              }}
              step={1}
              type="number"
            />
            <span className="text-xs text-[var(--color-text-faint)]">s</span>
          </label>
        </div>
      </PopoverContent>
    </Popover>
  );
}
