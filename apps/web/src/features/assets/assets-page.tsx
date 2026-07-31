import { Download, Film, ImageIcon, ListFilter, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";

const filters = ["全部", "参考图片", "生成视频", "收藏模板"];

export function AssetsPage() {
  return (
    <main className="mx-auto w-full max-w-6xl px-5 py-8 md:px-8">
      <div className="flex flex-wrap items-end justify-between gap-4 border-b border-[var(--color-border)] pb-5">
        <div>
          <h1 className="text-2xl font-semibold tracking-[-0.025em]">资产</h1>
          <p className="mt-2 text-sm text-[var(--color-text-muted)]">
            管理私有参考图片、生成视频与可复用参数。
          </p>
        </div>
        <Button variant="primary">
          <Plus aria-hidden="true" className="size-4" />
          上传素材
        </Button>
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-2">
        <ListFilter aria-hidden="true" className="mr-1 size-4 text-[var(--color-text-faint)]" />
        {filters.map((filter, index) => (
          <button
            className={
              index === 0
                ? "rounded-md bg-[var(--color-text)] px-3 py-1.5 text-sm text-white"
                : "rounded-md px-3 py-1.5 text-sm text-[var(--color-text-muted)] hover:bg-[var(--color-surface-muted)]"
            }
            key={filter}
            type="button"
          >
            {filter}
          </button>
        ))}
      </div>

      <section className="mt-10 rounded-lg border border-dashed border-[var(--color-border-strong)] bg-white px-6 py-16 text-center">
        <div className="mx-auto flex w-fit items-center gap-2 text-[var(--color-text-faint)]">
          <ImageIcon aria-hidden="true" className="size-6" />
          <Film aria-hidden="true" className="size-6" />
          <Download aria-hidden="true" className="size-6" />
        </div>
        <h2 className="mt-4 font-medium">还没有资产</h2>
        <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-[var(--color-text-muted)]">
          上传第一张参考图片或完成一次生成后，归属、时间、类型和下载操作会显示在这里。
        </p>
      </section>
    </main>
  );
}
