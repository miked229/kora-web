import { z } from "zod";
import { getMemberSession } from "@/lib/auth/session";
import { createAdminClient } from "@/lib/supabase/admin";
import { jsonError, jsonOk } from "@/lib/utils";

export const runtime = "nodejs";

export async function GET() {
  const session = getMemberSession();
  if (!session) return jsonError("No autenticado", 401);

  const supabase = createAdminClient();
  const { data, error } = await supabase
    .from("reservations")
    .select("*")
    .eq("member_id", session.member_id)
    .order("check_in", { ascending: true });

  if (error) return jsonError("No se pudieron cargar las reservaciones", 500);
  return jsonOk(data);
}

const actionSchema = z.discriminatedUnion("action", [
  z.object({
    action: z.literal("change"),
    reservation_id: z.string().uuid(),
    check_in: z.string(),
    check_out: z.string(),
  }),
  z.object({
    action: z.literal("cancel"),
    reservation_id: z.string().uuid(),
    reason: z.string().optional(),
  }),
]);

export async function POST(request: Request) {
  const session = getMemberSession();
  if (!session) return jsonError("No autenticado", 401);

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return jsonError("Cuerpo inválido", 400);
  }
  const parsed = actionSchema.safeParse(body);
  if (!parsed.success) return jsonError("Acción inválida", 400);

  const supabase = createAdminClient();

  // Verifica propiedad de la reservación.
  const { data: reservation } = await supabase
    .from("reservations")
    .select("*")
    .eq("id", parsed.data.reservation_id)
    .eq("member_id", session.member_id)
    .maybeSingle();

  if (!reservation) return jsonError("Reservación no encontrada", 404);

  if (parsed.data.action === "cancel") {
    const history = [
      ...(reservation.change_history ?? []),
      { type: "cancel", at: new Date().toISOString(), reason: parsed.data.reason ?? null },
    ];
    const { data, error } = await supabase
      .from("reservations")
      .update({ status: "cancelled", change_history: history })
      .eq("id", reservation.id)
      .select("*")
      .single();
    if (error) return jsonError("No se pudo cancelar", 500);
    return jsonOk(data);
  }

  // change
  const history = [
    ...(reservation.change_history ?? []),
    {
      type: "change",
      at: new Date().toISOString(),
      from: { check_in: reservation.check_in, check_out: reservation.check_out },
      to: { check_in: parsed.data.check_in, check_out: parsed.data.check_out },
    },
  ];
  const { data, error } = await supabase
    .from("reservations")
    .update({
      check_in: parsed.data.check_in,
      check_out: parsed.data.check_out,
      status: "changed",
      change_history: history,
    })
    .eq("id", reservation.id)
    .select("*")
    .single();
  if (error) return jsonError("No se pudo actualizar", 500);
  return jsonOk(data);
}
