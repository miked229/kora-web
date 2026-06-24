import { NextRequest } from "next/server";
import {
  listUnreadMessageIds,
  getMessage,
  sendReply,
  markAsRead,
} from "@/lib/channels/gmail";
import { findMemberByEmail } from "@/lib/services/members";
import { prepareConciergeTurn, completeConciergeReply } from "@/lib/ai/orchestrator";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Notificación push de Gmail (Google Pub/Sub) → respuesta automática del
 * concierge (end-to-end).
 *
 * Al recibir el push, procesa los correos no leídos: identifica al socio por
 * email, orquesta la respuesta y la envía en el mismo hilo, marcando el correo
 * como leído (idempotencia natural: un correo leído no se reprocesa).
 *
 * En producción, valida además el token OIDC de Pub/Sub (Authorization Bearer)
 * antes de procesar.
 */
export async function POST(request: NextRequest) {
  try {
    // (El cuerpo de Pub/Sub trae { message: { data } } con emailAddress/historyId;
    //  aquí usamos la bandeja de no leídos, que es robusta ante reordenamientos.)
    await request.json().catch(() => ({}));

    const ids = await listUnreadMessageIds(10);
    for (const id of ids) {
      const msg = await getMessage(id);
      if (!msg || !msg.body) {
        await markAsRead(id);
        continue;
      }

      const memberId = await findMemberByEmail(msg.fromEmail);
      if (!memberId) {
        // Remitente no reconocido: no respondemos automáticamente; queda para
        // un asesor (el flujo n8n puede enrutarlo). Marcamos como leído para no
        // reprocesar en cada push.
        await markAsRead(id);
        continue;
      }

      const prep = await prepareConciergeTurn({
        memberId,
        channel: "email",
        message: `Asunto: ${msg.subject}\n\n${msg.body}`,
        externalThreadId: msg.threadId,
        externalId: msg.id,
      });

      if (!prep.alreadyProcessed) {
        const reply = await completeConciergeReply(prep);
        await sendReply({
          to: msg.fromEmail,
          subject: msg.subject || "Tu consulta",
          body: reply,
          threadId: msg.threadId,
          inReplyTo: msg.messageIdHeader,
        });
      }
      await markAsRead(id);
    }
  } catch (err) {
    console.error("[gmail] webhook error:", err);
  }

  // Pub/Sub espera 2xx para considerar entregado el mensaje.
  // (204 no admite cuerpo; usamos 200 con confirmación.)
  return new Response("ok", { status: 200 });
}
