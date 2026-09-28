"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { BANKS, type CareProfile } from "@/lib/profile";
import { PROVIDERS, type Key } from "@/lib/providers";
import { PlaceList, TextList } from "@/components/ListEditor";
import { RELATIONSHIPS, forDisplay, validateContacts, welcomeCopy, type ContactField, type Contacts } from "@/lib/contacts";

type Phase = "idle" | "connecting" | "connected";
type Provider = (typeof PROVIDERS)[number];
type Screen = { kind: "contacts" } | { kind: "provider"; provider: Provider };

// Step 1 is who Gary calls and who Gary texts; then one connect card per provider.
const SCREENS: Screen[] = [{ kind: "contacts" }, ...PROVIDERS.map((provider) => ({ kind: "provider" as const, provider }))];

export default function Onboarding({
  initial,
  contacts: initialContacts,
  person,
  start,
}: {
  initial: CareProfile;
  contacts: Contacts;
  person: string;
  start?: string;
}) {
  const router = useRouter();
  const startIndex = start ? Math.max(1, SCREENS.findIndex((s) => s.kind === "provider" && s.provider.key === start)) : 0;
  const [step, setStep] = useState(startIndex);
  const [profile, setProfile] = useState(initial);
  const [contacts, setContacts] = useState<Contacts>(() => forDisplay(initialContacts));
  const [errors, setErrors] = useState<Partial<Record<ContactField, string>>>({});
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState("");
  const screen = SCREENS[step];
  const provider = screen.kind === "provider" ? screen.provider : null;
  const last = step === SCREENS.length - 1;
  const personName = contacts.person.name.trim().split(" ")[0] || person;

  function phaseFor(index: number): Phase {
    const s = SCREENS[index];
    return s.kind === "provider" && profile.connectors[s.provider.key].connected ? "connected" : "idle";
  }
  const [phase, setPhase] = useState<Phase>(() => phaseFor(startIndex));

  function setConnector(key: Key, patch: Record<string, unknown>) {
    setProfile((p) => ({ ...p, connectors: { ...p.connectors, [key]: { ...p.connectors[key], ...patch } } }));
  }
  function setPerson(patch: Partial<Contacts["person"]>) {
    setContacts((c) => ({ ...c, person: { ...c.person, ...patch } }));
  }
  function setCaregiver(patch: Partial<Contacts["caregiver"]>) {
    setContacts((c) => ({ ...c, caregiver: { ...c.caregiver, ...patch } }));
  }

  function persist(next: CareProfile, done = false) {
    // Fire and forget: the screen advances immediately; only a failure is surfaced.
    fetch("/api/profile", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile: { ...next, onboarded: done || next.onboarded } }),
      keepalive: true,
    })
      .then(async (res) => {
        if (!res.ok) {
          const body = await res.json().catch(() => ({ error: "unknown" }));
          setStatus("Could not save. " + (body.error || ""));
        }
      })
      .catch(() => setStatus("Could not save."));
  }

  // The contacts step waits for the save: a number that belongs to another account must be
  // shown here, and the caregiver's hello text is reported on the next screen.
  async function saveContactsStep() {
    const check = validateContacts(contacts);
    if (!check.ok) {
      setErrors(check.field ? { [check.field]: check.error } : {});
      setStatus(check.field ? "" : check.error);
      return;
    }
    setErrors({});
    setSaving(true);
    setStatus("Saving…");
    let body: { error?: string; field?: ContactField; contacts?: Contacts; welcome?: Parameters<typeof welcomeCopy>[0] } = {};
    let ok = false;
    try {
      const res = await fetch("/api/profile", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ profile, contacts: check.value, welcome: true }),
      });
      ok = res.ok;
      body = await res.json().catch(() => ({ error: "unknown" }));
    } catch {
      body = { error: "unknown" };
    }
    setSaving(false);
    if (!ok) {
      if (body.field) {
        setErrors({ [body.field]: body.error || "Check this." });
        setStatus("");
      } else {
        setStatus("Could not save. " + (body.error || ""));
      }
      return;
    }
    if (body.contacts) setContacts(forDisplay(body.contacts));
    setStatus(welcomeCopy(body.welcome, (body.contacts?.caregiver.name || contacts.caregiver.name).split(" ")[0]));
    goTo(step + 1);
  }

  function connect() {
    if (!provider) return;
    const key = provider.key;
    setPhase("connecting");
    window.setTimeout(() => {
      setConnector(key, { connected: true });
      setPhase("connected");
    }, 100);
  }

  function goTo(index: number) {
    setStep(index);
    setPhase(phaseFor(index));
  }

  function skip() {
    if (!provider) return;
    const next = { ...profile, connectors: { ...profile.connectors, [provider.key]: { ...profile.connectors[provider.key], connected: false } } };
    setProfile(next);
    persist(next, last);
    if (last) router.push("/dashboard/profile?tab=connections");
    else goTo(step + 1);
  }

  function cont() {
    persist(profile, last);
    if (last) router.push("/dashboard/profile?tab=connections");
    else goTo(step + 1);
  }

  const c = profile.connectors;
  const relationships = RELATIONSHIPS.includes(contacts.caregiver.relationship) || !contacts.caregiver.relationship
    ? RELATIONSHIPS
    : [...RELATIONSHIPS, contacts.caregiver.relationship];

  return (
    <>
      <div style={{ textAlign: "center", maxWidth: "36rem", margin: "0 auto 1rem" }}>
        {screen.kind === "contacts" ? (
          <>
            <p className="eyebrow">Who Gary calls</p>
            <h1>Who is Gary for, and who should Gary text?</h1>
            <p className="lede">Gary answers when their phone calls, and texts you when something needs your okay.</p>
          </>
        ) : (
          <>
            <p className="eyebrow">Connect apps</p>
            <h1>Connect the apps Gary will use for {personName}</h1>
            <p className="lede">One at a time. Gary never asks for a password or a card.</p>
          </>
        )}
      </div>

      <div className="connect-wrap">
        <div className="dots" aria-label={`Step ${step + 1} of ${SCREENS.length}`}>
          {SCREENS.map((s, i) => (
            <span key={s.kind === "provider" ? s.provider.key : "contacts"} className={i === step ? "on" : i < step ? "done" : ""} />
          ))}
          <em>{step + 1} of {SCREENS.length}</em>
        </div>

        {screen.kind === "contacts" && (
          <section className="connect-card" key="contacts">
            <div className="logo-pair">
              <div className="logo-circle gary"><img src="/logo-mark.png" alt="Gary logo" /></div>
            </div>
            <h2>Gary calls <strong>them</strong> and texts <strong>you</strong></h2>
            <p className="lede">Gary picks up when their number calls. Anything risky waits for your okay by text.</p>
            <div className="fields">
              <label>
                Their name
                <input value={contacts.person.name} onChange={(e) => setPerson({ name: e.target.value })} placeholder="Margaret Chen" autoComplete="off" aria-invalid={Boolean(errors["person.name"])} />
                {errors["person.name"] && <span className="field-error">{errors["person.name"]}</span>}
              </label>
              <label>
                Their phone
                <input type="tel" inputMode="tel" value={contacts.person.phone} onChange={(e) => setPerson({ phone: e.target.value })} placeholder="(408) 555-0123" autoComplete="off" aria-invalid={Boolean(errors["person.phone"])} />
                {errors["person.phone"] && <span className="field-error">{errors["person.phone"]}</span>}
              </label>
              <label>
                Your name
                <input value={contacts.caregiver.name} onChange={(e) => setCaregiver({ name: e.target.value })} placeholder="David Chen" autoComplete="name" aria-invalid={Boolean(errors["caregiver.name"])} />
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
                <input type="tel" inputMode="tel" value={contacts.caregiver.phone} onChange={(e) => setCaregiver({ phone: e.target.value })} placeholder="(650) 123-4567" autoComplete="tel" aria-invalid={Boolean(errors["caregiver.phone"])} />
                {errors["caregiver.phone"] && <span className="field-error">{errors["caregiver.phone"]}</span>}
              </label>
            </div>
            <p className="muted" style={{ margin: "0 0 1rem", fontSize: "0.85rem" }}>Gary texts this number when something needs your okay. Reply YES or NO.</p>
            <div className="connect-actions">
              <button type="button" onClick={saveContactsStep} disabled={saving}>{saving ? "Saving…" : "Continue"}</button>
            </div>
          </section>
        )}

        {provider && (
          <section className="connect-card" key={provider.key}>
            <div className="logo-pair">
              <div className="logo-circle gary"><img src="/logo-mark.png" alt="Gary logo" /></div>
              <div className="logo-circle"><img src={provider.key === "bank" ? (BANKS.find((b) => b.id === c.bank.institution)?.logo || provider.logo) : provider.logo} alt={`${provider.name} logo`} /></div>
            </div>
            <h2>Gary uses <strong>{provider.name}</strong> to {provider.does} for {personName}</h2>
            <p className="lede">Gary never asks {personName} for a password or a card. It only uses what you connect here.</p>
            <ul>
              {provider.bullets.map((b) => <li key={b}>{b}</li>)}
            </ul>

            {phase === "idle" && (
              <div className="connect-actions">
                <button type="button" onClick={connect} style={{ background: provider.color }}>Connect {provider.key === "bank" ? "a bank" : provider.name}</button>
                <button type="button" className="quiet-link" onClick={skip}>Not now</button>
              </div>
            )}
            {phase === "connecting" && (
              <div className="connect-status"><span className="spinner" aria-hidden="true" /> Connecting to {provider.name}…</div>
            )}
            {phase === "connected" && (
              <>
                <div className="connect-status"><span className="check" aria-hidden="true">✓</span> {provider.key === "bank" ? (BANKS.find((b) => b.id === c.bank.institution)?.label || "Bank") : provider.name} connected</div>
                <div className="fields">
                  {provider.key === "doordash" && (
                    <label>Usual order<input value={c.doordash.usual} onChange={(e) => setConnector("doordash", { usual: e.target.value })} placeholder="Chicken soup and tea" /></label>
                  )}
                  {provider.key === "uber" && (
                    <>
                      <label>Home<input value={c.uber.home} onChange={(e) => setConnector("uber", { home: e.target.value })} /></label>
                      <div className="group">
                        Other places {personName} goes
                        <PlaceList items={c.uber.places} onChange={(places) => setConnector("uber", { places })} />
                      </div>
                    </>
                  )}
                  {provider.key === "taskrabbit" && (
                    <label>Notes for the visit<input value={c.taskrabbit.notes} onChange={(e) => setConnector("taskrabbit", { notes: e.target.value })} placeholder="Ring twice, the dog is friendly" /></label>
                  )}
                  {provider.key === "gmail" && (
                    <label>Email address<input type="email" value={c.gmail.address} onChange={(e) => setConnector("gmail", { address: e.target.value })} placeholder="margaret@gmail.com" /></label>
                  )}
                  {provider.key === "bank" && (
                    <>
                      <label>Bank
                        <select value={c.bank.institution} onChange={(e) => setConnector("bank", { institution: e.target.value })}>
                          <option value="">Choose a bank</option>
                          {BANKS.map((b) => <option key={b.id} value={b.id}>{b.label}</option>)}
                        </select>
                      </label>
                      <label>Checking account, last 4 digits<input inputMode="numeric" maxLength={4} value={c.bank.last4} onChange={(e) => setConnector("bank", { last4: e.target.value.replace(/\D/g, "").slice(0, 4) })} placeholder="1234" /></label>
                      <p className="muted" style={{ margin: 0, fontSize: "0.85rem" }}>Demo only. No real bank is contacted and no credentials are stored.</p>
                    </>
                  )}
                  {provider.key === "groceries" && (
                    <>
                      <label>Usual store<input value={c.groceries.store} onChange={(e) => setConnector("groceries", { store: e.target.value })} placeholder="Sunrise Market" /></label>
                      <div className="group">
                        Dietary restrictions
                        <TextList items={c.groceries.restrictions} onChange={(restrictions) => setConnector("groceries", { restrictions })} placeholder="e.g. shrimp allergy, no desserts" addLabel="Add a restriction" />
                      </div>
                    </>
                  )}
                </div>
                <div className="connect-actions">
                  <button type="button" onClick={cont}>{last ? "Finish setup" : "Continue"}</button>
                </div>
              </>
            )}
          </section>
        )}

        <div className="connect-footer">
          <div>{step > 0 ? <button type="button" className="quiet-button" onClick={() => goTo(step - 1)}>Back</button> : <span />}</div>
          {status && <p className="muted" style={{ margin: 0 }}>{status}</p>}
        </div>
      </div>
    </>
  );
}
