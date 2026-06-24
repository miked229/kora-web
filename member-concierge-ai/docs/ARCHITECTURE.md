# Member Concierge AI — Arquitectura de la plataforma

> Plataforma premium SaaS para automatizar la atención de socios de membresías
> vacacionales y _timeshare_: chat IA 24/7, gestión de reservaciones, tickets,
> escalamiento humano, dashboard administrativo y omnicanalidad (Web, WhatsApp,
> Email) orquestada con n8n.

---

## 1. Visión general

```
                         ┌──────────────────────────────────────────────┐
                         │                 SOCIOS (Members)              │
                         │   Web Portal · WhatsApp · Email · App móvil    │
                         └───────────────┬──────────────┬───────────────┘
                                         │              │
                  ┌──────────────────────▼───┐   ┌──────▼─────────────────────┐
                  │     Next.js (App Router)  │   │   Canales externos          │
                  │  Portal socios + Admin    │   │  WhatsApp Cloud API · Gmail │
                  │  React Server Components   │   └──────┬──────────────────────┘
                  └───────────┬───────────────┘          │
                              │  Route Handlers (API)     │ Webhooks
                              ▼                           ▼
                  ┌───────────────────────────────────────────────────┐
                  │            Capa de servicios (src/lib)             │
                  │  AI Orchestrator · Intent/Sales Classifier ·       │
                  │  Ticketing · Reservations · Auth por membresía     │
                  └───────┬───────────────┬───────────────┬───────────┘
                          │               │               │
              ┌───────────▼──┐   ┌────────▼───────┐  ┌─────▼─────────┐
              │  Supabase /  │   │   OpenAI API   │  │     n8n       │
              │  PostgreSQL  │   │  Chat + Embeds │  │ Automatización │
              │  Auth · RLS  │   │  (RAG / FAQ)   │  │  (orquestador) │
              │  Storage     │   └────────────────┘  └───────────────┘
              └──────────────┘
```

**Principios de diseño**

- **Modular y por capas:** UI ↔ API (route handlers) ↔ servicios (`src/lib`) ↔
  datos (Supabase/Postgres). Ninguna página habla directamente con OpenAI ni con
  SQL crudo; todo pasa por la capa de servicios.
- **Seguro por defecto:** Row Level Security (RLS) en cada tabla, `service_role`
  solo en el servidor, validación de entrada con Zod, secretos fuera del código.
- **Omnicanal:** una conversación es la misma entidad sin importar si entró por
  Web, WhatsApp o Email. n8n normaliza y enruta.
- **Escalable:** _serverless-first_ (Vercel + Supabase), colas/automatización en
  n8n, RAG con `pgvector` para FAQ y base de conocimiento.

---

## 2. Stack tecnológico

| Capa                | Tecnología                                  | Rol |
| ------------------- | ------------------------------------------- | --- |
| Frontend / SSR      | **Next.js 14 (App Router)** + React 18      | Portal de socios y dashboard admin |
| Lenguaje            | **TypeScript** (strict)                     | Tipado end-to-end |
| Estilos             | **Tailwind CSS**                            | Tema "resort de lujo" |
| Base de datos       | **PostgreSQL** (vía **Supabase**)           | Datos transaccionales + `pgvector` |
| Backend gestionado  | **Supabase** (Auth, RLS, Storage, Edge)     | Auth, almacenamiento, políticas |
| IA                  | **OpenAI API** (chat + embeddings)          | Respuestas, clasificación, RAG |
| Email               | **Gmail API**                               | Bandeja de soporte bidireccional |
| Mensajería          | **WhatsApp Business Cloud API**             | Canal conversacional |
| Automatización      | **n8n**                                     | Orquestación de flujos y escalamientos |
| Hosting             | Vercel (web) + Supabase (datos) + n8n (VPS) | Infraestructura |

---

## 3. Estructura de carpetas

