import { createAdminClient } from "@/lib/supabase/admin";
import { MetricCard } from "@/components/admin/MetricCard";
import { Card, Badge } from "@/components/ui";

export const dynamic = "force-dynamic";

/**
 * Panel de métricas. Lee agregados directamente (server component con cliente
 * admin). La API `/api/metrics` expone los mismos KPIs para integraciones.
 */
export default async function AdminDashboard() {
  const admin = createAdminClient();
  const since = new Date(Date.now() - 30 * 86_400_000).toISOString();

  const [conv, tickets, openT, opps, escalated, recentTickets] = await Promise.all([
    admin.from("conversations").select("id", { count: "exact", head: true }).gte("created_at", since),
    admin.from("tickets").select("id", { count: "exact", head: true }).gte("created_at", since),
    admin.from("tickets").select("id", { count: "exact", head: true }).in("status", ["new", "open", "pending", "escalated"]),
    admin.from("sales_opportunities").select("id", { count: "exact", head: true }).gte("created_at", since),
    admin.from("conversations").select("id", { count: "exact", head: true }).eq("status", "assigned").gte("created_at", since),
    admin.from("tickets").select("id, subject, category, priority, status, created_at").order("created_at", { ascending: false }).limit(8),
  ]);

  const totalConv = conv.count ?? 0;
  const escalatedCount = escalated.count ?? 0;
  const automationRate =
    totalConv > 0 ? Math.round(((totalConv - escalatedCount) / totalConv) * 100) : 0;

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <header>
        <h1 className="text-3xl font-semibold">Métricas y analítica</h1>
        <p className="text-ocean-600">Resumen de los últimos 30 días.</p>
      </header>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard label="Conversaciones" value={totalConv} accent="ocean" />
        <MetricCard
          label="Tasa de automatización"
          value={`${automationRate}%`}
          hint="Resueltas sin asesor humano"
          accent="turquoise"
        />
        <MetricCard label="Tickets abiertos" value={openT.count ?? 0} accent="gold" />
        <MetricCard
          label="Oportunidades de venta"
          value={opps.count ?? 0}
          hint="Detectadas por IA"
          accent="gold"
        />
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <MetricCard label="Tickets (30d)" value={tickets.count ?? 0} />
        <MetricCard label="Escalamientos" value={escalatedCount} accent="turquoise" />
        <MetricCard
          label="Resueltas por IA"
          value={Math.max(0, totalConv - escalatedCount)}
          accent="ocean"
        />
      </div>

      <Card>
        <h2 className="mb-4 text-lg font-semibold">Tickets recientes</h2>
        <div className="divide-y divide-sand-200">
          {(recentTickets.data ?? []).map((t) => (
            <div key={t.id} className="flex items-center justify-between py-3">
              <div>
                <div className="font-medium">{t.subject}</div>
                <div className="text-xs text-ocean-500">{t.category}</div>
              </div>
              <div className="flex items-center gap-2">
                <Badge tone={t.priority === "urgent" ? "red" : "gold"}>{t.priority}</Badge>
                <Badge tone="ocean">{t.status}</Badge>
              </div>
            </div>
          ))}
          {(recentTickets.data ?? []).length === 0 && (
            <p className="py-3 text-sm text-ocean-500">Sin tickets aún.</p>
          )}
        </div>
      </Card>
    </div>
  );
}
