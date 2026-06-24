-- ============================================================================
-- Member Concierge AI — 0001_init.sql
-- Esquema base: extensiones, enums, tablas, índices.
-- ============================================================================

create extension if not exists "pgcrypto";   -- gen_random_uuid, crypt, gen_salt
create extension if not exists "vector";      -- pgvector (RAG)

-- ----------------------------------------------------------------------------
-- Enumeraciones
-- ----------------------------------------------------------------------------
create type membership_tier     as enum ('silver', 'gold', 'platinum', 'signature');
create type membership_status   as enum ('active', 'suspended', 'expired', 'cancelled');
create type reservation_status  as enum ('pending', 'confirmed', 'changed', 'cancelled', 'completed');
create type channel             as enum ('web', 'whatsapp', 'email');
create type conversation_status as enum ('open', 'bot', 'assigned', 'resolved', 'closed');
create type message_role        as enum ('member', 'assistant', 'agent', 'system');
create type ticket_status       as enum ('new', 'open', 'pending', 'escalated', 'resolved', 'closed');
create type ticket_priority     as enum ('low', 'medium', 'high', 'urgent');
create type ticket_category     as enum ('reservation', 'cancellation', 'billing', 'benefits', 'complaint', 'general');
create type agent_role          as enum ('agent', 'supervisor', 'admin');
create type opportunity_stage   as enum ('detected', 'qualified', 'contacted', 'won', 'lost');

-- ----------------------------------------------------------------------------
-- Núcleo: socios y membresías
-- ----------------------------------------------------------------------------
create table members (
  id             uuid primary key default gen_random_uuid(),
  membership_no  text unique not null,
  pin_hash       text not null,
  full_name      text not null,
  email          text,
  phone          text,                      -- E.164, vínculo con WhatsApp
  locale         text not null default 'es-MX',
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);
create index members_phone_idx on members (phone);
create index members_email_idx on members (lower(email));

create table memberships (
  id              uuid primary key default gen_random_uuid(),
  member_id       uuid not null references members(id) on delete cascade,
  tier            membership_tier not null default 'silver',
  status          membership_status not null default 'active',
  weeks_per_year  int not null default 1,
  points_balance  int not null default 0,
  start_date      date not null default current_date,
  end_date        date,
  created_at      timestamptz not null default now()
);
create index memberships_member_idx on memberships (member_id);

create table benefits (
  id            uuid primary key default gen_random_uuid(),
  code          text unique not null,
  name          text not null,
  description   text,
  tier_required membership_tier not null default 'silver',
  active        boolean not null default true
);

create table membership_benefits (
  id            uuid primary key default gen_random_uuid(),
  membership_id uuid not null references memberships(id) on delete cascade,
  benefit_id    uuid not null references benefits(id) on delete cascade,
  used          int not null default 0,
  quota         int,
  unique (membership_id, benefit_id)
);

-- ----------------------------------------------------------------------------
-- Reservaciones
-- ----------------------------------------------------------------------------
create table reservations (
  id                uuid primary key default gen_random_uuid(),
  member_id         uuid not null references members(id) on delete cascade,
  resort_name       text not null,
  room_type         text,
  check_in          date not null,
  check_out         date not null,
  guests            int not null default 2,
  status            reservation_status not null default 'pending',
  confirmation_code text unique,
  change_history    jsonb not null default '[]'::jsonb,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  check (check_out > check_in)
);
create index reservations_member_idx on reservations (member_id, check_in);

-- ----------------------------------------------------------------------------
-- Estado de cuenta
-- ----------------------------------------------------------------------------
create table account_statements (
  id          uuid primary key default gen_random_uuid(),
  member_id   uuid not null references members(id) on delete cascade,
  period      text not null,                 -- p. ej. '2026-06'
  amount_due  numeric(12,2) not null default 0,
  amount_paid numeric(12,2) not null default 0,
  due_date    date,
  paid_at     timestamptz,
  status      text not null default 'pending', -- pending | paid | overdue
  items       jsonb not null default '[]'::jsonb,
  created_at  timestamptz not null default now()
);
create index account_statements_member_idx on account_statements (member_id, period);

