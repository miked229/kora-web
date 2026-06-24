import { ChatWindow } from "@/components/portal/ChatWindow";

export const dynamic = "force-dynamic";

export default function ChatPage() {
  return (
    <div className="mx-auto max-w-3xl">
      <header className="mb-6">
        <h1 className="text-3xl font-semibold">Concierge AI</h1>
        <p className="text-ocean-600">Tu asistente personal, disponible 24/7.</p>
      </header>
      <ChatWindow />
    </div>
  );
}
