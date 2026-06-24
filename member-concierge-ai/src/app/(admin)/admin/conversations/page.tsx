import { createAdminClient } from "@/lib/supabase/admin";
import { Card, Badge } from "@/components/ui";
import { formatDate } from "@/lib/utils";

export const dynamic = "force-dynamic";

const channelTone: Record<string, "ocean" | "turquoise" | "gold"> = {
  web: "ocean",
  whatsapp: "turquoise",
  email: "gold",
};

export default async function AdminConversations() {
  const admin = createAdminClient();
  const { data: conversations } = await admin
    .from("conversations")
    .select("id, channel, status, subject, last_message_at, member_id, members(full_name, membership_no)")
    .order("last_message_at", { ascending: false })
    .limit(50);

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <header>
        <h1 className="text-3xl font-semibold">Conversaciones</h1>
        <p className="text-ocean-600">Historial omnicanal unificado.</p>
      </header>

      <Card className="p-0">
        <table className="w-full text-sm">
          <thead className="border-b border-sand-200 text-left text-ocean-500">
            <tr>
              <th className="px-5 py-3 font-medium">Socio</th>
              <th className="px-5 py-3 font-medium">Canal</th>
              <th className="px-5 py-3 font-medium">Estado</th>
              <th className="px-5 py-3 font-medium">Último mensaje</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-sand-100">
            {(conversations ?? []).map((c: any) => (
              <tr key={c.id} className="hover:bg-sand-50">
                <td className="px-5 py-3">
                  <div className="font-medium text-ocean-900">
                    {c.members?.full_name ?? "—"}
                  </div>
                  <div className="text-xs text-ocean-500">{c.members?.membership_no ?? ""}</div>
                </td>
                <td className="px-5 py-3">
                  <Badge tone={channelTone[c.channel] ?? "ocean"}>{c.channel}</Badge>
                </td>
                <td className="px-5 py-3">
                  <Badge tone={c.status === "assigned" ? "red" : "green"}>{c.status}</Badge>
                </td>
                <td className="px-5 py-3 text-ocean-600">
                  {formatDate(c.last_message_at)}
                </td>
              </tr>
            ))}
            {(conversations ?? []).length === 0 && (
              <tr>
                <td colSpan={4} className="px-5 py-6 text-center text-ocean-500">
                  Aún no hay conversaciones.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
