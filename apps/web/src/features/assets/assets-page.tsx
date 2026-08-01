import {
  Download,
  Film,
  Grid2X2,
  ImageIcon,
  List,
  Plus,
  RotateCcw,
  Search,
  Trash2,
} from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { AssetPreviewDialog } from "@/features/assets/asset-preview-dialog";
import {
  useAssets,
  useDeleteAsset,
  useUploadImage,
} from "@/features/studio/hooks";
import { inspirationTemplates } from "@/features/studio/templates";
import type { AssetType, StudioAsset } from "@/features/studio/types";
import { apiUrl } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import { defaultDraft, useStudioStore } from "@/store/studio-store";

const filters: Array<{ label: string; type: AssetType | "all" }> = [
  { label: "全部", type: "all" },
  { label: "参考图片", type: "image" },
  { label: "生成视频", type: "video" },
  { label: "收藏模板", type: "template" },
];

const templates: StudioAsset[] = inspirationTemplates.map((template) => ({
  id: `template-${template.id}`,
  type: "template",
  title: template.title,
  createdAt: new Date(0).toISOString(),
  mediaType: "image/png",
  sizeBytes: 0,
  previewUrl: template.previewUrl,
  draft: {
    ...defaultDraft,
    ...template.settings,
    prompt: template.prompt,
    queue: template.settings.quality === "高质量" ? "hq" : "fast",
    profile: template.settings.quality === "高质量" ? "hq" : "fast",
  },
}));

