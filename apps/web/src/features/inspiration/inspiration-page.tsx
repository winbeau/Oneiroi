import { ArrowRight, ImageIcon, Search, Sparkles, WandSparkles } from "lucide-react";
import { AnimatePresence, LayoutGroup, motion } from "motion/react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Reveal } from "@/components/motion/reveal";
import { Button } from "@/components/ui/button";
import { inspirationTemplates } from "@/features/studio/templates";
import { cn } from "@/lib/utils";
import { useStudioStore } from "@/store/studio-store";

const categories = ["全部", "团队灵感", "项目模板", "历史案例"] as const;

type Category = (typeof categories)[number];

const skyCityTemplate = inspirationTemplates.find((template) => template.id === "sky-city");
const roommateTemplate = inspirationTemplates.find(
  (template) => template.id === "roommate-romance-poster",
);

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
    <main className="mx-auto w-full max-w-[1240px] px-4 pb-16 pt-5 md:px-7 md:pt-8">
      <section className="paper-texture relative overflow-hidden rounded-[14px] border border-[var(--color-border)] bg-[var(--color-paper)] px-5 py-7 shadow-[var(--shadow-card)] md:px-9 md:py-10 lg:grid lg:min-h-[360px] lg:grid-cols-[minmax(0,1fr)_430px] lg:items-center lg:gap-10">
        <div aria-hidden="true" className="dream-grid pointer-events-none absolute inset-0 opacity-55" />
        <div className="relative z-10 max-w-2xl">
          <motion.div
            animate={{ opacity: 1, y: 0 }}
            className="flex items-center gap-2 text-xs font-semibold tracking-[0.08em] text-[var(--color-accent)]"
            initial={{ opacity: 0, y: 8 }}
            transition={{ duration: 0.4, delay: 0.05, ease: [0.2, 0.8, 0.2, 1] }}
          >
            <WandSparkles aria-hidden="true" className="size-4" />
            ONEIROI INSPIRATION
          </motion.div>
          <motion.h1
            animate={{ opacity: 1, y: 0 }}
            className="font-display mt-3 text-[34px] font-semibold leading-[1.14] tracking-[-0.035em] md:text-[48px] lg:text-[54px]"
            initial={{ opacity: 0, y: 12 }}
            transition={{ duration: 0.55, delay: 0.12, ease: [0.2, 0.8, 0.2, 1] }}
          >
            从一个清晰想法开始
          </motion.h1>
          <motion.p
            animate={{ opacity: 1, y: 0 }}
            className="mt-4 max-w-xl text-sm leading-7 text-[var(--color-text-muted)] md:text-[15px]"
            initial={{ opacity: 0, y: 10 }}
            transition={{ duration: 0.52, delay: 0.2, ease: [0.2, 0.8, 0.2, 1] }}
          >
            让灵感先成为画面，让每一次想象都通往更动人的下一帧。
          </motion.p>
          <motion.label
            animate={{ opacity: 1, y: 0 }}
            className="mt-6 flex h-12 max-w-xl items-center gap-3 rounded-xl border border-[var(--color-border-strong)] bg-white/88 px-3.5 shadow-[0_10px_28px_rgba(48,46,42,0.06)] transition focus-within:border-[var(--color-accent)]/45 focus-within:shadow-[0_14px_36px_rgba(75,68,136,0.10)]"
            initial={{ opacity: 0, y: 10 }}
            transition={{ duration: 0.5, delay: 0.28, ease: [0.2, 0.8, 0.2, 1] }}
          >
            <Search aria-hidden="true" className="size-4 text-[var(--color-text-faint)]" />
            <span className="sr-only">搜索灵感</span>
            <input
              className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-[var(--color-text-faint)]"
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索人物动作、产品镜头或案例"
              value={query}
            />
            {query && (
              <button
                className="rounded px-1.5 py-1 text-[10px] text-[var(--color-text-faint)] transition hover:bg-[var(--color-surface-muted)] hover:text-[var(--color-text)]"
                onClick={() => setQuery("")}
                type="button"
              >
                清除
              </button>
            )}
          </motion.label>
        </div>

        <div className="relative z-10 mx-auto mt-8 hidden h-[270px] w-full max-w-[430px] lg:block">
          <motion.div
            animate={{ opacity: 1, x: 0, rotate: -4 }}
            className="absolute left-0 top-7 aspect-[4/3] w-[62%] overflow-hidden rounded-[12px] border-4 border-white bg-[var(--color-preview)] shadow-[0_18px_44px_rgba(48,46,42,0.15)]"
            initial={{ opacity: 0, x: 24, rotate: -8 }}
            transition={{ duration: 0.65, delay: 0.25, ease: [0.2, 0.8, 0.2, 1] }}
          >
            <img
              alt="天空之城历史案例"
              className="size-full object-cover"
              src={skyCityTemplate?.previewUrl}
            />
            <span className="absolute bottom-3 left-3 rounded-full bg-black/45 px-2.5 py-1 text-[10px] text-white backdrop-blur">
              天空之城
            </span>
          </motion.div>
          <motion.div
            animate={{ opacity: 1, x: 0, rotate: 5 }}
            className="absolute bottom-0 right-1 aspect-[3/4] w-[48%] overflow-hidden rounded-[12px] border-4 border-white bg-[var(--color-preview)] shadow-[0_18px_44px_rgba(48,46,42,0.15)]"
            initial={{ opacity: 0, x: 28, rotate: 9 }}
            transition={{ duration: 0.65, delay: 0.36, ease: [0.2, 0.8, 0.2, 1] }}
          >
            <img
              alt="合租舍友暖心片段历史案例"
              className="size-full object-cover object-top"
              src={roommateTemplate?.previewUrl}
            />
            <span className="absolute bottom-3 right-3 rounded-full bg-black/45 px-2.5 py-1 text-[10px] text-white backdrop-blur">
              合租舍友
            </span>
          </motion.div>
          <motion.span
            animate={{ opacity: 1, scale: 1 }}
            className="dream-orbit absolute left-1/2 top-1/2 grid size-12 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full border border-white/70 bg-white/82 text-[var(--color-accent)] shadow-[0_14px_34px_rgba(48,46,42,0.14)] backdrop-blur-xl"
            initial={{ opacity: 0, scale: 0.75 }}
            transition={{ duration: 0.45, delay: 0.62, ease: [0.2, 0.8, 0.2, 1] }}
          >
            <Sparkles aria-hidden="true" className="size-5" />
          </motion.span>
        </div>
      </section>

      <div className="sticky top-[60px] z-30 -mx-2 mt-5 flex items-center gap-3 bg-[var(--color-canvas)]/88 px-2 py-3 backdrop-blur-xl">
        <LayoutGroup id="inspiration-categories">
          <div
            aria-label="灵感分类"
            className="hide-scrollbar flex min-w-0 flex-1 gap-1 overflow-x-auto"
            role="tablist"
          >
            {categories.map((item) => (
              <button
                aria-selected={category === item}
                className={cn(
                  "relative isolate shrink-0 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                  category === item
                    ? "text-[var(--color-text)]"
                    : "text-[var(--color-text-muted)] hover:text-[var(--color-text)]",
                )}
                key={item}
                onClick={() => setCategory(item)}
                role="tab"
                type="button"
              >
                {category === item && (
                  <motion.span
                    aria-hidden="true"
                    className="absolute inset-0 -z-10 rounded-md bg-white shadow-[var(--shadow-card)] ring-1 ring-[var(--color-border)]"
                    layoutId="inspiration-category-pill"
                    transition={{ duration: 0.28, ease: [0.2, 0.8, 0.2, 1] }}
                  />
                )}
                {item}
              </button>
            ))}
          </div>
        </LayoutGroup>
        <span className="shrink-0 text-[11px] text-[var(--color-text-faint)]">
          {visibleTemplates.length} 个模板
        </span>
      </div>

      <motion.section
        aria-label="灵感模板列表"
        className="mt-2 columns-1 gap-4 md:columns-2 xl:columns-3"
        layout
      >
        <AnimatePresence mode="popLayout">
          {visibleTemplates.map((template, index) => (
              <Reveal
                className="mb-4 inline-block w-full break-inside-avoid align-top"
                delay={index * 0.07}
                key={template.id}
              >
                <motion.article
                  className="group relative overflow-hidden rounded-[12px] border border-[var(--color-border)] bg-white shadow-[var(--shadow-card)] transition-[box-shadow,border-color] duration-150 hover:border-[var(--color-border-strong)] hover:shadow-[0_8px_22px_rgba(48,46,42,0.08)]"
                  layout
                  transition={{ layout: { duration: 0.36, ease: [0.2, 0.8, 0.2, 1] } }}
                >
                  <div className="relative overflow-hidden bg-[var(--color-preview)]">
                    <img
                      alt={`${template.title}参考图`}
                      className="block h-auto w-full transition duration-500 ease-[var(--ease-out-expo)] group-hover:brightness-[0.96]"
                      src={template.previewUrl}
                    />
                    <div className="absolute inset-0 bg-gradient-to-t from-black/48 via-transparent to-transparent opacity-75 transition group-hover:opacity-90" />
                    {template.secondaryPreviewUrl && (
                      <div className="absolute bottom-4 right-4 flex size-16 overflow-hidden rounded-lg border-2 border-white/80 shadow-[0_12px_28px_rgba(0,0,0,0.22)] transition duration-300 group-hover:-translate-y-1 group-hover:rotate-1">
                        <img
                          alt="尾帧缩略图"
                          className="size-full object-cover"
                          src={template.secondaryPreviewUrl}
                        />
                      </div>
                    )}
                    <span className="absolute left-4 top-4 rounded-full bg-white/82 px-2.5 py-1 text-[10px] font-semibold text-[var(--color-text)] backdrop-blur-md">
                      {template.category}
                    </span>
                    <Button
                      className="absolute bottom-4 left-4 translate-y-2 opacity-0 transition duration-300 group-hover:translate-y-0 group-hover:opacity-100 focus-visible:translate-y-0 focus-visible:opacity-100 max-lg:hidden"
                      onClick={() => applySelectedTemplate(template)}
                      size="sm"
                      variant="primary"
                    >
                      套用到生成
                      <ArrowRight aria-hidden="true" className="size-3.5" />
                    </Button>
                  </div>
                  <div className="flex flex-col p-4.5 md:p-5">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-[var(--color-accent)]">
                          {template.settings.quality} · {template.settings.ratio}
                        </p>
                        <h2 className="font-display mt-1.5 text-xl font-semibold leading-snug tracking-[-0.015em]">
                          {template.title}
                        </h2>
                      </div>
                      <ImageIcon
                        aria-hidden="true"
                        className="mt-1 size-4 shrink-0 text-[var(--color-text-faint)]"
                      />
                    </div>
                    <p className="mt-2.5 text-sm leading-6 text-[var(--color-text-muted)]">
                      {template.description}
                    </p>
                    <div className="mt-auto flex items-center gap-2 pt-4 text-[10px] text-[var(--color-text-faint)]">
                      <span>{template.settings.resolution}</span>
                      <span>·</span>
                      <span>{template.settings.duration} 秒</span>
                      <span>·</span>
                      <span>I2V</span>
                    </div>
                    <Button
                      className="mt-4 w-full lg:hidden"
                      onClick={() => applySelectedTemplate(template)}
                      size="sm"
                      variant="secondary"
                    >
                      套用到生成
                      <ArrowRight aria-hidden="true" className="size-3.5" />
                    </Button>
                  </div>
                </motion.article>
              </Reveal>
            ))}
        </AnimatePresence>
      </motion.section>

      {visibleTemplates.length === 0 && (
        <motion.div
          animate={{ opacity: 1, y: 0 }}
          className="mt-5 rounded-[12px] border border-dashed border-[var(--color-border-strong)] bg-white/55 px-6 py-16 text-center"
          initial={{ opacity: 0, y: 8 }}
        >
          <Search aria-hidden="true" className="mx-auto size-6 text-[var(--color-text-faint)]" />
          <h2 className="font-display mt-3 text-lg font-semibold">没有匹配的镜头模板</h2>
          <p className="mt-2 text-sm text-[var(--color-text-muted)]">
            换个关键词，或者清除筛选继续浏览。
          </p>
          <Button
            className="mt-4"
            onClick={() => {
              setQuery("");
              setCategory("全部");
            }}
            size="sm"
            variant="secondary"
          >
            清除筛选
          </Button>
        </motion.div>
      )}
    </main>
  );
}
