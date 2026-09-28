import Link from "next/link";
import { callHighlights, callOutcome, callTitle, careFirstName, eventBody, eventTitle, groupCalls, tone, type ActivityRow } from "@/lib/care";
import { DEMO_USER_ID, fmtTime, supabase } from "@/lib/supabase";

export const dynamic = "force-dynamic";

type Item = { at: number; call?: ReturnType<typeof groupCalls>["calls"][number]; row?: ActivityRow };

export default async function Dashboard() {
  const name = await careFirstName();
  const person = name === "them" ? "your person" : name;
  const client = supabase();
  if (!client) return <><h1>What happened</h1><div className="notice">The care desk is not connected yet. Add the Supabase address and anon key to the repo-root .env.</div></>;

  let activity = client.from("activity_log").select("*").order("created_at", { ascending: false }).limit(300);
  let waiting = client.from("approvals").select("id", { count: "exact", head: true }).eq("status", "pending");
  let reminders = client.from("reminders").select("id", { count: "exact", head: true }).eq("active", true);
  if (DEMO_USER_ID) {
    activity = activity.eq("user_id", DEMO_USER_ID);
    waiting = waiting.eq("user_id", DEMO_USER_ID);
    reminders = reminders.eq("user_id", DEMO_USER_ID);
  }
  const [log, held, scheduled] = await Promise.all([activity, waiting, reminders]);
  const rows = (log.data ?? []) as ActivityRow[];
  const { calls, loose } = groupCalls(rows);
  const weekAgo = Date.now() - 7 * 24 * 60 * 60 * 1000;
  const callsThisWeek = calls.filter((call) => call.startMs >= weekAgo).length;

  // One timeline, newest first: each call is one card, everything outside a call is its own entry.
  // Website work that ran outside a call is kept off the family's feed.
  const items: Item[] = [
    ...calls.map((call) => ({ at: call.startMs, call })),
    ...loose.filter((row) => !row.kind.startsWith("browser_job")).map((row) => ({ at: Date.parse(row.created_at), row })),
  ].sort((a, b) => b.at - a.at).slice(0, 40);

  return (
    <>
      <section className="hero">
        <div>
          <p className="eyebrow">What happened</p>
          <h1>{person}&apos;s recent calls</h1>
          <p className="lede">A plain record of the phone calls, the notes sent to you, and anything still open. Open a call to see everything that happened on it. Nothing here asks {person} for account numbers.</p>
        </div>
        <img src="/care-morning.png" alt="Soft morning light on a wooden table, with tea and a small sprig of leaves" />
      </section>
      <div className="stats">
        <div className="stat"><b>{callsThisWeek}</b><span>Calls this week</span></div>
        <div className="stat"><b>{held.count ?? 0}</b><span>Waiting on you</span></div>
        <div className="stat"><b>{scheduled.count ?? 0}</b><span>Calls you scheduled</span></div>
      </div>
      {log.error && <div className="notice">{log.error.message}</div>}
      {items.length ? (
        <ul className="feed">
          {items.map((item) =>
            item.call ? (
              <li key={`call-${item.call.id}`} className="call">
                <Link href={`/dashboard/calls/${encodeURIComponent(item.call.id)}`} className="call-link">
                  <div className="row-top">
                    <strong>{callTitle(item.call.reason, person)}</strong>
                    <span className="when">{fmtTime(item.call.started.created_at)}</span>
                  </div>
                  <p>{callOutcome(item.call)}</p>
                  {callHighlights(item.call, person).map((line, i) => <p key={i} className="highlight">{line}</p>)}
                  <span className="call-open">{item.call.events.length ? `${item.call.events.length} things happened` : "Open the call"} ›</span>
                </Link>
              </li>
            ) : (
              <li key={item.row!.id} className={tone(item.row!.kind, item.row!.data?.outcome as string | undefined)}>
                <div className="row-top">
                  <strong>{eventTitle(item.row!.kind, item.row!.data)}</strong>
                  <span className="when">{fmtTime(item.row!.created_at)}</span>
                </div>
                <p>{eventBody(item.row!, person)}</p>
              </li>
            ),
          )}
        </ul>
      ) : (
        !log.error && (
          <div className="empty">
            <img src="/care-morning.png" alt="" />
            <div>
              <h2>Nothing to review yet</h2>
              <p className="muted">When Gary calls {person}, the call will show up here. You can <Link href="/dashboard/reminders">schedule a call</Link> whenever you are ready.</p>
            </div>
          </div>
        )
      )}
    </>
  );
}
