import { NextRequest } from "next/server";
import { verifyWhatsappSignature, sendWhatsappText } from "@/lib/channels/whatsapp";
import { findMemberByPhone } from "@/lib/services/members";
import { prepareConciergeTurn, completeConciergeReply } from "@/lib/ai/orchestrator";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

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
 * Entrada de WhatsApp → respuesta automática del concierge (end-to-end):
 * verifica firma → identifica al socio por teléfono → orquesta (clasifica,
 * contexto, RAG, acciones) → genera respuesta → la envía por WhatsApp.
 * Idempotente por `wamid`.
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

  const value = payload?.entry?.[0]?.changes?.[0]?.value;
  const message = value?.messages?.[0];
  if (!message || message.type !== "text") {
    // status (delivered/read) u otro tipo: 200 para no reintentar.
    return new Response("ok", { status: 200 });
  }

  const from: string = message.from; // teléfono sin '+'
  const wamid: string = message.id;
  const text: string = message.text?.body ?? "";
  const phoneE164 = from.startsWith("+") ? from : `+${from}`;

  try {
    const memberId = await findMemberByPhone(phoneE164);

    if (!memberId) {
      await sendWhatsappText(
        from,
        "¡Hola! Para atenderte necesito vincular tu número con tu membresía. " +
          "Por favor responde con tu número de membresía (ej. KORA-100001) o " +
          "ingresa a tu portal de socio.",
      );
      return new Response("ok", { status: 200 });
    }

    const prep = await prepareConciergeTurn({
      memberId,
      channel: "whatsapp",
      message: text,
      externalThreadId: phoneE164,
      externalId: wamid,
    });

    // Reintento de Meta sobre un mensaje ya procesado: no responder de nuevo.
    if (prep.alreadyProcessed) {
      return new Response("ok", { status: 200 });
    }

    const reply = await completeConciergeReply(prep);
    await sendWhatsappText(from, reply);
  } catch (err) {
    console.error("[whatsapp] error procesando mensaje:", err);
    // 200 para evitar tormenta de reintentos; el mensaje queda persistido.
  }

  return new Response("ok", { status: 200 });
}
