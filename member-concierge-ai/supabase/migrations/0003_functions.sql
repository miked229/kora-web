-- ============================================================================
-- Member Concierge AI — 0003_functions.sql
-- Funciones de autenticación, contexto de sesión y RAG.
-- (Se nombra 0003 porque las políticas RLS de 0002 dependen de estas
--  funciones; en Supabase las migraciones se aplican por orden de archivo,
--  por lo que 0002_rls.sql las invoca con `create or replace` previo aquí.
--  Para entornos donde el orden estricto importe, aplica 0001 → 0003 → 0002.)
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Contexto de sesión del socio.
-- La app inyecta el claim `member_id` en `request.jwt.claims` (vía PostgREST /
-- set_config) tras validar la cookie de sesión firmada.
-- ----------------------------------------------------------------------------
create or replace function current_member_id()
returns uuid
language sql
stable
as $$
  select nullif(
    current_setting('request.jwt.claims', true)::jsonb ->> 'member_id',
    ''
  )::uuid;
$$;

-- ¿El usuario autenticado (Supabase Auth) es staff?
create or replace function is_staff()
returns boolean
language sql
stable
as $$
  select exists (
    select 1 from agents
    where id = auth.uid() and active = true
  );
$$;

create or replace function is_admin()
returns boolean
language sql
stable
as $$
  select exists (
    select 1 from agents
    where id = auth.uid() and active = true and role in ('admin', 'supervisor')
  );
$$;

-- ----------------------------------------------------------------------------
-- Registro de socio: hashea el PIN con bcrypt (pgcrypto).
-- ----------------------------------------------------------------------------
create or replace function register_member(
  p_membership_no text,
  p_pin           text,
  p_full_name     text,
  p_email         text default null,
  p_phone         text default null
)
returns uuid
language plpgsql
security definer
set search_path = public
as $$
declare
  v_id uuid;
begin
  insert into members (membership_no, pin_hash, full_name, email, phone)
  values (
    p_membership_no,
    crypt(p_pin, gen_salt('bf')),
    p_full_name,
    p_email,
    p_phone
  )
  returning id into v_id;
  return v_id;
end;
$$;

-- ----------------------------------------------------------------------------
-- Verificación de credenciales del socio (número de membresía + PIN).
-- Devuelve el id si es válido; NULL en caso contrario (sin filtrar el motivo).
-- ----------------------------------------------------------------------------
create or replace function verify_membership(
  p_membership_no text,
  p_pin           text
)
returns uuid
language plpgsql
security definer
set search_path = public
as $$
declare
  v members%rowtype;
begin
  select * into v from members where membership_no = p_membership_no;
  if not found then
    return null;
  end if;
  if v.pin_hash = crypt(p_pin, v.pin_hash) then
    return v.id;
  end if;
  return null;
end;
$$;

-- ----------------------------------------------------------------------------
-- Recuperación semántica para RAG.
-- ----------------------------------------------------------------------------
create or replace function match_knowledge(
  query_embedding vector(1536),
  match_threshold float default 0.75,
  match_count     int default 5
)
returns table (
  id uuid,
  title text,
  content text,
  category text,
  similarity float
)
language sql
stable
as $$
  select
    kb.id,
    kb.title,
    kb.content,
    kb.category,
    1 - (kb.embedding <=> query_embedding) as similarity
  from knowledge_base kb
  where kb.embedding is not null
    and 1 - (kb.embedding <=> query_embedding) > match_threshold
  order by kb.embedding <=> query_embedding
  limit match_count;
$$;

-- Exponer funciones de auth a los roles de PostgREST.
grant execute on function verify_membership(text, text) to anon, authenticated;
grant execute on function current_member_id() to anon, authenticated;
grant execute on function match_knowledge(vector, float, int) to authenticated;
