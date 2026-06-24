import Link from "next/link";
import { getMemberSession } from "@/lib/auth/session";
import { loadMemberContext } from "@/lib/services/members";
import { Card, Badge, Button } from "@/components/ui";
import { formatDate } from "@/lib/utils";
import { MessageCircle, CalendarCheck, Gift, ArrowRight } from "lucide-react";

export const dynamic = "force-dynamic";

export default async function PortalHome() {
  const session = getMemberSession()!;
  const { member, membership, reservations } = await loadMemberContext(session.member_id);

  const nextReservation = reservations[0];

  return (
    <div className="mx-auto max-w-5xl space-y-8">
      <header>
        <p className="text-sm text-ocean-500">Bienvenido de nuevo</p>
        <h1 className="text-3xl font-semibold">
          Hola, {member?.full_name?.split(" ")[0] ?? "socio"} 🌴
        </h1>
      </header>

      {/* Membresía */}
      <Card className="overflow-hidden bg-ocean-gradient p-0 text-white">
        <div className="flex flex-col gap-4 p-7 md:flex-row md:items-center md:justify-between">
          <div>
            <div className="text-sm text-sand-100/80">Tu membresía</div>
            <div className="mt-1 flex items-center gap-3">
              <span className="font-serif text-2xl font-semibold capitalize">
                {membership?.tier ?? "—"}
              </span>
              <Badge tone="gold">{membership?.status ?? "—"}</Badge>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-6">
            <div>
              <div className="text-2xl font-semibold">{membership?.weeks_per_year ?? 0}</div>
              <div className="text-xs text-sand-100/80">Semanas / año</div>
            </div>
            <div>
              <div className="text-2xl font-semibold">
                {(membership?.points_balance ?? 0).toLocaleString("es-MX")}
              </div>
              <div className="text-xs text-sand-100/80">Puntos</div>
            </div>
          </div>
        </div>
      </Card>

      {/* Próxima reservación */}
      {nextReservation && (
        <Card>
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold">Tu próxima estancia</h2>
            <Badge tone="turquoise">{nextReservation.status}</Badge>
          </div>
          <div className="mt-3 flex flex-col gap-1 text-ocean-700">
            <div className="font-medium text-ocean-900">{nextReservation.resort_name}</div>
            <div className="text-sm">{nextReservation.room_type}</div>
            <div className="text-sm">
              {formatDate(nextReservation.check_in)} → {formatDate(nextReservation.check_out)}
            </div>
          </div>
          <Link href="/portal/reservations" className="mt-4 inline-block">
            <Button variant="secondary" size="sm">
              Gestionar reservaciones <ArrowRight className="h-4 w-4" />
            </Button>
          </Link>
        </Card>
      )}

      {/* Accesos rápidos */}
      <div className="grid gap-4 md:grid-cols-3">
        <QuickAction
          href="/portal/chat"
          icon={<MessageCircle className="h-6 w-6" />}
          title="Concierge IA"
          desc="Resuelve cualquier duda al instante"
        />
        <QuickAction
          href="/portal/reservations"
          icon={<CalendarCheck className="h-6 w-6" />}
          title="Reservaciones"
          desc="Cambia o cancela tus estancias"
        />
        <QuickAction
          href="/portal/benefits"
          icon={<Gift className="h-6 w-6" />}
          title="Beneficios"
          desc="Aprovecha tu nivel de membresía"
        />
      </div>
    </div>
  );
}

function QuickAction({
  href,
  icon,
  title,
  desc,
}: {
  href: string;
  icon: React.ReactNode;
  title: string;
  desc: string;
}) {
  return (
    <Link href={href}>
      <Card className="h-full transition-transform hover:-translate-y-1">
        <div className="mb-3 inline-flex h-11 w-11 items-center justify-center rounded-xl bg-turquoise-50 text-turquoise-600">
          {icon}
        </div>
        <h3 className="font-semibold">{title}</h3>
        <p className="mt-1 text-sm text-ocean-600">{desc}</p>
      </Card>
    </Link>
  );
}
