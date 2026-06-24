import { NextRequest } from "next/server";

export const runtime = "nodejs";

/**
 * Notificación push de Gmail vía Google Pub/Sub.
 *
 * En producción:
 *  1. Validar el token OIDC de Pub/Sub (Authorization: Bearer ...).
 *  2. Decodificar `message.data` (base64) → { emailAddress, historyId }.
 *  3. Llamar a gmail.users.history.list para traer los mensajes nuevos.
 *  4. Identificar al socio por email, crear/actualizar conversación y procesar.
 *
 * El polling/lectura pesada se delega al flujo n8n "Soporte/Email entrante"
 * (ver docs/AUTOMATIONS.md) para centralizar credenciales y reintentos.
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json().catch(() => ({}));
    const data = body?.message?.data;
    if (data) {
      const decoded = JSON.parse(Buffer.from(data, "base64").toString("utf8"));
      console.warn("[gmail] notificación recibida:", decoded.historyId ?? "");
      // TODO: history.list + procesamiento (delegado a n8n en el MVP).
    }
  } catch (err) {
    console.error("[gmail] webhook error:", err);
  }
  // Pub/Sub espera 2xx para considerar entregado el mensaje.
  return new Response("ok", { status: 204 });
}
