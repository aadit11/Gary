import ReminderForm from "@/components/ReminderForm";
import { careFirstName } from "@/lib/care";
import { WEEKDAYS, loadProfile } from "@/lib/profile";
import { DEMO_USER_ID, supabase } from "@/lib/supabase";

export const dynamic = "force-dynamic";

const REPEAT: Record<string, string> = {
  daily: "Every day",
  weekdays: "Weekdays",
  weekly: "Once a week",
  once: "One time",
};

export default async function Reminders() {
  const name = await careFirstName();
  const person = name === "them" ? "your person" : name;
  const client = supabase();
  if (!client) return <><h1>Scheduled calls</h1><div className="notice">The care desk is not connected yet.</div></>;
  let q = client.from("reminders").select("*").order("time_of_day");
  if (DEMO_USER_ID) q = q.eq("user_id", DEMO_USER_ID);
  const { data, error } = await q;
  const rows = data ?? [];
  const profile = await loadProfile();

  return (
    <>
      <p className="eyebrow">Scheduled calls</p>
      <h1>What Gary should say</h1>
      <p className="lede">These are the calls Gary places to {person}. Write the words you want spoken. Gary will not add a dose or change the instruction.</p>
      <ReminderForm name={person} />
      {error && <div className="notice">{error.message}</div>}
      {rows.length ? (
        <div className="stack">
          {rows.map((row) => (
            <article key={row.id} className="reminder">
              <time>{String(row.time_of_day).slice(0, 5)}</time>
              <div>
                <strong>{row.message}</strong>
                <p className="muted">
                  {row.recurrence === "weekly"
                    ? `Every ${WEEKDAYS[profile.weekly_days[row.id]] || "week"}`
                    : REPEAT[row.recurrence] || row.recurrence}
                </p>
              </div>
              <span className={`pill ${row.active ? "approved" : ""}`}>{row.active ? "On" : "Off"}</span>
            </article>
          ))}
        </div>
      ) : (
        !error && (
          <div className="empty">
            <img src="/care-morning.png" alt="" />
            <div>
              <h2>No calls scheduled</h2>
              <p className="muted">Add one above. A morning medicine reminder is a good first call.</p>
            </div>
          </div>
        )
      )}
    </>
  );
}
