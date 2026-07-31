import { Clock3, PanelLeftClose, Plus, Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useWorkspaceStore } from "@/store/workspace-store";

const conversations = [
  { id: "draft", name: "未命名创作", meta: "刚刚" },
  { id: "product", name: "产品片段", meta: "昨天" },
  { id: "character", name: "角色镜头", meta: "3 天前" },
];

export function WorkspaceSidebar() {
  const sidebarOpen = useWorkspaceStore((state) => state.sidebarOpen);
  const setSidebarOpen = useWorkspaceStore((state) => state.setSidebarOpen);

  return (
    <aside
      className={cn(
        "absolute inset-y-0 left-0 z-30 w-64 border-r border-[var(--color-border)] bg-[var(--color-sidebar)] transition-transform md:static md:translate-x-0",
        sidebarOpen ? "translate-x-0" : "-translate-x-full md:hidden",
      )}
    >
      <div className="flex h-full flex-col p-3">
        <div className="flex items-center gap-2">
          <Button className="flex-1 justify-start" variant="primary">
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
            placeholder="搜索会话"
            type="search"
          />
        </label>

        <div className="mt-5 flex items-center gap-2 px-2 text-xs font-medium uppercase tracking-wide text-[var(--color-text-faint)]">
          <Clock3 aria-hidden="true" className="size-3.5" />
          最近会话
        </div>
        <ul className="mt-2 space-y-0.5">
          {conversations.map((conversation, index) => (
            <li key={conversation.id}>
              <button
                className={cn(
                  "w-full rounded-md px-2 py-2 text-left hover:bg-white/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)]",
                  index === 0 && "bg-white shadow-[var(--shadow-card)]",
                )}
                type="button"
              >
                <span className="block truncate text-sm">{conversation.name}</span>
                <span className="mt-0.5 block text-xs text-[var(--color-text-faint)]">
                  {conversation.meta}
                </span>
              </button>
            </li>
          ))}
        </ul>

        <div className="mt-auto rounded-md border border-[var(--color-border)] bg-white/70 p-3 text-xs text-[var(--color-text-muted)]">
          <div className="flex items-center justify-between">
            <span>当前队列</span>
            <span className="font-medium text-[var(--color-success)]">可用</span>
          </div>
          <p className="mt-1 text-[var(--color-text-faint)]">Fast 0 等待 · HQ 0 等待</p>
        </div>
      </div>
    </aside>
  );
}
