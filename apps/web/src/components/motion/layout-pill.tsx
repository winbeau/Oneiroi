import { motion } from "motion/react";

export function LayoutPill({ id = "active-pill" }: { id?: string }) {
  return (
    <motion.span
      aria-hidden="true"
      className="absolute inset-0 -z-10 rounded-[var(--radius-sm)] bg-white shadow-[0_1px_2px_rgba(48,46,42,0.06)] ring-1 ring-[var(--color-border)]"
      layoutId={id}
      transition={{ duration: 0.28, ease: [0.2, 0.8, 0.2, 1] }}
    />
  );
}
