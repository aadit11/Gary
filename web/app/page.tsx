import Link from "next/link";

export default function Home() {
  return (
    <>
      <h1>Gary</h1>
      <p>A phone-based voice assistant for older adults. Family members follow along here and approve anything risky by message.</p>
      <div className="cards">
        <div className="card"><h3><Link href="/dashboard">Activity log</Link></h3><p className="muted">Every call, tool, order, and approval.</p></div>
        <div className="card"><h3><Link href="/dashboard/reminders">Reminders</Link></h3><p className="muted">Schedule the calls Gary makes each day.</p></div>
        <div className="card"><h3><Link href="/dashboard/approvals">Approvals</Link></h3><p className="muted">What Scam Guard held, and what the family decided.</p></div>
        <div className="card"><h3><Link href="/mock/biller">Mock biller</Link></h3><p className="muted">The utility company Gary pays bills to.</p></div>
        <div className="card"><h3><Link href="/mock/services">Mock home services</Link></h3><p className="muted">Plumbers and handymen Gary can book.</p></div>
      </div>
      <p className="muted" style={{ marginTop: "1.5rem" }}>Food orders run on REAL&apos;s DashDish clone and rides on Udriver, driven by a browser agent.</p>
    </>
  );
}
