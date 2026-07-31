import { motion, useReducedMotion } from "motion/react";
import type { PropsWithChildren } from "react";

import { cn } from "@/lib/utils";

export function PageTransition({
  children,
  className,
}: PropsWithChildren<{ className?: string }>) {
  const reduceMotion = useReducedMotion();

  return (
    <motion.div
      animate={{ opacity: 1, y: 0 }}
      className={cn("min-h-0 flex-1", className)}
      exit={reduceMotion ? undefined : { opacity: 0, y: -4 }}
      initial={reduceMotion ? false : { opacity: 0, y: 8 }}
      transition={{ duration: reduceMotion ? 0 : 0.48, ease: [0.2, 0.8, 0.2, 1] }}
    >
      {children}
    </motion.div>
  );
}
