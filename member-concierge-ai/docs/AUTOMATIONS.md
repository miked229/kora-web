# Member Concierge AI — Automatizaciones e integraciones

Orquestador: **n8n**. Cada flujo se comunica con la app vía webhooks firmados
(`/api/webhooks/n8n`) y con los canales (WhatsApp/Gmail) mediante sus APIs.

## 1. Enrutado omnicanal (entrada)

```
WhatsApp Cloud API ─┐
Gmail push (Pub/Sub) ┼─► n8n: normalizar ─► POST /api/webhooks/n8n
Web (directo /chat) ─┘     a evento estándar      (identifica socio, crea/actualiza
                                                    conversación, invoca IA)
```

Evento estándar normalizado:

```jsonc
{
  "channel": "whatsapp | email | web",
  "external_thread_id": "wa:5215512345678",
  "from": { "phone": "+5215512345678", "email": null },
  "text": "Quiero cambiar mi reservación de julio",
  "external_id": "wamid.HBgL...",   // para idempotencia
  "received_at": "2026-06-24T17:00:00Z"
}
```

## 2. WhatsApp Business Cloud API

- **Verificación** del webhook: `GET /api/webhooks/whatsapp` responde el
  `hub.challenge` si `hub.verify_token` coincide con `WHATSAPP_VERIFY_TOKEN`.
- **Entrada:** `POST /api/webhooks/whatsapp` valida la firma `X-Hub-Signature-256`
  (HMAC con el _app secret_), deduplica por `wamid`, normaliza y procesa.
- **Salida:** `src/lib/channels/whatsapp.ts` envía vía Graph API
  (`/{phone_number_id}/messages`). Plantillas aprobadas para mensajes iniciados
  por la empresa; texto libre dentro de la ventana de 24 h.

## 3. Gmail API

- **Push** mediante Google Pub/Sub → `POST /api/webhooks/gmail` (token OIDC).
- Se hace `users.history.list` para traer los mensajes nuevos, se convierten a
  conversación y se responde con `users.messages.send` (hilo `In-Reply-To`).
- Etiquetas Gmail (`Soporte/Bot`, `Soporte/Humano`) reflejan el estado.

## 4. Flujos de negocio en n8n

| Flujo | Disparador | Acción |
| ----- | ---------- | ------ |
| **Escalamiento** | Ticket `priority=urgent` o `requires_human` | Notifica Slack/WhatsApp interno, asigna asesor, crea tarea |
| **Seguimiento de ventas** | Nueva `sales_opportunity` | _Drip_ de mensajes, recordatorios a ventas, actualiza `stage` |
| **Recordatorios de reserva** | Cron T-7 / T-1 | Mensaje WhatsApp/email al socio |
| **Post-estancia / CSAT** | `reservation.completed` | Encuesta de satisfacción, guarda `csat_score` |
| **Cobranza** | `account_statement.due` | Aviso de vencimiento; confirma pago |
| **Resumen diario** | Cron 08:00 | KPIs del día al equipo (Slack/email) |

## 5. Seguridad de webhooks

- **Idempotencia:** se ignora cualquier `external_id`/`wamid` ya procesado.
- **Firma:** WhatsApp (HMAC SHA-256), Gmail (OIDC), n8n (`N8N_WEBHOOK_SECRET` en
  cabecera `x-n8n-signature`).
- **Reintentos:** los webhooks responden `2xx` rápido y delegan trabajo pesado a
  colas/n8n para evitar timeouts.

## 6. Variables requeridas

Ver `.env.example`: `WHATSAPP_*`, `GMAIL_*`, `N8N_WEBHOOK_URL`,
`N8N_WEBHOOK_SECRET`, `OPENAI_API_KEY`.
