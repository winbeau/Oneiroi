import { PanelLeftOpen, Sparkles } from "lucide-react";

import { WorkspaceSidebar } from "@/components/layout/workspace-sidebar";
import { Button } from "@/components/ui/button";
import { AgentPanel } from "@/features/create/agent-panel";
import { Composer } from "@/features/create/composer";
import { JobCard } from "@/features/create/job-card";
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
    <main className="relative flex h-[calc(100vh-3.5rem)] min-h-[620px] overflow-hidden">
      <WorkspaceSidebar />

      <section className="flex min-w-0 flex-1 flex-col bg-white">
        <header className="flex h-14 shrink-0 items-center border-b border-[var(--color-border)] px-4 md:px-5">
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
            <h1 className="truncate text-sm font-medium">
              {activeConversation?.title ?? "未命名创作"}
            </h1>
            <p className="text-xs text-[var(--color-text-faint)]">
              {runningCount > 0
                ? `${runningCount} 个任务执行中`
                : conversationJobs.length > 0
                  ? `${conversationJobs.length} 条生成记录`
                  : "草稿 · 尚未提交任务"}
            </p>
          </div>
          <button
            className="ml-auto rounded-md px-2 py-1 text-sm text-[var(--color-text-muted)] hover:bg-[var(--color-surface-muted)]"
            type="button"
          >
            任务详情
          </button>
        </header>

        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
          <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col px-4 py-6 md:px-6 md:py-8">
            <AgentPanel />

            {conversationJobs.length === 0 ? (
              <div className="flex flex-1 items-center justify-center py-12">
                <div className="max-w-xl text-center">
                  <div className="mx-auto grid size-11 place-items-center rounded-lg border border-[var(--color-border)] bg-[var(--color-sidebar)] text-[var(--color-accent)]">
                    <Sparkles aria-hidden="true" className="size-5" />
                  </div>
                  <h2 className="mt-5 text-2xl font-semibold tracking-[-0.025em]">
                    把两张关键帧变成一段连贯镜头
                  </h2>
                  <p className="mt-3 text-sm leading-6 text-[var(--color-text-muted)]">
                    上传首帧和尾帧，描述人物动作、镜头和声音。提交后，这里会持续显示排队、模型准备、生成和编码状态。
                  </p>
                </div>
              </div>
            ) : (
              <section aria-label="生成任务" className="mt-5 space-y-4 pb-6">
                {conversationJobs.map((job) => (
                  <JobCard job={job} key={job.id} />
                ))}
              </section>
            )}
          </div>

          <div className="sticky bottom-0 z-10 bg-gradient-to-t from-white via-white to-transparent px-4 pb-4 pt-6 md:px-6 md:pb-6">
            <div className="mx-auto max-w-4xl">
              <Composer />
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
