# Member Concierge AI — Roadmap (MVP → Enterprise)

## Fase 0 — Fundaciones (semana 1–2)

- Repositorio, CI/CD, entornos (local/staging/prod).
- Esquema Supabase + RLS + seeds.
- Tema UI "resort de lujo", componentes base.
- Login por número de membresía + sesión segura.

## Fase 1 — MVP (semana 3–6) ✅ alcance inicial de este scaffold

Objetivo: **autoservicio funcional por web** que reduzca tickets.

- [x] Portal de socios (login, inicio, navegación premium).
- [x] **Chat IA 24/7** con contexto del socio + streaming.
- [x] Clasificación de intención + sentimiento + señal de venta.
- [x] Gestión de reservaciones (ver / cambiar / cancelar).
- [x] Beneficios de membresía y estado de cuenta.
- [x] Generación de tickets + escalamiento a humano.
- [x] Dashboard admin con métricas base.
- [x] Historial de conversaciones.
- [ ] RAG sobre FAQ con `pgvector` (estructura lista, ingestión pendiente).

**Criterio de éxito:** ≥ 50% de solicitudes resueltas sin asesor humano.

## Fase 2 — Omnicanal (semana 7–10)

- [x] Integración **WhatsApp Business Cloud API** (entrante + respuesta
  automática del concierge, idempotente por `wamid`).
- [x] Integración **Gmail API** (lectura OAuth2 + respuesta automática en hilo +
  marcado como leído).
- [x] **Orquestador compartido** reutilizado por web, WhatsApp y email.
- [ ] **n8n**: enrutado de remitentes no reconocidos, escalamientos, recordatorios.
- [ ] Identidad unificada socio ↔ teléfono/email (auto-vinculación por OTP).
- [ ] CSAT post-conversación.

**Criterio de éxito:** una sola bandeja unificada; respuesta < 1 min en bot.

## Fase 3 — Inteligencia de negocio (semana 11–14)

- Pipeline de **oportunidades de venta** + seguimiento automatizado.
- RAG completo con base de conocimiento versionada.
- Analítica avanzada: churn, CSAT, costo de tokens, SLA.
- A/B testing de prompts; _guardrails_ y evaluaciones.
- Roles y permisos finos (agente/supervisor/admin).

## Fase 4 — Enterprise / escalable (semana 15+)

- **Multi-tenant** (varios resorts/marcas con aislamiento por `org_id`).
- SSO/SAML para personal interno; auditoría y cumplimiento (SOC2/GDPR).
- Colas y workers dedicados (alta concurrencia), caché y _rate limiting_ global.
- Modelos IA configurables por tenant; _fine-tuning_/embeddings propios.
- App móvil (React Native) reutilizando la capa de servicios.
- Voz (IVR/llamadas) y traducción multilingüe automática.
- Observabilidad (OpenTelemetry), alertas y _dashboards_ SRE.
- Integraciones PMS/ERP (Opera, SAP) y pasarelas de pago.

## Comparativa MVP vs Enterprise

| Capacidad | MVP | Enterprise |
| --------- | --- | ---------- |
| Canales | Web | Web + WhatsApp + Email + Voz |
| Tenancy | Single | Multi-tenant aislado |
| IA | Chat + clasificación | RAG + fine-tuning + guardrails + evals |
| Auth socio | Membresía + PIN | Membresía + OTP/MFA |
| Auth staff | Email/contraseña | SSO/SAML + RBAC fino |
| Automatización | Básica (escalamiento) | Orquestación completa n8n + workers |
| Analítica | KPIs base | BI avanzado + predictivo (churn) |
| Cumplimiento | Buenas prácticas | SOC2/GDPR formal, retención configurable |
| Infra | Serverless | Serverless + colas + caché + SRE |
