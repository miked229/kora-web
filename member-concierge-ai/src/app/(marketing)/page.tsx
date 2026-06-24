import Link from "next/link";
import { Button, Badge } from "@/components/ui";
import { MessageCircle, CalendarCheck, Gift, ShieldCheck, Sparkles, Clock } from "lucide-react";

export default function MarketingPage() {
  return (
    <main className="min-h-screen">
      {/* Hero */}
      <section className="relative isolate overflow-hidden">
        <div
          className="absolute inset-0 -z-10 bg-cover bg-center"
          style={{
            backgroundImage:
              "linear-gradient(to bottom, rgba(14,46,64,0.55), rgba(14,46,64,0.75)), url('https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=2000&q=80')",
          }}
        />
        <nav className="mx-auto flex max-w-7xl items-center justify-between px-6 py-6 text-white">
          <span className="font-serif text-2xl font-semibold tracking-tight">
            Member Concierge <span className="text-gold-400">AI</span>
          </span>
          <div className="flex items-center gap-3">
            <Link href="/login">
              <Button variant="gold" size="sm">
                Acceso socios
              </Button>
            </Link>
          </div>
        </nav>

        <div className="mx-auto max-w-7xl px-6 pb-28 pt-16 text-white md:pt-28">
          <Badge tone="gold" className="mb-6 backdrop-blur">
            <Sparkles className="mr-1 h-3.5 w-3.5" /> Atención premium impulsada por IA
          </Badge>
          <h1 className="max-w-3xl text-4xl font-semibold leading-tight md:text-6xl">
            El concierge de tu membresía vacacional, disponible 24/7.
          </h1>
          <p className="mt-6 max-w-2xl text-lg text-sand-100/90">
            Reservaciones, beneficios, estado de cuenta y soporte instantáneo —
            con la calidez de un resort de lujo del Caribe y la inteligencia de la
            IA. Para socios exigentes y equipos que quieren escalar su servicio.
          </p>
          <div className="mt-10 flex flex-wrap gap-4">
            <Link href="/login">
              <Button variant="gold" size="lg">
                Ingresar con mi membresía
              </Button>
            </Link>
            <Link href="/admin">
              <Button
                size="lg"
                className="bg-white/10 text-white hover:bg-white/20 backdrop-blur"
              >
                Panel para asesores
              </Button>
            </Link>
          </div>

          <div className="mt-16 flex flex-wrap gap-8 text-sand-100/80">
            <Stat value="24/7" label="Disponibilidad del concierge" />
            <Stat value="-60%" label="Carga operativa de asesores" />
            <Stat value="<1 min" label="Tiempo de primera respuesta" />
          </div>
        </div>
      </section>

      {/* Características */}
      <section className="mx-auto max-w-7xl px-6 py-24">
        <h2 className="text-center text-3xl font-semibold md:text-4xl">
          Una experiencia de socio impecable
        </h2>
        <p className="mx-auto mt-4 max-w-2xl text-center text-ocean-700">
          Automatiza la atención, clasifica solicitudes y detecta oportunidades de
          venta sin perder el toque humano.
        </p>

        <div className="mt-14 grid gap-6 md:grid-cols-3">
          <Feature
            icon={<MessageCircle className="h-6 w-6" />}
            title="Chat IA 24/7"
            desc="Respuestas inmediatas y fundamentadas sobre tu membresía, en tu idioma."
          />
          <Feature
            icon={<CalendarCheck className="h-6 w-6" />}
            title="Reservaciones"
            desc="Consulta, cambia o cancela tus estancias con políticas claras al instante."
          />
          <Feature
            icon={<Gift className="h-6 w-6" />}
            title="Beneficios premium"
            desc="Conoce y aprovecha todos los beneficios según tu nivel de membresía."
          />
          <Feature
            icon={<Clock className="h-6 w-6" />}
            title="Tickets y escalamiento"
            desc="Cuando hace falta un humano, escalamos con todo el contexto listo."
          />
          <Feature
            icon={<Sparkles className="h-6 w-6" />}
            title="Omnicanal"
            desc="Web, WhatsApp y correo en una sola conversación unificada."
          />
          <Feature
            icon={<ShieldCheck className="h-6 w-6" />}
            title="Seguro y privado"
            desc="Datos cifrados, control de acceso por membresía y trazabilidad total."
          />
        </div>
      </section>

      <footer className="border-t border-sand-200 bg-white py-10 text-center text-sm text-ocean-600">
        © {new Date().getFullYear()} Member Concierge AI · Kora · Membresías
        vacacionales de lujo
      </footer>
    </main>
  );
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div>
      <div className="font-serif text-3xl font-semibold text-gold-400">{value}</div>
      <div className="text-sm">{label}</div>
    </div>
  );
}

function Feature({
  icon,
  title,
  desc,
}: {
  icon: React.ReactNode;
  title: string;
  desc: string;
}) {
  return (
    <div className="card p-7 transition-transform hover:-translate-y-1">
      <div className="mb-4 inline-flex h-12 w-12 items-center justify-center rounded-xl bg-ocean-gradient text-white">
        {icon}
      </div>
      <h3 className="text-xl font-semibold">{title}</h3>
      <p className="mt-2 text-ocean-700">{desc}</p>
    </div>
  );
}
