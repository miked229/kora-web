import Link from "next/link";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { LayoutDashboard, MessagesSquare, Ticket, Anchor } from "lucide-react";

export const dynamic = "force-dynamic";

/**
 * Dashboard administrativo: requiere staff autenticado (Supabase Auth) con
 * registro activo en `agents`. En desarrollo, si Supabase Auth no está
 * configurado, ajusta `ALLOW_ADMIN_PREVIEW` para previsualizar la UI.
 */
const ALLOW_ADMIN_PREVIEW = process.env.NODE_ENV !== "production";

export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  let authorized = false;
  if (user) {
    const { data: agent } = await supabase
      .from("agents")
      .select("active")
      .eq("id", user.id)
      .maybeSingle();
    authorized = Boolean(agent?.active);
  }

  if (!authorized && !ALLOW_ADMIN_PREVIEW) {
    redirect("/login");
  }

  return (
    <div className="flex min-h-screen bg-sand-50">
      <aside className="sticky top-0 hidden h-screen w-64 flex-col border-r border-sand-200 bg-white p-5 md:flex">
        <div className="mb-8 flex items-center gap-3">
          <div className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-ocean-gradient text-white">
            <Anchor className="h-5 w-5" />
          </div>
          <div>
            <div className="font-serif text-lg font-semibold leading-none">Kora Admin</div>
            <div className="text-xs text-ocean-500">Concierge AI</div>
          </div>
        </div>
        <nav className="space-y-1">
          <AdminLink href="/admin" icon={<LayoutDashboard className="h-5 w-5" />} label="Métricas" />
          <AdminLink href="/admin/conversations" icon={<MessagesSquare className="h-5 w-5" />} label="Conversaciones" />
          <AdminLink href="/admin/tickets" icon={<Ticket className="h-5 w-5" />} label="Tickets" />
        </nav>
        {!authorized && ALLOW_ADMIN_PREVIEW && (
          <p className="mt-auto rounded-lg bg-gold-300/20 px-3 py-2 text-xs text-gold-600">
            Vista previa (sin sesión de staff). Configura Supabase Auth para
            producción.
          </p>
        )}
      </aside>
      <main className="flex-1 px-6 py-8 md:px-10">{children}</main>
    </div>
  );
}

function AdminLink({ href, icon, label }: { href: string; icon: React.ReactNode; label: string }) {
  return (
    <Link
      href={href}
      className="flex items-center gap-3 rounded-xl px-4 py-2.5 text-sm text-ocean-700 hover:bg-sand-100"
    >
      {icon}
      {label}
    </Link>
  );
}
