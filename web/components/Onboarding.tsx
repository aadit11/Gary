"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { BANKS, type CareProfile } from "@/lib/profile";
import { PROVIDERS, type Key } from "@/lib/providers";
import { PlaceList, TextList } from "@/components/ListEditor";

type Phase = "idle" | "connecting" | "connected";

export default function Onboarding({ initial, person, start }: { initial: CareProfile; person: string; start?: string }) {
  const router = useRouter();
  const startIndex = Math.max(0, PROVIDERS.findIndex((p) => p.key === start));
  const [step, setStep] = useState(startIndex);
  const [profile, setProfile] = useState(initial);
  const [phase, setPhase] = useState<Phase>(initial.connectors[PROVIDERS[startIndex].key].connected ? "connected" : "idle");
  const [status, setStatus] = useState("");
  const provider = PROVIDERS[step];
  const last = step === PROVIDERS.length - 1;

  function setConnector(key: Key, patch: Record<string, unknown>) {
    setProfile((p) => ({ ...p, connectors: { ...p.connectors, [key]: { ...p.connectors[key], ...patch } } }));
  }

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

  function connect() {
    setPhase("connecting");
    window.setTimeout(() => {
      setConnector(provider.key, { connected: true });
      setPhase("connected");
    }, 350);
  }

  function goTo(index: number) {
    setStep(index);
    setPhase(profile.connectors[PROVIDERS[index].key].connected ? "connected" : "idle");
  }

  async function skip() {
    setConnector(provider.key, { connected: false });
    const next = { ...profile, connectors: { ...profile.connectors, [provider.key]: { ...profile.connectors[provider.key], connected: false } } };
    if (await persist(next, last)) {
      if (last) router.push("/dashboard/profile?tab=connections");
      else goTo(step + 1);
    }
  }

  async function cont() {
    if (await persist(profile, last)) {
      if (last) router.push("/dashboard/profile?tab=connections");
      else goTo(step + 1);
    }
  }

  const c = profile.connectors;

  return (
    <div className="connect-wrap">
      <div className="dots" aria-label={`Step ${step + 1} of ${PROVIDERS.length}`}>
        {PROVIDERS.map((p, i) => (
          <span key={p.key} className={i === step ? "on" : i < step ? "done" : ""} />
        ))}
        <em>{step + 1} of {PROVIDERS.length}</em>
      </div>

      <section className="connect-card" key={provider.key}>
        <div className="logo-pair">
          <div className="logo-circle gary" aria-hidden="true">G</div>
          <div className="logo-circle"><img src={provider.key === "bank" ? (BANKS.find((b) => b.id === c.bank.institution)?.logo || provider.logo) : provider.logo} alt={`${provider.name} logo`} /></div>
        </div>
        <h2>Gary uses <strong>{provider.name}</strong> to {provider.does} for {person}</h2>
        <p className="lede">Gary never asks {person} for a password or a card. It only uses what you connect here.</p>
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
                    Other places {person} goes
                    <PlaceList items={c.uber.places} onChange={(places) => setConnector("uber", { places })} />
                  </div>
                </>
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

      <div className="connect-footer">
        <div>{step > 0 ? <button type="button" className="quiet-button" onClick={() => goTo(step - 1)}>Back</button> : <span />}</div>
        {status && <p className="muted" style={{ margin: 0 }}>{status}</p>}
      </div>
    </div>
  );
}
