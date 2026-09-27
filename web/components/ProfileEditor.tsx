"use client";

import { useState } from "react";
import { PROVIDERS } from "@/lib/providers";
import Link from "next/link";
import {
  DIET_OPTIONS,
  EXPENSE_CATEGORIES,
  TIMEZONES,
  type CareProfile,
} from "@/lib/profile";

type Person = { name: string; phone: string; timezone: string; address: string };
type Tab = "settings" | "expenses" | "connections" | "diet";

const TABS: { id: Tab; label: string }[] = [
  { id: "settings", label: "Settings" },
  { id: "expenses", label: "Expenses" },
  { id: "connections", label: "Connections" },
  { id: "diet", label: "Diet" },
];

export default function ProfileEditor({ initial, person, startTab = "settings" }: { initial: CareProfile; person: Person; startTab?: Tab }) {
  const [tab, setTab] = useState<Tab>(startTab);
  const [profile, setProfile] = useState(initial);
  const [timezone, setTimezone] = useState(person.timezone || "America/New_York");
  const [status, setStatus] = useState("");

  function patchExpense(category: string, next: Partial<CareProfile["expenses"][number]>) {
    setProfile({
      ...profile,
      expenses: profile.expenses.map((row) => (row.category === category ? { ...row, ...next } : row)),
    });
  }

  async function save() {
    setStatus("Saving…");
    const res = await fetch("/api/profile", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile, timezone }),
    });
    if (res.ok) setStatus("Saved.");
    else {
      const body = await res.json().catch(() => ({ error: "unknown" }));
      setStatus("Could not save. " + (body.error || ""));
    }
  }

  const first = person.name?.split(" ")[0] || "them";

  return (
    <div>
      <div className="tabs" role="tablist">
        {TABS.map((item) => (
          <button key={item.id} type="button" className={tab === item.id ? "tab on" : "tab"} onClick={() => setTab(item.id)} role="tab" aria-selected={tab === item.id}>
            {item.label}
          </button>
        ))}
      </div>

      {tab === "settings" && (
        <section className="panel">
          <h2>Settings</h2>
          <p className="lede">These are the details Gary already uses for {first}. Calls follow this clock.</p>
          <div className="stack">
            <article className="decision"><strong>{person.name || "Name not set"}</strong><p className="muted">Phone ending {person.phone?.slice(-4) || "----"}</p></article>
            <label>
              Clock
              <select value={timezone} onChange={(e) => setTimezone(e.target.value)}>
                {TIMEZONES.map((zone) => <option key={zone} value={zone}>{zone.replace("America/", "").replace("_", " ")}</option>)}
              </select>
            </label>
            <label className="choice">
              <input type="checkbox" checked={profile.notify_expenses} onChange={(e) => setProfile({ ...profile, notify_expenses: e.target.checked })} />
              <span>Text me when a regular bill is due. {first} does not have to approve it.</span>
            </label>
          </div>
          <p className="muted"><Link href="/dashboard/onboarding">Review setup</Link></p>
        </section>
      )}

      {tab === "expenses" && (
        <section className="panel">
          <h2>Regular bills</h2>
          <p className="lede">Choose the bills {first} already pays. You get one reminder on the due day. Nothing here is a payment, and {first} is not asked to approve it.</p>
          <div className="stack">
            {profile.expenses.map((row) => {
              const label = EXPENSE_CATEGORIES.find((item) => item.id === row.category)?.label || row.category;
              return (
                <article key={row.category} className="choice">
                  <label>
                    <input type="checkbox" checked={row.active} onChange={(e) => patchExpense(row.category, { active: e.target.checked })} />
                    <strong>{label}</strong>
                  </label>
                  {row.active && (
                    <label>
                      Due day
                      <input type="number" min={1} max={28} value={row.due_day} aria-label={`${label} due day`} onChange={(e) => patchExpense(row.category, { due_day: Number(e.target.value) })} />
                    </label>
                  )}
                </article>
              );
            })}
          </div>
        </section>
      )}

      {tab === "connections" && (
        <section className="panel">
          <h2>Connections</h2>
          <p className="lede">Save the places Gary may use. This does not sign in to a bank, DoorDash, Uber, or Instacart, and it never asks for a password or card.</p>
          <div className="stack">
            <article className="decision">
              <label className="choice">
                <input type="checkbox" checked={profile.connectors.doordash.connected} onChange={(e) => setProfile({ ...profile, connectors: { ...profile.connectors, doordash: { ...profile.connectors.doordash, connected: e.target.checked } } })} />
                <span className="conn-row"><img src={PROVIDERS.find((p) => p.key === "doordash")!.logo} alt="" /><strong>{PROVIDERS.find((p) => p.key === "doordash")!.name}</strong></span>
              </label>
              {profile.connectors.doordash.connected && (
                <label>
                  Usual order
                  <input value={profile.connectors.doordash.usual} onChange={(e) => setProfile({ ...profile, connectors: { ...profile.connectors, doordash: { ...profile.connectors.doordash, usual: e.target.value } } })} placeholder="Chicken soup and tea" />
                </label>
              )}
            </article>
            <article className="decision">
              <label className="choice">
                <input type="checkbox" checked={profile.connectors.uber.connected} onChange={(e) => setProfile({ ...profile, connectors: { ...profile.connectors, uber: { ...profile.connectors.uber, connected: e.target.checked } } })} />
                <span className="conn-row"><img src={PROVIDERS.find((p) => p.key === "uber")!.logo} alt="" /><strong>{PROVIDERS.find((p) => p.key === "uber")!.name}</strong></span>
              </label>
              {profile.connectors.uber.connected && (
                <>
                  <label>Home<input value={profile.connectors.uber.home} onChange={(e) => setProfile({ ...profile, connectors: { ...profile.connectors, uber: { ...profile.connectors.uber, home: e.target.value } } })} /></label>
                  <label>Hospital<input value={profile.connectors.uber.hospital} onChange={(e) => setProfile({ ...profile, connectors: { ...profile.connectors, uber: { ...profile.connectors.uber, hospital: e.target.value } } })} placeholder="Springfield General" /></label>
                </>
              )}
            </article>
            <article className="decision">
              <label className="choice">
                <input type="checkbox" checked={profile.connectors.groceries.connected} onChange={(e) => setProfile({ ...profile, connectors: { ...profile.connectors, groceries: { ...profile.connectors.groceries, connected: e.target.checked } } })} />
                <span className="conn-row"><img src={PROVIDERS.find((p) => p.key === "groceries")!.logo} alt="" /><strong>{PROVIDERS.find((p) => p.key === "groceries")!.name}</strong></span>
              </label>
              {profile.connectors.groceries.connected && (
                <label>Store<input value={profile.connectors.groceries.store} onChange={(e) => setProfile({ ...profile, connectors: { ...profile.connectors, groceries: { ...profile.connectors.groceries, store: e.target.value } } })} placeholder="Sunrise Market" /></label>
              )}
            </article>
            <article className="decision">
              <label className="choice">
                <input type="checkbox" checked={profile.connectors.banking.connected} onChange={(e) => setProfile({ ...profile, connectors: { ...profile.connectors, banking: { connected: e.target.checked } } })} />
                <strong>Bill reminders</strong>
              </label>
              <p className="muted">Not a bank login. When this is on, the bills you chose send you a reminder. No money moves.</p>
            </article>
          </div>
        </section>
      )}

      {tab === "diet" && (
        <section className="panel">
          <h2>Diet</h2>
          <p className="lede">Gary keeps these in mind when food comes up. He will not suggest a dose or tell {first} to change a medicine.</p>
          <div className="stack">
            {DIET_OPTIONS.map((option) => (
              <label key={option.id} className="choice">
                <input
                  type="checkbox"
                  checked={profile.dietary.includes(option.id)}
                  onChange={(e) => setProfile({
                    ...profile,
                    dietary: e.target.checked ? [...profile.dietary, option.id] : profile.dietary.filter((id) => id !== option.id),
                  })}
                />
                <span>{option.label}</span>
              </label>
            ))}
          </div>
        </section>
      )}

      <button type="button" onClick={save}>Save profile</button>
      {status && <p className="muted">{status}</p>}
    </div>
  );
}
