"use client";

import { useState } from "react";
import { PROVIDERS } from "@/lib/providers";
import { PlaceList, TextList } from "@/components/ListEditor";
import Link from "next/link";
import { RELATIONSHIPS, forDisplay, validateContacts, welcomeCopy, type ContactField, type Contacts } from "@/lib/contacts";
import {
  DIET_OPTIONS,
  EXPENSE_CATEGORIES,
  TIMEZONES,
  BANKS,
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

export default function ProfileEditor({
  initial,
  contacts: initialContacts,
  person,
  startTab = "settings",
}: {
  initial: CareProfile;
  contacts: Contacts;
  person: Person;
  startTab?: Tab;
}) {
  const [tab, setTab] = useState<Tab>(startTab);
  const [profile, setProfile] = useState(initial);
  const [timezone, setTimezone] = useState(person.timezone || "America/New_York");
  const [contacts, setContacts] = useState<Contacts>(() => forDisplay(initialContacts));
  const [errors, setErrors] = useState<Partial<Record<ContactField, string>>>({});
  const [status, setStatus] = useState("");

  function setPerson(patch: Partial<Contacts["person"]>) {
    setContacts((c) => ({ ...c, person: { ...c.person, ...patch } }));
  }
  function setCaregiver(patch: Partial<Contacts["caregiver"]>) {
    setContacts((c) => ({ ...c, caregiver: { ...c.caregiver, ...patch } }));
  }
  const relationships = RELATIONSHIPS.includes(contacts.caregiver.relationship) || !contacts.caregiver.relationship
    ? RELATIONSHIPS
    : [...RELATIONSHIPS, contacts.caregiver.relationship];

  function patchExpense(category: string, next: Partial<CareProfile["expenses"][number]>) {
    setProfile({
      ...profile,
      expenses: profile.expenses.map((row) => (row.category === category ? { ...row, ...next } : row)),
    });
  }

  async function save() {
    const check = validateContacts(contacts);
    if (!check.ok) {
      setErrors(check.field ? { [check.field]: check.error } : {});
      setStatus(check.field ? "Check the highlighted field under Settings." : check.error);
      if (check.field) setTab("settings");
      return;
    }
    setErrors({});
    setStatus("Saving…");
    const res = await fetch("/api/profile", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile, timezone, contacts: check.value }),
    });
    const body = await res.json().catch(() => ({ error: "unknown" }));
    if (res.ok) {
      if (body.contacts) setContacts(forDisplay(body.contacts));
      // The route texts the caregiver only when their number changed; say so when it did.
      const hello = welcomeCopy(body.welcome, (body.contacts?.caregiver.name || contacts.caregiver.name).split(" ")[0]);
      setStatus(hello ? "Saved. " + hello.replace(/^Saved\. /, "") : "Saved.");
    } else {
      if (body.field) {
        setErrors({ [body.field]: body.error });
        setTab("settings");
      }
      setStatus("Could not save. " + (body.error || ""));
    }
  }

  const first = contacts.person.name.trim().split(" ")[0] || person.name?.split(" ")[0] || "them";

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
            <article className="decision">
              <strong>Who Gary calls</strong>
              <div className="fields">
                <label>
                  Their name
                  <input value={contacts.person.name} onChange={(e) => setPerson({ name: e.target.value })} aria-invalid={Boolean(errors["person.name"])} />
                  {errors["person.name"] && <span className="field-error">{errors["person.name"]}</span>}
                </label>
                <label>
                  Phone Gary answers
                  <input type="tel" inputMode="tel" value={contacts.person.phone} onChange={(e) => setPerson({ phone: e.target.value })} placeholder="(408) 981-4724" aria-invalid={Boolean(errors["person.phone"])} />
                  {errors["person.phone"] && <span className="field-error">{errors["person.phone"]}</span>}
                </label>
              </div>
            </article>
            <article className="decision">
              <strong>Who Gary texts for approvals</strong>
              <div className="fields">
                <label>
                  Your name
                  <input value={contacts.caregiver.name} onChange={(e) => setCaregiver({ name: e.target.value })} aria-invalid={Boolean(errors["caregiver.name"])} />
                  {errors["caregiver.name"] && <span className="field-error">{errors["caregiver.name"]}</span>}
                </label>
                <label>
                  You are their
                  <select value={contacts.caregiver.relationship} onChange={(e) => setCaregiver({ relationship: e.target.value })}>
                    <option value="">Choose one</option>
                    {relationships.map((r) => <option key={r} value={r}>{r}</option>)}
                  </select>
                </label>
                <label>
                  Your mobile
                  <input type="tel" inputMode="tel" value={contacts.caregiver.phone} onChange={(e) => setCaregiver({ phone: e.target.value })} placeholder="(650) 123-4567" aria-invalid={Boolean(errors["caregiver.phone"])} />
                  {errors["caregiver.phone"] && <span className="field-error">{errors["caregiver.phone"]}</span>}
                </label>
              </div>
              <p className="muted" style={{ fontSize: "0.85rem" }}>Approval requests are texted here. Changing this number sends a hello text to the new one.</p>
            </article>
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
          <p className="lede">Save the places Gary may use. The bank and Gmail connections are demo stand-ins; nothing signs in anywhere, and it never asks for a password or card.</p>
          <div className="stack">
            <article className="decision">
              <label className="choice">
                <input type="checkbox" checked={profile.connectors.groceries.connected} onChange={(e) => setProfile({ ...profile, connectors: { ...profile.connectors, groceries: { ...profile.connectors.groceries, connected: e.target.checked } } })} />
                <span className="conn-row"><img src={PROVIDERS.find((p) => p.key === "groceries")!.logo} alt="" /><strong>{PROVIDERS.find((p) => p.key === "groceries")!.name}</strong></span>
              </label>
              {profile.connectors.groceries.connected && (
                <div className="fields">
                  <label>Usual store<input value={profile.connectors.groceries.store} onChange={(e) => setProfile({ ...profile, connectors: { ...profile.connectors, groceries: { ...profile.connectors.groceries, store: e.target.value } } })} placeholder="Sunrise Market" /></label>
                  <div className="group">
                    Dietary restrictions
                    <TextList items={profile.connectors.groceries.restrictions} onChange={(restrictions) => setProfile({ ...profile, connectors: { ...profile.connectors, groceries: { ...profile.connectors.groceries, restrictions } } })} placeholder="e.g. shrimp allergy, no desserts" addLabel="Add a restriction" />
                  </div>
                </div>
              )}
            </article>
            <article className="decision">
              <label className="choice">
                <input type="checkbox" checked={profile.connectors.uber.connected} onChange={(e) => setProfile({ ...profile, connectors: { ...profile.connectors, uber: { ...profile.connectors.uber, connected: e.target.checked } } })} />
                <span className="conn-row"><img src={PROVIDERS.find((p) => p.key === "uber")!.logo} alt="" /><strong>{PROVIDERS.find((p) => p.key === "uber")!.name}</strong></span>
              </label>
              {profile.connectors.uber.connected && (
                <div className="fields">
                  <label>Home<input value={profile.connectors.uber.home} onChange={(e) => setProfile({ ...profile, connectors: { ...profile.connectors, uber: { ...profile.connectors.uber, home: e.target.value } } })} /></label>
                  <div className="group">
                    Other places
                    <PlaceList items={profile.connectors.uber.places} onChange={(places) => setProfile({ ...profile, connectors: { ...profile.connectors, uber: { ...profile.connectors.uber, places } } })} />
                  </div>
                </div>
              )}
            </article>
            <article className="decision">
              <label className="choice">
                <input type="checkbox" checked={profile.connectors.doordash.connected} onChange={(e) => setProfile({ ...profile, connectors: { ...profile.connectors, doordash: { ...profile.connectors.doordash, connected: e.target.checked } } })} />
                <span className="conn-row"><img src={PROVIDERS.find((p) => p.key === "doordash")!.logo} alt="" /><strong>{PROVIDERS.find((p) => p.key === "doordash")!.name}</strong></span>
              </label>
              {profile.connectors.doordash.connected && (
                <div className="fields">
                  <label>Usual order<input value={profile.connectors.doordash.usual} onChange={(e) => setProfile({ ...profile, connectors: { ...profile.connectors, doordash: { ...profile.connectors.doordash, usual: e.target.value } } })} placeholder="Chicken soup and tea" /></label>
                </div>
              )}
            </article>
            <article className="decision">
              <label className="choice">
                <input type="checkbox" checked={profile.connectors.gmail.connected} onChange={(e) => setProfile({ ...profile, connectors: { ...profile.connectors, gmail: { ...profile.connectors.gmail, connected: e.target.checked } } })} />
                <span className="conn-row"><img src={PROVIDERS.find((p) => p.key === "gmail")!.logo} alt="" /><strong>Gmail</strong></span>
              </label>
              {profile.connectors.gmail.connected && (
                <div className="fields">
                  <label>Email address<input type="email" value={profile.connectors.gmail.address} onChange={(e) => setProfile({ ...profile, connectors: { ...profile.connectors, gmail: { ...profile.connectors.gmail, address: e.target.value } } })} placeholder="margaret@gmail.com" /></label>
                </div>
              )}
            </article>
            <article className="decision">
              <label className="choice">
                <input type="checkbox" checked={profile.connectors.bank.connected} onChange={(e) => setProfile({ ...profile, connectors: { ...profile.connectors, bank: { ...profile.connectors.bank, connected: e.target.checked } } })} />
                <span className="conn-row"><img src={BANKS.find((b) => b.id === profile.connectors.bank.institution)?.logo || "/brands/bank.svg"} alt="" /><strong>{BANKS.find((b) => b.id === profile.connectors.bank.institution)?.label || "Bank"}</strong></span>
              </label>
              {profile.connectors.bank.connected && (
                <div className="fields">
                  <label>Bank
                    <select value={profile.connectors.bank.institution} onChange={(e) => setProfile({ ...profile, connectors: { ...profile.connectors, bank: { ...profile.connectors.bank, institution: e.target.value } } })}>
                      <option value="">Choose a bank</option>
                      {BANKS.map((b) => <option key={b.id} value={b.id}>{b.label}</option>)}
                    </select>
                  </label>
                  <label>Checking account, last 4 digits<input inputMode="numeric" maxLength={4} value={profile.connectors.bank.last4} onChange={(e) => setProfile({ ...profile, connectors: { ...profile.connectors, bank: { ...profile.connectors.bank, last4: e.target.value.replace(/\D/g, "").slice(0, 4) } } })} placeholder="1234" /></label>
                  <p className="muted" style={{ margin: 0, fontSize: "0.85rem" }}>Demo only. No real bank is contacted.</p>
                </div>
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
