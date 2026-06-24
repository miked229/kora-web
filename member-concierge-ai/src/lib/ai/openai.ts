import "server-only";

import OpenAI from "openai";
import { getServerEnv } from "@/lib/env";

let _client: OpenAI | null = null;

/** Cliente OpenAI singleton (solo servidor). */
export function openai() {
  if (!_client) {
    const { OPENAI_API_KEY } = getServerEnv();
    _client = new OpenAI({ apiKey: OPENAI_API_KEY });
  }
  return _client;
}

export function chatModel() {
  return getServerEnv().OPENAI_MODEL;
}

export function embeddingModel() {
  return getServerEnv().OPENAI_EMBEDDING_MODEL;
}

/** Genera el embedding de un texto para RAG. */
export async function embed(text: string): Promise<number[]> {
  const res = await openai().embeddings.create({
    model: embeddingModel(),
    input: text.replace(/\n/g, " "),
  });
  return res.data[0]!.embedding;
}
