import { z } from "zod";
import { getMemberSession } from "@/lib/auth/session";
import { openai, chatModel } from "@/lib/ai/openai";
import { buildSystemPrompt } from "@/lib/ai/prompts";
import { classifyMessage, shouldEscalate } from "@/lib/ai/classify";
import { retrieveKnowledge } from "@/lib/ai/rag";
import { loadMemberContext } from "@/lib/services/members";
import {
  appendMessage,
  assignToAgent,
  getOrCreateConversation,
  getHistory,
} from "@/lib/services/conversations";
import { createTicket } from "@/lib/services/tickets";
import { recordSalesOpportunity } from "@/lib/services/sales";
import { jsonError } from "@/lib/utils";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const schema = z.object({
  message: z.string().trim().min(1).max(4000),
  conversation_id: z.string().uuid().optional(),
});

/**
 * Orquestador del concierge IA (canal web).
 * Flujo: auth → contexto → clasificar → RAG → generar (streaming) →
 * acciones (ticket/escala/venta) → persistir.
 * Responde texto en streaming; los metadatos (intención, escalamiento,
 * conversation_id) viajan en cabeceras.
 */
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
  if (!parsed.success) return jsonError("Mensaje inválido", 400);

  const { message } = parsed.data;
  const memberId = session.member_id;

  // 1) Conversación + contexto del socio (en paralelo con la clasificación).
  const conversationId =
    parsed.data.conversation_id ??
    (await getOrCreateConversation({ memberId, channel: "web" }));

  const [context, classification, knowledge, history] = await Promise.all([
    loadMemberContext(memberId),
    classifyMessage(message),
    retrieveKnowledge(message),
    parsed.data.conversation_id ? getHistory(parsed.data.conversation_id) : Promise.resolve([]),
  ]);

  // 2) Persistir el mensaje del socio.
  await appendMessage({
    conversationId,
    role: "member",
    content: message,
    intent: classification.intent,
    sentiment: classification.sentiment,
  });

  // 3) Acciones de negocio derivadas de la clasificación.
  const escalate = shouldEscalate(classification);
  if (escalate) {
    await assignToAgent(conversationId);
    await createTicket({
      memberId,
      conversationId,
      subject: `Escalamiento: ${classification.intent}`,
      description: message,
      classification,
    });
  }
  if (classification.sales_signal.detected) {
    await recordSalesOpportunity({
      memberId,
      conversationId,
      signal: classification.sales_signal,
    });
  }

  // 4) Construir el prompt y generar respuesta en streaming.
  const systemPrompt = buildSystemPrompt({
    member: context.member ?? { full_name: session.full_name, locale: "es-MX" },
    membership: context.membership,
    reservations: context.reservations,
    knowledge,
  });

  const escalationNote = escalate
    ? "\n\n[NOTA INTERNA: Esta solicitud se está escalando a un asesor humano. Tranquiliza al socio e indícale que un asesor le contactará en breve.]"
    : "";

  const completion = await openai().chat.completions.create({
    model: chatModel(),
    temperature: 0.4,
    stream: true,
    messages: [
      { role: "system", content: systemPrompt + escalationNote },
      ...history.map((m) => ({
        role: m.role === "member" ? ("user" as const) : ("assistant" as const),
        content: m.content,
      })),
      { role: "user", content: message },
    ],
  });

  const encoder = new TextEncoder();
  let assistantText = "";

  const stream = new ReadableStream({
    async start(controller) {
      try {
        for await (const chunk of completion) {
          const delta = chunk.choices[0]?.delta?.content ?? "";
          if (delta) {
            assistantText += delta;
            controller.enqueue(encoder.encode(delta));
          }
        }
      } catch (err) {
        console.error("[chat] stream error:", err);
      } finally {
        // Persistir la respuesta del asistente al terminar.
        await appendMessage({
          conversationId,
          role: "assistant",
          content: assistantText,
          intent: classification.intent,
          sentiment: classification.sentiment,
        });
        controller.close();
      }
    },
  });

  return new Response(stream, {
    headers: {
      "content-type": "text/plain; charset=utf-8",
      "cache-control": "no-cache, no-transform",
      "x-conversation-id": conversationId,
      "x-intent": classification.intent,
      "x-escalated": String(escalate),
    },
  });
}
