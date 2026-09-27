"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { DIET_OPTIONS, EXPENSE_CATEGORIES, type CareProfile } from "@/lib/profile";

const STEPS = ["Diet", "DoorDash", "Uber", "Groceries", "Bills"];

export default function Onboarding({ initial }: { initial: CareProfile }) {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [profile, setProfile] = useState(initial);
  const [status, setStatus] = useState("");

  async function persist(next: CareProfile, done = false) {
    setStatus("Saving…");
    const res = await fetch("/api/profile", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile: { ...next, onboarded: done || next.onboarded } }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({ error: "unknown" }));
      setStatus("Could not save. " + (body.error || ""));
      return false;
    }
    setStatus("");
    return true;
  }

  async function next() {
    const last = step === STEPS.length - 1;
    const updated = { ...profile, onboarded: last };
    if (await persist(updated, last)) {
      setProfile(updated);
      if (last) router.push("/dashboard/profile");
      else setStep(step + 1);
    }
  }

  return (
    <div>
      <ol className="steps">
        {STEPS.map((label, index) => (
          <li key={label} className={index === step ? "on" : ""}>{label}</li>
        ))}
      </ol>
      {step === 0 && (
        <section className="panel">
          <h2>What should Gary keep in mind about food?</h2>
          <div className="stack">
            {DIET_OPTIONS.map((option) => (
              <label key={option.id} className="choice">
                <input type="checkbox" checked={profile.dietary.includes(option.id)} onChange={(e) => setProfile({ ...profile, dietary: e.target.checked ? [...profile.dietary, option.id] : profile.dietary.filter((id) => id !== option.id) })} />
                <span>{option.label}</span>
              </label>
            ))}
          </div>
        </section>
      )}
      {step === 1 && (
        <section className="panel">
          <h2>DoorDash</h2>
          <p className="lede">Save a usual order. Gary will not ask for a card or a password.</p>
          <label className="choice">
            <input type="checkbox" checked={profile.connectors.doordash.connected} onChange={(e) => setProfile({ ...profile, connectors: { ...profile.connectors, doordash: { ...profile.connectors.doordash, connected: e.target.checked } } })} />
            <span>Gary may help with food orders</span>
          </label>
          <label>
            Usual order
            <input value={profile.connectors.doordash.usual} onChange={(e) => setProfile({ ...profile, connectors: { ...profile.connectors, doordash: { ...profile.connectors.doordash, usual: e.target.value } } })} placeholder="Chicken soup and tea" />
          </label>
        </section>
      )}
      {step === 2 && (
        <section className="panel">
          <h2>Uber places</h2>
          <p className="lede">Home and the hospital are the two places a ride usually needs.</p>
          <label className="choice">
            <input type="checkbox" checked={profile.connectors.uber.connected} onChange={(e) => setProfile({ ...profile, connectors: { ...profile.connectors, uber: { ...profile.connectors.uber, connected: e.target.checked } } })} />
            <span>Save these places for rides</span>
          </label>
          <label>Home<input value={profile.connectors.uber.home} onChange={(e) => setProfile({ ...profile, connectors: { ...profile.connectors, uber: { ...profile.connectors.uber, home: e.target.value } } })} /></label>
          <label>Hospital<input value={profile.connectors.uber.hospital} onChange={(e) => setProfile({ ...profile, connectors: { ...profile.connectors, uber: { ...profile.connectors.uber, hospital: e.target.value } } })} placeholder="Springfield General" /></label>
        </section>
      )}
      {step === 3 && (
        <section className="panel">
          <h2>Groceries</h2>
          <label className="choice">
            <input type="checkbox" checked={profile.connectors.groceries.connected} onChange={(e) => setProfile({ ...profile, connectors: { ...profile.connectors, groceries: { ...profile.connectors.groceries, connected: e.target.checked } } })} />
            <span>Save a grocery store</span>
          </label>
          <label>Store<input value={profile.connectors.groceries.store} onChange={(e) => setProfile({ ...profile, connectors: { ...profile.connectors, groceries: { ...profile.connectors.groceries, store: e.target.value } } })} placeholder="Sunrise Market" /></label>
        </section>
      )}
      {step === 4 && (
        <section className="panel">
          <h2>Bills you already expect</h2>
          <p className="lede">Rent and the other regular bills can remind you on the due day. This is not a bank connection, and nobody has to approve them.</p>
          <label className="choice">
            <input type="checkbox" checked={profile.connectors.banking.connected} onChange={(e) => setProfile({ ...profile, notify_expenses: e.target.checked, connectors: { ...profile.connectors, banking: { connected: e.target.checked } } })} />
            <span>Remind me about these bills</span>
          </label>
          <div className="stack">
            {profile.expenses.map((row) => {
              const label = EXPENSE_CATEGORIES.find((item) => item.id === row.category)?.label || row.category;
              return (
                <label key={row.category} className="choice">
                  <input type="checkbox" checked={row.active} onChange={(e) => setProfile({ ...profile, expenses: profile.expenses.map((item) => item.category === row.category ? { ...item, active: e.target.checked } : item) })} />
                  <span>{label}, due on day {row.due_day}</span>
                </label>
              );
            })}
          </div>
        </section>
      )}
      <div className="row-top">
        {step > 0 && <button type="button" className="quiet-button" onClick={() => setStep(step - 1)}>Back</button>}
        <button type="button" onClick={next}>{step === STEPS.length - 1 ? "Finish setup" : "Continue"}</button>
      </div>
      {status && <p className="muted">{status}</p>}
    </div>
  );
}
