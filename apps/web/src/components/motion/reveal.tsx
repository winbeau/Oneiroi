import { motion, useReducedMotion } from "motion/react";
import type { CSSProperties, PropsWithChildren } from "react";

import { cn } from "@/lib/utils";

export function Reveal({
  children,
  className,
  delay = 0,
  y = 14,
  style,
}: PropsWithChildren<{
  className?: string;
  delay?: number;
  y?: number;
  style?: CSSProperties;
}>) {
  const reduceMotion = useReducedMotion();

  return (
    <motion.div
      className={cn(className)}
      initial={reduceMotion ? false : { opacity: 0, y }}
      style={style}
      transition={{ duration: reduceMotion ? 0 : 0.56, delay, ease: [0.2, 0.8, 0.2, 1] }}
      viewport={{ amount: 0.16, once: true }}
      whileInView={{ opacity: 1, y: 0 }}
    >
      {children}
    </motion.div>
  );
}
