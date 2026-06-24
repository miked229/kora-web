import "server-only";

import { createAdminClient } from "@/lib/supabase/admin";
import type { Member, Membership, Reservation } from "@/lib/types";

/** Carga el contexto del socio para alimentar al concierge IA. */
export async function loadMemberContext(memberId: string): Promise<{
  member: Member | null;
  membership: Membership | null;
  reservations: Reservation[];
}> {
  const supabase = createAdminClient();

  const [memberRes, membershipRes, reservationsRes] = await Promise.all([
    supabase
      .from("members")
      .select("id, membership_no, full_name, email, phone, locale")
      .eq("id", memberId)
      .maybeSingle(),
    supabase
      .from("memberships")
      .select("*")
      .eq("member_id", memberId)
      .eq("status", "active")
      .order("start_date", { ascending: false })
      .limit(1)
      .maybeSingle(),
    supabase
      .from("reservations")
      .select("*")
      .eq("member_id", memberId)
      .in("status", ["pending", "confirmed", "changed"])
      .order("check_in", { ascending: true }),
  ]);

  return {
    member: (memberRes.data as Member) ?? null,
    membership: (membershipRes.data as Membership) ?? null,
    reservations: (reservationsRes.data as Reservation[]) ?? [],
  };
}

/** Identifica a un socio por su número de teléfono (canal WhatsApp). */
export async function findMemberByPhone(phone: string): Promise<string | null> {
  const supabase = createAdminClient();
  const { data } = await supabase
    .from("members")
    .select("id")
    .eq("phone", phone)
    .maybeSingle();
  return data?.id ?? null;
}

/** Identifica a un socio por su email (canal Gmail). */
export async function findMemberByEmail(email: string): Promise<string | null> {
  const supabase = createAdminClient();
  const { data } = await supabase
    .from("members")
    .select("id")
    .ilike("email", email)
    .maybeSingle();
  return data?.id ?? null;
}
