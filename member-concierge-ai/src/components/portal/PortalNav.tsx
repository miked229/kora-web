"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Home,
  MessageCircle,
  CalendarCheck,
  Gift,
  Wallet,
  Ticket,
  LogOut,
  Anchor,
} from "lucide-react";
import { cn } from "@/lib/utils";

const items = [
  { href: "/portal", label: "Inicio", icon: Home },
  { href: "/portal/chat", label: "Concierge IA", icon: MessageCircle },
  { href: "/portal/reservations", label: "Reservaciones", icon: CalendarCheck },
  { href: "/portal/benefits", label: "Beneficios", icon: Gift },
  { href: "/portal/account", label: "Estado de cuenta", icon: Wallet },
  { href: "/portal/tickets", label: "Mis tickets", icon: Ticket },
];

export function PortalNav({
  memberName,
  membershipNo,
}: {
  memberName: string;
  membershipNo: string;
}) {
  const pathname = usePathname();
  const router = useRouter();

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" });
    router.push("/login");
    router.refresh();
  }

  return (
    <aside className="sticky top-0 hidden h-screen w-72 flex-col border-r border-sand-200 bg-white p-5 md:flex">
      <div className="mb-8 flex items-center gap-3">
        <div className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-ocean-gradient text-white">
          <Anchor className="h-5 w-5" />
        </div>
        <div>
          <div className="font-serif text-lg font-semibold leading-none">Kora</div>
          <div className="text-xs text-ocean-500">Member Concierge AI</div>
        </div>
      </div>

      <div className="mb-6 rounded-2xl bg-ocean-gradient p-4 text-white shadow-premium">
        <div className="text-xs text-sand-100/80">Socio</div>
        <div className="font-medium">{memberName || "—"}</div>
        <div className="mt-1 text-xs text-sand-100/80">{membershipNo}</div>
      </div>

      <nav className="flex-1 space-y-1">
        {items.map(({ href, label, icon: Icon }) => {
          const active = pathname === href;
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-3 rounded-xl px-4 py-2.5 text-sm transition-colors",
                active
                  ? "bg-turquoise-50 font-medium text-turquoise-700"
                  : "text-ocean-700 hover:bg-sand-100",
              )}
            >
              <Icon className="h-5 w-5" />
              {label}
            </Link>
          );
        })}
      </nav>

      <button
        onClick={logout}
        className="mt-4 flex items-center gap-3 rounded-xl px-4 py-2.5 text-sm text-ocean-600 hover:bg-sand-100"
      >
        <LogOut className="h-5 w-5" />
        Cerrar sesión
      </button>
    </aside>
  );
}
