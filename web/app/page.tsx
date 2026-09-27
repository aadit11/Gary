import Link from "next/link";
import { careFirstName } from "@/lib/care";

export default async function Home() {
  const name = await careFirstName();
  const person = name === "them" ? "your person" : name;
  return (
    <>
      <section className="hero">
        <div>
          <p className="eyebrow">For caregivers</p>
          <h1>A quiet desk for {person}&apos;s day</h1>
          <p className="lede">Gary talks with {person} by phone. You can see what was said, set the calls you want made, and decide anything that should wait.</p>
        </div>
        <img src="/care-morning.png" alt="Soft morning light on a wooden table, with tea and a small sprig of leaves" />
      </section>
      <div className="cards">
        <div className="card">
          <h3><Link href="/dashboard">What happened</Link></h3>
          <p className="muted">Calls, notes Gary sent you, and anything that did not get confirmed.</p>
        </div>
        <div className="card">
          <h3><Link href="/dashboard/reminders">Scheduled calls</Link></h3>
          <p className="muted">The daily reminders Gary will say out loud, in {person}&apos;s own time.</p>
        </div>
        <div className="card">
          <h3><Link href="/dashboard/approvals">Decisions</Link></h3>
          <p className="muted">Payments and requests held until you say yes or no.</p>
        </div>
        <div className="card">
          <h3><Link href="/dashboard/profile">Profile</Link></h3>
          <p className="muted">Diet, saved places, and the bills you want a reminder for.</p>
        </div>
      </div>
    </>
  );
}
