import {
  Download,
  Film,
  Grid2X2,
  ImageIcon,
  List,
  ListFilter,
  Plus,
  RotateCcw,
  Search,
  Trash2,
} from "lucide-react";
import { AnimatePresence, LayoutGroup, motion } from "motion/react";
import { useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { AssetPreviewDialog } from "@/features/assets/asset-preview-dialog";
import type { AssetType, StudioAsset } from "@/features/studio/types";
import { cn } from "@/lib/utils";
import { useStudioStore } from "@/store/studio-store";

const filters: Array<{ label: string; type: AssetType | "all" }> = [
  { label: "全部", type: "all" },
  { label: "参考图片", type: "image" },
  { label: "生成视频", type: "video" },
  { label: "收藏模板", type: "template" },
];

const typeLabel: Record<AssetType, string> = {
  image: "参考图片",
  video: "生成视频",
  template: "创作模板",
};

const fileToAsset = (file: File): Promise<StudioAsset> =>
  new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => {
      if (typeof reader.result !== "string") {
        reject(new Error("无法读取文件"));
        return;
      }
      resolve({
        id: `asset-upload-${Date.now().toString(36)}`,
        type: "image",
        title: file.name,
        createdAt: new Date().toISOString(),
        previewUrl: reader.result,
      });
    });
    reader.addEventListener("error", () => reject(reader.error));
    reader.readAsDataURL(file);
  });

const formatDate = (value: string) =>
  new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));

