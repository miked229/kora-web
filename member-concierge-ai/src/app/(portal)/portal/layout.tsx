import { redirect } from "next/navigation";
import { getMemberSession } from "@/lib/auth/session";
import { PortalNav } from "@/components/portal/PortalNav";

export const dynamic = "force-dynamic";

export default function PortalLayout({ children }: { children: React.ReactNode }) {
  // Verificación criptográfica real de la sesión (runtime Node).
  const session = getMemberSession();
  if (!session) redirect("/login");

  return (
    <div className="flex min-h-screen bg-sand-50">
      <PortalNav memberName={session.full_name} membershipNo={session.membership_no} />
      <main className="flex-1 px-6 py-8 md:px-10">{children}</main>
    </div>
  );
}
