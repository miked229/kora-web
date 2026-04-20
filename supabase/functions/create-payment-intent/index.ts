// Edge Function: create-payment-intent
// Creates a Stripe PaymentIntent and a pending booking atomically.
// Fully idempotent: re-using the same idempotency_key returns the
// existing client_secret without creating a duplicate booking or charge.

import Stripe from "npm:stripe@14.21.0";
import { createClient } from "npm:@supabase/supabase-js@2";

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...CORS, "Content-Type": "application/json" },
  });
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") return json({ error: "Method not allowed" }, 405);

  // ── Parse & validate input ─────────────────────────────────
  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return json({ error: "Invalid JSON body" }, 400);
  }

  const {
    idempotency_key,
    event_id,
    ticket_type,
    quantity,
    customer_name,
    customer_email,
  } = body as Record<string, unknown>;

  if (!idempotency_key || !event_id || !ticket_type || !quantity || !customer_name || !customer_email) {
    return json({ error: "Faltan campos requeridos" }, 400);
  }
  if (!["general", "vip"].includes(ticket_type as string)) {
    return json({ error: "Tipo de boleto inválido" }, 400);
  }
  const qty = Number(quantity);
  if (!Number.isInteger(qty) || qty < 1 || qty > 10) {
    return json({ error: "La cantidad debe ser entre 1 y 10" }, 400);
  }
  if (!EMAIL_RE.test(customer_email as string)) {
    return json({ error: "Email inválido" }, 400);
  }
  const name = String(customer_name).trim();
  if (name.length < 2) {
    return json({ error: "Nombre muy corto" }, 400);
  }

  // ── Clients ────────────────────────────────────────────────
  const supabase = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!
  );
  const stripe = new Stripe(Deno.env.get("STRIPE_SECRET_KEY")!, {
    apiVersion: "2024-06-20",
  });

  // ── Idempotency: check existing booking ────────────────────
  const { data: existing } = await supabase
    .from("bookings")
    .select("id, stripe_payment_intent_id, status")
    .eq("idempotency_key", idempotency_key)
    .maybeSingle();

  if (existing) {
    if (existing.status === "confirmed") {
      return json({ error: "Este boleto ya fue confirmado", already_confirmed: true }, 409);
    }
    // Return the same PaymentIntent
    try {
      const pi = await stripe.paymentIntents.retrieve(existing.stripe_payment_intent_id);
      return json({ client_secret: pi.client_secret, booking_id: existing.id });
    } catch (err) {
      console.error("Failed to retrieve Stripe PI:", err);
      return json({ error: "Error al recuperar el pago" }, 500);
    }
  }

  // ── Fetch event & check capacity ───────────────────────────
  const { data: event, error: evErr } = await supabase
    .from("events")
    .select("*")
    .eq("id", event_id)
    .eq("status", "active")
    .maybeSingle();

  if (evErr || !event) {
    return json({ error: "Evento no encontrado o no disponible" }, 404);
  }

  const capField = ticket_type === "vip" ? "capacity_vip" : "capacity_general";
  const soldField = ticket_type === "vip" ? "tickets_sold_vip" : "tickets_sold_general";
  const priceField = ticket_type === "vip" ? "price_vip" : "price_general";
  const available = (event[capField] as number) - (event[soldField] as number);

  if (available < qty) {
    return json({
      error: `Solo quedan ${available} boleto(s) disponibles`,
      available,
    }, 409);
  }

  const unitPrice = event[priceField] as number;
  const totalAmount = unitPrice * qty;
  const totalCents = Math.round(totalAmount * 100);

  // ── Create Stripe PaymentIntent ────────────────────────────
  let pi: Stripe.PaymentIntent;
  try {
    pi = await stripe.paymentIntents.create({
      amount: totalCents,
      currency: "mxn",
      automatic_payment_methods: { enabled: true },
      receipt_email: customer_email as string,
      description: `${event.name} — ${qty}x ${ticket_type}`,
      metadata: {
        idempotency_key: idempotency_key as string,
        event_id: event_id as string,
        ticket_type: ticket_type as string,
        quantity: String(qty),
        customer_name: name,
        customer_email: customer_email as string,
      },
    });
  } catch (err) {
    console.error("Stripe PI creation error:", err);
    return json({ error: "Error al inicializar el pago" }, 500);
  }

  // ── Persist booking (pending) ──────────────────────────────
  const { data: newBooking, error: insertErr } = await supabase
    .from("bookings")
    .insert({
      idempotency_key,
      event_id,
      customer_name: name,
      customer_email,
      ticket_type,
      quantity: qty,
      unit_price: unitPrice,
      total_amount: totalAmount,
      status: "pending",
      stripe_payment_intent_id: pi.id,
    })
    .select("id")
    .single();

  if (insertErr) {
    // Race condition: another request inserted with the same key
    const { data: raced } = await supabase
      .from("bookings")
      .select("id, stripe_payment_intent_id")
      .eq("idempotency_key", idempotency_key)
      .maybeSingle();

    if (raced) {
      // Cancel the orphaned Stripe PI
      await stripe.paymentIntents.cancel(pi.id).catch(console.error);
      const racedPi = await stripe.paymentIntents.retrieve(raced.stripe_payment_intent_id);
      return json({ client_secret: racedPi.client_secret, booking_id: raced.id });
    }
    // Unrecoverable: cancel PI and report error
    await stripe.paymentIntents.cancel(pi.id).catch(console.error);
    return json({ error: "Error al crear la reserva" }, 500);
  }

  // ── Audit log ──────────────────────────────────────────────
  await supabase.from("booking_logs").insert({
    booking_id: newBooking.id,
    action: "booking_created",
    new_status: "pending",
    details: { event_id, ticket_type, quantity: qty, total_amount: totalAmount, stripe_pi: pi.id },
  });

  return json({ client_secret: pi.client_secret!, booking_id: newBooking.id });
});
