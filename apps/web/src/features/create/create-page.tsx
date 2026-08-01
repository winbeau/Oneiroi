import { PanelLeftOpen, Rows3, Sparkles } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";

import { WorkspaceSidebar } from "@/components/layout/workspace-sidebar";
import { Button } from "@/components/ui/button";
import { ComputeControl } from "@/features/compute/compute-control";
import { AgentPanel } from "@/features/create/agent-panel";
import { Composer } from "@/features/create/composer";
import { JobCard } from "@/features/create/job-card";
import {
  useConversations,
  useJobEvents,
  useJobs,
} from "@/features/studio/hooks";
import { useStudioStore } from "@/store/studio-store";
import { useWorkspaceStore } from "@/store/workspace-store";

function CreationConsole() {
  const [agentOpen, setAgentOpen] = useState(false);
  return (
    <div className="w-full">
      <Composer agentOpen={agentOpen} onAgentToggle={() => setAgentOpen((value) => !value)} />
      <AnimatePresence initial={false}>
        {agentOpen && (
          <motion.div className="mx-auto mt-4 max-w-[760px] overflow-hidden">
            <AgentPanel defaultOpen />
          </motion.div>
        )}
      </AnimatePresence>
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

        <ComputeControl activeJobs={activeJobs.length} />

        <div className="scrollbar-notion flex min-h-0 flex-1 flex-col overflow-y-auto">
          {conversationJobs.length === 0 ? (
            <div className="relative mx-auto flex w-full max-w-[1120px] flex-1 items-center justify-center px-4 py-10 md:px-7">
              <div className="relative z-10 w-full max-w-[920px]">
                <CreationConsole />
              </div>
            </div>
          ) : (
            <>
              <div className="mx-auto w-full max-w-[1120px] flex-1 px-4 pb-2 pt-5 md:px-7">
                <section aria-label="生成任务" className="pb-5">
                  <div className="mb-4 flex items-end justify-between gap-4">
                    <div>
                      <p className="flex items-center gap-2 text-xs font-medium text-[var(--color-accent)]">
                        <Sparkles className="size-3.5" /> CREATION TIMELINE
                      </p>
                      <h2 className="font-display mt-1.5 text-2xl font-semibold">镜头正在成形</h2>
                    </div>
                  </div>
                  <AnimatePresence initial={false} mode="popLayout">
                    <div className="space-y-4">
                      {conversationJobs.map((job) => (
                        <motion.div key={job.id} layout>
                          <JobCard job={job} />
                        </motion.div>
                      ))}
                    </div>
                  </AnimatePresence>
                </section>
              </div>
              <div className="sticky bottom-0 z-20 mt-auto bg-gradient-to-t from-[var(--color-canvas)] via-[var(--color-canvas)]/96 to-transparent px-3 pb-3 pt-8 md:px-7">
                <div className="mx-auto max-w-[980px]">
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