```
member-concierge-ai/
├─ docs/
│  ├─ ARCHITECTURE.md          # Este documento
│  ├─ DATABASE.md              # Modelo de datos detallado
│  ├─ AUTOMATIONS.md           # Flujos n8n + integraciones
│  └─ ROADMAP.md               # MVP → Enterprise
├─ supabase/
│  ├─ migrations/
│  │  ├─ 0001_init.sql         # Esquema, enums, índices
│  │  ├─ 0002_rls.sql          # Políticas Row Level Security
│  │  └─ 0003_functions.sql    # Funciones (auth membresía, RAG match)
│  └─ seed.sql                 # Datos demo (socios, FAQ, beneficios)
├─ src/
│  ├─ app/
│  │  ├─ (marketing)/          # Landing pública premium
│  │  │  └─ page.tsx
│  │  ├─ (portal)/             # Área autenticada de socios
│  │  │  ├─ login/page.tsx     # Login por nº de membresía
│  │  │  └─ portal/
│  │  │     ├─ layout.tsx      # Shell con navegación
│  │  │     ├─ page.tsx        # Inicio / resumen
│  │  │     ├─ chat/page.tsx   # Chat IA 24/7
│  │  │     ├─ reservations/page.tsx
│  │  │     ├─ benefits/page.tsx
│  │  │     ├─ account/page.tsx
│  │  │     └─ tickets/page.tsx
│  │  ├─ (admin)/              # Dashboard administrativo
│  │  │  └─ admin/
│  │  │     ├─ layout.tsx
│  │  │     ├─ page.tsx        # Métricas y analítica
│  │  │     ├─ conversations/page.tsx
│  │  │     └─ tickets/page.tsx
│  │  ├─ api/                  # Route Handlers (backend)
│  │  │  ├─ auth/login/route.ts
│  │  │  ├─ auth/logout/route.ts
│  │  │  ├─ chat/route.ts      # Orquestador IA (streaming)
│  │  │  ├─ tickets/route.ts
│  │  │  ├─ reservations/route.ts
│  │  │  ├─ metrics/route.ts
│  │  │  └─ webhooks/
│  │  │     ├─ whatsapp/route.ts
│  │  │     ├─ gmail/route.ts
│  │  │     └─ n8n/route.ts
│  │  ├─ globals.css
│  │  └─ layout.tsx            # Root layout + fuentes
│  ├─ components/
│  │  ├─ ui/                   # Primitivos (Button, Card, Badge, Input…)
│  │  ├─ portal/               # Sidebar, ChatWindow, MembershipCard…
│  │  └─ admin/                # MetricCard, charts, tablas
│  ├─ lib/
│  │  ├─ supabase/
│  │  │  ├─ client.ts          # Cliente navegador (anon)
│  │  │  ├─ server.ts          # Cliente servidor (cookies/RLS)
│  │  │  └─ admin.ts           # Cliente service_role (solo server)
│  │  ├─ ai/
│  │  │  ├─ openai.ts          # Cliente OpenAI
│  │  │  ├─ prompts.ts         # System prompts y plantillas
│  │  │  ├─ classify.ts        # Clasificación de intención + venta
│  │  │  └─ rag.ts             # Recuperación de conocimiento (pgvector)
│  │  ├─ auth/session.ts       # Sesión por número de membresía
│  │  ├─ services/             # Lógica de negocio (tickets, reservas…)
│  │  ├─ channels/             # whatsapp.ts, gmail.ts (envío saliente)
│  │  ├─ types.ts              # Tipos de dominio
│  │  ├─ env.ts                # Validación de variables (Zod)
│  │  └─ utils.ts
│  └─ middleware.ts            # Protección de rutas + refresco de sesión
├─ .env.example
├─ next.config.mjs
├─ tailwind.config.ts
├─ tsconfig.json
└─ package.json
```

---

## 4. Modelo de datos (resumen)

Detalle completo en [`DATABASE.md`](./DATABASE.md). Entidades núcleo:

- **`members`** — socios y su número de membresía (login).
- **`memberships`** — tipo/plan, nivel (Silver/Gold/Platinum), vigencia.
- **`reservations`** — reservaciones, cambios y cancelaciones.
- **`benefits`** / **`membership_benefits`** — catálogo y asignación de beneficios.
- **`account_statements`** — estado de cuenta y pagos.
- **`conversations`** + **`messages`** — historial omnicanal (web/WhatsApp/email).
- **`tickets`** — solicitudes generadas y su ciclo de vida.
- **`sales_opportunities`** — oportunidades detectadas por la IA.
- **`knowledge_base`** — FAQ/políticas con embeddings (`pgvector`) para RAG.
- **`agents`** + **`audit_log`** — asesores humanos y trazabilidad.

