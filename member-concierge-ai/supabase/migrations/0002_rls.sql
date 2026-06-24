-- ============================================================================
-- Member Concierge AI — 0002_rls.sql
-- Row Level Security: un socio solo ve sus datos; el staff accede ampliado.
-- Requiere las funciones de 0003_functions.sql (current_member_id, is_staff…).
-- Aplica el orden 0001 → 0003 → 0002 si tu runner es estricto con dependencias.
-- ============================================================================

alter table members             enable row level security;
alter table memberships         enable row level security;
alter table benefits            enable row level security;
alter table membership_benefits enable row level security;
alter table reservations        enable row level security;
alter table account_statements  enable row level security;
alter table conversations       enable row level security;
alter table messages            enable row level security;
alter table tickets             enable row level security;
alter table sales_opportunities enable row level security;
alter table knowledge_base      enable row level security;
alter table agents              enable row level security;

-- ----------------------------------------------------------------------------
-- members
-- ----------------------------------------------------------------------------
create policy members_self_select on members
  for select using (id = current_member_id() or is_staff());
create policy members_self_update on members
  for update using (id = current_member_id());
create policy members_staff_all on members
  for all using (is_staff()) with check (is_staff());

-- ----------------------------------------------------------------------------
-- memberships / benefits
-- ----------------------------------------------------------------------------
create policy memberships_owner on memberships
  for select using (member_id = current_member_id() or is_staff());

create policy benefits_read on benefits
  for select using (true);                     -- catálogo público autenticado

create policy membership_benefits_owner on membership_benefits
  for select using (
    is_staff() or exists (
      select 1 from memberships m
      where m.id = membership_benefits.membership_id
        and m.member_id = current_member_id()
    )
  );

-- ----------------------------------------------------------------------------
-- reservations
-- ----------------------------------------------------------------------------
create policy reservations_select on reservations
  for select using (member_id = current_member_id() or is_staff());
create policy reservations_insert on reservations
  for insert with check (member_id = current_member_id() or is_staff());
create policy reservations_update on reservations
  for update using (member_id = current_member_id() or is_staff());

-- ----------------------------------------------------------------------------
-- account_statements
-- ----------------------------------------------------------------------------
create policy statements_owner on account_statements
  for select using (member_id = current_member_id() or is_staff());

-- ----------------------------------------------------------------------------
-- conversations / messages
-- ----------------------------------------------------------------------------
create policy conversations_select on conversations
  for select using (member_id = current_member_id() or is_staff());
create policy conversations_insert on conversations
  for insert with check (member_id = current_member_id() or is_staff());
create policy conversations_update on conversations
  for update using (member_id = current_member_id() or is_staff());

create policy messages_select on messages
  for select using (
    is_staff() or exists (
      select 1 from conversations c
      where c.id = messages.conversation_id
        and c.member_id = current_member_id()
    )
  );
create policy messages_insert on messages
  for insert with check (
    is_staff() or exists (
      select 1 from conversations c
      where c.id = messages.conversation_id
        and c.member_id = current_member_id()
    )
  );

-- ----------------------------------------------------------------------------
-- tickets
-- ----------------------------------------------------------------------------
create policy tickets_select on tickets
  for select using (member_id = current_member_id() or is_staff());
create policy tickets_insert on tickets
  for insert with check (member_id = current_member_id() or is_staff());
create policy tickets_update on tickets
  for update using (is_staff() or member_id = current_member_id());

-- ----------------------------------------------------------------------------
-- sales_opportunities (solo staff las gestiona)
-- ----------------------------------------------------------------------------
create policy sales_staff on sales_opportunities
  for all using (is_staff()) with check (is_staff());

-- ----------------------------------------------------------------------------
-- knowledge_base (lectura autenticada, escritura staff)
-- ----------------------------------------------------------------------------
create policy kb_read on knowledge_base
  for select using (true);
create policy kb_write on knowledge_base
  for all using (is_staff()) with check (is_staff());

-- ----------------------------------------------------------------------------
-- agents (cada uno ve su ficha; admin gestiona)
-- ----------------------------------------------------------------------------
create policy agents_self on agents
  for select using (id = auth.uid() or is_admin());
create policy agents_admin on agents
  for all using (is_admin()) with check (is_admin());

-- NOTA: el cliente `service_role` (solo servidor) omite RLS para operaciones de
-- sistema (webhooks, IA, automatizaciones). Nunca exponer esa clave al cliente.
