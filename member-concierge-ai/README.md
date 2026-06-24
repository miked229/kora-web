# Member Concierge AI

> Plataforma **premium SaaS** para automatizar la atención de socios de
> membresías vacacionales y _timeshare_: chat IA 24/7, gestión de reservaciones,
> beneficios, estado de cuenta, tickets, escalamiento humano, dashboard
> administrativo y soporte **omnicanal** (Web · WhatsApp · Email) orquestado con
> **n8n**.

Diseño visual inspirado en resorts de lujo del Caribe — paleta **azul océano,
turquesa, blanco arena y dorado**.

---

## 🧱 Stack

Next.js 14 (App Router) · TypeScript · Tailwind CSS · Supabase / PostgreSQL
(`pgvector`) · OpenAI API · Gmail API · WhatsApp Business Cloud API · n8n.

## 📚 Documentación

- [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) — arquitectura completa.
- [`docs/DATABASE.md`](./docs/DATABASE.md) — modelo de datos y RLS.
- [`docs/AUTOMATIONS.md`](./docs/AUTOMATIONS.md) — integraciones y flujos n8n.
- [`docs/ROADMAP.md`](./docs/ROADMAP.md) — MVP → Enterprise.

## 🚀 Puesta en marcha (local)

```bash
# 1) Dependencias
npm install

# 2) Variables de entorno
cp .env.example .env.local      # rellena Supabase + OpenAI como mínimo

# 3) Base de datos (Supabase CLI)
supabase start
supabase db reset               # aplica migraciones + seed
#   Orden de migraciones si tu runner es estricto: 0001 → 0003 → 0002

# 4) (Opcional) Indexar la base de conocimiento para RAG
npx tsx scripts/ingest-knowledge.ts

# 5) App
npm run dev                     # http://localhost:3000
```

### Credenciales demo (socio)

`Número de membresía:` **KORA-100001** · `PIN:` **1234**

## 🗂️ Estructura

```
src/app        → rutas (marketing, portal socios, admin, API)
src/components → UI premium (ui/, portal/, admin/)
src/lib        → servicios: ai/, supabase/, auth/, services/, channels/
supabase/      → migraciones SQL + seed
docs/          → arquitectura, base de datos, automatizaciones, roadmap
scripts/       → utilidades (ingesta de conocimiento)
```

## ✨ Funcionalidades (MVP incluido)

Portal de socios · login por nº de membresía · **Chat IA 24/7** con streaming ·
clasificación de intención/sentimiento/venta · gestión de reservaciones
(cambio/cancelación) · beneficios por nivel · estado de cuenta · tickets +
escalamiento a humano · dashboard admin con métricas · historial omnicanal ·
webhooks WhatsApp/Gmail/n8n.

## 🔐 Seguridad

RLS en todas las tablas · `service_role` solo en servidor · validación con Zod ·
sesión de socio firmada (HMAC, cookie httpOnly) · webhooks verificados e
idempotentes · cabeceras de seguridad. Ver `docs/ARCHITECTURE.md §10`.

## 📦 Scripts

| Script | Acción |
| ------ | ------ |
| `npm run dev` | Servidor de desarrollo |
| `npm run build` / `start` | Build y arranque de producción |
| `npm run lint` / `typecheck` | Calidad de código |
| `npm run db:reset` | Reaplica migraciones + seed |
| `npm run db:types` | Genera tipos TS desde el esquema |

---

© Kora · Member Concierge AI — Membresías vacacionales de lujo.
