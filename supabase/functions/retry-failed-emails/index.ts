// Edge Function: retry-failed-emails
// Cron job (every 5 minutes) that re-invokes send-confirmation
// for emails that failed or are still pending after 2+ minutes.
// Configure in supabase/config.toml as a scheduled function.

import { createClient } from "npm:@supabase/supabase-js@2";

Deno.serve(async (_req) => {
  const supabase = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!
  );

  // Find emails that need retrying:
  //  • status in ('failed', 'retrying', 'pending')
  //  • under max_attempts
  //  • last_attempt_at is null or older than 2 minutes (avoid piling on a live attempt)
  const { data: stale, error } = await supabase
    .from("email_logs")
    .select("id, booking_id, attempts, max_attempts, status, last_attempt_at")
    .in("status", ["failed", "retrying", "pending"])
    .filter("attempts", "lt", supabase.raw ? 3 : 3) // max_attempts
    .or("last_attempt_at.is.null,last_attempt_at.lt." +
      new Date(Date.now() - 2 * 60 * 1000).toISOString());

  if (error) {
    console.error("Failed to query email_logs:", error);
    return new Response("DB error", { status: 500 });
  }

  if (!stale || stale.length === 0) {
    return new Response(JSON.stringify({ retried: 0 }), {
      headers: { "Content-Type": "application/json" },
    });
  }

  const baseUrl = Deno.env.get("SUPABASE_URL")!;
  const svcKey  = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

  // Retry each in parallel (email function is idempotent)
  const results = await Promise.allSettled(
    stale.map((row) =>
      fetch(`${baseUrl}/functions/v1/send-confirmation`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${svcKey}`,
        },
        body: JSON.stringify({ booking_id: row.booking_id }),
      })
    )
  );

  const succeeded = results.filter((r) => r.status === "fulfilled").length;
  const failed    = results.filter((r) => r.status === "rejected").length;

  console.log(`Email retry run: ${succeeded} succeeded, ${failed} failed`);

  return new Response(
    JSON.stringify({ retried: stale.length, succeeded, failed }),
    { headers: { "Content-Type": "application/json" } }
  );
});
