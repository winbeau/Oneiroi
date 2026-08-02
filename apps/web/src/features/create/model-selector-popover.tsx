import { Box, Check, ChevronDown, Gauge, Zap } from "lucide-react";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import type { ProfileCapability, ProfileTier } from "@/features/studio/types";
import { cn } from "@/lib/utils";

const modelMeta = {
  fast: {
    label: "LTX 2.3 快速",
    description: "蒸馏版推理链路，适合快速迭代与较长时长。",
    icon: Zap,
  },
  hq: {
    label: "LTX 2.3 高质量",
    description: "Dev + 两阶段增强，优先细节、稳定性与最终质量。",
    icon: Gauge,
  },
} satisfies Record<ProfileTier, object>;

export function ModelSelectorPopover({
  profiles,
  value,
  onChange,
}: {
  profiles: ProfileCapability[];
  value: ProfileTier;
  onChange: (profile: ProfileCapability) => void;
}) {
  const selected = profiles.find((profile) => profile.tier === value);
  const selectedMeta = modelMeta[value] as {
    label: string;
    description: string;
    icon: typeof Zap;
  };

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          aria-label="选择 LTX 2.3 模型"
          className="inline-flex h-9 items-center gap-2 rounded-[5px] border border-[var(--color-border)] bg-white/78 px-3 text-xs font-medium transition hover:bg-white"
          type="button"
        >
          <Box className="size-3.5" /> {selectedMeta.label}
          <ChevronDown className="size-3" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[min(440px,calc(100vw-2rem))] p-2">
        <div className="px-2 pb-2 pt-1">
          <p className="text-xs font-semibold">选择模型 · LTX 2.3</p>
          <p className="mt-1 text-[10px] text-[var(--color-text-faint)]">
            模型规格和可用状态来自 Gateway capabilities。
          </p>
        </div>
        <div className="space-y-1">
          {profiles.map((profile) => {
            const resolutions = profile.resolutions ?? [];
            const durations = profile.durations ?? [];
            const durationLabel = durations.length
              ? durations.length > 2
                ? `${Math.min(...durations)}–${Math.max(...durations)} 秒`
                : `${durations.join("/")} 秒`
              : "—";
            const meta = modelMeta[profile.tier] as {
              label: string;
              description: string;
              icon: typeof Zap;
            };
            const Icon = meta.icon;
            const active = profile.tier === value;
            return (
              <button
                aria-disabled={!profile.available}
                className={cn(
                  "flex w-full items-start gap-3 rounded-[6px] px-3 py-3 text-left transition",
                  active ? "bg-[var(--color-accent-soft)]" : "hover:bg-[var(--color-surface-muted)]",
                  !profile.available && "cursor-not-allowed opacity-45",
                )}
                disabled={!profile.available}
                key={profile.id}
                onClick={() => onChange(profile)}
                type="button"
              >
                <span className="grid size-10 shrink-0 place-items-center rounded-[6px] border bg-white">
                  <Icon className="size-4" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold">{meta.label}</span>
                    <span className="rounded-full bg-[var(--color-surface-muted)] px-1.5 py-0.5 text-[8px] font-semibold text-[var(--color-text-muted)]">
                      {profile.available ? "READY" : "UNAVAILABLE"}
                    </span>
                  </span>
                  <span className="mt-1 block text-[11px] leading-5 text-[var(--color-text-muted)]">
                    {meta.description}
                  </span>
                  <span className="mt-1 block truncate font-mono text-[9px] text-[var(--color-text-faint)]">
                    {profile.id} · {resolutions.join("/")} · {durationLabel}
                  </span>
                  {!profile.available && profile.unavailableReason && (
                    <span className="mt-1 block text-[9px] text-[var(--color-warning)]">
                      {profile.unavailableReason}
                    </span>
                  )}
                </span>
                {active && <Check className="mt-1 size-4 shrink-0 text-[var(--color-accent)]" />}
              </button>
            );
          })}
          {profiles.length === 0 && (
            <p className="px-3 py-5 text-center text-xs text-[var(--color-text-muted)]">
              正在读取模型能力…
            </p>
          )}
        </div>
        {selected && !selected.available && (
          <p className="mx-2 mt-2 rounded-[5px] bg-[rgb(214_154_87_/_10%)] px-2.5 py-2 text-[10px] text-[var(--color-warning)]">
            当前选择尚未就绪，请前往“算力”页调整热加载资源。
          </p>
        )}
      </PopoverContent>
    </Popover>
  );
}
