import "server-only";

import { openai, chatModel } from "./openai";
import { CLASSIFY_SYSTEM_PROMPT } from "./prompts";
import type { IntentClassification } from "@/lib/types";

const FALLBACK: IntentClassification = {
  intent: "other",
  sentiment: "neutral",
  urgency: "low",
  requires_human: false,
  sales_signal: { detected: false, product: null, confidence: 0 },
};

/**
 * Clasifica un mensaje del socio: intención, sentimiento, urgencia,
 * necesidad de humano y señal de venta. Devuelve un fallback seguro si el
 * modelo no produce JSON válido.
 */
export async function classifyMessage(message: string): Promise<IntentClassification> {
  try {
    const res = await openai().chat.completions.create({
      model: chatModel(),
      temperature: 0,
      response_format: { type: "json_object" },
      messages: [
        { role: "system", content: CLASSIFY_SYSTEM_PROMPT },
        { role: "user", content: message },
      ],
    });

    const raw = res.choices[0]?.message?.content;
    if (!raw) return FALLBACK;

    const parsed = JSON.parse(raw) as Partial<IntentClassification>;
    return {
      intent: parsed.intent ?? FALLBACK.intent,
      sentiment: parsed.sentiment ?? FALLBACK.sentiment,
      urgency: parsed.urgency ?? FALLBACK.urgency,
      requires_human: parsed.requires_human ?? false,
      sales_signal: {
        detected: parsed.sales_signal?.detected ?? false,
        product: parsed.sales_signal?.product ?? null,
        confidence: parsed.sales_signal?.confidence ?? 0,
      },
    };
  } catch {
    return FALLBACK;
  }
}

/** Regla de negocio: ¿se debe escalar a un asesor humano? */
export function shouldEscalate(c: IntentClassification): boolean {
  if (c.requires_human) return true;
  if (c.sentiment === "negative" && c.urgency === "high") return true;
  if ((c.intent === "complaint" || c.intent === "cancellation") && c.urgency !== "low") {
    return true;
  }
  return false;
}
