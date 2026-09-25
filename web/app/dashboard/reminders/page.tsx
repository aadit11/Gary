import ReminderForm from "@/components/ReminderForm";
import { supabase, DEMO_USER_ID } from "@/lib/supabase";

export const dynamic = "force-dynamic";

export default async function Reminders() {
  const client = supabase();
  if (!client) return <><h1>Reminders</h1><div className="notice">Supabase is not configured.</div></>;
  let q = client.from("reminders").select("*").order("time_of_day");
  if (DEMO_USER_ID) q = q.eq("user_id", DEMO_USER_ID);
  const { data, error } = await q;
  return (
    <>
      <h1>Reminders</h1>
      <ReminderForm />
      {error && <div className="notice">{error.message}</div>}
      <table>
        <thead><tr><th>Time</th><th>Message</th><th>Repeat</th><th>Active</th></tr></thead>
        <tbody>
          {(data ?? []).map((r) => (
            <tr key={r.id}><td>{String(r.time_of_day).slice(0, 5)}</td><td>{r.message}</td><td>{r.recurrence}</td><td>{r.active ? "yes" : "no"}</td></tr>
          ))}
          {!data?.length && !error && <tr><td colSpan={4} className="muted">No reminders scheduled.</td></tr>}
        </tbody>
      </table>
    </>
  );
}
