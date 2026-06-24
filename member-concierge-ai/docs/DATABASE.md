# Member Concierge AI — Modelo de datos

Base de datos **PostgreSQL** gestionada por **Supabase**. Todas las tablas con
`member_id` están protegidas por **Row Level Security (RLS)**. El esquema vive en
`supabase/migrations/`.

## Diagrama de entidades (texto)

```
members ──1:N── memberships ──1:N── membership_benefits ──N:1── benefits
   │
   ├──1:N── reservations
   ├──1:N── account_statements
   ├──1:N── conversations ──1:N── messages
   ├──1:N── tickets ──N:1── agents
   └──1:N── sales_opportunities

knowledge_base (embeddings, pgvector)        agents ──1:N── tickets
audit_log (trazabilidad global)              app_users (Supabase Auth ↔ agents)
```

## Enumeraciones

| Enum | Valores |
| ---- | ------- |
| `membership_tier` | `silver`, `gold`, `platinum`, `signature` |
| `membership_status` | `active`, `suspended`, `expired`, `cancelled` |
| `reservation_status` | `pending`, `confirmed`, `changed`, `cancelled`, `completed` |
| `channel` | `web`, `whatsapp`, `email` |
| `conversation_status` | `open`, `bot`, `assigned`, `resolved`, `closed` |
| `message_role` | `member`, `assistant`, `agent`, `system` |
| `ticket_status` | `new`, `open`, `pending`, `escalated`, `resolved`, `closed` |
| `ticket_priority` | `low`, `medium`, `high`, `urgent` |
| `ticket_category` | `reservation`, `cancellation`, `billing`, `benefits`, `complaint`, `general` |
| `agent_role` | `agent`, `supervisor`, `admin` |
| `opportunity_stage` | `detected`, `qualified`, `contacted`, `won`, `lost` |

## Tablas principales

### `members`
Socio. El **número de membresía** es la credencial de acceso.

| Columna | Tipo | Notas |
| ------- | ---- | ----- |
| `id` | `uuid` PK | |
| `membership_no` | `text` UNIQUE | Login del socio |
| `pin_hash` | `text` | Hash bcrypt/pgcrypto del PIN |
| `full_name` | `text` | |
| `email` | `text` | Para OTP/notificaciones |
| `phone` | `text` | E.164, vínculo con WhatsApp |
| `locale` | `text` | `es-MX` por defecto |
| `created_at` / `updated_at` | `timestamptz` | |

### `memberships`
Plan/contrato del socio (un socio puede renovar/tener varios históricos).

| Columna | Tipo | Notas |
| ------- | ---- | ----- |
| `id` | `uuid` PK | |
| `member_id` | `uuid` FK | |
| `tier` | `membership_tier` | |
| `status` | `membership_status` | |
| `weeks_per_year` | `int` | Semanas vacacionales |
| `points_balance` | `int` | Puntos canjeables |
| `start_date` / `end_date` | `date` | Vigencia |

### `benefits` / `membership_benefits`
Catálogo de beneficios y su asignación por tier/membresía.

`benefits`: `id`, `code`, `name`, `description`, `tier_required`, `active`.
`membership_benefits`: `id`, `membership_id` FK, `benefit_id` FK, `used`, `quota`.

### `reservations`
Reservaciones, cambios y cancelaciones.

| Columna | Tipo | Notas |
| ------- | ---- | ----- |
| `id` | `uuid` PK | |
| `member_id` | `uuid` FK | |
| `resort_name` | `text` | |
| `room_type` | `text` | |
| `check_in` / `check_out` | `date` | |
| `guests` | `int` | |
| `status` | `reservation_status` | |
| `confirmation_code` | `text` | |
| `change_history` | `jsonb` | Auditoría de cambios |

### `account_statements`
Estado de cuenta y pagos.

`id`, `member_id` FK, `period`, `amount_due` `numeric`, `amount_paid` `numeric`,
`due_date`, `paid_at`, `status` (`pending|paid|overdue`), `items` `jsonb`.

### `conversations` / `messages`
Historial **omnicanal**. Una conversación agrupa mensajes de un canal/hilo.

`conversations`: `id`, `member_id` FK (nullable hasta identificar), `channel`,
`status`, `assigned_agent_id` FK, `external_thread_id` (id de WhatsApp/Gmail),
`last_message_at`, `csat_score`, `created_at`.

`messages`: `id`, `conversation_id` FK, `role` (`message_role`), `content`,
`intent`, `sentiment`, `tokens`, `external_id` (idempotencia), `created_at`.

### `tickets`
Solicitudes y su ciclo de vida.

`id`, `member_id` FK, `conversation_id` FK, `subject`, `category`, `priority`,
`status`, `assigned_agent_id` FK, `sla_due_at`, `resolution`, `created_at`,
`resolved_at`.

### `sales_opportunities`
Oportunidades de venta detectadas por la IA.

`id`, `member_id` FK, `conversation_id` FK, `product`, `stage`, `confidence`
`numeric`, `estimated_value` `numeric`, `notes`, `created_at`.

### `knowledge_base`
FAQ, políticas y beneficios indexados para **RAG** (`pgvector`).

`id`, `title`, `content`, `category`, `tier_scope`, `embedding` `vector(1536)`,
`source`, `updated_at`. Índice `ivfflat` sobre `embedding`.

### `agents`
Asesores humanos (vinculados a Supabase Auth).

`id` (= `auth.users.id`), `full_name`, `email`, `role` (`agent_role`), `active`,
`max_concurrent`, `created_at`.

### `audit_log`
Trazabilidad de acciones sensibles.

`id`, `actor_type` (`member|agent|system`), `actor_id`, `action`, `entity`,
`entity_id`, `metadata` `jsonb`, `created_at`.

## Políticas RLS (resumen)

- **Socios:** `member_id = current_member_id()` para SELECT/INSERT/UPDATE en sus
  propias filas (`reservations`, `tickets`, `conversations`, `messages`,
  `account_statements`, `sales_opportunities`).
- **Agentes/Admins:** acceso ampliado vía `is_staff()` / `is_admin()` basados en
  `agents.role`.
- **`knowledge_base`:** lectura pública autenticada; escritura solo staff.
- `current_member_id()` lee el claim de la sesión de membresía
  (`request.jwt.claims -> member_id`).

Las funciones (`verify_membership`, `current_member_id`, `is_staff`,
`match_knowledge`) están en `0003_functions.sql`.
