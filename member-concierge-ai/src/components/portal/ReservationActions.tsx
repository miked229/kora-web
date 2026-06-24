"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button, Input } from "@/components/ui";

export function ReservationActions({ reservationId }: { reservationId: string }) {
  const router = useRouter();
  const [mode, setMode] = useState<"idle" | "change">("idle");
  const [checkIn, setCheckIn] = useState("");
  const [checkOut, setCheckOut] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(action: "change" | "cancel") {
    setLoading(true);
    try {
      await fetch("/api/reservations", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(
          action === "cancel"
            ? { action, reservation_id: reservationId }
            : { action, reservation_id: reservationId, check_in: checkIn, check_out: checkOut },
        ),
      });
      setMode("idle");
      router.refresh();
    } finally {
      setLoading(false);
    }
  }

  if (mode === "change") {
    return (
      <div className="flex flex-col gap-2">
        <div className="flex gap-2">
          <Input type="date" value={checkIn} onChange={(e) => setCheckIn(e.target.value)} />
          <Input type="date" value={checkOut} onChange={(e) => setCheckOut(e.target.value)} />
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="secondary" disabled={loading || !checkIn || !checkOut} onClick={() => submit("change")}>
            Confirmar cambio
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setMode("idle")}>
            Cancelar
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex gap-2">
      <Button size="sm" variant="secondary" onClick={() => setMode("change")}>
        Cambiar fechas
      </Button>
      <Button
        size="sm"
        variant="ghost"
        className="text-red-600 hover:bg-red-50"
        disabled={loading}
        onClick={() => submit("cancel")}
      >
        Cancelar
      </Button>
    </div>
  );
}
