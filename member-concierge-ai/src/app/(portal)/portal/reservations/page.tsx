import { getMemberSession } from "@/lib/auth/session";
import { createAdminClient } from "@/lib/supabase/admin";
import { Card, Badge } from "@/components/ui";
import { formatDate } from "@/lib/utils";
import { ReservationActions } from "@/components/portal/ReservationActions";
import type { Reservation } from "@/lib/types";

export const dynamic = "force-dynamic";

const statusTone: Record<string, "ocean" | "turquoise" | "gold" | "red" | "green"> = {
  confirmed: "green",
  pending: "gold",
  changed: "turquoise",
  cancelled: "red",
  completed: "ocean",
};

export default async function ReservationsPage() {
  const session = getMemberSession()!;
  const supabase = createAdminClient();
  const { data } = await supabase
    .from("reservations")
    .select("*")
    .eq("member_id", session.member_id)
    .order("check_in", { ascending: true });

  const reservations = (data ?? []) as Reservation[];

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <header>
        <h1 className="text-3xl font-semibold">Mis reservaciones</h1>
        <p className="text-ocean-600">Consulta, cambia o cancela tus estancias.</p>
      </header>

      {reservations.length === 0 && (
        <Card>
          <p className="text-ocean-600">Aún no tienes reservaciones registradas.</p>
        </Card>
      )}

      <div className="space-y-4">
        {reservations.map((r) => (
          <Card key={r.id} className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div>
              <div className="flex items-center gap-3">
                <h3 className="text-lg font-semibold">{r.resort_name}</h3>
                <Badge tone={statusTone[r.status] ?? "ocean"}>{r.status}</Badge>
              </div>
              <p className="text-sm text-ocean-600">{r.room_type}</p>
              <p className="mt-1 text-sm text-ocean-700">
                {formatDate(r.check_in)} → {formatDate(r.check_out)} · {r.guests} huéspedes
              </p>
              {r.confirmation_code && (
                <p className="mt-1 text-xs text-ocean-500">Código: {r.confirmation_code}</p>
              )}
            </div>
            {!["cancelled", "completed"].includes(r.status) && (
              <ReservationActions reservationId={r.id} />
            )}
          </Card>
        ))}
      </div>
    </div>
  );
}
