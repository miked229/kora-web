import "server-only";

/**
 * Integración con Gmail API (cuenta de soporte).
 *
 * En producción se usa OAuth2 con `GMAIL_CLIENT_ID/SECRET/REFRESH_TOKEN` para
 * obtener un access token, y la API REST de Gmail para leer (history.list) y
 * responder (messages.send) manteniendo el hilo (`In-Reply-To`).
 *
 * Aquí se deja la firma del servicio; el intercambio OAuth y el polling/push
 * por Pub/Sub se orquestan vía n8n (ver docs/AUTOMATIONS.md).
 */

interface OutboundEmail {
  to: string;
  subject: string;
  body: string;
  threadId?: string;
  inReplyTo?: string;
}

export async function sendSupportEmail(email: OutboundEmail): Promise<void> {
  const from = process.env.GMAIL_SUPPORT_ADDRESS;
  if (!from) {
    console.warn("[gmail] GMAIL_SUPPORT_ADDRESS no configurado; email omitido");
    return;
  }

  // TODO: implementar OAuth2 + gmail.users.messages.send.
  // Recomendado: delegar el envío al flujo n8n "Soporte/Email saliente"
  // para centralizar credenciales y reintentos.
  console.warn(
    `[gmail] (stub) enviar a ${email.to} asunto="${email.subject}" — delegar a n8n`,
  );
}
