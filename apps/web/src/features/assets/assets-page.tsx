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
import { useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
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
    <main className="mx-auto w-full max-w-6xl px-5 py-8 md:px-8">
      <div className="flex flex-wrap items-end justify-between gap-4 border-b border-[var(--color-border)] pb-5">
        <div>
          <h1 className="text-2xl font-semibold tracking-[-0.025em]">资产</h1>
          <p className="mt-2 text-sm text-[var(--color-text-muted)]">
            管理私有参考图片、生成视频与可复用参数。
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
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-2">
        <ListFilter aria-hidden="true" className="mr-1 size-4 text-[var(--color-text-faint)]" />
        {filters.map((item) => (
          <button
            aria-pressed={filter === item.type}
            className={
              filter === item.type
                ? "rounded-md bg-[var(--color-text)] px-3 py-1.5 text-sm text-white"
                : "rounded-md px-3 py-1.5 text-sm text-[var(--color-text-muted)] hover:bg-[var(--color-surface-muted)]"
            }
            key={item.type}
            onClick={() => setFilter(item.type)}
            type="button"
          >
            {item.label}
          </button>
        ))}

        <label className="ml-auto flex h-9 min-w-48 items-center gap-2 rounded-md border border-[var(--color-border)] px-2 text-sm text-[var(--color-text-muted)] focus-within:border-[var(--color-border-strong)]">
          <Search aria-hidden="true" className="size-4" />
          <span className="sr-only">搜索资产</span>
          <input
            className="min-w-0 flex-1 bg-transparent outline-none placeholder:text-[var(--color-text-faint)]"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索资产"
            value={query}
          />
        </label>
        <div className="flex rounded-md border border-[var(--color-border)] p-0.5">
          <button
            aria-label="网格视图"
            aria-pressed={assetView === "grid"}
            className={cn(
              "grid size-7 place-items-center rounded",
              assetView === "grid" ? "bg-[var(--color-surface-muted)]" : "text-[var(--color-text-faint)]",
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
              "grid size-7 place-items-center rounded",
              assetView === "list" ? "bg-[var(--color-surface-muted)]" : "text-[var(--color-text-faint)]",
            )}
            onClick={() => setAssetView("list")}
            type="button"
          >
            <List aria-hidden="true" className="size-3.5" />
          </button>
        </div>
      </div>

      {visibleAssets.length === 0 ? (
        <section className="mt-10 rounded-lg border border-dashed border-[var(--color-border-strong)] bg-white px-6 py-16 text-center">
          <div className="mx-auto flex w-fit items-center gap-2 text-[var(--color-text-faint)]">
            <ImageIcon aria-hidden="true" className="size-6" />
            <Film aria-hidden="true" className="size-6" />
            <Download aria-hidden="true" className="size-6" />
          </div>
          <h2 className="mt-4 font-medium">没有匹配的资产</h2>
          <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-[var(--color-text-muted)]">
            上传参考图片或完成一次生成后，归属、时间、类型和操作会显示在这里。
          </p>
        </section>
      ) : (
        <section
          aria-label="资产列表"
          className={cn(
            "mt-6",
            assetView === "grid" ? "grid gap-4 sm:grid-cols-2 lg:grid-cols-3" : "space-y-2",
          )}
        >
          {visibleAssets.map((asset) => (
            <article
              className={cn(
                "group overflow-hidden rounded-xl border border-[var(--color-border)] bg-white shadow-[var(--shadow-card)]",
                assetView === "list" && "flex items-center p-2",
              )}
              key={asset.id}
            >
              <div
                className={cn(
                  "relative overflow-hidden bg-[var(--color-preview)]",
                  assetView === "grid" ? "aspect-video" : "h-20 w-32 shrink-0 rounded-lg",
                )}
              >
                <img alt={asset.title} className="size-full object-cover" src={asset.previewUrl} />
                <span className="absolute left-2 top-2 rounded bg-black/55 px-1.5 py-0.5 text-[10px] text-white">
                  {typeLabel[asset.type]}
                </span>
              </div>
              <div className={cn("min-w-0 p-4", assetView === "list" && "flex flex-1 items-center gap-4 py-2")}>
                <div className="min-w-0 flex-1">
                  <h2 className="truncate text-sm font-medium">{asset.title}</h2>
                  <p className="mt-1 text-xs text-[var(--color-text-faint)]">{formatDate(asset.createdAt)}</p>
                  {asset.draft && (
                    <p className="mt-2 truncate text-xs text-[var(--color-text-muted)]">
                      {asset.draft.quality} · {asset.draft.resolution} · {asset.draft.duration} 秒
                    </p>
                  )}
                </div>
                <div className={cn("mt-3 flex gap-1", assetView === "list" && "mt-0")}>
                  <Button onClick={() => reuse(asset)} size="sm" variant="ghost">
                    <RotateCcw aria-hidden="true" className="size-3.5" />
                    <span className={assetView === "grid" ? "" : "sr-only"}>复用</span>
                  </Button>
                  {asset.type === "image" && (
                    <Button asChild size="sm" variant="ghost">
                      <a download={asset.title} href={asset.previewUrl}>
                        <Download aria-hidden="true" className="size-3.5" />
                        <span className="sr-only">下载</span>
                      </a>
                    </Button>
                  )}
                  <Button onClick={() => deleteAsset(asset.id)} size="sm" variant="ghost">
                    <Trash2 aria-hidden="true" className="size-3.5" />
                    <span className="sr-only">删除</span>
                  </Button>
                </div>
              </div>
            </article>
          ))}
        </section>
      )}
    </main>
  );
}
