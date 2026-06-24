import { z } from "zod";
import { createAdminClient } from "@/lib/supabase/admin";
import { createSessionToken, setSessionCookie } from "@/lib/auth/session";
import { jsonError, jsonOk } from "@/lib/utils";

export const runtime = "nodejs";

const schema = z.object({
  membership_no: z.string().trim().min(3).max(40),
  pin: z.string().min(4).max(12),
});

// Rate limiting en memoria (MVP). En producción usar Redis/Upstash.
const attempts = new Map<string, { count: number; ts: number }>();
const WINDOW_MS = 5 * 60_000;
const MAX_ATTEMPTS = 5;

function rateLimited(key: string): boolean {
  const now = Date.now();
  const rec = attempts.get(key);
  if (!rec || now - rec.ts > WINDOW_MS) {
    attempts.set(key, { count: 1, ts: now });
    return false;
  }
  rec.count += 1;
  return rec.count > MAX_ATTEMPTS;
}

export async function POST(request: Request) {
  const ip = request.headers.get("x-forwarded-for")?.split(",")[0] ?? "unknown";
  if (rateLimited(ip)) {
    return jsonError("Demasiados intentos. Inténtalo de nuevo en unos minutos.", 429);
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return jsonError("Cuerpo inválido", 400);
  }

  const parsed = schema.safeParse(body);
  if (!parsed.success) {
    return jsonError("Número de membresía o PIN inválidos", 400);
  }

  const supabase = createAdminClient();

  // Verificación de credenciales vía función Postgres (hash bcrypt).
  const { data: memberId, error } = await supabase.rpc("verify_membership", {
    p_membership_no: parsed.data.membership_no,
    p_pin: parsed.data.pin,
  });

  // Mensaje genérico para no revelar si la membresía existe.
  if (error || !memberId) {
    return jsonError("Credenciales incorrectas. Verifica tus datos.", 401);
  }

  const { data: member } = await supabase
    .from("members")
    .select("membership_no, full_name")
    .eq("id", memberId)
    .single();

  const token = createSessionToken({
    member_id: memberId as string,
    membership_no: member?.membership_no ?? parsed.data.membership_no,
    full_name: member?.full_name ?? "",
  });
  setSessionCookie(token);

  return jsonOk({ member_id: memberId, full_name: member?.full_name ?? "" });
}
