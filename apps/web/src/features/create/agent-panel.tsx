import { ArrowRight, Bot, Lightbulb, Sparkles, WandSparkles } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useStudioStore } from "@/store/studio-store";

const buildSuggestion = (idea: string) => {
  const subject = idea.trim() || "人物打开床头的隐藏柜门";
  return `${subject}。固定广角机位，先明确主体动作，再保持人物身份、场景几何和光线一致。加入轻微、连续、可观察的手部和衣物运动，镜头运动克制，环境声音自然，不添加对白。`;
};

export function AgentPanel({ defaultOpen = false }: { defaultOpen?: boolean }) {
  const draft = useStudioStore((state) => state.draft);
  const updateDraft = useStudioStore((state) => state.updateDraft);
  const [open, setOpen] = useState(defaultOpen);
  const [idea, setIdea] = useState("");
  const [suggestion, setSuggestion] = useState("");

  const improve = () => {
    const next = buildSuggestion(idea || draft.prompt);
    setSuggestion(next);
  };

  return (
    <motion.section
      className="overflow-hidden rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-white/65 shadow-[var(--shadow-card)] backdrop-blur-sm"
      layout
      transition={{ duration: 0.32, ease: [0.2, 0.8, 0.2, 1] }}
    >
      <button
        aria-expanded={open}
        aria-label={open ? "收起 Agent 模式" : "展开 Agent 模式"}
        className="flex w-full items-center gap-3 px-3.5 py-3 text-left transition hover:bg-white/65 md:px-4"
        onClick={() => setOpen((value) => !value)}
        type="button"
      >
        <span className="relative grid size-9 shrink-0 place-items-center rounded-[10px] bg-[var(--color-text)] text-white shadow-[0_6px_16px_rgba(48,46,42,0.14)]">
          <Bot aria-hidden="true" className="size-4" />
          <span className="absolute -right-0.5 -top-0.5 size-2 rounded-full border-2 border-white bg-[var(--color-accent)]" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold">Agent 模式</span>
            <span className="rounded-full bg-[var(--color-accent-soft)] px-2 py-0.5 text-[10px] font-medium text-[var(--color-accent)]">
              灵感搜索 · 创意设计
            </span>
          </span>
          <span className="mt-0.5 block truncate text-xs text-[var(--color-text-muted)]">
            把模糊想法整理成镜头建议，确认后再带入生成。
          </span>
        </span>
        <span className="hidden items-center gap-1.5 text-[11px] text-[var(--color-text-faint)] sm:flex">
          {open ? "收起" : "展开"}
          <ArrowRight
            aria-hidden="true"
            className={`size-3.5 transition-transform duration-300 ${open ? "rotate-90" : ""}`}
          />
        </span>
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            animate={{ height: "auto", opacity: 1 }}
            className="overflow-hidden"
            exit={{ height: 0, opacity: 0 }}
            initial={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.34, ease: [0.2, 0.8, 0.2, 1] }}
          >
            <div className="border-t border-[var(--color-border)] px-3.5 pb-4 pt-3.5 md:px-4">
              <div className="flex flex-col gap-2 sm:flex-row">
                <label className="min-w-0 flex-1">
                  <span className="sr-only">描述你的创意</span>
                  <input
                    className="h-10 w-full rounded-lg border border-[var(--color-border-strong)] bg-white/90 px-3 text-sm outline-none transition placeholder:text-[var(--color-text-faint)] focus:border-[var(--color-accent)] focus:shadow-[0_0_0_3px_var(--color-accent-soft)]"
                    onChange={(event) => setIdea(event.target.value)}
                    placeholder="例如：她从隐藏书柜里拿出一本书"
                    value={idea}
                  />
                </label>
                <Button onClick={improve} size="md" variant="primary">
                  <WandSparkles aria-hidden="true" className="size-3.5" />
                  整理镜头
                </Button>
              </div>

              <AnimatePresence mode="wait">
                {suggestion && (
                  <motion.div
                    animate={{ opacity: 1, y: 0 }}
                    className="mt-3 rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-canvas)] p-3.5"
                    exit={{ opacity: 0, y: -6 }}
                    initial={{ opacity: 0, y: 8 }}
                    key={suggestion}
                    transition={{ duration: 0.28, ease: [0.2, 0.8, 0.2, 1] }}
                  >
                    <div className="flex items-center gap-2 text-xs font-semibold text-[var(--color-accent)]">
                      <span className="grid size-6 place-items-center rounded-md bg-[var(--color-accent-soft)]">
                        <Lightbulb aria-hidden="true" className="size-3.5" />
                      </span>
                      镜头建议 · 等待确认
                    </div>
                    <p className="mt-2.5 text-sm leading-6 text-[var(--color-text)]">
                      {suggestion}
                    </p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <Button
                        onClick={() => updateDraft({ prompt: suggestion })}
                        size="sm"
                        variant="primary"
                      >
                        <Sparkles aria-hidden="true" className="size-3.5" />
                        采用建议
                      </Button>
                      <Button onClick={() => setSuggestion("")} size="sm" variant="ghost">
                        保留原文
                      </Button>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.section>
  );
}
