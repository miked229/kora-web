import Link from "next/link";
import { Button } from "@/components/ui";

export default function NotFound() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-sand-50 px-6 text-center">
      <div className="font-serif text-6xl font-semibold text-turquoise-500">404</div>
      <h1 className="font-serif text-2xl font-semibold text-ocean-900">
        Esta página se fue de vacaciones
      </h1>
      <p className="max-w-md text-ocean-600">
        No encontramos lo que buscas. Regresa al inicio y sigamos navegando.
      </p>
      <Link href="/">
        <Button variant="gold">Volver al inicio</Button>
      </Link>
    </div>
  );
}
