import { ArrowRight, Bot, Lightbulb, WandSparkles } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useStudioStore } from "@/store/studio-store";

const buildSuggestion = (idea: string) => {
  const subject = idea.trim() || "人物打开床头的隐藏柜门";
  return `${subject}。固定广角机位，先明确主体动作，再保持人物身份、场景几何和光线一致。加入轻微、连续、可观察的手部和衣物运动，镜头运动克制，环境声音自然，不添加对白。`;
};

export function AgentPanel() {
  const draft = useStudioStore((state) => state.draft);
  const updateDraft = useStudioStore((state) => state.updateDraft);
  const [open, setOpen] = useState(false);
  const [idea, setIdea] = useState("");
  const [suggestion, setSuggestion] = useState("");

  const improve = () => {
    const next = buildSuggestion(idea || draft.prompt);
    setSuggestion(next);
  };

  return (
    <section className="rounded-xl border border-[var(--color-border)] bg-[var(--color-sidebar)] p-4">
      <div className="flex items-start gap-3">
        <div className="grid size-9 shrink-0 place-items-center rounded-lg bg-[var(--color-text)] text-white">
          <Bot aria-hidden="true" className="size-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="font-medium">Agent 模式</h2>
            <span className="rounded-full bg-white px-2 py-0.5 text-[11px] text-[var(--color-text-muted)]">
              自动 · 灵感搜索 · 创意设计
            </span>
          </div>
          <p className="mt-1 text-sm leading-6 text-[var(--color-text-muted)]">
            把一句模糊想法整理成可执行的镜头描述。建议会先展示给你确认，不会自动提交长任务。
          </p>
        </div>
        <button
          aria-expanded={open}
          aria-label={open ? "收起 Agent 模式" : "展开 Agent 模式"}
          className="rounded-md p-1.5 text-[var(--color-text-muted)] hover:bg-white hover:text-[var(--color-text)]"
          onClick={() => setOpen((value) => !value)}
          type="button"
        >
          <ArrowRight className={`size-4 transition-transform ${open ? "rotate-90" : ""}`} />
        </button>
      </div>

      {open && (
        <div className="mt-4 border-t border-[var(--color-border)] pt-4">
          <div className="flex gap-2">
            <label className="min-w-0 flex-1">
              <span className="sr-only">描述你的创意</span>
              <input
                className="h-10 w-full rounded-md border border-[var(--color-border-strong)] bg-white px-3 text-sm outline-none placeholder:text-[var(--color-text-faint)] focus:border-[var(--color-accent)]"
                onChange={(event) => setIdea(event.target.value)}
                placeholder="例如：她从隐藏书柜里拿出一本书"
                value={idea}
              />
            </label>
            <Button onClick={improve} size="sm" variant="primary">
              <WandSparkles aria-hidden="true" className="size-3.5" />
              整理镜头
            </Button>
          </div>

          {suggestion && (
            <div className="mt-3 rounded-lg border border-[var(--color-border)] bg-white p-3">
              <div className="flex items-center gap-2 text-xs font-medium text-[var(--color-accent)]">
                <Lightbulb aria-hidden="true" className="size-3.5" />
                镜头建议
              </div>
              <p className="mt-2 text-sm leading-6 text-[var(--color-text)]">{suggestion}</p>
              <div className="mt-3 flex gap-2">
                <Button onClick={() => updateDraft({ prompt: suggestion })} size="sm" variant="secondary">
                  采用建议
                </Button>
                <Button onClick={() => setSuggestion("")} size="sm" variant="ghost">
                  保留原文
                </Button>
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
