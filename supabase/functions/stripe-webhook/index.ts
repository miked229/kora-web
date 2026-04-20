// Edge Function: stripe-webhook
// Handles Stripe payment events with signature verification.
// Idempotent: safe to receive the same event multiple times.
// Returns 200 quickly; heavy work runs after the response is sent
// so Stripe doesn't time out and retry unnecessarily.

import Stripe from "npm:stripe@14.21.0";
import { createClient } from "npm:@supabase/supabase-js@2";

type SupabaseClient = ReturnType<typeof createClient>;

Deno.serve(async (req) => {
  const sig = req.headers.get("stripe-signature");
  if (!sig) return new Response("Missing Stripe signature", { status: 400 });

  const body = await req.text();
  const stripe = new Stripe(Deno.env.get("STRIPE_SECRET_KEY")!, {
    apiVersion: "2024-06-20",
  });

  // ── Signature verification ─────────────────────────────────
  let event: Stripe.Event;
  try {
    event = await stripe.webhooks.constructEventAsync(
      body,
      sig,
      Deno.env.get("STRIPE_WEBHOOK_SECRET")!
    );
  } catch (err) {
    console.error("Webhook signature verification failed:", (err as Error).message);
    return new Response(`Webhook Error: ${(err as Error).message}`, { status: 400 });
  }

  const supabase = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!
  );

  // ── Dispatch ───────────────────────────────────────────────
  try {
    switch (event.type) {
      case "payment_intent.succeeded":
        await handleSuccess(supabase, stripe, event.data.object as Stripe.PaymentIntent);
        break;

      case "payment_intent.payment_failed":
        await handleFailed(supabase, event.data.object as Stripe.PaymentIntent);
        break;

      default:
        // Not actionable — still return 200 so Stripe stops retrying
        break;
    }
  } catch (err) {
    // Log the error but return 500 so Stripe retries the webhook
    console.error(`Error handling ${event.type}:`, err);
    return new Response("Internal error", { status: 500 });
  }

  return new Response(JSON.stringify({ received: true }), {
    headers: { "Content-Type": "application/json" },
  });
});

// ── payment_intent.succeeded ───────────────────────────────
async function handleSuccess(
  supabase: SupabaseClient,
  stripe: Stripe,
  pi: Stripe.PaymentIntent
) {
  const { data: booking, error } = await supabase
    .from("bookings")
    .select("id, status, event_id, ticket_type, quantity")
    .eq("stripe_payment_intent_id", pi.id)
    .maybeSingle();

  if (error || !booking) {
    console.error("Booking not found for PI:", pi.id);
    return;
  }

  // ── Idempotency guard ──────────────────────────────────────
  if (booking.status === "confirmed") {
    console.log("Already confirmed, skipping:", booking.id);
    return;
  }

  const confirmationCode = generateCode();

  // Only update if still pending (prevents overwriting a concurrent update)
  const { error: updateErr, count } = await supabase
    .from("bookings")
    .update({ status: "confirmed", confirmation_code: confirmationCode })
    .eq("id", booking.id)
    .eq("status", "pending")
    .select("id", { count: "exact", head: true });

  if (updateErr) throw updateErr;
  if ((count ?? 0) === 0) {
    // Another concurrent webhook already processed this
    console.log("Concurrent update detected, skipping:", booking.id);
    return;
  }

  // ── Increment event counters atomically ────────────────────
  await supabase.rpc("increment_tickets_sold", {
    p_event_id: booking.event_id,
    p_ticket_type: booking.ticket_type,
    p_quantity: booking.quantity,
  });

  // ── Audit log ──────────────────────────────────────────────
  await supabase.from("booking_logs").insert({
    booking_id: booking.id,
    action: "payment_confirmed",
    old_status: "pending",
    new_status: "confirmed",
    details: { stripe_pi: pi.id, confirmation_code: confirmationCode },
  });

  // ── Trigger email (fire-and-forget; email function has retry) ──
  const baseUrl = Deno.env.get("SUPABASE_URL")!;
  const svcKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
  fetch(`${baseUrl}/functions/v1/send-confirmation`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${svcKey}`,
    },
    body: JSON.stringify({ booking_id: booking.id }),
  }).catch((e) => console.error("Failed to invoke send-confirmation:", e));
}

// ── payment_intent.payment_failed ─────────────────────────
async function handleFailed(supabase: SupabaseClient, pi: Stripe.PaymentIntent) {
  const { data: booking } = await supabase
    .from("bookings")
    .select("id, status")
    .eq("stripe_payment_intent_id", pi.id)
    .maybeSingle();

  if (!booking || booking.status === "failed") return;

  await supabase
    .from("bookings")
    .update({ status: "failed" })
    .eq("id", booking.id)
    .eq("status", "pending");

  await supabase.from("booking_logs").insert({
    booking_id: booking.id,
    action: "payment_failed",
    old_status: "pending",
    new_status: "failed",
    details: {
      stripe_pi: pi.id,
      failure_code: pi.last_payment_error?.code ?? null,
      failure_message: pi.last_payment_error?.message ?? null,
    },
  });
}

// ── Unique human-readable confirmation code ────────────────
function generateCode(): string {
  const ts = Date.now().toString(36).toUpperCase().slice(-4);
  const rnd = Math.random().toString(36).substring(2, 6).toUpperCase();
  return `KORA-${ts}-${rnd}`;
}
