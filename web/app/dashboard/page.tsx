import { supabase, DEMO_USER_ID, fmtTime } from "@/lib/supabase";

export const dynamic = "force-dynamic";

export default async function Dashboard() {
  const client = supabase();
  if (!client) return <><h1>Activity</h1><div className="notice">Supabase is not configured. Add SUPABASE_ANON_KEY to the repo-root .env.</div></>;
  let q = client.from("activity_log").select("*").order("created_at", { ascending: false }).limit(50);
  if (DEMO_USER_ID) q = q.eq("user_id", DEMO_USER_ID);
  const { data, error } = await q;
  return (
    <>
      <h1>Activity</h1>
      {error && <div className="notice">{error.message}</div>}
      <table>
        <thead><tr><th>When</th><th>Event</th><th>Details</th></tr></thead>
        <tbody>
          {(data ?? []).map((row) => (
            <tr key={row.id}><td className="muted">{fmtTime(row.created_at)}</td><td><span className="pill">{row.kind}</span></td><td>{row.summary}</td></tr>
          ))}
          {!data?.length && !error && <tr><td colSpan={3} className="muted">Nothing yet.</td></tr>}
        </tbody>
      </table>
    </>
  );
}
