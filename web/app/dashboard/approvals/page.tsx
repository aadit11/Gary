import DecisionButtons from "@/components/DecisionButtons";
import { careFirstName } from "@/lib/care";
import { DEMO_USER_ID, fmtTime, supabase } from "@/lib/supabase";

export const dynamic = "force-dynamic";

function money(amount: unknown) {
  const value = Number(amount);
  if (!Number.isFinite(value)) return "";
  return `$${value.toFixed(2)}`;
}

const ACTION: Record<string, string> = {
  pay_person: "Payment",
  pay_bill: "Bill",
  place_order: "Order",
  book_service: "Home visit",
  book_ride: "Ride",
};

function requestLine(row: { action?: string; payload?: { amount?: unknown; to?: string; payee?: string } | null }) {
  const action = ACTION[row.action || ""] || (row.action || "Request").replaceAll("_", " ");
  const amount = money(row.payload?.amount);
  const who = row.payload?.to || row.payload?.payee;
  if (amount && who) return `${action} of ${amount} to ${who}`;
  if (amount) return `${action} of ${amount}`;
  if (who) return `${action} for ${who}`;
  return action;
}

export default async function Approvals() {
  const name = await careFirstName();
  const person = name === "them" ? "your person" : name;
  const client = supabase();
  if (!client) return <><h1>Decisions</h1><div className="notice">The care desk is not connected yet.</div></>;
  let q = client.from("approvals").select("*").order("created_at", { ascending: false }).limit(50);
  if (DEMO_USER_ID) q = q.eq("user_id", DEMO_USER_ID);
  const { data, error } = await q;
  const rows = data ?? [];
  const pending = rows.filter((row) => row.status === "pending");
  const earlier = rows.filter((row) => row.status !== "pending");

  return (
    <>
      <p className="eyebrow">Decisions</p>
      <h1>What is waiting on you</h1>
      <p className="lede">Gary holds a payment or an unusual request until you decide. Approve or deny here, or reply YES or NO by message; either way Gary tells {person} on the call.</p>
      {error && <div className="notice">{error.message}</div>}
      {!rows.length && !error && (
        <div className="empty">
          <img src="/care-morning.png" alt="" />
          <div>
            <h2>Nothing is held</h2>
            <p className="muted">When something needs your yes or no, it will sit here until you answer by message.</p>
          </div>
        </div>
      )}
      {pending.length > 0 && (
        <section>
          <h2>Still open</h2>
          <div className="stack">
            {pending.map((row) => (
              <article key={row.id} className="decision pending">
                <div className="row-top">
                  <strong>{requestLine(row)}</strong>
                  <span className="pill pending">waiting</span>
                </div>
                <p>{row.reason}</p>
                <p className="when">{fmtTime(row.created_at)}</p>
                <DecisionButtons id={row.id} />
              </article>
            ))}
          </div>
        </section>
      )}
      {earlier.length > 0 && (
        <section>
          <h2>Already decided</h2>
          <div className="stack">
            {earlier.map((row) => (
              <article key={row.id} className="decision">
                <div className="row-top">
                  <strong>{requestLine(row)}</strong>
                  <span className={`pill ${row.status}`}>{row.status}</span>
                </div>
                <p>{row.reason}</p>
                <p className="when">{fmtTime(row.resolved_at || row.created_at)}</p>
              </article>
            ))}
          </div>
        </section>
      )}
    </>
  );
}
