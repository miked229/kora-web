import { getMemberSession } from "@/lib/auth/session";
import { createAdminClient } from "@/lib/supabase/admin";
import { Card, Badge } from "@/components/ui";
import { formatDate } from "@/lib/utils";
import { NewTicketForm } from "@/components/portal/NewTicketForm";

export const dynamic = "force-dynamic";

const statusTone: Record<string, "ocean" | "turquoise" | "gold" | "red" | "green"> = {
  new: "gold",
  open: "turquoise",
  pending: "gold",
  escalated: "red",
  resolved: "green",
  closed: "ocean",
};

const priorityTone: Record<string, "ocean" | "gold" | "red"> = {
  low: "ocean",
  medium: "gold",
  high: "gold",
  urgent: "red",
};

export default async function TicketsPage() {
  const session = getMemberSession()!;
  const supabase = createAdminClient();
  const { data: tickets } = await supabase
    .from("tickets")
    .select("*")
    .eq("member_id", session.member_id)
    .order("created_at", { ascending: false });

  const list = tickets ?? [];

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <header>
        <h1 className="text-3xl font-semibold">Mis tickets</h1>
        <p className="text-ocean-600">Da seguimiento a tus solicitudes de soporte.</p>
      </header>

      <NewTicketForm />

      <div className="space-y-3">
        {list.map((t) => (
          <Card key={t.id} className="flex items-start justify-between gap-4">
            <div>
              <h3 className="font-semibold">{t.subject}</h3>
              {t.description && (
                <p className="mt-1 line-clamp-2 text-sm text-ocean-600">{t.description}</p>
              )}
              <p className="mt-2 text-xs text-ocean-500">
                {t.category} · creado el {formatDate(t.created_at)}
              </p>
            </div>
            <div className="flex shrink-0 flex-col items-end gap-2">
              <Badge tone={statusTone[t.status] ?? "ocean"}>{t.status}</Badge>
              <Badge tone={priorityTone[t.priority] ?? "ocean"}>{t.priority}</Badge>
            </div>
          </Card>
        ))}
        {list.length === 0 && (
          <Card>
            <p className="text-ocean-600">No tienes tickets. ¡Todo en orden! 🌊</p>
          </Card>
        )}
      </div>
    </div>
  );
}
