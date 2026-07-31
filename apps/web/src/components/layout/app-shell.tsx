import {
  CircleUserRound,
  Clapperboard,
  Images,
  Lightbulb,
} from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";

import { cn } from "@/lib/utils";

const navigation = [
  { to: "/inspiration", label: "灵感", icon: Lightbulb },
  { to: "/create", label: "生成", icon: Clapperboard },
  { to: "/assets", label: "资产", icon: Images },
];

export function AppShell() {
  return (
    <div className="min-h-screen bg-[var(--color-canvas)] text-[var(--color-text)]">
      <header className="sticky top-0 z-40 flex h-14 items-center border-b border-[var(--color-border)] bg-white/95 px-4 backdrop-blur-sm md:px-6">
        <NavLink
          aria-label="Oneiroi Studio 首页"
          className="mr-5 flex shrink-0 items-center gap-2.5 font-semibold tracking-[-0.02em]"
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

        <nav aria-label="主导航" className="flex h-full items-center gap-1">
          {navigation.map(({ icon: Icon, label, to }) => (
            <NavLink
              className={({ isActive }) =>
                cn(
                  "relative flex h-full items-center gap-2 px-3 text-sm text-[var(--color-text-muted)] transition-colors hover:text-[var(--color-text)]",
                  isActive &&
                    "font-medium text-[var(--color-text)] after:absolute after:inset-x-3 after:bottom-0 after:h-0.5 after:bg-[var(--color-accent)]",
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

        <button
          aria-label="打开账户菜单"
          className="ml-auto grid size-9 place-items-center rounded-md text-[var(--color-text-muted)] hover:bg-[var(--color-surface-muted)] hover:text-[var(--color-text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)]"
          type="button"
        >
          <CircleUserRound aria-hidden="true" className="size-5" />
        </button>
      </header>
      <Outlet />
    </div>
  );
}