Todas las tablas con `member_id` están protegidas por **RLS**: un socio solo ve
sus datos; los `agents`/`admins` acceden según rol.

---

## 5. Autenticación

Dos planos de identidad:

1. **Socios — login por número de membresía.**
   - El socio ingresa **número de membresía + PIN/última verificación** (email o
     WhatsApp OTP en la versión escalable).
   - `POST /api/auth/login` valida contra `members` mediante la función Postgres
     `verify_membership(membership_no, pin)` (hash con `pgcrypto`), evitando
     enumeración de cuentas (mensajes genéricos, _rate limiting_).
   - Se emite una **sesión firmada (HMAC)** en cookie `httpOnly`, `secure`,
     `sameSite=lax`. La cookie contiene `member_id` y `membership_no` y se usa
     para fijar el contexto RLS (`request.jwt.claims`).
   - `middleware.ts` protege `(portal)/*` y refresca la sesión.

2. **Personal interno — Supabase Auth (email/contraseña + SSO).**
   - Asesores y administradores usan Supabase Auth con roles (`agent`, `admin`,
     `supervisor`) almacenados en `agents.role` y propagados por _custom claims_.
   - El dashboard `(admin)/*` exige rol `agent+`.

> **Por qué no Supabase Auth para socios:** los socios se identifican por número
> de membresía (no necesariamente email), y muchos llegan vía WhatsApp. El plano
> de membresía desacopla el canal de la identidad. La OTP por WhatsApp/email se
> añade en la fase escalable para MFA real.

---

## 6. Orquestador de IA

Flujo de un mensaje entrante (cualquier canal):

```
mensaje → normalizar → cargar contexto del socio (reservas, plan, saldo)
        → CLASIFICAR intención + sentimiento + señal de venta (classify.ts)
        → RAG: recuperar FAQ/políticas relevantes (rag.ts + pgvector)
        → generar respuesta (prompts.ts + OpenAI, streaming)
        → ACCIONES: ¿crear ticket? ¿reservar? ¿escalar a humano?
        → persistir mensaje + métricas + oportunidad de venta
        → responder por el canal de origen
```

**Clasificación de intención** (`src/lib/ai/classify.ts`) devuelve JSON estricto:

```jsonc
{
  "intent": "reservation_change | cancellation | billing | benefits | faq | complaint | sales_lead | other",
  "sentiment": "positive | neutral | negative",
  "urgency": "low | medium | high",
  "requires_human": false,
  "sales_signal": { "detected": true, "product": "upgrade_platinum", "confidence": 0.78 }
}
```

**Reglas de escalamiento** (a asesor humano):

- `sentiment = negative` + `urgency = high`, o
- intención `complaint` / `cancellation` con riesgo de churn, o
- la IA declara `requires_human = true` (baja confianza), o
- el socio lo solicita explícitamente ("quiero hablar con un asesor").

El escalamiento crea/actualiza un **ticket**, notifica vía n8n (Slack/WhatsApp
interno) y marca la conversación como `assigned`.

**RAG / Base de conocimiento:** las FAQ, políticas de cancelación y beneficios se
indexan como embeddings en `knowledge_base.embedding (vector)`. La función
`match_knowledge(query_embedding, threshold, count)` recupera los fragmentos más
relevantes que se inyectan en el _system prompt_ para respuestas fundamentadas.

---

## 7. Diseño de API (Route Handlers)

| Método | Ruta                         | Descripción | Auth |
| ------ | ---------------------------- | ----------- | ---- |
| POST   | `/api/auth/login`            | Login por nº de membresía | público (rate-limited) |
| POST   | `/api/auth/logout`           | Cierra sesión | socio |
| POST   | `/api/chat`                  | Mensaje al concierge IA (streaming SSE) | socio |
| GET    | `/api/reservations`          | Lista reservaciones del socio | socio |
| POST   | `/api/reservations`          | Crear / cambiar / cancelar | socio |
| GET    | `/api/tickets`               | Tickets del socio | socio |
| POST   | `/api/tickets`               | Crear ticket / escalar | socio |
| GET    | `/api/metrics`               | KPIs del dashboard | admin |
| POST   | `/api/webhooks/whatsapp`     | Entrada de WhatsApp Cloud API | firma Meta |
| GET    | `/api/webhooks/whatsapp`     | Verificación del webhook | token |
| POST   | `/api/webhooks/gmail`        | Notificación push de Gmail (Pub/Sub) | OIDC |
| POST   | `/api/webhooks/n8n`          | Acciones desde n8n (enrutado, notif.) | secreto compartido |

