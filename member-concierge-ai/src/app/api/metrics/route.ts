import { createClient } from "@/lib/supabase/server";
import { createAdminClient } from "@/lib/supabase/admin";
import { jsonError, jsonOk } from "@/lib/utils";

export const runtime = "nodejs";

/**
 * KPIs del dashboard administrativo. Requiere staff autenticado (Supabase Auth).
 */
export async function GET() {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return jsonError("No autenticado", 401);

  const { data: agent } = await supabase
    .from("agents")
    .select("role, active")
    .eq("id", user.id)
    .maybeSingle();
  if (!agent?.active) return jsonError("Acceso restringido", 403);

  // Agregaciones con cliente admin (lecturas de sistema).
  const admin = createAdminClient();
  const since = new Date(Date.now() - 30 * 86_400_000).toISOString();

  const [conversations, tickets, openTickets, opportunities, escalated] = await Promise.all([
    admin.from("conversations").select("id", { count: "exact", head: true }).gte("created_at", since),
    admin.from("tickets").select("id", { count: "exact", head: true }).gte("created_at", since),
    admin.from("tickets").select("id", { count: "exact", head: true }).in("status", ["new", "open", "pending", "escalated"]),
    admin.from("sales_opportunities").select("id", { count: "exact", head: true }).gte("created_at", since),
    admin.from("conversations").select("id", { count: "exact", head: true }).eq("status", "assigned").gte("created_at", since),
  ]);

  const totalConversations = conversations.count ?? 0;
  const escalatedCount = escalated.count ?? 0;
  const automationRate =
    totalConversations > 0
      ? Math.round(((totalConversations - escalatedCount) / totalConversations) * 100)
      : 0;

  return jsonOk({
    period_days: 30,
    conversations: totalConversations,
    tickets: tickets.count ?? 0,
    open_tickets: openTickets.count ?? 0,
    sales_opportunities: opportunities.count ?? 0,
    escalated: escalatedCount,
    automation_rate: automationRate,
  });
}
