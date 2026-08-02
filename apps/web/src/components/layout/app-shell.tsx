import { useQuery } from "@tanstack/react-query";
import {
  CircleUserRound,
  Clapperboard,
  Cpu,
  Images,
  Lightbulb,
  LogOut,
  Moon,
  Settings,
  Sparkle,
  Sparkles,
} from "lucide-react";
import { AnimatePresence, LayoutGroup, motion } from "motion/react";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { LayoutPill } from "@/components/motion/layout-pill";
import { PageTransition } from "@/components/motion/page-transition";
import { ComputeSessionSync } from "@/features/compute/compute-session-sync";
import { useComputeSession } from "@/features/compute/hooks";
import { apiRequest } from "@/lib/api-client";
import { cn } from "@/lib/utils";

type ServiceHealth = {
  service: string;
  version: string;
};

const navigation = [
  { to: "/inspiration", label: "灵感", icon: Lightbulb },
  { to: "/create", label: "生成", icon: Clapperboard },
  { to: "/assets", label: "资产", icon: Images },
  { to: "/compute", label: "算力", icon: Cpu },
];

export function AppShell() {
  const location = useLocation();
  const [accountOpen, setAccountOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const compute = useComputeSession();
  const computeSession = compute.data;
  const computeReady = Boolean(
    computeSession && ["ready", "degraded"].includes(computeSession.state),
  );
  const computeLabel = computeReady
    ? `${computeSession?.allocatedGpuCount ?? 0} 张 H100 · Fast ${computeSession?.profilePlan.fast ?? 0} / HQ ${computeSession?.profilePlan.hq ?? 0}`
    : computeSession && ["requested", "allocating", "loading"].includes(computeSession.state)
      ? "算力加载中"
      : computeSession && ["draining", "releasing"].includes(computeSession.state)
        ? "算力释放中"
        : "算力未加载";
  const computeCompactLabel = computeReady
    ? `${computeSession?.allocatedGpuCount ?? 0} H100 · F${computeSession?.profilePlan.fast ?? 0}/H${computeSession?.profilePlan.hq ?? 0}`
    : computeLabel;
  const health = useQuery({
    queryKey: ["system", "health"],
    queryFn: () => apiRequest<ServiceHealth>("/healthz"),
    retry: false,
  });

  useEffect(() => {
    const update = () => setScrolled(window.scrollY > 8);
    update();
    window.addEventListener("scroll", update, { passive: true });
    return () => window.removeEventListener("scroll", update);
  }, []);

  return (
    <div className="flex min-h-screen flex-col bg-[var(--color-canvas)] text-[var(--color-text)]">
      <ComputeSessionSync />
      <header
        className={cn(
          "sticky top-0 z-50 flex h-[60px] shrink-0 items-center border-b px-3 transition-[background-color,box-shadow,border-color] duration-300 md:px-6",
          scrolled
            ? "border-[var(--color-border)] bg-[var(--color-canvas)]/88 shadow-[0_6px_22px_rgba(48,46,42,0.05)] backdrop-blur-xl"
            : "border-transparent bg-[var(--color-canvas)]/72 backdrop-blur-lg",
        )}
      >
        <NavLink
          aria-label="Oneiroi Studio 首页"
          className="group mr-3 flex shrink-0 items-center gap-2.5 md:mr-7"
          onClick={() => setAccountOpen(false)}
          to="/create"
        >
          <motion.span
            aria-hidden="true"
            className="relative grid size-8 place-items-center text-[var(--color-text)]"
            transition={{ duration: 0.22, ease: [0.2, 0.8, 0.2, 1] }}
            whileHover={{ rotate: -3, scale: 1.04 }}
          >
            <Moon className="size-4 -translate-x-px translate-y-px" strokeWidth={1.8} />
            <Sparkle
              className="absolute right-[5px] top-[5px] size-2.5 fill-[#f6cf68]/20 text-[#f6cf68] drop-shadow-[0_0_4px_rgba(246,207,104,0.9)]"
              strokeWidth={2.1}
            />
          </motion.span>
          <span className="hidden leading-none sm:block">
            <span className="block text-sm font-semibold tracking-[-0.025em]">Oneiroi</span>
            <span className="mt-1 block text-[9px] font-medium uppercase tracking-[0.18em] text-[var(--color-text-faint)]">
              Studio
            </span>
          </span>
        </NavLink>

        <LayoutGroup id="main-navigation">
          <nav
            aria-label="主导航"
            className="flex h-10 min-w-0 items-center gap-0.5 rounded-lg bg-[var(--color-surface-muted)]/72 p-1"
          >
            {navigation.map(({ icon: Icon, label, to }) => (
              <NavLink
                aria-label={label}
                className={({ isActive }) =>
                  cn(
                    "relative isolate flex h-8 items-center gap-1.5 rounded-[var(--radius-sm)] px-2.5 text-sm font-medium transition-colors duration-200 sm:gap-2 sm:px-3",
                    isActive
                      ? "text-[var(--color-text)]"
                      : "text-[var(--color-text-muted)] hover:text-[var(--color-text)]",
                  )
                }
                key={to}
                onClick={() => setAccountOpen(false)}
                to={to}
              >
                {({ isActive }) => (
                  <>
                    {isActive && <LayoutPill id="main-nav-pill" />}
                    <Icon aria-hidden="true" className="size-3.5" strokeWidth={1.8} />
                    <span className="hidden sm:inline">{label}</span>
                  </>
                )}
              </NavLink>
            ))}
          </nav>
        </LayoutGroup>

        <div className="ml-auto flex items-center gap-1.5">
          <NavLink
            aria-label={computeLabel}
            className="group flex h-9 min-w-0 items-center gap-2 rounded-lg px-2 text-[var(--color-text-muted)] transition hover:bg-[var(--color-surface-muted)] hover:text-[var(--color-text)] sm:px-2.5"
            onClick={() => setAccountOpen(false)}
            title={computeLabel}
            to="/compute"
          >
            <span className="block max-w-[104px] truncate text-[9px] font-medium sm:hidden">
              {computeCompactLabel}
            </span>
            <span className="hidden max-w-[250px] truncate text-[11px] font-medium sm:block">
              {computeLabel}
            </span>
            <span className="relative flex size-2.5 shrink-0" role="status">
              <span
                className={cn(
                  "relative inline-flex size-2.5 rounded-full ring-2 ring-white transition-colors",
                  computeReady ? "bg-[var(--color-success)]" : "bg-[var(--color-danger)]",
                )}
              />
            </span>
          </NavLink>

          <div className="relative">
            <button
              aria-expanded={accountOpen}
              aria-label="打开账户菜单"
              className="grid size-9 place-items-center rounded-full text-[var(--color-text-muted)] transition hover:bg-[var(--color-surface-muted)] hover:text-[var(--color-text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)]/35"
              onClick={() => setAccountOpen((value) => !value)}
              type="button"
            >
              <CircleUserRound aria-hidden="true" className="size-5" strokeWidth={1.7} />
            </button>
            <AnimatePresence>
              {accountOpen && (
                <motion.div
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  className="absolute right-0 top-11 w-64 origin-top-right rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-white/96 p-2 shadow-[var(--shadow-menu)] backdrop-blur-xl"
                  exit={{ opacity: 0, y: -4, scale: 0.98 }}
                  initial={{ opacity: 0, y: -4, scale: 0.98 }}
                  transition={{ duration: 0.16, ease: [0.2, 0.8, 0.2, 1] }}
                >
                  <div className="rounded-lg bg-[var(--color-surface-muted)]/70 px-3 py-3">
                    <div className="flex items-center gap-2">
                      <span className="grid size-8 place-items-center rounded-full bg-[var(--color-accent-soft)] text-[var(--color-accent)]">
                        <Sparkles aria-hidden="true" className="size-3.5" />
                      </span>
                      <div>
                        <p className="text-sm font-medium">内部创作者</p>
                        <p className="mt-0.5 text-[11px] text-[var(--color-text-faint)]">
                          demo@oneiroi.local
                        </p>
                      </div>
                    </div>
                    <p className="mt-3 flex items-center gap-2 text-xs text-[var(--color-text-muted)]">
                      <span
                        className={cn(
                          "size-1.5 rounded-full",
                          health.isSuccess ? "bg-[var(--color-success)]" : "bg-amber-400",
                        )}
                      />
                      {health.isSuccess ? "工作区服务已连接" : "演示任务流已启用"}
                    </p>
                  </div>
                  <button
                    className="mt-1 flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm text-[var(--color-text-muted)] transition hover:bg-[var(--color-surface-muted)] hover:text-[var(--color-text)]"
                    type="button"
                  >
                    <Settings aria-hidden="true" className="size-4" />
                    工作区设置
                  </button>
                  <button
                    className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm text-[var(--color-text-muted)] transition hover:bg-[var(--color-surface-muted)] hover:text-[var(--color-text)]"
                    type="button"
                  >
                    <LogOut aria-hidden="true" className="size-4" />
                    退出登录
                  </button>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>
      </header>

      <AnimatePresence initial={false} mode="wait">
        <PageTransition className="flex flex-col" key={location.pathname}>
          <Outlet />
        </PageTransition>
      </AnimatePresence>
    </div>
  );
}
