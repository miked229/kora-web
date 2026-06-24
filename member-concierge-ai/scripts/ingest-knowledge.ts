/**
 * Ingesta de la base de conocimiento: genera embeddings para las filas de
 * `knowledge_base` que aún no los tienen y los guarda para habilitar RAG.
 *
 * Uso:
 *   npx tsx scripts/ingest-knowledge.ts
 *
 * Requiere en el entorno: NEXT_PUBLIC_SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY,
 * OPENAI_API_KEY, OPENAI_EMBEDDING_MODEL.
 */
import { createClient } from "@supabase/supabase-js";
import OpenAI from "openai";

async function main() {
  const supabase = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!,
    { auth: { persistSession: false } },
  );
  const openai = new OpenAI({ apiKey: process.env.OPENAI_API_KEY! });
  const model = process.env.OPENAI_EMBEDDING_MODEL ?? "text-embedding-3-small";

  const { data: rows, error } = await supabase
    .from("knowledge_base")
    .select("id, title, content")
    .is("embedding", null);

  if (error) throw error;
  if (!rows?.length) {
    console.warn("No hay artículos pendientes de indexar.");
    return;
  }

  for (const row of rows) {
    const input = `${row.title}\n\n${row.content}`.replace(/\n/g, " ");
    const res = await openai.embeddings.create({ model, input });
    const embedding = res.data[0]!.embedding;

    const { error: upErr } = await supabase
      .from("knowledge_base")
      .update({ embedding, updated_at: new Date().toISOString() })
      .eq("id", row.id);

    if (upErr) console.error(`Error en ${row.id}:`, upErr.message);
    else console.warn(`✓ Indexado: ${row.title}`);
  }

  console.warn(`Listo. ${rows.length} artículo(s) procesado(s).`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
