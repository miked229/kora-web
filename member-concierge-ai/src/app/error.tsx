"use client";

import { useEffect } from "react";
import { Button } from "@/components/ui";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[app] error boundary:", error);
  }, [error]);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-sand-50 px-6 text-center">
      <h1 className="font-serif text-3xl font-semibold text-ocean-900">
        Algo no salió como esperábamos
      </h1>
      <p className="max-w-md text-ocean-600">
        Tuvimos un inconveniente al cargar esta sección. Por favor inténtalo de
        nuevo; si persiste, nuestro equipo ya está al tanto.
      </p>
      <Button variant="secondary" onClick={reset}>
        Reintentar
      </Button>
    </div>
  );
}
