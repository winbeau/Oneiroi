import { Check, X } from "lucide-react";
import { motion } from "motion/react";

import type { JobStage } from "@/features/studio/types";
import { cn } from "@/lib/utils";

const timelineStages: Array<{ stage: JobStage; label: string }> = [
  { stage: "uploaded", label: "上传" },
  { stage: "queued", label: "排队" },
  { stage: "assigned", label: "分配" },
  { stage: "preparing", label: "准备" },
  { stage: "generating", label: "生成" },
  { stage: "encoding", label: "编码" },
  { stage: "succeeded", label: "完成" },
];

const order: JobStage[] = [
  "draft",
  "uploaded",
  "queued",
  "assigned",
  "preparing",
  "generating",
  "encoding",
  "succeeded",
];

export function JobTimeline({ stage }: { stage: JobStage }) {
  const terminalFailure = stage === "failed" || stage === "cancelled";
  const currentIndex = terminalFailure
    ? Math.max(0, timelineStages.findIndex((item) => item.stage === "generating"))
    : Math.max(0, order.indexOf(stage) - 1);

  return (
    <div className="hide-scrollbar overflow-x-auto" aria-label="任务阶段">
      <ol className="flex min-w-[560px] items-start px-0.5">
        {timelineStages.map((item, index) => {
          const complete = !terminalFailure && index < currentIndex;
          const current = index === currentIndex;
          return (
            <li className="relative flex flex-1 flex-col items-center" key={item.stage}>
              {index > 0 && (
                <span className="absolute right-1/2 top-[7px] h-px w-full bg-[var(--color-border-strong)]">
                  {(complete || current) && !terminalFailure && (
                    <motion.span
                      animate={{ scaleX: 1 }}
                      className="absolute inset-0 origin-left bg-[var(--color-accent)]"
                      initial={{ scaleX: 0 }}
                      transition={{ duration: 0.45, ease: [0.2, 0.8, 0.2, 1] }}
                    />
                  )}
                </span>
              )}
              <span
                className={cn(
                  "relative z-10 grid size-[15px] place-items-center rounded-full border transition-colors duration-300",
                  complete && "border-[var(--color-accent)] bg-[var(--color-accent)] text-white",
                  current &&
                    !terminalFailure &&
                    "border-[var(--color-accent)] bg-white text-[var(--color-accent)] shadow-[0_0_0_4px_var(--color-accent-soft)]",
                  current &&
                    terminalFailure &&
                    "border-[var(--color-danger)] bg-white text-[var(--color-danger)] shadow-[0_0_0_4px_rgba(184,74,74,0.10)]",
                  !complete && !current && "border-[var(--color-border-strong)] bg-white",
                )}
              >
                {complete && <Check aria-hidden="true" className="size-2.5" strokeWidth={2.5} />}
                {current && terminalFailure && <X aria-hidden="true" className="size-2.5" strokeWidth={2.5} />}
                {current && !terminalFailure && (
                  <span className="soft-pulse size-1.5 rounded-full bg-[var(--color-accent)]" />
                )}
              </span>
              <span
                className={cn(
                  "mt-2 text-[10px] font-medium",
                  complete || current
                    ? "text-[var(--color-text)]"
                    : "text-[var(--color-text-faint)]",
                )}
              >
                {item.label}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
