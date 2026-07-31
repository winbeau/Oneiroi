import { ArrowUpRight, ImageIcon, WandSparkles } from "lucide-react";

const examples = [
  {
    title: "安静的产品镜头",
    description: "柔和侧光下，镜头缓慢靠近桌面上的产品，背景保持简洁。",
    ratio: "16:9",
    tier: "快速",
  },
  {
    title: "角色环境叙事",
    description: "人物站在雨后的街道，轻微转头，环境反射与微风自然变化。",
    ratio: "16:9",
    tier: "高质量",
  },
  {
    title: "竖屏氛围片段",
    description: "清晨窗边的植物随风轻晃，固定机位，低强度运动。",
    ratio: "9:16",
    tier: "快速",
  },
];

export function InspirationPage() {
  return (
    <main className="mx-auto w-full max-w-6xl px-5 py-10 md:px-8">
      <div className="max-w-2xl">
        <div className="mb-3 flex items-center gap-2 text-sm font-medium text-[var(--color-accent)]">
          <WandSparkles aria-hidden="true" className="size-4" />
          灵感模板
        </div>
        <h1 className="text-3xl font-semibold tracking-[-0.03em]">从一个清晰想法开始</h1>
        <p className="mt-3 leading-7 text-[var(--color-text-muted)]">
          一期只展示内部整理的示例。选择后会把参考规格和提示词带入生成页。
        </p>
      </div>

      <section aria-label="灵感模板列表" className="mt-8 grid gap-4 md:grid-cols-3">
        {examples.map((example) => (
          <article
            className="group overflow-hidden rounded-lg border border-[var(--color-border)] bg-white shadow-[var(--shadow-card)]"
            key={example.title}
          >
            <div className="grid aspect-video place-items-center bg-[var(--color-preview)] text-white/50">
              <ImageIcon aria-hidden="true" className="size-7" />
            </div>
            <div className="p-4">
              <div className="flex items-start justify-between gap-3">
                <h2 className="font-medium">{example.title}</h2>
                <ArrowUpRight
                  aria-hidden="true"
                  className="size-4 shrink-0 text-[var(--color-text-faint)] transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5"
                />
              </div>
              <p className="mt-2 text-sm leading-6 text-[var(--color-text-muted)]">
                {example.description}
              </p>
              <div className="mt-4 flex gap-2 text-xs text-[var(--color-text-muted)]">
                <span className="rounded bg-[var(--color-surface-muted)] px-2 py-1">
                  {example.ratio}
                </span>
                <span className="rounded bg-[var(--color-surface-muted)] px-2 py-1">
                  {example.tier}
                </span>
              </div>
            </div>
          </article>
        ))}
      </section>
    </main>
  );
}
