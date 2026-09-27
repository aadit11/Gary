import Link from "next/link";
import { careFirstName } from "@/lib/care";
import { PROVIDERS } from "@/lib/providers";

export default async function Home() {
  const name = await careFirstName();
  const person = name === "them" ? "your parent" : name;
  return (
    <>
      <section className="hero">
        <div>
          <p className="eyebrow">For families</p>
          <h1>The phone is the interface.</h1>
          <p className="lede">
            To an older adult, every app is a new interface to learn. Gary lets {person} use modern services through the one
            interface they&apos;ve known their whole life: a phone call. You stay in the loop, and anything risky waits for your okay.
          </p>
          <div className="landing-cta">
            <Link href="/dashboard/onboarding?fresh=1"><button type="button">Get started</button></Link>
            <Link href="/dashboard" className="quiet-link">I already have an account</Link>
          </div>
          <div className="works-with">
            <span>Works with</span>
            <div className="brand-row">
              {PROVIDERS.map((p) => (
                <span className="brand-chip" key={p.key}><img src={p.logo} alt="" /> {p.key === "bank" ? "Your bank" : p.name}</span>
              ))}
            </div>
          </div>
        </div>
        <img src="/care-morning.png" alt="Soft morning light on a wooden table, with tea and a small sprig of leaves" />
      </section>
      <div className="cards">
        <div className="card">
          <h3>Call and ask</h3>
          <p className="muted">{person} dials one number and says what they need: dinner, a ride, the electric bill. Gary reads it back and does it.</p>
        </div>
        <div className="card">
          <h3>Family in the loop</h3>
          <p className="muted">Every call, order, and payment shows up on your desk. Reminders go out at the times you set.</p>
        </div>
        <div className="card">
          <h3>Scam Guard</h3>
          <p className="muted">New payees, big amounts, and &quot;IRS agent&quot; calls are paused and sent to you. Reply YES or NO and Gary tells {person} on the spot.</p>
        </div>
      </div>
    </>
  );
}
