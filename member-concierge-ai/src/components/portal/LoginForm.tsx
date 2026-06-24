"use client";

import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { Button, Input, Card } from "@/components/ui";
import { Anchor } from "lucide-react";

export function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const next = searchParams.get("next") ?? "/portal";

  const [membershipNo, setMembershipNo] = useState("");
  const [pin, setPin] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ membership_no: membershipNo, pin }),
      });
      const json = await res.json();
      if (!res.ok) {
        setError(json.error ?? "No se pudo iniciar sesión");
        return;
      }
      router.push(next);
      router.refresh();
    } catch {
      setError("Error de red. Inténtalo de nuevo.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card className="w-full max-w-md p-8">
      <div className="mb-6 flex flex-col items-center text-center">
        <div className="mb-3 inline-flex h-14 w-14 items-center justify-center rounded-2xl bg-ocean-gradient text-white">
          <Anchor className="h-7 w-7" />
        </div>
        <h1 className="text-2xl font-semibold">Bienvenido, socio</h1>
        <p className="mt-1 text-sm text-ocean-600">
          Ingresa con tu número de membresía
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="mb-1 block text-sm font-medium text-ocean-800">
            Número de membresía
          </label>
          <Input
            autoComplete="username"
            placeholder="KORA-100001"
            value={membershipNo}
            onChange={(e) => setMembershipNo(e.target.value)}
            required
          />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-ocean-800">PIN</label>
          <Input
            type="password"
            autoComplete="current-password"
            placeholder="••••"
            value={pin}
            onChange={(e) => setPin(e.target.value)}
            required
          />
        </div>

        {error && (
          <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>
        )}

        <Button type="submit" variant="gold" size="lg" className="w-full" disabled={loading}>
          {loading ? "Ingresando…" : "Ingresar"}
        </Button>
      </form>

      <p className="mt-6 text-center text-xs text-ocean-500">
        Demo: <span className="font-medium">KORA-100001</span> · PIN{" "}
        <span className="font-medium">1234</span>
      </p>
      <p className="mt-2 text-center text-xs">
        <Link href="/" className="text-turquoise-600 hover:underline">
          ← Volver al inicio
        </Link>
      </p>
    </Card>
  );
}
