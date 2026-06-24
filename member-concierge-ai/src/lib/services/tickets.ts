import "server-only";

import { createAdminClient } from "@/lib/supabase/admin";
import { notifyN8n } from "@/lib/channels/n8n";
import type {
  IntentClassification,
  TicketCategory,
  TicketPriority,
} from "@/lib/types";

/** Mapea la intención clasificada a la categoría del ticket. */
function categoryFromIntent(intent: IntentClassification["intent"]): TicketCategory {
  switch (intent) {
    case "reservation_change":
      return "reservation";
    case "cancellation":
      return "cancellation";
    case "billing":
      return "billing";
    case "benefits":
      return "benefits";
    case "complaint":
      return "complaint";
    default:
      return "general";
  }
}

/** Mapea urgencia → prioridad SLA. */
function priorityFromUrgency(c: IntentClassification): TicketPriority {
  if (c.requires_human && c.sentiment === "negative") return "urgent";
  if (c.urgency === "high") return "high";
  if (c.urgency === "medium") return "medium";
  return "low";
}

const SLA_HOURS: Record<TicketPriority, number> = {
  urgent: 1,
  high: 4,
  medium: 24,
  low: 72,
};

export async function createTicket(params: {
  memberId: string;
  conversationId?: string | null;
  subject: string;
  description?: string;
  classification?: IntentClassification;
  category?: TicketCategory;
  priority?: TicketPriority;
}) {
  const supabase = createAdminClient();

  const category =
    params.category ??
    (params.classification ? categoryFromIntent(params.classification.intent) : "general");
  const priority =
    params.priority ??
    (params.classification ? priorityFromUrgency(params.classification) : "medium");

  const slaDue = new Date(Date.now() + SLA_HOURS[priority] * 3600_000).toISOString();

  const { data, error } = await supabase
    .from("tickets")
    .insert({
      member_id: params.memberId,
      conversation_id: params.conversationId ?? null,
      subject: params.subject,
      description: params.description ?? null,
      category,
      priority,
      status: "new",
      sla_due_at: slaDue,
    })
    .select("*")
    .single();

  if (error) throw error;

  // Notificar a n8n para enrutado/escalamiento (best-effort).
  await notifyN8n("ticket.created", {
    ticket_id: data.id,
    member_id: params.memberId,
    category,
    priority,
    subject: params.subject,
  });

  return data;
}
