import { NextRequest } from "next/server";
import { verifyWhatsappSignature, sendWhatsappText } from "@/lib/channels/whatsapp";
import { findMemberByPhone, loadMemberContext } from "@/lib/services/members";
import {
  appendMessage,
  getOrCreateConversation,
} from "@/lib/services/conversations";
import { classifyMessage } from "@/lib/ai/classify";

export const runtime = "nodejs";

/**
 * Verificación del webhook (Meta hace GET con hub.challenge).
 */
export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  const mode = params.get("hub.mode");
  const token = params.get("hub.verify_token");
  const challenge = params.get("hub.challenge");

  if (mode === "subscribe" && token === process.env.WHATSAPP_VERIFY_TOKEN) {
    return new Response(challenge ?? "", { status: 200 });
  }
  return new Response("Forbidden", { status: 403 });
}

/**
 * Entrada de mensajes de WhatsApp. Verifica firma, deduplica por `wamid`,
 * identifica al socio por teléfono y procesa con la misma lógica del concierge.
 */
export async function POST(request: NextRequest) {
  const rawBody = await request.text();
  const signature = request.headers.get("x-hub-signature-256");

  if (!verifyWhatsappSignature(rawBody, signature)) {
    return new Response("Invalid signature", { status: 401 });
  }

  let payload: any;
  try {
    payload = JSON.parse(rawBody);
  } catch {
    return new Response("Bad request", { status: 400 });
  }

  // Estructura WhatsApp Cloud API.
  const value = payload?.entry?.[0]?.changes?.[0]?.value;
  const message = value?.messages?.[0];
  if (!message) {
    // Puede ser un status (delivered/read); responder 200 para no reintentar.
    return new Response("ok", { status: 200 });
  }

  const from: string = message.from; // teléfono del socio (sin '+')
  const wamid: string = message.id;
  const text: string = message.text?.body ?? "";

  const phoneE164 = from.startsWith("+") ? from : `+${from}`;
  const memberId = await findMemberByPhone(phoneE164);

  if (!memberId) {
    await sendWhatsappText(
      from,
      "¡Hola! Para atenderte necesito vincular tu número con tu membresía. " +
        "Por favor responde con tu número de membresía (ej. KORA-100001).",
    );
    return new Response("ok", { status: 200 });
  }

  const conversationId = await getOrCreateConversation({
    memberId,
    channel: "whatsapp",
    externalThreadId: phoneE164,
  });

  const classification = await classifyMessage(text);

  // Idempotencia: external_id (wamid) tiene índice único.
  await appendMessage({
    conversationId,
    role: "member",
    content: text,
    intent: classification.intent,
    sentiment: classification.sentiment,
    externalId: wamid,
  });

  // En este MVP la generación de respuesta para WhatsApp se delega a n8n, que
  // invoca el orquestador y responde con `sendWhatsappText`. Aquí confirmamos
  // recepción y dejamos el mensaje persistido para el flujo asíncrono.
  await loadMemberContext(memberId); // (precarga de contexto / warmup)

  return new Response("ok", { status: 200 });
}
