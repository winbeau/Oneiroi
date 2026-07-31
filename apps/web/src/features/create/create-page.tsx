import {
  ChevronDown,
  ImagePlus,
  PanelLeftOpen,
  Send,
  SlidersHorizontal,
  Sparkles,
} from "lucide-react";

import { WorkspaceSidebar } from "@/components/layout/workspace-sidebar";
import { Button } from "@/components/ui/button";
import { useWorkspaceStore } from "@/store/workspace-store";

const parameters = ["I2V", "快速", "16:9", "720p", "5 秒"];

export function CreatePage() {
  const sidebarOpen = useWorkspaceStore((state) => state.sidebarOpen);
  const setSidebarOpen = useWorkspaceStore((state) => state.setSidebarOpen);

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
            <h1 className="truncate text-sm font-medium">未命名创作</h1>
            <p className="text-xs text-[var(--color-text-faint)]">草稿 · 尚未提交任务</p>
          </div>
          <button
            className="ml-auto rounded-md px-2 py-1 text-sm text-[var(--color-text-muted)] hover:bg-[var(--color-surface-muted)]"
            type="button"
          >
            任务详情
          </button>
        </header>

        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
          <div className="mx-auto flex w-full max-w-3xl flex-1 items-center justify-center px-5 py-10">
            <div className="max-w-xl text-center">
              <div className="mx-auto grid size-11 place-items-center rounded-lg border border-[var(--color-border)] bg-[var(--color-sidebar)] text-[var(--color-accent)]">
                <Sparkles aria-hidden="true" className="size-5" />
              </div>
              <h2 className="mt-5 text-2xl font-semibold tracking-[-0.025em]">
                把一张图片变成一段镜头
              </h2>
              <p className="mt-3 text-sm leading-6 text-[var(--color-text-muted)]">
                上传单张参考图，描述运动、镜头和氛围。任务提交后，阶段、进度、排队位置与错误信息会持续显示在会话中。
              </p>
            </div>
          </div>

          <div className="sticky bottom-0 bg-gradient-to-t from-white via-white to-transparent px-4 pb-4 pt-8 md:px-6 md:pb-6">
            <form className="mx-auto max-w-3xl rounded-xl border border-[var(--color-border-strong)] bg-white p-3 shadow-[0_8px_30px_rgba(55,53,47,0.08)]">
              <div className="flex gap-3">
                <label className="grid size-14 shrink-0 cursor-pointer place-items-center rounded-lg border border-dashed border-[var(--color-border-strong)] bg-[var(--color-sidebar)] text-[var(--color-text-faint)] hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]">
                  <span className="sr-only">上传一张参考图片</span>
                  <ImagePlus aria-hidden="true" className="size-5" />
                  <input accept="image/*" className="sr-only" type="file" />
                </label>
                <label className="min-w-0 flex-1">
                  <span className="sr-only">生成提示词</span>
                  <textarea
                    className="min-h-14 w-full resize-none bg-transparent px-1 py-1 text-sm leading-6 outline-none placeholder:text-[var(--color-text-faint)]"
                    placeholder="描述你希望画面如何运动，例如：镜头缓慢向前推进，人物轻微抬头，衣角随风摆动……"
                    rows={2}
                  />
                </label>
              </div>

              <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-[var(--color-border)] pt-3">
                {parameters.map((parameter) => (
                  <button
                    className="inline-flex h-8 items-center gap-1 rounded-md bg-[var(--color-surface-muted)] px-2.5 text-xs font-medium text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
                    key={parameter}
                    type="button"
                  >
                    {parameter}
                    <ChevronDown aria-hidden="true" className="size-3" />
                  </button>
                ))}
                <button
                  aria-label="打开高级参数"
                  className="grid size-8 place-items-center rounded-md text-[var(--color-text-muted)] hover:bg-[var(--color-surface-muted)] hover:text-[var(--color-text)]"
                  type="button"
                >
                  <SlidersHorizontal aria-hidden="true" className="size-4" />
                </button>
                <span className="ml-auto hidden text-xs text-[var(--color-text-faint)] sm:inline">
                  Fast 队列当前无需等待
                </span>
                <Button aria-label="提交生成任务" size="icon" type="submit" variant="primary">
                  <Send aria-hidden="true" className="size-4" />
                </Button>
              </div>
            </form>
          </div>
        </div>
      </section>
    </main>
  );
}
