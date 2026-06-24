import "server-only";

/**
 * Modo DEMO — adaptador de datos en memoria.
 *
 * Cuando `DEMO_MODE=true`, `createAdminClient()` devuelve este cliente simulado
 * en lugar de Supabase, sirviendo los mismos datos que `supabase/seed.sql`.
 * Permite previsualizar/vender la plataforma (y generar capturas) sin levantar
 * la base de datos ni servicios externos. NO se activa en producción salvo que
 * se ponga explícitamente la variable de entorno.
 *
 * Soporta el subconjunto de la API de supabase-js que usa la app:
 * from().select().eq().in().order().limit().maybeSingle()/single(), await,
 * insert().select().single() y rpc().
 */

type Row = Record<string, any>;

const member: Row = {
  id: "demo-member",
  membership_no: "KORA-100001",
  full_name: "María Fernanda López",
  email: "maria@example.com",
  phone: "+5215512345001",
  locale: "es-MX",
};

const memberRef = { full_name: member.full_name, membership_no: member.membership_no };

const fixtures: Record<string, Row[]> = {
  members: [member],
  memberships: [
    {
      id: "ms1",
      member_id: "demo-member",
      tier: "platinum",
      status: "active",
      weeks_per_year: 3,
      points_balance: 45000,
      start_date: "2024-01-01",
      end_date: "2031-01-01",
    },
  ],
  reservations: [
    {
      id: "r1",
      member_id: "demo-member",
      resort_name: "Kora Riviera Maya",
      room_type: "Suite Ocean View",
      check_in: "2026-07-12",
      check_out: "2026-07-19",
      guests: 4,
      status: "confirmed",
      confirmation_code: "CNF-7A19X2",
      change_history: [],
    },
    {
      id: "r2",
      member_id: "demo-member",
      resort_name: "Kora Los Cabos",
      room_type: "Junior Suite",
      check_in: "2026-09-05",
      check_out: "2026-09-10",
      guests: 2,
      status: "pending",
      confirmation_code: "CNF-9C05B7",
      change_history: [],
    },
  ],
  benefits: [
    { id: "b1", code: "LATE_CHECKOUT", name: "Late check-out", description: "Salida tardía hasta las 15:00", tier_required: "silver", active: true },
    { id: "b2", code: "UPGRADE", name: "Upgrade de habitación", description: "Mejora de categoría sujeta a disponibilidad", tier_required: "gold", active: true },
    { id: "b3", code: "SPA", name: "Acceso premium al spa", description: "Circuito de hidroterapia incluido", tier_required: "gold", active: true },
    { id: "b4", code: "AIRPORT", name: "Transporte aeropuerto", description: "Traslado privado de cortesía", tier_required: "platinum", active: true },
    { id: "b5", code: "CONCIERGE", name: "Concierge dedicado", description: "Asistente personal 24/7", tier_required: "platinum", active: true },
  ],
  account_statements: [
    { id: "s1", member_id: "demo-member", period: "2026-06", amount_due: 0, amount_paid: 12500, due_date: "2026-06-10", status: "paid", items: [] },
    { id: "s2", member_id: "demo-member", period: "2026-05", amount_due: 8900, amount_paid: 0, due_date: "2026-06-30", status: "pending", items: [] },
  ],
  tickets: [
    { id: "t1", member_id: "demo-member", members: memberRef, subject: "Cambio de fechas — Riviera Maya", description: "Solicito mover mi estancia de julio una semana.", category: "reservation", priority: "high", status: "escalated", created_at: "2026-06-22T15:30:00Z", sla_due_at: "2026-06-22T19:30:00Z" },
    { id: "t2", member_id: "demo-member", members: memberRef, subject: "Duda sobre beneficios Platinum", description: "¿El transporte al aeropuerto aplica para 4 personas?", category: "benefits", priority: "low", status: "resolved", created_at: "2026-06-20T11:00:00Z" },
    { id: "t3", member_id: "demo-member", members: memberRef, subject: "Factura de mantenimiento 2026", description: "Necesito la factura del último pago.", category: "billing", priority: "medium", status: "open", created_at: "2026-06-23T09:15:00Z" },
    { id: "t4", member_id: "demo-member", members: memberRef, subject: "Upgrade a Signature", description: "Interesada en mejorar mi membresía.", category: "general", priority: "medium", status: "new", created_at: "2026-06-24T08:05:00Z" },
  ],
  conversations: [
    { id: "c1", member_id: "demo-member", members: memberRef, channel: "web", status: "resolved", subject: "Beneficios de mi membresía", last_message_at: "2026-06-24T10:12:00Z" },
    { id: "c2", member_id: "demo-member", members: memberRef, channel: "whatsapp", status: "resolved", subject: "Cambio de reservación", last_message_at: "2026-06-24T09:40:00Z" },
    { id: "c3", member_id: "demo-member", members: memberRef, channel: "email", status: "assigned", subject: "Reclamo de facturación", last_message_at: "2026-06-23T18:22:00Z" },
    { id: "c4", member_id: "demo-member", members: memberRef, channel: "web", status: "resolved", subject: "Política de cancelación", last_message_at: "2026-06-23T16:05:00Z" },
    { id: "c5", member_id: "demo-member", members: memberRef, channel: "whatsapp", status: "bot", subject: "Estado de cuenta", last_message_at: "2026-06-23T12:30:00Z" },
    { id: "c6", member_id: "demo-member", members: memberRef, channel: "web", status: "resolved", subject: "Upgrade Platinum", last_message_at: "2026-06-22T20:11:00Z" },
    { id: "c7", member_id: "demo-member", members: memberRef, channel: "email", status: "resolved", subject: "Confirmación de estancia", last_message_at: "2026-06-22T14:48:00Z" },
    { id: "c8", member_id: "demo-member", members: memberRef, channel: "whatsapp", status: "resolved", subject: "Late check-out", last_message_at: "2026-06-21T19:03:00Z" },
  ],
  sales_opportunities: [
    { id: "o1", member_id: "demo-member", product: "upgrade_signature", stage: "qualified", confidence: 0.82, created_at: "2026-06-24T08:06:00Z" },
    { id: "o2", member_id: "demo-member", product: "semana_adicional", stage: "detected", confidence: 0.64, created_at: "2026-06-22T20:12:00Z" },
    { id: "o3", member_id: "demo-member", product: "spa_premium", stage: "contacted", confidence: 0.71, created_at: "2026-06-20T10:00:00Z" },
  ],
  messages: [],
  knowledge_base: [],
};

