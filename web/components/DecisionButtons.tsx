"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export default function DecisionButtons({ id }: { id: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState<"yes" | "no" | null>(null);
  const [note, setNote] = useState("");

  async function decide(approved: boolean) {
    setBusy(approved ? "yes" : "no");
    const res = await fetch(`/api/approvals/${id}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ approved }) });
    const body = await res.json().catch(() => ({}));
    setNote(res.ok ? body.message || (approved ? "Approved." : "Denied.") : "Could not save: " + (body.error || res.status));
    setBusy(null);
    if (res.ok) router.refresh();
  }

  return (
    <div className="decision-actions">
      <button type="button" onClick={() => decide(true)} disabled={busy !== null}>{busy === "yes" ? "Approving…" : "Approve"}</button>
      <button type="button" className="deny" onClick={() => decide(false)} disabled={busy !== null}>{busy === "no" ? "Denying…" : "Deny"}</button>
      {note && <span className="note">{note}</span>}
    </div>
  );
}
