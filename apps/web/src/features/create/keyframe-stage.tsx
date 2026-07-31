import { ArrowRight, ImagePlus, Sparkles } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";

import type { MediaReference } from "@/features/studio/types";
import { useStudioStore } from "@/store/studio-store";

function FrameCard({
  label,
  reference,
  delay,
}: {
  label: string;
  reference: MediaReference | null;
  delay: number;
}) {
  const reduceMotion = useReducedMotion();

  return (
    <motion.div
      animate={{ opacity: 1, y: 0, rotate: 0 }}
      className="group relative z-10 w-full max-w-[290px]"
      initial={reduceMotion ? false : { opacity: 0, y: 18, rotate: label === "首帧" ? -2 : 2 }}
      transition={{ duration: 0.6, delay, ease: [0.2, 0.8, 0.2, 1] }}
    >
      <div className="relative aspect-[4/3] overflow-hidden rounded-[16px] border border-white/70 bg-white shadow-[0_20px_50px_rgba(48,46,42,0.11)] ring-1 ring-[var(--color-border)] transition duration-300 ease-[var(--ease-out-expo)] group-hover:-translate-y-1 group-hover:shadow-[0_26px_64px_rgba(48,46,42,0.14)]">
        {reference ? (
          <img
            alt={`${label}预览`}
            className="size-full object-cover transition-transform duration-700 ease-[var(--ease-out-expo)] group-hover:scale-[1.025]"
            src={reference.url}
          />
        ) : (
          <div className="paper-texture grid size-full place-items-center">
            <span className="grid size-12 place-items-center rounded-full border border-[var(--color-border)] bg-white/75 text-[var(--color-text-faint)] shadow-[var(--shadow-card)]">
              <ImagePlus aria-hidden="true" className="size-5" />
            </span>
          </div>
        )}
        <div className="absolute inset-x-0 bottom-0 flex items-end justify-between bg-gradient-to-t from-black/48 via-black/10 to-transparent px-4 pb-3 pt-12 text-white">
          <span className="text-xs font-medium tracking-wide">{label}</span>
          <span className="max-w-32 truncate text-[10px] text-white/70">
            {reference?.name ?? "等待上传"}
          </span>
        </div>
      </div>
    </motion.div>
  );
}

export function KeyframeStage() {
  const draft = useStudioStore((state) => state.draft);

  return (
    <section className="relative flex min-h-[360px] flex-1 flex-col items-center justify-center overflow-hidden rounded-[22px] border border-[var(--color-border)] bg-[var(--color-paper)] px-5 py-10 shadow-[var(--shadow-card)] md:min-h-[430px] md:px-10">
      <div aria-hidden="true" className="dream-grid pointer-events-none absolute inset-0 opacity-70" />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -left-24 top-8 size-72 rounded-full bg-[rgb(218_158_91_/_10%)] blur-3xl"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -right-20 bottom-0 size-80 rounded-full bg-[var(--color-accent-soft)] blur-3xl"
      />

      <motion.div
        animate={{ opacity: 1, y: 0 }}
        className="relative z-10 mb-8 text-center"
        initial={{ opacity: 0, y: 10 }}
        transition={{ duration: 0.5, ease: [0.2, 0.8, 0.2, 1] }}
      >
        <p className="flex items-center justify-center gap-2 text-xs font-medium text-[var(--color-accent)]">
          <Sparkles aria-hidden="true" className="size-3.5" />
          KEYFRAME STAGE
        </p>
        <h2 className="font-display mt-2 text-2xl font-semibold tracking-[-0.025em] md:text-[30px]">
          从两个瞬间，生长出一段镜头
        </h2>
        <p className="mx-auto mt-2 max-w-xl text-sm leading-6 text-[var(--color-text-muted)]">
          首尾帧决定叙事边界，Prompt 描述中间发生的动作、镜头与声音。
        </p>
      </motion.div>

      <div className="relative z-10 flex w-full max-w-[760px] flex-col items-center justify-center gap-5 sm:flex-row sm:gap-16">
        <FrameCard delay={0.12} label="首帧" reference={draft.firstFrame} />

        <div className="relative flex shrink-0 items-center justify-center sm:absolute sm:left-1/2 sm:top-1/2 sm:-translate-x-1/2 sm:-translate-y-1/2">
          <div className="frame-flow h-px w-20 bg-[var(--color-border-strong)] sm:w-24" />
          <span className="absolute grid size-9 place-items-center rounded-full border border-[var(--color-border)] bg-white text-[var(--color-accent)] shadow-[0_8px_24px_rgba(48,46,42,0.10)]">
            <ArrowRight aria-hidden="true" className="size-4" />
          </span>
        </div>

        <FrameCard delay={0.2} label="尾帧" reference={draft.lastFrame} />
      </div>

      <p className="relative z-10 mt-7 text-[11px] text-[var(--color-text-faint)]">
        在下方创作器中上传或替换图片
      </p>
    </section>
  );
}
