import { getMemberSession } from "@/lib/auth/session";
import { createAdminClient } from "@/lib/supabase/admin";
import { loadMemberContext } from "@/lib/services/members";
import { Card, Badge } from "@/components/ui";
import { Gift, Lock } from "lucide-react";
import type { MembershipTier } from "@/lib/types";

export const dynamic = "force-dynamic";

const TIER_ORDER: MembershipTier[] = ["silver", "gold", "platinum", "signature"];

function tierUnlocked(memberTier: MembershipTier | undefined, required: MembershipTier) {
  if (!memberTier) return false;
  return TIER_ORDER.indexOf(memberTier) >= TIER_ORDER.indexOf(required);
}

export default async function BenefitsPage() {
  const session = getMemberSession()!;
  const { membership } = await loadMemberContext(session.member_id);

  const supabase = createAdminClient();
  const { data: benefits } = await supabase
    .from("benefits")
    .select("*")
    .eq("active", true)
    .order("tier_required");

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <header>
        <h1 className="text-3xl font-semibold">Beneficios de membresía</h1>
        <p className="text-ocean-600">
          Tu nivel actual:{" "}
          <span className="font-medium capitalize text-ocean-900">
            {membership?.tier ?? "—"}
          </span>
        </p>
      </header>

      <div className="grid gap-4 md:grid-cols-2">
        {(benefits ?? []).map((b) => {
          const unlocked = tierUnlocked(membership?.tier, b.tier_required);
          return (
            <Card key={b.id} className={unlocked ? "" : "opacity-70"}>
              <div className="mb-3 flex items-center justify-between">
                <div className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-turquoise-50 text-turquoise-600">
                  {unlocked ? <Gift className="h-5 w-5" /> : <Lock className="h-5 w-5" />}
                </div>
                <Badge tone={unlocked ? "green" : "ocean"}>
                  {unlocked ? "Disponible" : `Requiere ${b.tier_required}`}
                </Badge>
              </div>
              <h3 className="font-semibold">{b.name}</h3>
              <p className="mt-1 text-sm text-ocean-600">{b.description}</p>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
