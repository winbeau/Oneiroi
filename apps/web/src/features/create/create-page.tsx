import { PanelLeftOpen, Rows3, Sparkles } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";

import { WorkspaceSidebar } from "@/components/layout/workspace-sidebar";
import { Button } from "@/components/ui/button";
import { AgentPanel } from "@/features/create/agent-panel";
import { Composer } from "@/features/create/composer";
import { JobCard } from "@/features/create/job-card";
import { KeyframeStage } from "@/features/create/keyframe-stage";
import { useStudioStore } from "@/store/studio-store";
import { useWorkspaceStore } from "@/store/workspace-store";

export function CreatePage() {
  const sidebarOpen = useWorkspaceStore((state) => state.sidebarOpen);
  const setSidebarOpen = useWorkspaceStore((state) => state.setSidebarOpen);
  const activeConversationId = useStudioStore((state) => state.activeConversationId);
  const conversations = useStudioStore((state) => state.conversations);
  const jobs = useStudioStore((state) => state.jobs);
  const activeConversation = conversations.find(
    (conversation) => conversation.id === activeConversationId,
  );
  const conversationJobs = jobs.filter(
    (job) => job.conversationId === activeConversationId,
  );
  const runningCount = conversationJobs.filter(
    (job) => !["succeeded", "failed", "cancelled"].includes(job.stage),
  ).length;

  return (
    <main className="relative flex h-[calc(100vh-60px)] min-h-[620px] overflow-hidden">
      <WorkspaceSidebar />

      <section className="flex min-w-0 flex-1 flex-col bg-[var(--color-canvas)]">
        <header className="flex h-[54px] shrink-0 items-center border-b border-[var(--color-border)]/80 bg-[var(--color-canvas)]/80 px-4 backdrop-blur-lg md:px-6">
          {!sidebarOpen && (
            <Button
              aria-label="展开会话栏"
              className="mr-2"
              onClick={() => setSidebarOpen(true)}
              size="icon"
              variant="ghost"
            >
              <PanelLeftOpen aria-hidden="true" className="size-4" />
            </Button>
          )}
          <div className="min-w-0">
            <h1 className="truncate text-sm font-semibold tracking-[-0.01em]">
              {activeConversation?.title ?? "未命名创作"}
            </h1>
            <p className="mt-0.5 flex items-center gap-1.5 text-[10px] uppercase tracking-[0.08em] text-[var(--color-text-faint)]">
              <span
                className={`size-1.5 rounded-full ${
                  runningCount > 0 ? "soft-pulse bg-[var(--color-accent)]" : "bg-[var(--color-border-strong)]"
                }`}
              />
              {runningCount > 0
                ? `${runningCount} TASKS RUNNING`
                : conversationJobs.length > 0
                  ? `${conversationJobs.length} GENERATIONS`
                  : "DRAFT · READY"}
            </p>
          </div>
          <button
            className="ml-auto inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs text-[var(--color-text-muted)] transition hover:bg-[var(--color-surface-muted)] hover:text-[var(--color-text)]"
            type="button"
          >
            <Rows3 aria-hidden="true" className="size-3.5" />
            任务详情
          </button>
        </header>

        <div className="scrollbar-notion flex min-h-0 flex-1 flex-col overflow-y-auto">
          <div className="mx-auto flex w-full max-w-[1120px] flex-1 flex-col px-4 pb-2 pt-5 md:px-7 md:pt-7">
            <AgentPanel />

            {conversationJobs.length === 0 ? (
              <div className="mt-4 flex flex-1 pb-3">
                <KeyframeStage />
              </div>
            ) : (
              <section aria-label="生成任务" className="mt-7 pb-5">
                <div className="mb-4 flex items-end justify-between gap-4">
                  <div>
                    <p className="flex items-center gap-2 text-xs font-medium text-[var(--color-accent)]">
                      <Sparkles aria-hidden="true" className="size-3.5" />
                      CREATION TIMELINE
                    </p>
                    <h2 className="font-display mt-1.5 text-2xl font-semibold tracking-[-0.02em]">
                      镜头正在成形
                    </h2>
                  </div>
                  <p className="hidden text-xs text-[var(--color-text-faint)] sm:block">
                    阶段状态会持续同步
                  </p>
                </div>
                <AnimatePresence initial={false} mode="popLayout">
                  <div className="space-y-4">
                    {conversationJobs.map((job) => (
                      <motion.div
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: -8 }}
                        initial={{ opacity: 0, y: 12 }}
                        key={job.id}
                        layout
                        transition={{ duration: 0.38, ease: [0.2, 0.8, 0.2, 1] }}
                      >
                        <JobCard job={job} />
                      </motion.div>
                    ))}
                  </div>
                </AnimatePresence>
              </section>
            )}
          </div>

          <div className="sticky bottom-0 z-20 mt-auto bg-gradient-to-t from-[var(--color-canvas)] via-[var(--color-canvas)]/96 to-transparent px-3 pb-3 pt-8 md:px-7 md:pb-5">
            <div className="mx-auto max-w-[980px]">
              <Composer />
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
