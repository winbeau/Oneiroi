import { ChevronLeft, ChevronRight, Download, RotateCcw } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import type { StudioAsset } from "@/features/studio/types";

const formatDate = (value: string) =>
  new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));

export function AssetPreviewDialog({
  asset,
  assets,
  onOpenChange,
  onSelect,
  onReuse,
}: {
  asset: StudioAsset | null;
  assets: StudioAsset[];
  onOpenChange: (open: boolean) => void;
  onSelect: (asset: StudioAsset) => void;
  onReuse: (asset: StudioAsset) => void;
}) {
  const index = asset ? assets.findIndex((item) => item.id === asset.id) : -1;
  const previous = index > 0 ? assets[index - 1] : null;
  const next = index >= 0 && index < assets.length - 1 ? assets[index + 1] : null;

  return (
    <Dialog onOpenChange={onOpenChange} open={Boolean(asset)}>
      {asset && (
        <DialogContent className="grid max-h-[90vh] grid-rows-[minmax(0,1fr)_auto] lg:grid-cols-[minmax(0,1.55fr)_340px] lg:grid-rows-1">
          <div className="relative grid min-h-[320px] place-items-center overflow-hidden bg-[var(--color-preview)] lg:min-h-[620px]">
            <img
              alt={asset.title}
              className="max-h-[72vh] max-w-full object-contain"
              src={asset.previewUrl}
            />
            {previous && (
              <button
                aria-label="上一个资产"
                className="absolute left-3 top-1/2 grid size-10 -translate-y-1/2 place-items-center rounded-full bg-black/38 text-white backdrop-blur-md transition hover:bg-black/55 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
                onClick={() => onSelect(previous)}
                type="button"
              >
                <ChevronLeft aria-hidden="true" className="size-5" />
              </button>
            )}
            {next && (
              <button
                aria-label="下一个资产"
                className="absolute right-3 top-1/2 grid size-10 -translate-y-1/2 place-items-center rounded-full bg-black/38 text-white backdrop-blur-md transition hover:bg-black/55 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
                onClick={() => onSelect(next)}
                type="button"
              >
                <ChevronRight aria-hidden="true" className="size-5" />
              </button>
            )}
          </div>
          <div className="scrollbar-notion overflow-y-auto p-5 lg:p-6">
            <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[var(--color-accent)]">
              {asset.type} asset
            </p>
            <DialogTitle className="font-display mt-2 text-2xl font-semibold leading-tight tracking-[-0.02em]">
              {asset.title}
            </DialogTitle>
            <DialogDescription className="mt-2 text-sm text-[var(--color-text-muted)]">
              {formatDate(asset.createdAt)}
            </DialogDescription>

            {asset.draft && (
              <div className="mt-5 rounded-[var(--radius-lg)] bg-[var(--color-surface-muted)] p-4">
                <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-[var(--color-text-faint)]">
                  Generation settings
                </p>
                <dl className="mt-3 grid grid-cols-2 gap-3 text-xs">
                  <div>
                    <dt className="text-[var(--color-text-faint)]">质量</dt>
                    <dd className="mt-1 font-medium">{asset.draft.quality}</dd>
                  </div>
                  <div>
                    <dt className="text-[var(--color-text-faint)]">规格</dt>
                    <dd className="mt-1 font-medium">
                      {asset.draft.resolution} · {asset.draft.ratio}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[var(--color-text-faint)]">时长</dt>
                    <dd className="mt-1 font-medium">{asset.draft.duration} 秒</dd>
                  </div>
                  <div>
                    <dt className="text-[var(--color-text-faint)]">Seed</dt>
                    <dd className="font-mono mt-1 font-medium">{asset.draft.seed}</dd>
                  </div>
                </dl>
                <p className="mt-4 line-clamp-6 border-t border-[var(--color-border)] pt-3 text-xs leading-5 text-[var(--color-text-muted)]">
                  {asset.draft.prompt}
                </p>
              </div>
            )}

            <div className="mt-6 flex flex-wrap gap-2">
              <Button onClick={() => onReuse(asset)} variant="primary">
                <RotateCcw aria-hidden="true" className="size-4" />
                复用到生成
              </Button>
              <Button asChild variant="secondary">
                <a download={asset.title} href={asset.previewUrl}>
                  <Download aria-hidden="true" className="size-4" />
                  下载
                </a>
              </Button>
            </div>
          </div>
        </DialogContent>
      )}
    </Dialog>
  );
}
