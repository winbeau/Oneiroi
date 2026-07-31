import { Clock3, PanelLeftClose, Plus, Search } from "lucide-react";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useStudioStore } from "@/store/studio-store";
import { useWorkspaceStore } from "@/store/workspace-store";

const relativeTime = (value: string) => {
  const elapsed = Date.now() - new Date(value).getTime();
  if (elapsed < 60_000) return "刚刚";
  if (elapsed < 3_600_000) return `${Math.floor(elapsed / 60_000)} 分钟前`;
  if (elapsed < 86_400_000) return `${Math.floor(elapsed / 3_600_000)} 小时前`;
  return `${Math.floor(elapsed / 86_400_000)} 天前`;
};

export function WorkspaceSidebar() {
  const [query, setQuery] = useState("");
  const sidebarOpen = useWorkspaceStore((state) => state.sidebarOpen);
  const setSidebarOpen = useWorkspaceStore((state) => state.setSidebarOpen);
  const conversations = useStudioStore((state) => state.conversations);
  const activeConversationId = useStudioStore((state) => state.activeConversationId);
  const setActiveConversation = useStudioStore((state) => state.setActiveConversation);
  const createConversation = useStudioStore((state) => state.createConversation);
  const jobs = useStudioStore((state) => state.jobs);

  const visibleConversations = useMemo(
    () =>
      conversations.filter((conversation) =>
        conversation.title.toLowerCase().includes(query.trim().toLowerCase()),
      ),
    [conversations, query],
  );
  const activeJobs = jobs.filter(
    (job) => !["succeeded", "failed", "cancelled"].includes(job.stage),
  );
  const fastWaiting = activeJobs.filter((job) => job.draft.queue === "fast").length;
  const hqWaiting = activeJobs.filter((job) => job.draft.queue === "hq").length;

  return (
    <>
      {sidebarOpen && (
        <button
          aria-label="关闭会话栏遮罩"
          className="absolute inset-0 z-20 bg-black/10 md:hidden"
          onClick={() => setSidebarOpen(false)}
          type="button"
        />
      )}
      <aside
        aria-label="创作会话"
        className={cn(
          "absolute inset-y-0 left-0 z-30 w-64 border-r border-[var(--color-border)] bg-[var(--color-sidebar)] transition-transform md:static md:translate-x-0",
          sidebarOpen ? "translate-x-0" : "-translate-x-full md:hidden",
        )}
      >
        <div className="flex h-full flex-col p-3">
          <div className="flex items-center gap-2">
            <Button
              className="flex-1 justify-start"
              onClick={() => {
                createConversation();
                setSidebarOpen(false);
              }}
              variant="primary"
            >
              <Plus aria-hidden="true" className="size-4" />
              新建创作
            </Button>
            <Button
              aria-label="收起会话栏"
              className="md:hidden"
              onClick={() => setSidebarOpen(false)}
              size="icon"
              variant="ghost"
            >
              <PanelLeftClose aria-hidden="true" className="size-4" />
            </Button>
          </div>

          <label className="mt-3 flex h-9 items-center gap-2 rounded-md border border-transparent px-2 text-sm text-[var(--color-text-muted)] focus-within:border-[var(--color-border-strong)] focus-within:bg-white">
            <Search aria-hidden="true" className="size-4" />
            <span className="sr-only">搜索会话</span>
            <input
              className="min-w-0 flex-1 bg-transparent outline-none placeholder:text-[var(--color-text-faint)]"
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索会话"
              type="search"
              value={query}
            />
          </label>

          <div className="mt-5 flex items-center gap-2 px-2 text-xs font-medium uppercase tracking-wide text-[var(--color-text-faint)]">
            <Clock3 aria-hidden="true" className="size-3.5" />
            最近会话
          </div>
          <ul className="mt-2 space-y-0.5 overflow-y-auto">
            {visibleConversations.map((conversation) => (
              <li key={conversation.id}>
                <button
                  aria-current={
                    conversation.id === activeConversationId ? "page" : undefined
                  }
                  className={cn(
                    "w-full rounded-md px-2 py-2 text-left hover:bg-white/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)]",
                    conversation.id === activeConversationId &&
                      "bg-white shadow-[var(--shadow-card)]",
                  )}
                  onClick={() => {
                    setActiveConversation(conversation.id);
                    setSidebarOpen(false);
                  }}
                  type="button"
                >
                  <span className="block truncate text-sm">{conversation.title}</span>
                  <span className="mt-0.5 block text-xs text-[var(--color-text-faint)]">
                    {relativeTime(conversation.updatedAt)}
                  </span>
                </button>
              </li>
            ))}
          </ul>

          <div className="mt-auto rounded-md border border-[var(--color-border)] bg-white/70 p-3 text-xs text-[var(--color-text-muted)]">
            <div className="flex items-center justify-between">
              <span>当前队列</span>
              <span className="font-medium text-[var(--color-success)]">
                {activeJobs.length === 0 ? "可用" : "运行中"}
              </span>
            </div>
            <p className="mt-1 text-[var(--color-text-faint)]">
              Fast {fastWaiting} 个任务 · HQ {hqWaiting} 个任务
            </p>
          </div>
        </div>
      </aside>
    </>
  );
}
