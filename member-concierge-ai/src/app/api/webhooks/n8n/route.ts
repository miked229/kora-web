import { z } from "zod";
import { verifyN8nSignature } from "@/lib/channels/n8n";
import { sendWhatsappText } from "@/lib/channels/whatsapp";
import { jsonError, jsonOk } from "@/lib/utils";

export const runtime = "nodejs";

/**
 * Acciones entrantes desde n8n (orquestador). Verifica el secreto compartido.
 * Permite a los flujos de automatización ejecutar acciones de salida
 * (p. ej. enviar una respuesta generada por el orquestador al canal correcto).
 */
const schema = z.object({
  action: z.enum(["send_whatsapp", "noop"]),
  payload: z.record(z.unknown()).default({}),
});

export async function POST(request: Request) {
  const rawBody = await request.text();
  const signature = request.headers.get("x-n8n-signature");

  if (!verifyN8nSignature(rawBody, signature)) {
    return jsonError("Firma inválida", 401);
  }

  let body: unknown;
  try {
    body = JSON.parse(rawBody);
  } catch {
    return jsonError("Cuerpo inválido", 400);
  }
  const parsed = schema.safeParse(body);
  if (!parsed.success) return jsonError("Acción inválida", 400);

  switch (parsed.data.action) {
    case "send_whatsapp": {
      const { to, text } = parsed.data.payload as { to?: string; text?: string };
      if (to && text) await sendWhatsappText(to, text);
      return jsonOk({ sent: Boolean(to && text) });
    }
    default:
      return jsonOk({ ok: true });
  }
}
