import "server-only";

import crypto from "crypto";

/**
 * Integración con WhatsApp Business Cloud API (Graph API).
 */

const GRAPH_URL = "https://graph.facebook.com/v20.0";

/** Envía un mensaje de texto a un socio por WhatsApp. */
export async function sendWhatsappText(to: string, text: string) {
  const phoneNumberId = process.env.WHATSAPP_PHONE_NUMBER_ID;
  const token = process.env.WHATSAPP_ACCESS_TOKEN;
  if (!phoneNumberId || !token) {
    console.warn("[whatsapp] credenciales no configuradas; mensaje omitido");
    return;
  }

  const res = await fetch(`${GRAPH_URL}/${phoneNumberId}/messages`, {
    method: "POST",
    headers: {
      authorization: `Bearer ${token}`,
      "content-type": "application/json",
    },
    body: JSON.stringify({
      messaging_product: "whatsapp",
      to,
      type: "text",
      text: { body: text },
    }),
  });

  if (!res.ok) {
    console.error("[whatsapp] envío fallido:", res.status, await res.text());
  }
}

/** Valida la firma X-Hub-Signature-256 del webhook de Meta. */
export function verifyWhatsappSignature(rawBody: string, signature: string | null): boolean {
  const appSecret = process.env.WHATSAPP_ACCESS_TOKEN; // usar APP_SECRET dedicado en prod
  if (!appSecret || !signature) return false;
  const expected =
    "sha256=" + crypto.createHmac("sha256", appSecret).update(rawBody).digest("hex");
  try {
    return crypto.timingSafeEqual(Buffer.from(signature), Buffer.from(expected));
  } catch {
    return false;
  }
}