type Pred = (r: Row) => boolean;

class DemoBuilder implements PromiseLike<{ data: Row[]; count: number | null; error: null }> {
  private rows: Row[];
  private preds: Pred[] = [];
  private head = false;
  private wantCount = false;
  private lim: number | null = null;

  constructor(table: string) {
    this.rows = (fixtures[table] ?? []).map((r) => ({ ...r }));
  }

  select(_sel?: string, opts?: { count?: string; head?: boolean }) {
    if (opts?.count) this.wantCount = true;
    if (opts?.head) this.head = true;
    return this;
  }
  eq(col: string, val: unknown) {
    this.preds.push((r) => r[col] === val);
    return this;
  }
  in(col: string, vals: unknown[]) {
    this.preds.push((r) => vals.includes(r[col]));
    return this;
  }
  ilike(col: string, val: string) {
    const needle = val.replace(/%/g, "").toLowerCase();
    this.preds.push((r) => String(r[col] ?? "").toLowerCase().includes(needle));
    return this;
  }
  gte() { return this; }
  lte() { return this; }
  is() { return this; }
  not() { return this; }
  order() { return this; }
  limit(n: number) { this.lim = n; return this; }

  private apply(): Row[] {
    let r = this.rows.filter((row) => this.preds.every((p) => p(row)));
    if (this.lim != null) r = r.slice(0, this.lim);
    return r;
  }

  maybeSingle() {
    return Promise.resolve({ data: this.apply()[0] ?? null, error: null });
  }
  single() {
    return Promise.resolve({ data: this.apply()[0] ?? null, error: null });
  }

  // Awaitable: resolves to { data, count }.
  then<TResult1 = { data: Row[]; count: number | null; error: null }>(
    onfulfilled?: ((value: { data: Row[]; count: number | null; error: null }) => TResult1 | PromiseLike<TResult1>) | null,
  ): PromiseLike<TResult1> {
    const r = this.apply();
    const value = this.head
      ? { data: null as unknown as Row[], count: r.length, error: null as null }
      : { data: r, count: this.wantCount ? r.length : null, error: null as null };
    return Promise.resolve(onfulfilled ? onfulfilled(value) : (value as unknown as TResult1));
  }
}

class DemoInsert {
  constructor(private rows: Row[]) {}
  select() { return this; }
  single() { return Promise.resolve({ data: this.rows[0] ?? null, error: null }); }
  maybeSingle() { return Promise.resolve({ data: this.rows[0] ?? null, error: null }); }
  then(onfulfilled?: (value: { data: Row[]; error: null }) => unknown) {
    const value = { data: this.rows, error: null as null };
    return Promise.resolve(onfulfilled ? onfulfilled(value) : value);
  }
}

function makeClient() {
  return {
    from(table: string) {
      return {
        select: (...a: any[]) => new DemoBuilder(table).select(...(a as [string, any])),
        insert: (values: Row | Row[]) => {
          const arr = Array.isArray(values) ? values : [values];
          const inserted = arr.map((v, i) => ({
            id: `demo-${Date.now()}-${i}`,
            created_at: new Date().toISOString(),
            ...v,
          }));
          return new DemoInsert(inserted);
        },
        update: () => ({ eq: () => ({ select: () => ({ single: () => Promise.resolve({ data: null, error: null }) }) }) }),
      };
    },
    rpc(name: string) {
      if (name === "verify_membership") return Promise.resolve({ data: member.id, error: null });
      return Promise.resolve({ data: [], error: null });
    },
    auth: {
      getUser: async () => ({ data: { user: null }, error: null }),
    },
  };
}

export function isDemoMode(): boolean {
  return process.env.DEMO_MODE === "true";
}

export function createDemoClient() {
  return makeClient();
}
