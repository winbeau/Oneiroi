import { ArrowRight, ImageIcon, Search, WandSparkles } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { inspirationTemplates } from "@/features/studio/templates";
import { useStudioStore } from "@/store/studio-store";

const categories = ["全部", "团队灵感", "项目模板", "历史案例"] as const;

type Category = (typeof categories)[number];

export function InspirationPage() {
  const navigate = useNavigate();
  const applyTemplate = useStudioStore((state) => state.applyTemplate);
  const [category, setCategory] = useState<Category>("全部");
  const [query, setQuery] = useState("");

  const visibleTemplates = useMemo(
    () =>
      inspirationTemplates.filter((template) => {
        const matchesCategory = category === "全部" || template.category === category;
        const search = query.trim().toLowerCase();
        const matchesSearch =
          !search ||
          template.title.toLowerCase().includes(search) ||
          template.description.toLowerCase().includes(search);
        return matchesCategory && matchesSearch;
      }),
    [category, query],
  );

  const applySelectedTemplate = (template: (typeof inspirationTemplates)[number]) => {
    applyTemplate(template);
    navigate("/create");
  };

  return (
    <main className="mx-auto w-full max-w-6xl px-5 py-8 md:px-8">
      <section className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-sidebar)] px-5 py-7 md:px-8 md:py-9">
        <div className="max-w-2xl">
          <div className="mb-3 flex items-center gap-2 text-sm font-medium text-[var(--color-accent)]">
            <WandSparkles aria-hidden="true" className="size-4" />
            团队灵感库
          </div>
          <h1 className="text-3xl font-semibold tracking-[-0.03em] md:text-4xl">
            从一个清晰想法开始
          </h1>
          <p className="mt-3 max-w-xl leading-7 text-[var(--color-text-muted)]">
            浏览内部整理的镜头模板，直接把参考图、Prompt 和规格带入生成页。这里是创作起点，不是公开社区。
          </p>
        </div>
        <div className="mt-6 flex max-w-xl items-center gap-2 rounded-lg border border-[var(--color-border-strong)] bg-white px-3 py-2">
          <Search aria-hidden="true" className="size-4 text-[var(--color-text-faint)]" />
          <label className="min-w-0 flex-1">
            <span className="sr-only">搜索灵感</span>
            <input
              className="w-full bg-transparent text-sm outline-none placeholder:text-[var(--color-text-faint)]"
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索人物动作、产品镜头或案例"
              value={query}
            />
          </label>
        </div>
      </section>

      <div className="mt-6 flex flex-wrap items-center gap-2" role="tablist" aria-label="灵感分类">
        {categories.map((item) => (
          <button
            aria-selected={category === item}
            className={`rounded-md px-3 py-1.5 text-sm transition ${
              category === item
                ? "bg-[var(--color-text)] text-white"
                : "text-[var(--color-text-muted)] hover:bg-[var(--color-surface-muted)]"
            }`}
            key={item}
            onClick={() => setCategory(item)}
            role="tab"
            type="button"
          >
            {item}
          </button>
        ))}
        <span className="ml-auto text-xs text-[var(--color-text-faint)]">
          {visibleTemplates.length} 个模板
        </span>
      </div>

      <section aria-label="灵感模板列表" className="mt-5 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {visibleTemplates.map((template) => (
          <article
            className="group overflow-hidden rounded-xl border border-[var(--color-border)] bg-white shadow-[var(--shadow-card)]"
            key={template.id}
          >
            <div className="relative aspect-video overflow-hidden bg-[var(--color-preview)]">
              <img
                alt={`${template.title}参考图`}
                className="size-full object-cover transition duration-300 group-hover:scale-[1.02]"
                src={template.previewUrl}
              />
              {template.secondaryPreviewUrl && (
                <div className="absolute bottom-3 right-3 flex size-14 overflow-hidden rounded-md border-2 border-white/80 shadow-lg">
                  <img alt="尾帧缩略图" className="size-full object-cover" src={template.secondaryPreviewUrl} />
                </div>
              )}
            </div>
            <div className="p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-[11px] font-medium text-[var(--color-accent)]">{template.category}</p>
                  <h2 className="mt-1 font-medium">{template.title}</h2>
                </div>
                <ImageIcon aria-hidden="true" className="size-4 shrink-0 text-[var(--color-text-faint)]" />
              </div>
              <p className="mt-2 min-h-12 text-sm leading-6 text-[var(--color-text-muted)]">
                {template.description}
              </p>
              <div className="mt-4 flex items-center gap-2 text-xs text-[var(--color-text-muted)]">
                <span className="rounded bg-[var(--color-surface-muted)] px-2 py-1">{template.settings.ratio}</span>
                <span className="rounded bg-[var(--color-surface-muted)] px-2 py-1">{template.settings.quality}</span>
                <span className="rounded bg-[var(--color-surface-muted)] px-2 py-1">{template.settings.duration} 秒</span>
              </div>
              <Button className="mt-4 w-full" onClick={() => applySelectedTemplate(template)} size="sm" variant="secondary">
                套用到生成
                <ArrowRight aria-hidden="true" className="size-3.5" />
              </Button>
            </div>
          </article>
        ))}
      </section>

      {visibleTemplates.length === 0 && (
        <div className="mt-8 rounded-xl border border-dashed border-[var(--color-border-strong)] px-6 py-14 text-center text-sm text-[var(--color-text-muted)]">
          没有匹配的内部模板，换个关键词试试。
        </div>
      )}
    </main>
  );
}
