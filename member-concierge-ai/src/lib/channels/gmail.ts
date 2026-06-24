import "server-only";

/**
 * Integración con Gmail API (cuenta de soporte) mediante OAuth2 con refresh
 * token + REST (sin SDK pesado). Permite leer correos no leídos, responder en
 * el mismo hilo y marcarlos como leídos.
 */

const TOKEN_URL = "https://oauth2.googleapis.com/token";
const API = "https://gmail.googleapis.com/gmail/v1/users/me";

let cachedToken: { value: string; expiresAt: number } | null = null;

/** Obtiene (y cachea) un access token a partir del refresh token. */
async function getAccessToken(): Promise<string | null> {
  const clientId = process.env.GMAIL_CLIENT_ID;
  const clientSecret = process.env.GMAIL_CLIENT_SECRET;
  const refreshToken = process.env.GMAIL_REFRESH_TOKEN;
  if (!clientId || !clientSecret || !refreshToken) return null;

  if (cachedToken && cachedToken.expiresAt > Date.now() + 30_000) {
    return cachedToken.value;
  }

  const res = await fetch(TOKEN_URL, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      client_id: clientId,
      client_secret: clientSecret,
      refresh_token: refreshToken,
      grant_type: "refresh_token",
    }),
  });

  if (!res.ok) {
    console.error("[gmail] token error:", res.status, await res.text());
    return null;
  }
  const json = (await res.json()) as { access_token: string; expires_in: number };
  cachedToken = {
    value: json.access_token,
    expiresAt: Date.now() + json.expires_in * 1000,
  };
  return json.access_token;
}

export interface GmailMessage {
  id: string;
  threadId: string;
  from: string;
  fromEmail: string;
  subject: string;
  body: string;
  messageIdHeader: string | null;
}

function header(headers: { name: string; value: string }[], name: string): string {
  return headers.find((h) => h.name.toLowerCase() === name.toLowerCase())?.value ?? "";
}

function decodeBase64Url(data: string): string {
  return Buffer.from(data.replace(/-/g, "+").replace(/_/g, "/"), "base64").toString("utf8");
}

/** Extrae el cuerpo de texto plano de la estructura MIME de Gmail. */
function extractBody(payload: any): string {
  if (!payload) return "";
  if (payload.mimeType === "text/plain" && payload.body?.data) {
    return decodeBase64Url(payload.body.data);
  }
  if (Array.isArray(payload.parts)) {
    for (const part of payload.parts) {
      const text = extractBody(part);
      if (text) return text;
    }
  }
  if (payload.body?.data) return decodeBase64Url(payload.body.data);
  return "";
}

/** Lista los IDs de correos no leídos dirigidos a soporte (no enviados por nosotros). */
export async function listUnreadMessageIds(max = 10): Promise<string[]> {
  const token = await getAccessToken();
  if (!token) return [];
  const q = encodeURIComponent("is:unread -from:me");
  const res = await fetch(`${API}/messages?q=${q}&maxResults=${max}`, {
    headers: { authorization: `Bearer ${token}` },
  });
  if (!res.ok) return [];
  const json = (await res.json()) as { messages?: { id: string }[] };
  return (json.messages ?? []).map((m) => m.id);
}

/** Obtiene y parsea un mensaje de Gmail. */
export async function getMessage(id: string): Promise<GmailMessage | null> {
  const token = await getAccessToken();
  if (!token) return null;
  const res = await fetch(`${API}/messages/${id}?format=full`, {
    headers: { authorization: `Bearer ${token}` },
  });
  if (!res.ok) return null;
  const json = (await res.json()) as any;

  const headers = json.payload?.headers ?? [];
  const fromRaw = header(headers, "From");
  const fromEmail = fromRaw.match(/<([^>]+)>/)?.[1] ?? fromRaw.trim();

  return {
    id: json.id,
    threadId: json.threadId,
    from: fromRaw,
    fromEmail,
    subject: header(headers, "Subject"),
    body: extractBody(json.payload).trim(),
    messageIdHeader: header(headers, "Message-ID") || null,
  };
}

/** Envía una respuesta dentro del mismo hilo. */
export async function sendReply(params: {
  to: string;
  subject: string;
  body: string;
  threadId: string;
  inReplyTo?: string | null;
}): Promise<boolean> {
  const token = await getAccessToken();
  const from = process.env.GMAIL_SUPPORT_ADDRESS;
  if (!token || !from) {
    console.warn("[gmail] sin credenciales; respuesta omitida");
    return false;
  }

  const subject = params.subject.startsWith("Re:") ? params.subject : `Re: ${params.subject}`;
  const headers = [
    `From: ${from}`,
    `To: ${params.to}`,
    `Subject: ${subject}`,
    "Content-Type: text/plain; charset=UTF-8",
    "MIME-Version: 1.0",
  ];
  if (params.inReplyTo) {
    headers.push(`In-Reply-To: ${params.inReplyTo}`, `References: ${params.inReplyTo}`);
  }
  const mime = `${headers.join("\r\n")}\r\n\r\n${params.body}`;
  const raw = Buffer.from(mime)
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");

  const res = await fetch(`${API}/messages/send`, {
    method: "POST",
    headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
    body: JSON.stringify({ raw, threadId: params.threadId }),
  });

  if (!res.ok) {
    console.error("[gmail] send error:", res.status, await res.text());
    return false;
  }
  return true;
}

/** Quita la etiqueta UNREAD (marca como leído, evita reprocesar). */
export async function markAsRead(id: string): Promise<void> {
  const token = await getAccessToken();
  if (!token) return;
  await fetch(`${API}/messages/${id}/modify`, {
    method: "POST",
    headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
    body: JSON.stringify({ removeLabelIds: ["UNREAD"] }),
  });
}
