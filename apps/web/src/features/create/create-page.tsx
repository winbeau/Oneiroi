import { Moon, PanelLeftOpen, Rows3, Sparkle } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";

import { WorkspaceSidebar } from "@/components/layout/workspace-sidebar";
import { Button } from "@/components/ui/button";
import { AgentPanel } from "@/features/create/agent-panel";
import { Composer } from "@/features/create/composer";
import { JobCard } from "@/features/create/job-card";
import {
  useConversations,
  useJobEvents,
  useJobs,
} from "@/features/studio/hooks";
import { cn } from "@/lib/utils";
import { useStudioStore } from "@/store/studio-store";
import { useWorkspaceStore } from "@/store/workspace-store";

function CreationConsole() {
  return (
    <div className="space-y-2.5">
      <AgentPanel />
      <Composer />
    </div>
  );
}

function BrandSlogan({ compact = false }: { compact?: boolean }) {
  return (
    <div
      className={cn(
        "flex items-center justify-center gap-3 text-center font-display font-semibold tracking-[-0.025em] text-[var(--color-text)]",
        compact ? "mb-7 text-xl md:text-2xl" : "mb-10 text-[30px] md:text-[36px]",
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          "relative grid shrink-0 place-items-center text-[var(--color-text)]",
          compact ? "size-9" : "size-11",
        )}
      >
        <Moon
          className={cn(
            "-translate-x-[1px] translate-y-[1px]",
            compact ? "size-[27px]" : "size-[33px]",
          )}
          strokeWidth={1.8}
        />
        <Sparkle
          className={cn(
            "absolute fill-[#f6cf68]/20 text-[#f6cf68] drop-shadow-[0_0_5px_rgba(246,207,104,0.9)]",
            compact ? "right-[2px] top-[2px] size-[15px]" : "right-[1px] top-[1px] size-[18px]",
          )}
          strokeWidth={2.1}
        />
      </span>
      <span>Oneiroi，让每个想象都有下一帧。</span>
    </div>
  );
}

export function CreatePage() {
  const sidebarOpen = useWorkspaceStore((state) => state.sidebarOpen);
  const setSidebarOpen = useWorkspaceStore((state) => state.setSidebarOpen);
  const activeConversationId = useStudioStore((state) => state.activeConversationId);
  const conversations = useConversations().data ?? [];
  const jobsQuery = useJobs();
  const jobs = jobsQuery.data ?? [];
  useJobEvents(jobs);
  const activeConversation = conversations.find((item) => item.id === activeConversationId);
  const conversationJobs = jobs.filter((job) => job.conversationId === activeConversationId);
  const activeJobs = jobs.filter(
    (job) => !["succeeded", "failed", "cancelled"].includes(job.stage),
  );

  return (
    <main className="relative flex h-[calc(100vh-60px)] min-h-[620px] overflow-hidden">
      <WorkspaceSidebar />
      <section className="flex min-w-0 flex-1 flex-col bg-[var(--color-canvas)]">
        <header className="flex h-[54px] shrink-0 items-center border-b border-[var(--color-border)]/80 px-4 md:px-6">
          {!sidebarOpen && (
            <Button
              aria-label="展开会话栏"
              className="mr-2"
              onClick={() => setSidebarOpen(true)}
              size="icon"
              variant="ghost"
            >
              <PanelLeftOpen className="size-4" />
            </Button>
          )}
          <div className="min-w-0">
            <h1 className="truncate text-sm font-semibold">
              {activeConversation?.title ?? "未命名创作"}
            </h1>
            <p className="mt-0.5 text-[10px] uppercase text-[var(--color-text-faint)]">
              {activeJobs.length > 0 ? `${activeJobs.length} TASKS RUNNING` : "SERVER SYNCED"}
            </p>
          </div>
          <button className="ml-auto inline-flex items-center gap-1.5 text-xs" type="button">
            <Rows3 className="size-3.5" /> 任务详情
          </button>
        </header>

        <div className="scrollbar-notion flex min-h-0 flex-1 flex-col overflow-y-auto">
          {conversationJobs.length === 0 ? (
            <div className="relative mx-auto flex w-full max-w-[1120px] flex-1 items-center justify-center px-4 py-10 md:px-7">
              <div className="relative z-10 w-full max-w-[920px]">
                <BrandSlogan />
                <CreationConsole />
              </div>
            </div>
          ) : (
            <>
              <div className="mx-auto w-full max-w-[1080px] flex-1 px-4 pb-2 pt-6 md:px-7">
                <section aria-label="创作对话" className="pb-5">
                  <div className="mb-6 flex items-center gap-3 text-[10px] font-medium text-[var(--color-text-faint)]">
                    <span className="h-px flex-1 bg-[var(--color-border)]" />
                    今天
                    <span className="h-px flex-1 bg-[var(--color-border)]" />
                  </div>
                  <AnimatePresence initial={false} mode="popLayout">
                    <div className="space-y-7">
                      {[...conversationJobs].reverse().map((job) => (
                        <motion.div key={job.id} layout>
                          <JobCard job={job} />
                        </motion.div>
                      ))}
                    </div>
                  </AnimatePresence>
                </section>
              </div>
              <div className="sticky bottom-0 z-20 mt-auto bg-gradient-to-t from-[var(--color-canvas)] via-[var(--color-canvas)]/97 to-transparent px-3 pb-3 pt-10 md:px-7">
                <div className="mx-auto max-w-[1040px]">
                  <CreationConsole />
                </div>
              </div>
            </>
          )}
          {jobsQuery.isError && (
            <p className="p-4 text-center text-sm text-[var(--color-danger)]">
              无法读取任务；生产模式不会使用浏览器 timer 推进状态。
            </p>
          )}
        </div>
      </section>
    </main>
  );
}
