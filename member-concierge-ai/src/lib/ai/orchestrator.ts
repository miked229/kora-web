import "server-only";

import type OpenAI from "openai";
import { openai, chatModel } from "./openai";
import { buildSystemPrompt } from "./prompts";
import { classifyMessage, shouldEscalate } from "./classify";
import { retrieveKnowledge } from "./rag";
import { loadMemberContext } from "@/lib/services/members";
import {
  appendMessage,
  assignToAgent,
  getOrCreateConversation,
  getHistory,
  messageExistsByExternalId,
} from "@/lib/services/conversations";
import { createTicket } from "@/lib/services/tickets";
import { recordSalesOpportunity } from "@/lib/services/sales";
import type { Channel, IntentClassification } from "@/lib/types";

type ChatMessageParam = OpenAI.Chat.Completions.ChatCompletionMessageParam;

export interface ConciergeTurnInput {
  memberId: string;
  channel: Channel;
  message: string;
  /** Para web: conversación existente (ya validada como propia). */
  conversationId?: string;
  /** Para WhatsApp/Email: hilo externo (teléfono / threadId). */
  externalThreadId?: string;
  /** Idempotencia del mensaje entrante (wamid / id de Gmail). */
  externalId?: string;
  /** Nombre por defecto si aún no se cargó el perfil. */
  fallbackName?: string;
}

export interface ConciergeTurnPrep {
  alreadyProcessed: boolean;
  conversationId: string;
  classification: IntentClassification;
  escalate: boolean;
  /** system + historial + mensaje actual del socio, listo para OpenAI. */
  messages: ChatMessageParam[];
}

/**
 * Prepara un turno del concierge para CUALQUIER canal:
 * resuelve conversación, deduplica, clasifica, recupera contexto + RAG,
 * persiste el mensaje del socio y ejecuta acciones (escalamiento/ticket/venta).
 * Devuelve los mensajes listos para generar la respuesta (streaming o no).
 */
export async function prepareConciergeTurn(
  input: ConciergeTurnInput,
): Promise<ConciergeTurnPrep> {
  const { memberId, channel, message } = input;

  // Idempotencia para canales externos.
  if (input.externalId && (await messageExistsByExternalId(input.externalId))) {
    return {
      alreadyProcessed: true,
      conversationId: input.conversationId ?? "",
      classification: {
        intent: "other",
        sentiment: "neutral",
        urgency: "low",
        requires_human: false,
        sales_signal: { detected: false, product: null, confidence: 0 },
      },
      escalate: false,
      messages: [],
    };
  }

  const conversationId =
    input.conversationId ??
    (await getOrCreateConversation({
      memberId,
      channel,
      externalThreadId: input.externalThreadId ?? null,
    }));

  const [context, classification, knowledge, history] = await Promise.all([
    loadMemberContext(memberId),
    classifyMessage(message),
    retrieveKnowledge(message),
    getHistory(conversationId),
  ]);

  // Persistir el mensaje del socio (con idempotencia por external_id).
  await appendMessage({
    conversationId,
    role: "member",
    content: message,
    intent: classification.intent,
    sentiment: classification.sentiment,
    externalId: input.externalId ?? null,
  });

  // Acciones de negocio.
  const escalate = shouldEscalate(classification);
  if (escalate) {
    await assignToAgent(conversationId);
    await createTicket({
      memberId,
      conversationId,
      subject: `Escalamiento (${channel}): ${classification.intent}`,
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

  // Construcción del prompt.
  const systemPrompt = buildSystemPrompt({
    member: context.member ?? { full_name: input.fallbackName ?? "socio", locale: "es-MX" },
    membership: context.membership,
    reservations: context.reservations,
    knowledge,
  });

  const escalationNote = escalate
    ? "\n\n[NOTA INTERNA: Esta solicitud se está escalando a un asesor humano. Tranquiliza al socio e indícale que un asesor le contactará en breve.]"
    : "";

  const messages: ChatMessageParam[] = [
    { role: "system", content: systemPrompt + escalationNote },
    ...history.map((m) => ({
      role: m.role === "member" ? ("user" as const) : ("assistant" as const),
      content: m.content,
    })),
    { role: "user", content: message },
  ];

  return { alreadyProcessed: false, conversationId, classification, escalate, messages };
}

/**
 * Genera la respuesta COMPLETA (sin streaming) y la persiste.
 * Para canales asíncronos: WhatsApp y Email.
 */
export async function completeConciergeReply(prep: ConciergeTurnPrep): Promise<string> {
  const completion = await openai().chat.completions.create({
    model: chatModel(),
    temperature: 0.4,
    messages: prep.messages,
  });

  const text =
    completion.choices[0]?.message?.content?.trim() ||
    "Gracias por tu mensaje. Un asesor te atenderá en breve.";

  await appendMessage({
    conversationId: prep.conversationId,
    role: "assistant",
    content: text,
    intent: prep.classification.intent,
    sentiment: prep.classification.sentiment,
    tokens: completion.usage?.total_tokens ?? null,
  });

  return text;
}
