import "server-only";

import crypto from "crypto";

/**
 * Notifica un evento a n8n para disparar automatizaciones (escalamiento,
 * seguimiento de ventas, recordatorios). Best-effort: nunca lanza.
 */
export async function notifyN8n(event: string, payload: Record<string, unknown>) {
  const url = process.env.N8N_WEBHOOK_URL;
  const secret = process.env.N8N_WEBHOOK_SECRET;
  if (!url) return;

  try {
    const body = JSON.stringify({ event, payload, ts: Date.now() });
    const signature = secret
      ? crypto.createHmac("sha256", secret).update(body).digest("hex")
      : "";

    await fetch(url, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-n8n-signature": signature,
      },
      body,
    });
  } catch (err) {
    console.error("[n8n] notify failed:", err);
  }
}

/** Verifica la firma de un webhook entrante desde n8n. */
export function verifyN8nSignature(rawBody: string, signature: string | null): boolean {
  const secret = process.env.N8N_WEBHOOK_SECRET;
  if (!secret || !signature) return false;
  const expected = crypto.createHmac("sha256", secret).update(rawBody).digest("hex");
  try {
    return crypto.timingSafeEqual(Buffer.from(signature), Buffer.from(expected));
  } catch {
    return false;
  }
}
