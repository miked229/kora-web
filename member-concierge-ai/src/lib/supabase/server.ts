import { createServerClient, type CookieOptions } from "@supabase/ssr";
import { cookies } from "next/headers";
import { clientEnv } from "@/lib/env";

type CookieToSet = { name: string; value: string; options?: CookieOptions };

/**
 * Cliente Supabase para el servidor (Server Components / Route Handlers).
 * Usa la clave anónima y respeta RLS. Las cookies mantienen la sesión de
 * Supabase Auth (staff). Para el contexto de socio se inyecta el claim
 * `member_id` mediante `accessToken` en operaciones específicas si aplica.
 */
export function createClient() {
  const cookieStore = cookies();

  return createServerClient(
    clientEnv.NEXT_PUBLIC_SUPABASE_URL,
    clientEnv.NEXT_PUBLIC_SUPABASE_ANON_KEY,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet: CookieToSet[]) {
          try {
            cookiesToSet.forEach(({ name, value, options }) =>
              cookieStore.set(name, value, options),
            );
          } catch {
            // `setAll` puede invocarse desde un Server Component (solo lectura);
            // el middleware se encarga de refrescar la sesión.
          }
        },
      },
    },
  );
}
