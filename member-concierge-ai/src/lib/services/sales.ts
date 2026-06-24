import "server-only";

import { createAdminClient } from "@/lib/supabase/admin";
import { notifyN8n } from "@/lib/channels/n8n";
import type { IntentClassification } from "@/lib/types";

/**
 * Registra una oportunidad de venta detectada por la IA y dispara el
 * seguimiento automatizado en n8n.
 */
export async function recordSalesOpportunity(params: {
  memberId: string;
  conversationId?: string | null;
  signal: IntentClassification["sales_signal"];
}) {
  if (!params.signal.detected) return null;

  const supabase = createAdminClient();
  const { data, error } = await supabase
    .from("sales_opportunities")
    .insert({
      member_id: params.memberId,
      conversation_id: params.conversationId ?? null,
      product: params.signal.product ?? "interes_general",
      stage: "detected",
      confidence: params.signal.confidence,
    })
    .select("*")
    .single();

  if (error) return null;

  await notifyN8n("sales.opportunity_detected", {
    opportunity_id: data.id,
    member_id: params.memberId,
    product: data.product,
    confidence: data.confidence,
  });

  return data;
}
