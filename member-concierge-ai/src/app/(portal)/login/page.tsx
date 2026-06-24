import { Suspense } from "react";
import { LoginForm } from "@/components/portal/LoginForm";

export const dynamic = "force-dynamic";

export default function LoginPage() {
  return (
    <main className="relative flex min-h-screen items-center justify-center px-6">
      <div
        className="absolute inset-0 -z-10 bg-cover bg-center"
        style={{
          backgroundImage:
            "linear-gradient(135deg, rgba(14,46,64,0.85), rgba(15,169,158,0.65)), url('https://images.unsplash.com/photo-1544551763-46a013bb70d5?auto=format&fit=crop&w=2000&q=80')",
        }}
      />
      <Suspense fallback={<div className="text-white">Cargando…</div>}>
        <LoginForm />
      </Suspense>
    </main>
  );
}
