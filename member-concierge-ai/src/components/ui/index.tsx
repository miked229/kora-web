import * as React from "react";
import { cn } from "@/lib/utils";

/** Botón premium con variantes. */
export function Button({
  className,
  variant = "primary",
  size = "md",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "gold";
  size?: "sm" | "md" | "lg";
}) {
  const variants: Record<string, string> = {
    primary: "bg-ocean-700 text-white hover:bg-ocean-800 shadow-premium",
    secondary: "bg-turquoise-500 text-white hover:bg-turquoise-600",
    ghost: "bg-transparent text-ocean-800 hover:bg-ocean-50",
    gold: "bg-gold-500 text-ocean-900 hover:bg-gold-600 font-semibold",
  };
  const sizes: Record<string, string> = {
    sm: "h-9 px-4 text-sm",
    md: "h-11 px-6 text-sm",
    lg: "h-12 px-8 text-base",
  };
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-xl font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-gold-400 focus:ring-offset-2 disabled:opacity-50 disabled:pointer-events-none",
        variants[variant],
        sizes[size],
        className,
      )}
      {...props}
    />
  );
}

export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("card p-6", className)} {...props} />;
}

export function Badge({
  className,
  tone = "ocean",
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & {
  tone?: "ocean" | "turquoise" | "gold" | "red" | "green";
}) {
  const tones: Record<string, string> = {
    ocean: "bg-ocean-100 text-ocean-800",
    turquoise: "bg-turquoise-100 text-turquoise-800",
    gold: "bg-gold-300/40 text-gold-600",
    red: "bg-red-100 text-red-700",
    green: "bg-emerald-100 text-emerald-700",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-3 py-1 text-xs font-medium",
        tones[tone],
        className,
      )}
      {...props}
    />
  );
}

export const Input = React.forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement>
>(function Input({ className, ...props }, ref) {
  return (
    <input
      ref={ref}
      className={cn(
        "h-11 w-full rounded-xl border border-sand-300 bg-white px-4 text-ocean-900 placeholder:text-ocean-300 focus:border-turquoise-400 focus:outline-none focus:ring-2 focus:ring-turquoise-200",
        className,
      )}
      {...props}
    />
  );
});