export function AssetsPage() {
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const assetsQuery = useAssets();
  const upload = useUploadImage();
  const remove = useDeleteAsset();
  const updateDraft = useStudioStore((state) => state.updateDraft);
  const assetView = useStudioStore((state) => state.assetView);
  const setAssetView = useStudioStore((state) => state.setAssetView);
  const [filter, setFilter] = useState<AssetType | "all">("all");
  const [query, setQuery] = useState("");
  const [selectedAsset, setSelectedAsset] = useState<StudioAsset | null>(null);

  const visibleAssets = useMemo(
    () =>
      [...(assetsQuery.data ?? []), ...templates].filter((asset) => {
        const matchesType = filter === "all" || asset.type === filter;
        return (
          matchesType && asset.title.toLowerCase().includes(query.trim().toLowerCase())
        );
      }),
    [assetsQuery.data, filter, query],
  );

  const reuse = (asset: StudioAsset) => {
    if (asset.draft) updateDraft(asset.draft);
    else
      updateDraft({
        firstFrame: {
          name: asset.title,
          url: asset.previewUrl,
          assetId: asset.id,
        },
      });
    navigate("/create");
  };

  return (
    <main className="mx-auto w-full max-w-[1240px] px-4 pb-16 pt-7 md:px-7 md:pt-10">
      <header className="flex flex-col gap-5 border-b border-[var(--color-border)] pb-7 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--color-accent)]">
            PRIVATE LIBRARY
          </p>
          <h1 className="font-display mt-2 text-[40px] font-semibold">资产</h1>
          <p className="mt-3 text-sm text-[var(--color-text-muted)]">
            服务端保存参考图、真实 MP4 和授权下载入口。
          </p>
        </div>
        <Button onClick={() => inputRef.current?.click()} variant="primary">
          <Plus className="size-4" /> 上传素材
        </Button>
        <input
          ref={inputRef}
          accept="image/png,image/jpeg,image/webp"
          className="sr-only"
          onChange={async (event) => {
            const file = event.target.files?.[0];
            if (file) await upload.mutateAsync({ file, title: file.name });
            event.target.value = "";
          }}
          type="file"
        />
      </header>

      <div className="sticky top-[60px] z-30 mt-4 flex flex-wrap items-center gap-2 bg-[var(--color-canvas)]/88 py-3 backdrop-blur-xl">
        {filters.map((item) => (
          <button
            className={cn(
              "rounded-md px-3 py-1.5 text-sm",
              filter === item.type ? "bg-white shadow-[var(--shadow-card)]" : "text-[var(--color-text-muted)]",
            )}
            key={item.type}
            onClick={() => setFilter(item.type)}
            type="button"
          >
            {item.label}
          </button>
        ))}
        <label className="ml-auto flex h-9 items-center gap-2 rounded-lg border bg-white/65 px-2.5">
          <Search className="size-3.5" />
          <span className="sr-only">搜索资产</span>
          <input
            className="bg-transparent outline-none"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索资产"
            value={query}
          />
        </label>
        <Button
          aria-label={assetView === "grid" ? "列表视图" : "网格视图"}
          onClick={() => setAssetView(assetView === "grid" ? "list" : "grid")}
          size="icon"
          variant="ghost"
        >
          {assetView === "grid" ? <List className="size-4" /> : <Grid2X2 className="size-4" />}
        </Button>
      </div>

      {assetsQuery.isError && (
        <p className="mt-5 text-sm text-[var(--color-danger)]">无法读取服务端资产。</p>
      )}
      {visibleAssets.length === 0 ? (
        <section className="mt-8 rounded-[20px] border border-dashed p-16 text-center">
          <ImageIcon className="mx-auto size-6" />
          <h2 className="font-display mt-4 text-xl font-semibold">没有匹配的资产</h2>
        </section>
      ) : (
        <section
          aria-label="资产列表"
          className={cn(
            "mt-5",
            assetView === "grid"
              ? "grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4"
              : "space-y-2",
          )}
        >
          {visibleAssets.map((asset) => {
            const preview = apiUrl(asset.previewUrl);
            return (
              <article
                className={cn(
                  "group overflow-hidden rounded-[16px] border bg-white shadow-[var(--shadow-card)]",
                  assetView === "list" && "flex items-center p-2",
                )}
                key={asset.id}
              >
                <button
                  aria-label={`预览 ${asset.title}`}
                  className={cn(
                    "relative block overflow-hidden bg-[var(--color-preview)]",
                    assetView === "grid" ? "aspect-video w-full" : "h-20 w-32",
                  )}
                  onClick={() => setSelectedAsset(asset)}
                  type="button"
                >
                  {asset.type === "video" ? (
                    <video className="size-full object-cover" muted preload="metadata" src={preview} />
                  ) : (
                    <img alt={asset.title} className="size-full object-cover" src={preview} />
                  )}
                  <span className="absolute left-2 top-2 rounded-full bg-white/80 px-2 py-1 text-[9px]">
                    {asset.type === "video" ? <Film className="inline size-3" /> : null} {asset.type}
                  </span>
                </button>
                <div className="min-w-0 flex-1 p-3">
                  <h2 className="truncate text-sm font-semibold">{asset.title}</h2>
                  <div className="mt-3 flex gap-1">
                    <Button aria-label={`复用 ${asset.title}`} onClick={() => reuse(asset)} size="icon" variant="ghost">
                      <RotateCcw className="size-3.5" />
                    </Button>
                    <Button asChild size="icon" variant="ghost">
                      <a aria-label={`下载 ${asset.title}`} href={preview}>
                        <Download className="size-3.5" />
                      </a>
                    </Button>
                    {asset.type !== "template" && (
                      <Button
                        aria-label={`删除 ${asset.title}`}
                        onClick={() => remove.mutate(asset.id)}
                        size="icon"
                        variant="ghost"
                      >
                        <Trash2 className="size-3.5" />
                      </Button>
                    )}
                  </div>
                </div>
              </article>
            );
          })}
        </section>
      )}

      <AssetPreviewDialog
        asset={selectedAsset}
        assets={visibleAssets}
        onOpenChange={(open) => !open && setSelectedAsset(null)}
        onReuse={reuse}
        onSelect={setSelectedAsset}
      />
    </main>
  );
}
