import { z } from "zod";
import { getMemberSession } from "@/lib/auth/session";
import { createAdminClient } from "@/lib/supabase/admin";
import { createTicket } from "@/lib/services/tickets";
import { jsonError, jsonOk } from "@/lib/utils";

export const runtime = "nodejs";

export async function GET() {
  const session = getMemberSession();
  if (!session) return jsonError("No autenticado", 401);

  const supabase = createAdminClient();
  const { data, error } = await supabase
    .from("tickets")
    .select("*")
    .eq("member_id", session.member_id)
    .order("created_at", { ascending: false });

  if (error) return jsonError("No se pudieron cargar los tickets", 500);
  return jsonOk(data);
}

const schema = z.object({
  subject: z.string().trim().min(3).max(160),
  description: z.string().trim().max(4000).optional(),
  category: z
    .enum(["reservation", "cancellation", "billing", "benefits", "complaint", "general"])
    .optional(),
  conversation_id: z.string().uuid().optional(),
});

export async function POST(request: Request) {
  const session = getMemberSession();
  if (!session) return jsonError("No autenticado", 401);

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return jsonError("Cuerpo inválido", 400);
  }
  const parsed = schema.safeParse(body);
  if (!parsed.success) return jsonError("Datos del ticket inválidos", 400);

  try {
    const ticket = await createTicket({
      memberId: session.member_id,
      conversationId: parsed.data.conversation_id ?? null,
      subject: parsed.data.subject,
      description: parsed.data.description,
      category: parsed.data.category,
    });
    return jsonOk(ticket, 201);
  } catch {
    return jsonError("No se pudo crear el ticket", 500);
  }
}
