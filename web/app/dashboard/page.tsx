import Link from "next/link";
import { careFirstName, eventBody, eventTitle, tone } from "@/lib/care";
import { DEMO_USER_ID, fmtTime, supabase } from "@/lib/supabase";

export const dynamic = "force-dynamic";

export default async function Dashboard() {
  const name = await careFirstName();
  const person = name === "them" ? "your person" : name;
  const client = supabase();
  if (!client) return <><h1>What happened</h1><div className="notice">The care desk is not connected yet. Add the Supabase address and anon key to the repo-root .env.</div></>;

  let activity = client.from("activity_log").select("*").order("created_at", { ascending: false }).limit(40);
  let waiting = client.from("approvals").select("id", { count: "exact", head: true }).eq("status", "pending");
  let reminders = client.from("reminders").select("id", { count: "exact", head: true }).eq("active", true);
  if (DEMO_USER_ID) {
    activity = activity.eq("user_id", DEMO_USER_ID);
    waiting = waiting.eq("user_id", DEMO_USER_ID);
    reminders = reminders.eq("user_id", DEMO_USER_ID);
  }
  const [log, held, calls] = await Promise.all([activity, waiting, reminders]);
  const rows = log.data ?? [];
  const recentCalls = rows.filter((row) => row.kind === "call_started").length;

  return (
    <>
      <section className="hero">
        <div>
          <p className="eyebrow">What happened</p>
          <h1>{person}&apos;s recent calls</h1>
          <p className="lede">A plain record of the phone calls, the notes sent to you, and anything still open. Nothing here asks {person} for account numbers.</p>
        </div>
        <img src="/care-morning.png" alt="Soft morning light on a wooden table, with tea and a small sprig of leaves" />
      </section>
      <div className="stats">
        <div className="stat"><b>{recentCalls}</b><span>recent calls</span></div>
        <div className="stat"><b>{held.count ?? 0}</b><span>waiting on you</span></div>
        <div className="stat"><b>{calls.count ?? 0}</b><span>calls you scheduled</span></div>
      </div>
      {log.error && <div className="notice">{log.error.message}</div>}
      {rows.length ? (
        <ul className="feed">
          {rows.map((row) => (
            <li key={row.id} className={tone(row.kind, row.data?.outcome)}>
              <div className="row-top">
                <strong>{eventTitle(row.kind, row.data)}</strong>
                <span className="when">{fmtTime(row.created_at)}</span>
              </div>
              <p>{eventBody(row, person)}</p>
            </li>
          ))}
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