-- ----------------------------------------------------------------------------
-- Personal interno (vinculado a Supabase Auth: id = auth.users.id)
-- ----------------------------------------------------------------------------
create table agents (
  id             uuid primary key,           -- = auth.users.id
  full_name      text not null,
  email          text not null,
  role           agent_role not null default 'agent',
  active         boolean not null default true,
  max_concurrent int not null default 5,
  created_at     timestamptz not null default now()
);

-- ----------------------------------------------------------------------------
-- Conversaciones omnicanal + mensajes
-- ----------------------------------------------------------------------------
create table conversations (
  id                 uuid primary key default gen_random_uuid(),
  member_id          uuid references members(id) on delete set null,
  channel            channel not null default 'web',
  status             conversation_status not null default 'bot',
  assigned_agent_id  uuid references agents(id) on delete set null,
  external_thread_id text,                    -- id de WhatsApp/Gmail
  subject            text,
  csat_score         int,                     -- 1..5
  last_message_at    timestamptz not null default now(),
  created_at         timestamptz not null default now()
);
create index conversations_member_idx on conversations (member_id, last_message_at desc);
create index conversations_status_idx on conversations (status);
create unique index conversations_external_idx
  on conversations (channel, external_thread_id)
  where external_thread_id is not null;

create table messages (
  id              uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references conversations(id) on delete cascade,
  role            message_role not null,
  content         text not null,
  intent          text,
  sentiment       text,
  tokens          int,
  external_id     text,                       -- idempotencia (wamid, gmail id)
  created_at      timestamptz not null default now()
);
create index messages_conversation_idx on messages (conversation_id, created_at);
create unique index messages_external_idx on messages (external_id) where external_id is not null;

-- ----------------------------------------------------------------------------
-- Tickets
-- ----------------------------------------------------------------------------
create table tickets (
  id                uuid primary key default gen_random_uuid(),
  member_id         uuid not null references members(id) on delete cascade,
  conversation_id   uuid references conversations(id) on delete set null,
  subject           text not null,
  description       text,
  category          ticket_category not null default 'general',
  priority          ticket_priority not null default 'medium',
  status            ticket_status not null default 'new',
  assigned_agent_id uuid references agents(id) on delete set null,
  sla_due_at        timestamptz,
  resolution        text,
  created_at        timestamptz not null default now(),
  resolved_at       timestamptz
);
create index tickets_member_idx on tickets (member_id, created_at desc);
create index tickets_status_idx on tickets (status, priority);

-- ----------------------------------------------------------------------------
-- Oportunidades de venta detectadas por la IA
-- ----------------------------------------------------------------------------
create table sales_opportunities (
  id               uuid primary key default gen_random_uuid(),
  member_id        uuid not null references members(id) on delete cascade,
  conversation_id  uuid references conversations(id) on delete set null,
  product          text not null,
  stage            opportunity_stage not null default 'detected',
  confidence       numeric(4,3) not null default 0,   -- 0..1
  estimated_value  numeric(12,2),
  notes            text,
  created_at       timestamptz not null default now()
);
create index sales_member_idx on sales_opportunities (member_id);
create index sales_stage_idx on sales_opportunities (stage);

-- ----------------------------------------------------------------------------
-- Base de conocimiento (RAG con pgvector)
-- ----------------------------------------------------------------------------
create table knowledge_base (
  id          uuid primary key default gen_random_uuid(),
  title       text not null,
  content     text not null,
  category    text,
  tier_scope  membership_tier,               -- null = aplica a todos
  source      text,
  embedding   vector(1536),                  -- text-embedding-3-small
  updated_at  timestamptz not null default now()
);
create index knowledge_embedding_idx on knowledge_base
  using ivfflat (embedding vector_cosine_ops) with (lists = 100);

-- ----------------------------------------------------------------------------
-- Auditoría
-- ----------------------------------------------------------------------------
create table audit_log (
  id          uuid primary key default gen_random_uuid(),
  actor_type  text not null,                 -- member | agent | system
  actor_id    uuid,
  action      text not null,
  entity      text,
  entity_id   uuid,
  metadata    jsonb not null default '{}'::jsonb,
  created_at  timestamptz not null default now()
);
create index audit_entity_idx on audit_log (entity, entity_id);

-- ----------------------------------------------------------------------------
-- Trigger genérico de updated_at
-- ----------------------------------------------------------------------------
create or replace function set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger members_updated      before update on members      for each row execute function set_updated_at();
create trigger reservations_updated before update on reservations for each row execute function set_updated_at();
