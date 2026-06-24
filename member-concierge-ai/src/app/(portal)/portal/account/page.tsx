import { getMemberSession } from "@/lib/auth/session";
import { createAdminClient } from "@/lib/supabase/admin";
import { Card, Badge } from "@/components/ui";
import { formatCurrency, formatDate } from "@/lib/utils";

export const dynamic = "force-dynamic";

const statusTone: Record<string, "green" | "gold" | "red"> = {
  paid: "green",
  pending: "gold",
  overdue: "red",
};

export default async function AccountPage() {
  const session = getMemberSession()!;
  const supabase = createAdminClient();
  const { data: statements } = await supabase
    .from("account_statements")
    .select("*")
    .eq("member_id", session.member_id)
    .order("period", { ascending: false });

  const list = statements ?? [];
  const totalDue = list.reduce((sum, s) => sum + Number(s.amount_due) - Number(s.amount_paid), 0);

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <header>
        <h1 className="text-3xl font-semibold">Estado de cuenta</h1>
        <p className="text-ocean-600">Tus cuotas, pagos y saldos.</p>
      </header>

      <Card className="bg-ocean-gradient text-white">
        <div className="text-sm text-sand-100/80">Saldo pendiente total</div>
        <div className="mt-1 font-serif text-3xl font-semibold">
          {formatCurrency(Math.max(0, totalDue))}
        </div>
      </Card>

      <div className="space-y-3">
        {list.map((s) => (
          <Card key={s.id} className="flex items-center justify-between">
            <div>
              <div className="flex items-center gap-3">
                <h3 className="font-semibold">Periodo {s.period}</h3>
                <Badge tone={statusTone[s.status] ?? "gold"}>{s.status}</Badge>
              </div>
              {s.due_date && (
                <p className="mt-1 text-sm text-ocean-600">
                  Vence: {formatDate(s.due_date)}
                </p>
              )}
            </div>
            <div className="text-right">
              <div className="font-semibold">
                {formatCurrency(Number(s.amount_due))}
              </div>
              <div className="text-xs text-ocean-500">
                Pagado: {formatCurrency(Number(s.amount_paid))}
              </div>
            </div>
          </Card>
        ))}
        {list.length === 0 && (
          <Card>
            <p className="text-ocean-600">No hay movimientos en tu estado de cuenta.</p>
          </Card>
        )}
      </div>
    </div>
  );
}
