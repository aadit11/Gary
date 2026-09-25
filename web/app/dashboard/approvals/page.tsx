import { supabase, DEMO_USER_ID, fmtTime } from "@/lib/supabase";

export const dynamic = "force-dynamic";

export default async function Approvals() {
  const client = supabase();
  if (!client) return <><h1>Approvals</h1><div className="notice">Supabase is not configured.</div></>;
  let q = client.from("approvals").select("*").order("created_at", { ascending: false }).limit(50);
  if (DEMO_USER_ID) q = q.eq("user_id", DEMO_USER_ID);
  const { data, error } = await q;
  return (
    <>
      <h1>Approvals</h1>
      {error && <div className="notice">{error.message}</div>}
      <table>
        <thead><tr><th>When</th><th>Request</th><th>Held because</th><th>Decision</th></tr></thead>
        <tbody>
          {(data ?? []).map((a) => (
            <tr key={a.id}>
              <td className="muted">{fmtTime(a.created_at)}</td>
              <td>{a.action.replace(/_/g, " ")}{a.payload?.amount ? ` · $${Number(a.payload.amount).toFixed(2)}` : ""}{a.payload?.to ? ` to ${a.payload.to}` : ""}</td>
              <td>{a.reason}</td>
              <td><span className={`pill ${a.status}`}>{a.status}</span>{a.resolved_at && <span className="muted"> {fmtTime(a.resolved_at)}</span>}</td>
            </tr>
          ))}
          {!data?.length && !error && <tr><td colSpan={4} className="muted">Nothing held yet.</td></tr>}
        </tbody>
      </table>
    </>
  );
}