Convenciones: validación con **Zod**, respuestas `{ data }` / `{ error }`,
códigos HTTP correctos, idempotencia en webhooks (deduplicación por `external_id`).

---

## 8. Flujos de usuario

**A. Socio resuelve una duda (autoservicio):**
`Login → Portal → Chat IA → respuesta fundamentada (RAG) → encuesta CSAT`.

**B. Cambio de reservación:**
`Chat: "quiero cambiar mi reservación de julio" → IA confirma datos → valida
políticas → propone alternativas → socio confirma → actualiza reservation →
genera comprobante → email/WhatsApp`.

**C. Escalamiento a humano:**
`IA detecta queja/baja confianza → crea ticket → asigna asesor (round-robin) →
notifica por n8n → asesor responde desde Admin → socio recibe en su canal`.

**D. Oportunidad de venta:**
`IA detecta interés en upgrade → registra sales_opportunity → notifica a ventas →
seguimiento automatizado (n8n) → conversión`.

**E. Omnicanal por WhatsApp:**
`Socio escribe a WhatsApp → webhook → identifica por teléfono → misma lógica de
chat → respuesta → todo queda en el historial unificado`.

---

## 9. Automatizaciones (n8n)

Detalle en [`AUTOMATIONS.md`](./AUTOMATIONS.md). Flujos clave:

1. **Enrutado omnicanal:** normaliza WhatsApp/Email/Web a un evento estándar.
2. **Escalamiento:** ticket de alta urgencia → notifica equipo + crea tarea.
3. **Seguimiento de ventas:** _drip_ automatizado para `sales_opportunities`.
4. **Recordatorios de reservación:** T-7 / T-1 días, encuestas post-estancia.
5. **Cobranza/estado de cuenta:** avisos de vencimiento y confirmaciones de pago.
6. **Sincronización Gmail:** push de Gmail → conversación → respuesta del agente.

---

## 10. Seguridad

- **RLS** en todas las tablas; `service_role` jamás expuesto al cliente.
- **Validación** de toda entrada con Zod; sanitización antes de prompts.
- **Secretos** solo en variables de entorno (ver `.env.example`).
- **Webhooks** verificados (firma de Meta, OIDC de Google Pub/Sub, secreto n8n) e
  **idempotentes**.
- **PII:** cifrado en reposo (Supabase), minimización de datos en prompts,
  registros de auditoría (`audit_log`).
- **Rate limiting** en login y `/api/chat`.
- **Cabeceras de seguridad** (CSP, HSTS, etc.) en `next.config.mjs`.
- **Cumplimiento:** base lista para GDPR/derecho de supresión y retención
  configurable de conversaciones.

---

## 11. Observabilidad y métricas

KPIs expuestos en el dashboard (`/api/metrics`):

- Volumen de conversaciones por canal y por día.
- **Tasa de automatización** (% resuelto sin humano).
- Tiempo de primera respuesta y de resolución.
- CSAT / sentimiento promedio.
- Tickets abiertos/cerrados, SLA en riesgo.
- Oportunidades de venta detectadas y convertidas (pipeline).
- Costo de tokens IA por conversación.

---

## 12. Estrategia de entornos y despliegue

- **Local:** Supabase CLI (`supabase start`) + `next dev` + n8n local.
- **Staging/Prod:** Vercel (web) ↔ Supabase (DB/Auth/Storage) ↔ n8n (VPS/Docker).
- **Migraciones** versionadas en `supabase/migrations`.
- **CI/CD:** lint + typecheck + `supabase db push` + deploy Vercel por rama.

Ver [`ROADMAP.md`](./ROADMAP.md) para el plan MVP → Enterprise.