export function AssetsPage() {
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const assets = useStudioStore((state) => state.assets);
  const addAsset = useStudioStore((state) => state.addAsset);
  const deleteAsset = useStudioStore((state) => state.deleteAsset);
  const updateDraft = useStudioStore((state) => state.updateDraft);
  const assetView = useStudioStore((state) => state.assetView);
  const setAssetView = useStudioStore((state) => state.setAssetView);
  const [filter, setFilter] = useState<AssetType | "all">("all");
  const [query, setQuery] = useState("");
  const [selectedAsset, setSelectedAsset] = useState<StudioAsset | null>(null);

  const visibleAssets = useMemo(
    () =>
      assets.filter((asset) => {
        const matchesType = filter === "all" || asset.type === filter;
        const matchesQuery = asset.title
          .toLowerCase()
          .includes(query.trim().toLowerCase());
        return matchesType && matchesQuery;
      }),
    [assets, filter, query],
  );

  const reuse = (asset: StudioAsset) => {
    if (asset.draft) updateDraft(asset.draft);
    else
      updateDraft({
        firstFrame: { name: asset.title, url: asset.previewUrl },
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
          <h1 className="font-display mt-2 text-[36px] font-semibold leading-none tracking-[-0.035em] md:text-[46px]">
            资产
          </h1>
          <p className="mt-3 max-w-xl text-sm leading-6 text-[var(--color-text-muted)]">
            保存参考图片、生成结果与可复用参数。每个作品都可以回到创作器继续生长。
          </p>
        </div>
        <Button onClick={() => inputRef.current?.click()} variant="primary">
          <Plus aria-hidden="true" className="size-4" />
          上传素材
        </Button>
        <input
          ref={inputRef}
          accept="image/*"
          className="sr-only"
          onChange={async (event) => {
            const file = event.target.files?.[0];
            if (file) addAsset(await fileToAsset(file));
            event.target.value = "";
          }}
          type="file"
        />
      </header>

      <div className="sticky top-[60px] z-30 -mx-2 mt-4 flex flex-wrap items-center gap-2 rounded-b-xl bg-[var(--color-canvas)]/88 px-2 py-3 backdrop-blur-xl">
        <ListFilter aria-hidden="true" className="mr-1 size-3.5 text-[var(--color-text-faint)]" />
        <LayoutGroup id="asset-filters">
          <div className="hide-scrollbar flex min-w-0 gap-1 overflow-x-auto">
            {filters.map((item) => (
              <button
                aria-pressed={filter === item.type}
                className={cn(
                  "relative isolate shrink-0 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                  filter === item.type
                    ? "text-[var(--color-text)]"
                    : "text-[var(--color-text-muted)] hover:text-[var(--color-text)]",
                )}
                key={item.type}
                onClick={() => setFilter(item.type)}
                type="button"
              >
                {filter === item.type && (
                  <motion.span
                    aria-hidden="true"
                    className="absolute inset-0 -z-10 rounded-md bg-white shadow-[var(--shadow-card)] ring-1 ring-[var(--color-border)]"
                    layoutId="asset-filter-pill"
                    transition={{ duration: 0.28, ease: [0.2, 0.8, 0.2, 1] }}
                  />
                )}
                {item.label}
              </button>
            ))}
          </div>
        </LayoutGroup>

        <label className="order-last flex h-9 min-w-full items-center gap-2 rounded-lg border border-[var(--color-border)] bg-white/65 px-2.5 text-sm text-[var(--color-text-muted)] transition focus-within:border-[var(--color-accent)]/35 focus-within:bg-white sm:order-none sm:ml-auto sm:min-w-48 sm:max-w-64">
          <Search aria-hidden="true" className="size-3.5" />
          <span className="sr-only">搜索资产</span>
          <input
            className="min-w-0 flex-1 bg-transparent outline-none placeholder:text-[var(--color-text-faint)]"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索资产"
            value={query}
          />
        </label>
        <div className="flex rounded-lg border border-[var(--color-border)] bg-white/60 p-0.5">
          <button
            aria-label="网格视图"
            aria-pressed={assetView === "grid"}
            className={cn(
              "grid size-7 place-items-center rounded-md transition",
              assetView === "grid"
                ? "bg-white text-[var(--color-text)] shadow-[var(--shadow-card)]"
                : "text-[var(--color-text-faint)] hover:text-[var(--color-text)]",
            )}
            onClick={() => setAssetView("grid")}
            type="button"
          >
            <Grid2X2 aria-hidden="true" className="size-3.5" />
          </button>
          <button
            aria-label="列表视图"
            aria-pressed={assetView === "list"}
            className={cn(
              "grid size-7 place-items-center rounded-md transition",
              assetView === "list"
                ? "bg-white text-[var(--color-text)] shadow-[var(--shadow-card)]"
                : "text-[var(--color-text-faint)] hover:text-[var(--color-text)]",
            )}
            onClick={() => setAssetView("list")}
            type="button"
          >
            <List aria-hidden="true" className="size-3.5" />
          </button>
        </div>
      </div>

      {visibleAssets.length === 0 ? (
        <motion.section
          animate={{ opacity: 1, y: 0 }}
          className="paper-texture mt-8 rounded-[20px] border border-dashed border-[var(--color-border-strong)] bg-white/55 px-6 py-20 text-center"
          initial={{ opacity: 0, y: 10 }}
        >
          <div className="mx-auto flex w-fit items-center gap-2 text-[var(--color-text-faint)]">
            <ImageIcon aria-hidden="true" className="size-6" />
            <Film aria-hidden="true" className="size-6" />
            <Download aria-hidden="true" className="size-6" />
          </div>
          <h2 className="font-display mt-4 text-xl font-semibold">没有匹配的资产</h2>
          <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-[var(--color-text-muted)]">
            上传参考图片或完成一次生成后，作品、参数和复用入口会出现在这里。
          </p>
          {(query || filter !== "all") && (
            <Button
              className="mt-4"
              onClick={() => {
                setQuery("");
                setFilter("all");
              }}
              size="sm"
              variant="secondary"
            >
              清除筛选
            </Button>
          )}
        </motion.section>
      ) : (
        <motion.section
          aria-label="资产列表"
          className={cn(
            "mt-5",
            assetView === "grid"
              ? "grid items-start gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4"
              : "space-y-2",
          )}
          layout
        >
          <AnimatePresence mode="popLayout">
            {visibleAssets.map((asset) => (
              <motion.article
                animate={{ opacity: 1, scale: 1 }}
                className={cn(
                  "group overflow-hidden rounded-[16px] border border-[var(--color-border)] bg-white shadow-[var(--shadow-card)] transition-[border-color,box-shadow] hover:border-[var(--color-border-strong)] hover:shadow-[0_18px_46px_rgba(48,46,42,0.09)]",
                  assetView === "list" && "flex items-center p-2",
                )}
                exit={{ opacity: 0, scale: 0.97 }}
                initial={{ opacity: 0, scale: 0.98 }}
                key={asset.id}
                layout
                transition={{ duration: 0.32, ease: [0.2, 0.8, 0.2, 1] }}
              >
                <button
                  aria-label={`预览 ${asset.title}`}
                  className={cn(
                    "relative block overflow-hidden bg-[var(--color-preview)] outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--color-accent)]",
                    assetView === "grid"
                      ? asset.type === "video"
                        ? "aspect-video w-full"
                        : "aspect-[4/3] w-full"
                      : "h-20 w-32 shrink-0 rounded-[10px]",
                  )}
                  onClick={() => setSelectedAsset(asset)}
                  type="button"
                >
                  <img
                    alt={asset.title}
                    className="size-full object-cover transition-transform duration-700 ease-[var(--ease-out-expo)] group-hover:scale-[1.03]"
                    src={asset.previewUrl}
                  />
                  <div className="absolute inset-0 bg-gradient-to-t from-black/58 via-transparent to-transparent opacity-70 transition group-hover:opacity-95" />
                  <span className="absolute left-2.5 top-2.5 rounded-full bg-white/82 px-2 py-1 text-[9px] font-semibold text-[var(--color-text)] backdrop-blur-md">
                    {typeLabel[asset.type]}
                  </span>
                  {assetView === "grid" && (
                    <span className="absolute bottom-3 left-3 translate-y-2 text-[11px] font-medium text-white/90 opacity-0 transition duration-300 group-hover:translate-y-0 group-hover:opacity-100">
                      点击查看作品
                    </span>
                  )}
                </button>
                <div
                  className={cn(
                    "min-w-0 p-3.5",
                    assetView === "list" && "flex flex-1 items-center gap-4 py-2",
                  )}
                >
                  <div className="min-w-0 flex-1">
                    <h2 className="truncate text-sm font-semibold">{asset.title}</h2>
                    <p className="mt-1 text-[10px] text-[var(--color-text-faint)]">
                      {formatDate(asset.createdAt)}
                    </p>
                    {asset.draft && (
                      <p className="mt-2 truncate text-[11px] text-[var(--color-text-muted)]">
                        {asset.draft.quality} · {asset.draft.resolution} · {asset.draft.duration} 秒
                      </p>
                    )}
                  </div>
                  <div
                    className={cn(
                      "mt-3 flex gap-1 transition-opacity",
                      assetView === "list" ? "mt-0" : "lg:opacity-0 lg:group-hover:opacity-100 lg:group-focus-within:opacity-100",
                    )}
                  >
                    <Button
                      aria-label={`复用 ${asset.title}`}
                      onClick={() => reuse(asset)}
                      size="icon"
                      variant="ghost"
                    >
                      <RotateCcw aria-hidden="true" className="size-3.5" />
                    </Button>
                    <Button asChild size="icon" variant="ghost">
                      <a aria-label={`下载 ${asset.title}`} download={asset.title} href={asset.previewUrl}>
                        <Download aria-hidden="true" className="size-3.5" />
                      </a>
                    </Button>
                    <Button
                      aria-label={`删除 ${asset.title}`}
                      onClick={() => {
                        deleteAsset(asset.id);
                        if (selectedAsset?.id === asset.id) setSelectedAsset(null);
                      }}
                      size="icon"
                      variant="ghost"
                    >
                      <Trash2 aria-hidden="true" className="size-3.5" />
                    </Button>
                  </div>
                </div>
              </motion.article>
            ))}
          </AnimatePresence>
        </motion.section>
      )}

      <AssetPreviewDialog
        asset={selectedAsset}
        assets={visibleAssets}
        onOpenChange={(open) => {
          if (!open) setSelectedAsset(null);
        }}
        onReuse={reuse}
        onSelect={setSelectedAsset}
      />
    </main>
  );
}
