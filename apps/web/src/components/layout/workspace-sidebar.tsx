import { Clock3, PencilLine, PanelLeftClose, Plus, Search, Sparkles, Trash2 } from "lucide-react";
import { AnimatePresence, LayoutGroup, motion } from "motion/react";
import { useEffect, useMemo, useState, type MouseEvent as ReactMouseEvent } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  useConversations,
  useCreateConversation,
  useDeleteConversation,
  useJobs,
  useRenameConversation,
} from "@/features/studio/hooks";
import type { Conversation } from "@/features/studio/types";
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
  const deleteConversation = useDeleteConversation();
  const renameConversation = useRenameConversation();
  const [pendingDelete, setPendingDelete] = useState<Conversation | null>(null);
  const [pendingRename, setPendingRename] = useState<Conversation | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [contextMenu, setContextMenu] = useState<{
    conversation: Conversation;
    x: number;
    y: number;
  } | null>(null);
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

  const openContextMenu = (
    event: ReactMouseEvent,
    conversation: Conversation,
  ) => {
    event.preventDefault();
    const x = Math.min(event.clientX, window.innerWidth - 180);
    const y = Math.min(event.clientY, window.innerHeight - 120);
    setContextMenu({ conversation, x, y });
  };

  const closeContextMenu = () => setContextMenu(null);

  const startRename = (conversation: Conversation) => {
    closeContextMenu();
    setRenameValue(conversation.title);
    setPendingRename(conversation);
  };

  const confirmRename = () => {
    if (!pendingRename) return;
    const title = renameValue.trim();
    if (!title || title === pendingRename.title) {
      setPendingRename(null);
      return;
    }
    renameConversation.mutate(
      { conversationId: pendingRename.id, title },
      { onSettled: () => setPendingRename(null) },
    );
  };

  const confirmDelete = () => {
    if (!pendingDelete) return;
    deleteConversation.mutate(pendingDelete.id, {
      onSuccess: () => {
        if (activeConversationId === pendingDelete.id) {
          const remaining = conversations.filter(
            (item) => item.id !== pendingDelete.id,
          );
          setActiveConversation(remaining[0]?.id ?? "");
        }
        setPendingDelete(null);
      },
    });
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
              className="flex-1 transform-none justify-start border-transparent bg-white/75 shadow-none hover:transform-none hover:bg-white active:transform-none"
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
                    <div
                      className="group relative"
                      onContextMenu={(event) => openContextMenu(event, conversation)}
                    >
                      <button
                        aria-current={active ? "page" : undefined}
                        className={cn(
                          "relative isolate w-full overflow-hidden rounded-md py-2 pl-2.5 pr-9 text-left outline-none",
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
                        <span className="block truncate text-sm font-medium">
                          {conversation.title}
                        </span>
                        <span className="mt-1 block text-[11px] text-[var(--color-text-faint)]">
                          {relativeTime(conversation.updatedAt)}
                        </span>
                      </button>
                      <button
                        aria-label={`删除会话 ${conversation.title}`}
                        className="absolute right-1.5 top-1/2 grid size-6 -translate-y-1/2 place-items-center rounded text-[var(--color-text-faint)] opacity-0 transition hover:bg-white/75 hover:text-[var(--color-danger)] focus-visible:opacity-100 group-hover:opacity-100"
                        onClick={(event) => {
                          event.stopPropagation();
                          setPendingDelete(conversation);
                        }}
                        title="删除会话及其全部生成资产"
                        type="button"
                      >
                        <Trash2 className="size-3.5" />
                      </button>
                    </div>
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

      {contextMenu && (
        <>
          <button
            aria-label="关闭菜单"
            className="fixed inset-0 z-[80] cursor-default"
            onClick={closeContextMenu}
            onContextMenu={(event) => {
              event.preventDefault();
              closeContextMenu();
            }}
            type="button"
          />
          <div
            className="fixed z-[85] w-40 overflow-hidden rounded-lg border border-[var(--color-border)] bg-[var(--color-paper)] p-1 shadow-[0_16px_48px_rgba(26,23,20,0.22)]"
            style={{ left: contextMenu.x, top: contextMenu.y }}
          >
            <button
              className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-xs text-[var(--color-text)] transition hover:bg-[var(--color-surface-muted)]"
              onClick={() => startRename(contextMenu.conversation)}
              type="button"
            >
              <PencilLine className="size-3.5" /> 重命名
            </button>
            <button
              className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-xs text-[var(--color-danger)] transition hover:bg-[rgb(184_74_74_/_8%)]"
              onClick={() => {
                closeContextMenu();
                setPendingDelete(contextMenu.conversation);
              }}
              type="button"
            >
              <Trash2 className="size-3.5" /> 删除会话
            </button>
          </div>
        </>
      )}

      <Dialog
        onOpenChange={(open) => {
          if (!open) {
            setPendingRename(null);
            setPendingDelete(null);
          }
        }}
        open={pendingRename !== null || pendingDelete !== null}
      >
        <DialogContent className="max-w-sm p-6">
          {pendingRename ? (
            <>
              <DialogTitle className="text-base font-semibold text-[var(--color-text)]">
                重命名会话
              </DialogTitle>
              <DialogDescription className="mt-2 text-sm leading-6 text-[var(--color-text-muted)]">
                为「{pendingRename.title}」设置新名称。
              </DialogDescription>
              <input
                autoFocus
                className="mt-3 h-10 w-full rounded-md border border-[var(--color-border-strong)] bg-white/90 px-3 text-sm outline-none focus:border-[var(--color-accent)]/40 focus:ring-2 focus:ring-[var(--color-accent)]/15"
                maxLength={100}
                onChange={(event) => setRenameValue(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") confirmRename();
                }}
                value={renameValue}
              />
              <div className="mt-5 flex justify-end gap-2">
                <Button
                  disabled={renameConversation.isPending}
                  onClick={() => setPendingRename(null)}
                  size="md"
                  variant="ghost"
                >
                  取消
                </Button>
                <Button
                  disabled={
                    renameConversation.isPending || !renameValue.trim()
                  }
                  onClick={confirmRename}
                  size="md"
                >
                  {renameConversation.isPending ? "保存中…" : "保存"}
                </Button>
              </div>
            </>
          ) : (
            <>
              <DialogTitle className="text-base font-semibold text-[var(--color-text)]">
                删除会话
              </DialogTitle>
              <DialogDescription className="mt-2 text-sm leading-6 text-[var(--color-text-muted)]">
                将删除「{pendingDelete?.title ?? ""}」及其全部生成视频与参考图片资产，且不可恢复。
              </DialogDescription>
              <div className="mt-5 flex justify-end gap-2">
                <Button
                  disabled={deleteConversation.isPending}
                  onClick={() => setPendingDelete(null)}
                  size="md"
                  variant="ghost"
                >
                  取消
                </Button>
                <Button
                  className="bg-[var(--color-danger)] text-white shadow-sm hover:bg-[var(--color-danger)] hover:brightness-110 focus-visible:ring-2 focus-visible:ring-[var(--color-danger)]/30"
                  disabled={deleteConversation.isPending}
                  onClick={confirmDelete}
                  size="md"
                >
                  {deleteConversation.isPending ? "删除中…" : "确认删除"}
                </Button>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
