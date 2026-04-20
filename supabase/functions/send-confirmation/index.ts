// Edge Function: send-confirmation
// Sends a booking confirmation email via Resend.
// Idempotent: safe to call multiple times for the same booking —
// if the email was already sent, it returns success without re-sending.
// Tracks every attempt in email_logs for full auditability.

import { createClient } from "npm:@supabase/supabase-js@2";

type Supabase = ReturnType<typeof createClient>;

const MAX_ATTEMPTS = 3;

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...CORS, "Content-Type": "application/json" },
  });
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });

  let booking_id: string;
  try {
    ({ booking_id } = await req.json());
  } catch {
    return json({ error: "Invalid JSON" }, 400);
  }
  if (!booking_id) return json({ error: "Missing booking_id" }, 400);

  const supabase = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!
  );

  // ── Fetch booking with event details ───────────────────────
  const { data: booking, error: bErr } = await supabase
    .from("bookings")
    .select("*, events(name, date, venue)")
    .eq("id", booking_id)
    .maybeSingle();

  if (bErr || !booking) return json({ error: "Booking not found" }, 404);
  if (booking.status !== "confirmed") {
    return json({ error: "Booking is not confirmed" }, 400);
  }

  // ── Idempotency: check email_logs ─────────────────────────
  const { data: logEntry } = await supabase
    .from("email_logs")
    .select("id, status, attempts")
    .eq("booking_id", booking_id)
    .eq("email_type", "confirmation")
    .maybeSingle();

  if (logEntry?.status === "sent") {
    return json({ success: true, already_sent: true });
  }
  if (logEntry && logEntry.attempts >= MAX_ATTEMPTS) {
    return json({ error: "Max retry attempts reached" }, 429);
  }

  // ── Upsert email_logs entry ───────────────────────────────
  let logId: string;
  const now = new Date().toISOString();

  if (logEntry) {
    logId = logEntry.id;
    await supabase
      .from("email_logs")
      .update({ status: "retrying", attempts: logEntry.attempts + 1, last_attempt_at: now })
      .eq("id", logId);
  } else {
    const { data: newLog, error: logErr } = await supabase
      .from("email_logs")
      .insert({
        booking_id,
        email_type: "confirmation",
        recipient_email: booking.customer_email,
        status: "pending",
        attempts: 1,
        last_attempt_at: now,
      })
      .select("id")
      .single();

    if (logErr || !newLog) {
      // Conflict → another concurrent invocation already created the row
      const { data: concLog } = await supabase
        .from("email_logs")
        .select("id, status")
        .eq("booking_id", booking_id)
        .eq("email_type", "confirmation")
        .maybeSingle();
      if (concLog?.status === "sent") return json({ success: true, already_sent: true });
      return json({ error: "Failed to create email log" }, 500);
    }
    logId = newLog.id;
  }

  // ── Build & send email ─────────────────────────────────────
  const event = booking.events as { name: string; date: string; venue: string };
  const eventDate = new Date(event.date);
  const formattedDate = eventDate.toLocaleDateString("es-MX", {
    weekday: "long", year: "numeric", month: "long", day: "numeric",
  });
  const formattedTime = eventDate.toLocaleTimeString("es-MX", {
    hour: "2-digit", minute: "2-digit", timeZoneName: "short",
  });

  const emailPayload = {
    from: "KORA Events <confirmacion@koramx.com>",
    to: booking.customer_email,
    subject: `✓ Confirmación — ${event.name}`,
    html: buildEmail({
      customerName:     booking.customer_name,
      eventName:        event.name,
      eventDate:        formattedDate,
      eventTime:        formattedTime,
      venue:            event.venue,
      ticketType:       booking.ticket_type,
      quantity:         booking.quantity,
      totalAmount:      booking.total_amount,
      confirmationCode: booking.confirmation_code,
    }),
  };

  try {
    const res = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${Deno.env.get("RESEND_API_KEY")!}`,
      },
      body: JSON.stringify(emailPayload),
    });

    if (!res.ok) {
      const errBody = await res.text();
      throw new Error(`Resend ${res.status}: ${errBody}`);
    }

    await supabase
      .from("email_logs")
      .update({ status: "sent", sent_at: new Date().toISOString() })
      .eq("id", logId);

    return json({ success: true });
  } catch (err) {
    const msg = (err as Error).message;
    console.error("Email send failed:", msg);

    await supabase
      .from("email_logs")
      .update({ status: "failed", error_message: msg })
      .eq("id", logId);

    return json({ error: "Failed to send email", detail: msg }, 500);
  }
});

// ── HTML email template (luxury black/gold) ────────────────
function buildEmail(d: {
  customerName: string;
  eventName: string;
  eventDate: string;
  eventTime: string;
  venue: string;
  ticketType: string;
  quantity: number;
  totalAmount: number;
  confirmationCode: string;
}): string {
  const rows = [
    ["EVENTO",           d.eventName],
    ["FECHA",            d.eventDate],
    ["HORA",             d.eventTime],
    ["LUGAR",            d.venue],
    ["TIPO DE BOLETO",   d.ticketType.toUpperCase()],
    ["CANTIDAD",         `${d.quantity} boleto${d.quantity > 1 ? "s" : ""}`],
    ["TOTAL PAGADO",     `$${Number(d.totalAmount).toFixed(2)} MXN`],
  ].map(([label, value]) => `
    <tr>
      <td style="padding:10px 16px;color:#C9960C;font-size:11px;letter-spacing:2px;
                 text-transform:uppercase;border-bottom:1px solid #222;width:40%">${label}</td>
      <td style="padding:10px 16px;color:#F0E6C8;font-size:15px;
                 border-bottom:1px solid #222">${value}</td>
    </tr>`).join("");

  return `<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Confirmación KORA</title>
</head>
<body style="margin:0;padding:24px;background:#0a0a0a;font-family:'Georgia',serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;margin:0 auto">
    <!-- Header -->
    <tr>
      <td style="background:#000;padding:40px;text-align:center;border-bottom:2px solid #C9960C;
                 border-radius:8px 8px 0 0">
        <div style="color:#C9960C;font-size:36px;letter-spacing:8px;font-weight:normal">K O R A</div>
        <div style="color:#C9960C;font-size:11px;letter-spacing:4px;margin-top:8px">CONFIRMACIÓN DE RESERVA</div>
      </td>
    </tr>
    <!-- Body -->
    <tr>
      <td style="background:#111;padding:40px;border-left:1px solid #C9960C;border-right:1px solid #C9960C">
        <p style="color:#F0E6C8;margin:0 0 24px">
          Hola, <strong>${d.customerName}</strong>.
        </p>
        <p style="color:#aaa;margin:0 0 28px;font-size:14px;line-height:1.6">
          Tu reserva ha sido confirmada y tu pago procesado exitosamente.
          Presenta este código en la entrada del evento.
        </p>

        <!-- Confirmation code -->
        <div style="background:#0d0d00;border:1px solid #C9960C;border-radius:6px;
                    padding:24px;text-align:center;margin-bottom:32px">
          <div style="color:#C9960C;font-size:11px;letter-spacing:3px;margin-bottom:10px">
            CÓDIGO DE CONFIRMACIÓN
          </div>
          <div style="color:#E8C96A;font-size:30px;letter-spacing:6px;font-weight:bold">
            ${d.confirmationCode}
          </div>
        </div>

        <!-- Details table -->
        <table width="100%" cellpadding="0" cellspacing="0"
               style="border:1px solid #222;border-radius:4px;overflow:hidden">
          ${rows}
        </table>

        <p style="color:#666;font-size:12px;margin:28px 0 0;line-height:1.6">
          Si tienes alguna pregunta, responde a este correo o contáctanos en
          <a href="https://koramx.com" style="color:#C9960C">koramx.com</a>.
        </p>
      </td>
    </tr>
    <!-- Footer -->
    <tr>
      <td style="background:#0a0a0a;padding:24px;text-align:center;
                 border:1px solid #1a1a1a;border-top:1px solid #333;border-radius:0 0 8px 8px">
        <p style="color:#555;font-size:12px;margin:4px 0">KORA Events — Cozumel, Quintana Roo, México</p>
        <p style="color:#555;font-size:12px;margin:4px 0">
          <a href="https://koramx.com" style="color:#C9960C;text-decoration:none">koramx.com</a>
          &nbsp;·&nbsp;
          <a href="https://instagram.com/koramx" style="color:#C9960C;text-decoration:none">@koramx</a>
        </p>
      </td>
    </tr>
  </table>
</body>
</html>`;
}
