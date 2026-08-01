import { Clock3, PanelLeftClose, Plus, Search, Sparkles } from "lucide-react";
import { AnimatePresence, LayoutGroup, motion } from "motion/react";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  useConversations,
  useCreateConversation,
  useJobs,
} from "@/features/studio/hooks";
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
  const activeConversationId = useStudioStore((state) => state.activeConversationId);
  const setActiveConversation = useStudioStore((state) => state.setActiveConversation);
  const resetDraft = useStudioStore((state) => state.resetDraft);
  const conversationsQuery = useConversations();
  const jobsQuery = useJobs();
  const createConversation = useCreateConversation();
  const conversations = useMemo(
    () => conversationsQuery.data ?? [],
    [conversationsQuery.data],
  );
  const jobs = jobsQuery.data ?? [];

  useEffect(() => {
    if (!activeConversationId && conversations[0]) {
      setActiveConversation(conversations[0].id);
    }
  }, [activeConversationId, conversations, setActiveConversation]);

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

  const closeOnMobile = () => {
    if (window.matchMedia("(max-width: 767px)").matches) setSidebarOpen(false);
  };

  return (
    <>
      <AnimatePresence>
        {sidebarOpen && (
          <motion.button
            animate={{ opacity: 1 }}
            aria-label="关闭会话栏遮罩"
            className="absolute inset-0 z-20 bg-[#1d1b19]/16 backdrop-blur-[2px] md:hidden"
            exit={{ opacity: 0 }}
            initial={{ opacity: 0 }}
            onClick={() => setSidebarOpen(false)}
            transition={{ duration: 0.2 }}
            type="button"
          />
        )}
      </AnimatePresence>

      <aside
        aria-label="创作会话"
        className={cn(
          "absolute inset-y-0 left-0 z-30 w-[248px] border-r border-[var(--color-border)] bg-[var(--color-sidebar)]/96 backdrop-blur-xl transition-transform duration-300 ease-[var(--ease-out-expo)] md:relative md:backdrop-blur-none",
          sidebarOpen ? "translate-x-0" : "-translate-x-full md:hidden",
        )}
      >
        <div className="flex h-full flex-col px-3 pb-3 pt-3">
          <div className="flex items-center gap-2">
            <Button
              className="flex-1 justify-start border-transparent bg-white/75 shadow-none hover:bg-white"
              disabled={createConversation.isPending}
              onClick={() =>
                createConversation.mutate("未命名创作", {
                  onSuccess: (conversation) => {
                    setActiveConversation(conversation.id);
                    resetDraft();
                    closeOnMobile();
                  },
                })
              }
              variant="secondary"
            >
              <span className="grid size-5 place-items-center rounded bg-[var(--color-accent-soft)] text-[var(--color-accent)]">
                <Plus aria-hidden="true" className="size-3.5" />
              </span>
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

          <label className="mt-3 flex h-9 items-center gap-2 rounded-md border border-transparent px-2 text-sm text-[var(--color-text-muted)] transition focus-within:border-[var(--color-border)] focus-within:bg-white/85">
            <Search aria-hidden="true" className="size-3.5" />
            <span className="sr-only">搜索会话</span>
            <input
              className="min-w-0 flex-1 bg-transparent text-sm outline-none"
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索会话"
              type="search"
              value={query}
            />
          </label>

          <div className="mt-5 flex items-center gap-2 px-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-[var(--color-text-faint)]">
            <Clock3 aria-hidden="true" className="size-3" />
            最近会话
          </div>

          <LayoutGroup id="conversation-list">
            <ul className="scrollbar-notion mt-2 min-h-0 flex-1 space-y-0.5 overflow-y-auto pr-1">
              {visibleConversations.map((conversation) => {
                const active = conversation.id === activeConversationId;
                return (
                  <li key={conversation.id}>
                    <button
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "relative isolate w-full overflow-hidden rounded-md px-2.5 py-2 text-left outline-none",
                        active
                          ? "text-[var(--color-text)]"
                          : "text-[var(--color-text-muted)] hover:bg-white/55",
                      )}
                      onClick={() => {
                        setActiveConversation(conversation.id);
                        closeOnMobile();
                      }}
                      type="button"
                    >
                      {active && (
                        <motion.span
                          aria-hidden="true"
                          className="absolute inset-0 -z-10 rounded-md bg-[var(--color-accent-soft)]"
                          layoutId="conversation-active"
                        />
                      )}
                      <span className="block truncate text-sm font-medium">{conversation.title}</span>
                      <span className="mt-1 block text-[11px] text-[var(--color-text-faint)]">
                        {relativeTime(conversation.updatedAt)}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </LayoutGroup>

          {conversationsQuery.isError && (
            <p className="px-2 text-xs text-[var(--color-danger)]">Gateway 会话服务不可用</p>
          )}
          <div className="mt-3 overflow-hidden rounded-lg border border-[var(--color-border)] bg-white/55">
            <div className="flex items-center justify-between px-3 py-2.5 text-xs">
              <span className="flex items-center gap-2 text-[var(--color-text-muted)]">
                <Sparkles className="size-3.5 text-[var(--color-accent)]" />
                计算队列
              </span>
              <span className="font-medium text-[var(--color-accent)]">
                {activeJobs.length === 0 ? "空闲" : "运行中"}
              </span>
            </div>
            <div className="border-t border-[var(--color-border)] px-3 py-2 text-[10px] text-[var(--color-text-faint)]">
              FAST {fastWaiting} · HQ {hqWaiting}
            </div>
          </div>
        </div>
      </aside>
    </>
  );
}
