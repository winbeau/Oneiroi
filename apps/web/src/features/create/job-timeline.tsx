import { Check, X } from "lucide-react";

import type { JobStage } from "@/features/studio/types";
import { cn } from "@/lib/utils";

const stages = [
  { id: "assigned", label: "分配" },
  { id: "loading_model", label: "模型" },
  { id: "prompt_encoding", label: "Prompt" },
  { id: "diffusion", label: "扩散" },
  { id: "stage_2", label: "增强" },
  { id: "encoding", label: "编码" },
  { id: "succeeded", label: "完成" },
] as const;

const stageIndex: Record<JobStage, number> = {
  draft: 0,
  uploaded: 0,
  queued: 0,
  assigned: 0,
  loading_model: 1,
  preparing: 2,
  generating: 3,
  encoding: 5,
  cancel_requested: 3,
  succeeded: 6,
  failed: 3,
  cancelled: 3,
};

export function JobTimeline({
  stage,
  phase,
  currentStep,
  totalSteps,
}: {
  stage: JobStage;
  phase?: string | null;
  currentStep?: number | null;
  totalSteps?: number | null;
}) {
  const terminalFailure = stage === "failed" || stage === "cancelled";
  const currentIndex = phase === "stage_2" ? 4 : stageIndex[stage];

  return (
    <div aria-label="任务阶段" className="hide-scrollbar overflow-x-auto">
      <ol className="flex min-w-[560px] items-start px-0.5">
        {stages.map((item, index) => {
          const complete = !terminalFailure && index < currentIndex;
          const current = index === currentIndex;
          return (
            <li className="relative flex flex-1 flex-col items-center" key={item.id}>
              {index > 0 && (
                <span className="absolute right-1/2 top-[7px] h-px w-full bg-[var(--color-border-strong)]">
                  {(complete || current) && !terminalFailure && (
                    <span className="absolute inset-0 bg-[var(--color-accent)]" />
                  )}
                </span>
              )}
              <span
                className={cn(
                  "relative z-10 grid size-[15px] place-items-center rounded-full border",
                  complete && "border-[var(--color-accent)] bg-[var(--color-accent)] text-white",
                  current && !terminalFailure && "border-[var(--color-accent)] bg-white",
                  current && terminalFailure && "border-[var(--color-danger)] bg-white",
                  !complete && !current && "border-[var(--color-border-strong)] bg-white",
                )}
              >
                {complete && <Check className="size-2.5" />}
                {current && terminalFailure && <X className="size-2.5" />}
                {current && !terminalFailure && (
                  <span className="soft-pulse size-1.5 rounded-full bg-[var(--color-accent)]" />
                )}
              </span>
              <span className="mt-2 text-[10px] font-medium">{item.label}</span>
              {item.id === "diffusion" && currentStep != null && totalSteps != null && (
                <span className="mt-0.5 font-mono text-[9px] text-[var(--color-text-faint)]">
                  {currentStep}/{totalSteps}
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
