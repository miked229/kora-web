import "server-only";

import { createAdminClient } from "@/lib/supabase/admin";
import type { Channel, ConversationStatus, MessageRole } from "@/lib/types";

/**
 * Servicio de conversaciones y mensajes (capa de negocio).
 * Usa el cliente admin: SIEMPRE filtra por member_id explícitamente.
 */

export async function getOrCreateConversation(params: {
  memberId: string;
  channel: Channel;
  externalThreadId?: string | null;
}): Promise<string> {
  const supabase = createAdminClient();
  const { memberId, channel, externalThreadId = null } = params;

  if (externalThreadId) {
    const { data: existing } = await supabase
      .from("conversations")
      .select("id")
      .eq("channel", channel)
      .eq("external_thread_id", externalThreadId)
      .maybeSingle();
    if (existing) return existing.id;
  }

  const { data, error } = await supabase
    .from("conversations")
    .insert({
      member_id: memberId,
      channel,
      external_thread_id: externalThreadId,
      status: "bot" satisfies ConversationStatus,
    })
    .select("id")
    .single();

  if (error) throw error;
  return data.id;
}

export async function appendMessage(params: {
  conversationId: string;
  role: MessageRole;
  content: string;
  intent?: string | null;
  sentiment?: string | null;
  tokens?: number | null;
  externalId?: string | null;
}) {
  const supabase = createAdminClient();
  await supabase.from("messages").insert({
    conversation_id: params.conversationId,
    role: params.role,
    content: params.content,
    intent: params.intent ?? null,
    sentiment: params.sentiment ?? null,
    tokens: params.tokens ?? null,
    external_id: params.externalId ?? null,
  });
  await supabase
    .from("conversations")
    .update({ last_message_at: new Date().toISOString() })
    .eq("id", params.conversationId);
}

export async function getHistory(conversationId: string, limit = 20) {
  const supabase = createAdminClient();
  const { data } = await supabase
    .from("messages")
    .select("role, content, created_at")
    .eq("conversation_id", conversationId)
    .order("created_at", { ascending: true })
    .limit(limit);
  return data ?? [];
}

/**
 * Idempotencia para canales externos: ¿ya procesamos este mensaje?
 * (wamid de WhatsApp, id de Gmail). Evita respuestas duplicadas ante reintentos
 * del webhook.
 */
export async function messageExistsByExternalId(externalId: string): Promise<boolean> {
  const supabase = createAdminClient();
  const { data } = await supabase
    .from("messages")
    .select("id")
    .eq("external_id", externalId)
    .maybeSingle();
  return Boolean(data);
}

/**
 * Verifica que una conversación pertenezca al socio indicado.
 * Evita que un socio acceda a (o escriba en) conversaciones ajenas pasando un
 * `conversation_id` arbitrario.
 */
export async function isConversationOwnedBy(
  conversationId: string,
  memberId: string,
): Promise<boolean> {
  const supabase = createAdminClient();
  const { data } = await supabase
    .from("conversations")
    .select("id")
    .eq("id", conversationId)
    .eq("member_id", memberId)
    .maybeSingle();
  return Boolean(data);
}

export async function assignToAgent(conversationId: string) {
  const supabase = createAdminClient();
  await supabase
    .from("conversations")
    .update({ status: "assigned" satisfies ConversationStatus })
    .eq("id", conversationId);
}
