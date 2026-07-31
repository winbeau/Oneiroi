import { useQuery } from "@tanstack/react-query";
import {
  CircleUserRound,
  Clapperboard,
  Images,
  Lightbulb,
  LogOut,
  MoonStar,
  Settings,
  Sparkles,
} from "lucide-react";
import { AnimatePresence, LayoutGroup, motion } from "motion/react";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { LayoutPill } from "@/components/motion/layout-pill";
import { PageTransition } from "@/components/motion/page-transition";
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
];

export function AppShell() {
  const location = useLocation();
  const [accountOpen, setAccountOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
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
            className="relative grid size-8 place-items-center overflow-hidden rounded-[10px] bg-[var(--color-text)] text-white shadow-[0_5px_14px_rgba(48,46,42,0.16)]"
            transition={{ duration: 0.22, ease: [0.2, 0.8, 0.2, 1] }}
            whileHover={{ rotate: -3, scale: 1.04 }}
          >
            <MoonStar className="size-4" strokeWidth={1.8} />
            <span className="absolute right-1.5 top-1.5 size-1 rounded-full bg-[#bcb4ff]" />
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
                    <span>{label}</span>
                  </>
                )}
              </NavLink>
            ))}
          </nav>
        </LayoutGroup>

        <div className="ml-auto flex items-center gap-1.5">
          <span
            aria-label={health.isSuccess ? "服务已连接" : "浏览器演示模式"}
            className="grid size-8 place-items-center rounded-full text-[var(--color-text-muted)]"
            role="status"
            title={health.isSuccess ? `BFF ${health.data.version} 已连接` : "当前使用浏览器演示任务流"}
          >
            <span className="relative flex size-2.5">
              {!health.isSuccess && (
                <span className="absolute inline-flex size-full animate-ping rounded-full bg-amber-400/55" />
              )}
              <span
                className={cn(
                  "relative inline-flex size-2.5 rounded-full ring-2 ring-white",
                  health.isSuccess ? "bg-[var(--color-success)]" : "bg-amber-400",
                )}
              />
            </span>
          </span>

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
