import "server-only";

import { createClient as createSupabaseClient } from "@supabase/supabase-js";
import { clientEnv, getServerEnv } from "@/lib/env";
import { isDemoMode, createDemoClient } from "@/lib/supabase/demo";

/**
 * Cliente con `service_role`: OMITE RLS. Úsalo SOLO en el servidor para
 * operaciones de sistema (webhooks, IA, automatizaciones, semillas).
 * NUNCA lo importes en componentes de cliente.
 *
 * Para fijar el contexto de un socio concreto y respetar la lógica de negocio,
 * filtra siempre explícitamente por `member_id`.
 */
export function createAdminClient() {
  // Modo demo: datos en memoria, sin Supabase ni servicios externos.
  if (isDemoMode()) {
    return createDemoClient() as unknown as ReturnType<typeof createSupabaseClient>;
  }

  const env = getServerEnv();
  return createSupabaseClient(
    clientEnv.NEXT_PUBLIC_SUPABASE_URL,
    env.SUPABASE_SERVICE_ROLE_KEY,
    {
      auth: { persistSession: false, autoRefreshToken: false },
    },
  );
}
