import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import {
  forwardRef,
  type ButtonHTMLAttributes,
  type ElementRef,
} from "react";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-[var(--radius-sm)] text-sm font-medium transition-[color,background-color,border-color,box-shadow,transform] duration-200 ease-[var(--ease-out-expo)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)]/35 focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--color-canvas)] active:translate-y-px disabled:pointer-events-none disabled:opacity-45",
  {
    variants: {
      variant: {
        primary:
          "border border-transparent bg-[var(--color-accent)] text-white shadow-[0_1px_2px_rgba(55,48,126,0.22)] hover:-translate-y-0.5 hover:bg-[var(--color-accent-hover)] hover:shadow-[0_7px_18px_rgba(87,77,189,0.20)]",
        secondary:
          "border border-[var(--color-border-strong)] bg-white/90 text-[var(--color-text)] shadow-[var(--shadow-card)] hover:-translate-y-0.5 hover:bg-white hover:shadow-[0_6px_16px_rgba(48,46,42,0.08)]",
        ghost:
          "text-[var(--color-text-muted)] hover:bg-[var(--color-surface-muted)] hover:text-[var(--color-text)]",
      },
      size: {
        sm: "h-8 px-3 text-xs",
        md: "h-9 px-4",
        icon: "size-9",
      },
    },
    defaultVariants: {
      variant: "secondary",
      size: "md",
    },
  },
);

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean;
  };

export const Button = forwardRef<ElementRef<"button">, ButtonProps>(
  ({ asChild = false, className, size, variant, ...props }, ref) => {
    const Component = asChild ? Slot : "button";

    return (
      <Component
        className={cn(buttonVariants({ size, variant }), className)}
        ref={ref}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";
