import { clearSessionCookie } from "@/lib/auth/session";
import { jsonOk } from "@/lib/utils";

export const runtime = "nodejs";

export async function POST() {
  clearSessionCookie();
  return jsonOk({ ok: true });
}
