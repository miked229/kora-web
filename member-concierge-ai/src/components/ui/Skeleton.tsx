import { cn } from "@/lib/utils";

/** Bloque de carga con efecto shimmer, en tono arena. */
export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-xl bg-sand-200/70", className)} />;
}
