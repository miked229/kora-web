import { Card } from "@/components/ui";
import { cn } from "@/lib/utils";

export function MetricCard({
  label,
  value,
  hint,
  accent = "ocean",
}: {
  label: string;
  value: string | number;
  hint?: string;
  accent?: "ocean" | "turquoise" | "gold";
}) {
  const accents: Record<string, string> = {
    ocean: "text-ocean-700",
    turquoise: "text-turquoise-600",
    gold: "text-gold-500",
  };
  return (
    <Card>
      <div className="text-sm text-ocean-500">{label}</div>
      <div className={cn("mt-2 font-serif text-3xl font-semibold", accents[accent])}>
        {value}
      </div>
      {hint && <div className="mt-1 text-xs text-ocean-400">{hint}</div>}
    </Card>
  );
}
