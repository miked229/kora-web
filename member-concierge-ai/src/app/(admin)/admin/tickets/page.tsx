import { createAdminClient } from "@/lib/supabase/admin";
import { Card, Badge } from "@/components/ui";
import { formatDate } from "@/lib/utils";

export const dynamic = "force-dynamic";

const statusTone: Record<string, "ocean" | "turquoise" | "gold" | "red" | "green"> = {
  new: "gold",
  open: "turquoise",
  pending: "gold",
  escalated: "red",
  resolved: "green",
  closed: "ocean",
};

export default async function AdminTickets() {
  const admin = createAdminClient();
  const { data: tickets } = await admin
    .from("tickets")
    .select("id, subject, category, priority, status, sla_due_at, created_at, members(full_name, membership_no)")
    .order("created_at", { ascending: false })
    .limit(80);

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <header>
        <h1 className="text-3xl font-semibold">Tickets</h1>
        <p className="text-ocean-600">Cola de soporte con SLA y prioridad.</p>
      </header>

      <Card className="p-0">
        <table className="w-full text-sm">
          <thead className="border-b border-sand-200 text-left text-ocean-500">
            <tr>
              <th className="px-5 py-3 font-medium">Asunto</th>
              <th className="px-5 py-3 font-medium">Socio</th>
              <th className="px-5 py-3 font-medium">Prioridad</th>
              <th className="px-5 py-3 font-medium">Estado</th>
              <th className="px-5 py-3 font-medium">Creado</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-sand-100">
            {(tickets ?? []).map((t: any) => (
              <tr key={t.id} className="hover:bg-sand-50">
                <td className="px-5 py-3">
                  <div className="font-medium text-ocean-900">{t.subject}</div>
                  <div className="text-xs text-ocean-500">{t.category}</div>
                </td>
                <td className="px-5 py-3 text-ocean-700">{t.members?.full_name ?? "—"}</td>
                <td className="px-5 py-3">
                  <Badge tone={t.priority === "urgent" ? "red" : "gold"}>{t.priority}</Badge>
                </td>
                <td className="px-5 py-3">
                  <Badge tone={statusTone[t.status] ?? "ocean"}>{t.status}</Badge>
                </td>
                <td className="px-5 py-3 text-ocean-600">{formatDate(t.created_at)}</td>
              </tr>
            ))}
            {(tickets ?? []).length === 0 && (
              <tr>
                <td colSpan={5} className="px-5 py-6 text-center text-ocean-500">
                  Sin tickets en la cola.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
