import "server-only";

import { embed } from "./openai";
import { createAdminClient } from "@/lib/supabase/admin";

export interface KnowledgeMatch {
  id: string;
  title: string;
  content: string;
  category: string | null;
  similarity: number;
}

/**
 * Recupera fragmentos de la base de conocimiento relevantes a la consulta
 * (RAG con pgvector vía la función `match_knowledge`).
 */
export async function retrieveKnowledge(
  query: string,
  opts: { threshold?: number; count?: number } = {},
): Promise<KnowledgeMatch[]> {
  const { threshold = 0.75, count = 5 } = opts;

  try {
    const embedding = await embed(query);
    const supabase = createAdminClient();

    const { data, error } = await supabase.rpc("match_knowledge", {
      query_embedding: embedding as unknown as string,
      match_threshold: threshold,
      match_count: count,
    });

    if (error || !data) return [];
    return data as KnowledgeMatch[];
  } catch {
    // RAG es best-effort: si falla, el chat sigue funcionando sin contexto extra.
    return [];
  }
}
