import { z } from "zod";
import { getMemberSession } from "@/lib/auth/session";
import { openai, chatModel } from "@/lib/ai/openai";
import { prepareConciergeTurn } from "@/lib/ai/orchestrator";
import { appendMessage, isConversationOwnedBy } from "@/lib/services/conversations";
import { jsonError } from "@/lib/utils";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const schema = z.object({
  message: z.string().trim().min(1).max(4000),
  conversation_id: z.string().uuid().optional(),
});

/**
 * Concierge IA — canal web (streaming).
 * Toda la lógica (clasificación, contexto, RAG, acciones) vive en el
 * orquestador compartido; aquí solo añadimos el streaming SSE y la persistencia
 * incremental de la respuesta.
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

  const memberId = session.member_id;

  // Si llega un conversation_id, verificar propiedad.
  if (parsed.data.conversation_id) {
    const owned = await isConversationOwnedBy(parsed.data.conversation_id, memberId);
    if (!owned) return jsonError("Conversación no encontrada", 404);
  }

  const prep = await prepareConciergeTurn({
    memberId,
    channel: "web",
    message: parsed.data.message,
    conversationId: parsed.data.conversation_id,
    fallbackName: session.full_name,
  });

  const completion = await openai().chat.completions.create({
    model: chatModel(),
    temperature: 0.4,
    stream: true,
    messages: prep.messages,
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
        await appendMessage({
          conversationId: prep.conversationId,
          role: "assistant",
          content: assistantText,
          intent: prep.classification.intent,
          sentiment: prep.classification.sentiment,
        });
        controller.close();
      }
    },
  });

  return new Response(stream, {
    headers: {
      "content-type": "text/plain; charset=utf-8",
      "cache-control": "no-cache, no-transform",
      "x-conversation-id": prep.conversationId,
      "x-intent": prep.classification.intent,
      "x-escalated": String(prep.escalate),
    },
  });
}
