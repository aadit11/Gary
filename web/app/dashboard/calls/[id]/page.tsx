import Link from "next/link";
import { notFound } from "next/navigation";
import { callOutcome, callTitle, careFirstName, durationLabel, eventBody, eventTitle, groupCalls, tone, type ActivityRow } from "@/lib/care";
import { DEMO_USER_ID, fmtTime, supabase } from "@/lib/supabase";

export const dynamic = "force-dynamic";

const WINDOW_MS = 30 * 60 * 1000;

export default async function CallPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const name = await careFirstName();
  const person = name === "them" ? "your person" : name;
  const client = supabase();
  if (!client) return <div className="notice">The care desk is not connected yet.</div>;

  // Find when the call started, then load everything logged from then until well after it ended.
  let startQuery = client.from("activity_log").select("*").eq("kind", "call_started").eq("id", id).limit(1);
  if (DEMO_USER_ID) startQuery = startQuery.eq("user_id", DEMO_USER_ID);
  const start = (await startQuery).data?.[0] as ActivityRow | undefined;
  if (!start) notFound();
  const from = new Date(Date.parse(start.created_at) - 60_000).toISOString();
  const to = new Date(Date.parse(start.created_at) + WINDOW_MS).toISOString();
  let query = client.from("activity_log").select("*").gte("created_at", from).lte("created_at", to).order("created_at", { ascending: true });
  if (DEMO_USER_ID) query = query.eq("user_id", DEMO_USER_ID);
  const rows = ((await query).data ?? []) as ActivityRow[];
  const call = groupCalls(rows).calls.find((c) => c.id === id);
  if (!call) notFound();

  const events = [call.started, ...call.events, ...(call.ended ? [call.ended] : [])];

  return (
    <>
      <p className="eyebrow"><Link href="/dashboard" className="quiet-link">‹ All calls</Link></p>
      <h1>{callTitle(call.reason, person)}</h1>
      <p className="lede">
        {fmtTime(call.started.created_at)}, {durationLabel(call.startMs, call.endMs)}. {callOutcome(call)}
      </p>
      <ul className="feed">
        {events.map((row) => (
          <li key={row.id} className={tone(row.kind, row.data?.outcome as string | undefined)}>
            <div className="row-top">
              <strong>{eventTitle(row.kind, row.data)}</strong>
              <span className="when">{fmtTime(row.created_at)}</span>
            </div>
            <p>{eventBody(row, person)}</p>
          </li>
        ))}
      </ul>
    </>
  );
}
