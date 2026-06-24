"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Card, Button, Input } from "@/components/ui";
import { Plus } from "lucide-react";

const CATEGORIES = [
  { value: "reservation", label: "Reservación" },
  { value: "cancellation", label: "Cancelación" },
  { value: "billing", label: "Facturación" },
  { value: "benefits", label: "Beneficios" },
  { value: "complaint", label: "Queja" },
  { value: "general", label: "General" },
];

export function NewTicketForm() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [subject, setSubject] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("general");
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    try {
      await fetch("/api/tickets", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ subject, description, category }),
      });
      setSubject("");
      setDescription("");
      setOpen(false);
      router.refresh();
    } finally {
      setLoading(false);
    }
  }

  if (!open) {
    return (
      <Button variant="secondary" onClick={() => setOpen(true)}>
        <Plus className="h-4 w-4" /> Nuevo ticket
      </Button>
    );
  }

  return (
    <Card>
      <form onSubmit={submit} className="space-y-3">
        <Input
          placeholder="Asunto"
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
          required
          minLength={3}
        />
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          className="h-11 w-full rounded-xl border border-sand-300 bg-white px-4 text-sm focus:border-turquoise-400 focus:outline-none"
        >
          {CATEGORIES.map((c) => (
            <option key={c.value} value={c.value}>
              {c.label}
            </option>
          ))}
        </select>
        <textarea
          placeholder="Describe tu solicitud…"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={3}
          className="w-full rounded-xl border border-sand-300 bg-white px-4 py-3 text-sm focus:border-turquoise-400 focus:outline-none"
        />
        <div className="flex gap-2">
          <Button type="submit" variant="secondary" disabled={loading || subject.length < 3}>
            {loading ? "Creando…" : "Crear ticket"}
          </Button>
          <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
            Cancelar
          </Button>
        </div>
      </form>
    </Card>
  );
}
