import { useQuery } from "@tanstack/react-query";
import {
  CircleUserRound,
  Clapperboard,
  Images,
  Lightbulb,
  LogOut,
  Settings,
} from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";

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
  const [accountOpen, setAccountOpen] = useState(false);
  const health = useQuery({
    queryKey: ["system", "health"],
    queryFn: () => apiRequest<ServiceHealth>("/healthz"),
    retry: false,
  });

  return (
    <div className="min-h-screen bg-[var(--color-canvas)] text-[var(--color-text)]">
      <header className="sticky top-0 z-40 flex h-14 items-center border-b border-[var(--color-border)] bg-white/95 px-3 backdrop-blur-sm md:px-6">
        <NavLink
          aria-label="Oneiroi Studio 首页"
          className="mr-3 flex shrink-0 items-center gap-2.5 font-semibold tracking-[-0.02em] md:mr-5"
          to="/create"
        >
          <span
            aria-hidden="true"
            className="grid size-7 place-items-center rounded-md bg-[var(--color-text)] text-xs text-white"
          >
            O
          </span>
          <span className="hidden sm:inline">Oneiroi Studio</span>
        </NavLink>

        <nav aria-label="主导航" className="flex h-full min-w-0 items-center gap-0.5 sm:gap-1">
          {navigation.map(({ icon: Icon, label, to }) => (
            <NavLink
              className={({ isActive }) =>
                cn(
                  "relative flex h-full items-center gap-1.5 px-2 text-sm text-[var(--color-text-muted)] transition-colors hover:text-[var(--color-text)] sm:gap-2 sm:px-3",
                  isActive &&
                    "font-medium text-[var(--color-text)] after:absolute after:inset-x-2 after:bottom-0 after:h-0.5 after:bg-[var(--color-accent)] sm:after:inset-x-3",
                )
              }
              key={to}
              to={to}
            >
              <Icon aria-hidden="true" className="size-4" />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-2">
          <span
            className="hidden items-center gap-1.5 text-xs text-[var(--color-text-faint)] lg:flex"
            title={health.isSuccess ? `BFF ${health.data.version}` : "当前使用浏览器演示数据"}
          >
            <span
              className={cn(
                "size-1.5 rounded-full",
                health.isSuccess ? "bg-[var(--color-success)]" : "bg-amber-400",
              )}
            />
            {health.isSuccess ? "服务已连接" : "演示模式"}
          </span>
          <div className="relative">
            <button
              aria-expanded={accountOpen}
              aria-label="打开账户菜单"
              className="grid size-9 place-items-center rounded-md text-[var(--color-text-muted)] hover:bg-[var(--color-surface-muted)] hover:text-[var(--color-text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)]"
              onClick={() => setAccountOpen((value) => !value)}
              type="button"
            >
              <CircleUserRound aria-hidden="true" className="size-5" />
            </button>
            {accountOpen && (
              <div className="absolute right-0 top-11 w-56 rounded-lg border border-[var(--color-border)] bg-white p-2 shadow-lg">
                <div className="border-b border-[var(--color-border)] px-2 py-2">
                  <p className="text-sm font-medium">内部创作者</p>
                  <p className="mt-0.5 text-xs text-[var(--color-text-faint)]">demo@oneiroi.local</p>
                </div>
                <button
                  className="mt-1 flex w-full items-center gap-2 rounded-md px-2 py-2 text-sm text-[var(--color-text-muted)] hover:bg-[var(--color-surface-muted)]"
                  type="button"
                >
                  <Settings aria-hidden="true" className="size-4" />
                  工作区设置
                </button>
                <button
                  className="flex w-full items-center gap-2 rounded-md px-2 py-2 text-sm text-[var(--color-text-muted)] hover:bg-[var(--color-surface-muted)]"
                  type="button"
                >
                  <LogOut aria-hidden="true" className="size-4" />
                  退出登录
                </button>
              </div>
            )}
          </div>
        </div>
      </header>
      <Outlet />
    </div>
  );
}
