"use client";

import { useRef, useState } from "react";
import { Send, Sparkles, UserRound } from "lucide-react";
import { Button } from "@/components/ui";
import { cn } from "@/lib/utils";

interface Msg {
  role: "member" | "assistant";
  content: string;
}

const SUGGESTIONS = [
  "¿Cuáles son mis beneficios?",
  "Quiero cambiar mi reservación de julio",
  "¿Cuál es la política de cancelación?",
  "Muéstrame mi estado de cuenta",
];

export function ChatWindow() {
  const [messages, setMessages] = useState<Msg[]>([
    {
      role: "assistant",
      content:
        "¡Hola! Soy tu Concierge AI ✨ Estoy aquí 24/7 para ayudarte con reservaciones, beneficios, tu estado de cuenta y mucho más. ¿En qué puedo ayudarte hoy?",
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [escalated, setEscalated] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  function scrollToBottom() {
    requestAnimationFrame(() => {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
    });
  }

  async function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed || loading) return;

    setMessages((m) => [...m, { role: "member", content: trimmed }, { role: "assistant", content: "" }]);
    setInput("");
    setLoading(true);
    scrollToBottom();

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          message: trimmed,
          conversation_id: conversationId ?? undefined,
        }),
      });

      const convId = res.headers.get("x-conversation-id");
      if (convId) setConversationId(convId);
      if (res.headers.get("x-escalated") === "true") setEscalated(true);

      if (!res.body) throw new Error("sin respuesta");
      const reader = res.body.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunk = decoder.decode(value, { stream: true });
        setMessages((m) => {
          const copy = [...m];
          copy[copy.length - 1] = {
            role: "assistant",
            content: copy[copy.length - 1].content + chunk,
          };
          return copy;
        });
        scrollToBottom();
      }
    } catch {
      setMessages((m) => {
        const copy = [...m];
        copy[copy.length - 1] = {
          role: "assistant",
          content: "Lo siento, hubo un problema al responder. Inténtalo de nuevo.",
        };
        return copy;
      });
    } finally {
      setLoading(false);
      scrollToBottom();
    }
  }

  return (
    <div className="flex h-[calc(100vh-8rem)] flex-col card overflow-hidden p-0">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-sand-200 bg-ocean-gradient px-6 py-4 text-white">
        <div className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-white/15">
          <Sparkles className="h-5 w-5" />
        </div>
        <div>
          <div className="font-medium">Concierge AI</div>
          <div className="text-xs text-sand-100/80">En línea · responde al instante</div>
        </div>
      </div>

      {/* Mensajes */}
      <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto px-6 py-6">
        {messages.map((m, i) => (
          <div
            key={i}
            className={cn("flex gap-3", m.role === "member" ? "justify-end" : "justify-start")}
          >
            {m.role === "assistant" && (
              <div className="mt-1 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-turquoise-100 text-turquoise-700">
                <Sparkles className="h-4 w-4" />
              </div>
            )}
            <div
              className={cn(
                "max-w-[78%] whitespace-pre-wrap rounded-2xl px-4 py-3 text-sm leading-relaxed",
                m.role === "member"
                  ? "bg-ocean-700 text-white"
                  : "bg-sand-100 text-ocean-900",
              )}
            >
              {m.content || (loading ? "…" : "")}
            </div>
            {m.role === "member" && (
              <div className="mt-1 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-ocean-100 text-ocean-700">
                <UserRound className="h-4 w-4" />
              </div>
            )}
          </div>
        ))}

        {escalated && (
          <div className="rounded-xl border border-gold-300 bg-gold-300/20 px-4 py-3 text-sm text-gold-600">
            🛎️ Tu solicitud fue escalada a un asesor humano. Te contactaremos en breve
            con todo el contexto de esta conversación.
          </div>
        )}
      </div>

      {/* Sugerencias */}
      {messages.length <= 1 && (
        <div className="flex flex-wrap gap-2 px-6 pb-2">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              onClick={() => send(s)}
              className="rounded-full border border-sand-300 bg-white px-3 py-1.5 text-xs text-ocean-700 hover:border-turquoise-400 hover:text-turquoise-700"
            >
              {s}
            </button>
          ))}
        </div>
      )}

      {/* Input */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
        className="flex items-center gap-2 border-t border-sand-200 p-4"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Escribe tu mensaje…"
          className="h-11 flex-1 rounded-xl border border-sand-300 bg-white px-4 text-sm focus:border-turquoise-400 focus:outline-none focus:ring-2 focus:ring-turquoise-200"
        />
        <Button type="submit" variant="secondary" disabled={loading || !input.trim()}>
          <Send className="h-4 w-4" />
        </Button>
      </form>
    </div>
  );
}
