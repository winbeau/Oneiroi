import { Check, ChevronDown, ImageIcon, Video } from "lucide-react";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

export function GenerationTypePopover() {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          aria-label="选择生成类型"
          className="inline-flex h-9 items-center gap-2 rounded-[5px] border border-[var(--color-border)] bg-white/78 px-3 text-xs font-medium transition hover:bg-white"
          type="button"
        >
          <Video className="size-3.5" /> 视频生成 <ChevronDown className="size-3" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-72 p-2">
        <p className="px-2 pb-2 pt-1 text-[10px] font-medium text-[var(--color-text-faint)]">
          选择生成类型
        </p>
        <button
          className="flex w-full items-center gap-3 rounded-[6px] bg-[var(--color-accent-soft)] px-3 py-3 text-left"
          type="button"
        >
          <span className="grid size-9 place-items-center rounded-[5px] border bg-white text-[var(--color-accent)]">
            <Video className="size-4" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-sm font-semibold">视频生成</span>
            <span className="mt-0.5 block text-[10px] text-[var(--color-text-muted)]">
              使用 LTX 2.3 图生视频
            </span>
          </span>
          <Check className="size-4 text-[var(--color-accent)]" />
        </button>
        <button
          aria-disabled="true"
          className="mt-1 flex w-full cursor-not-allowed items-center gap-3 rounded-[6px] px-3 py-3 text-left opacity-45"
          disabled
          type="button"
        >
          <span className="grid size-9 place-items-center rounded-[5px] border bg-white">
            <ImageIcon className="size-4" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="flex items-center gap-2 text-sm font-semibold">
              图像生成
              <span className="rounded-full bg-[var(--color-surface-muted)] px-1.5 py-0.5 text-[8px] font-medium">
                暂未开放
              </span>
            </span>
            <span className="mt-0.5 block text-[10px] text-[var(--color-text-muted)]">
              已预留入口，不接入本轮逻辑
            </span>
          </span>
        </button>
      </PopoverContent>
    </Popover>
  );
}
