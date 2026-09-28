// Who Gary calls and who Gary texts. These live in the real tables the backend reads, not in
// the care profile JSON: users.name/phone is the elder (inbound calls are matched on that
// phone) and the first family_contacts row with can_approve = true is the caregiver (approval
// texts go there, and YES/NO replies are matched on that phone).
import { DEMO_USER_ID, supabase } from "@/lib/supabase";

export type Contacts = {
  person: { name: string; phone: string };
  caregiver: { name: string; relationship: string; phone: string };
};
export type ContactField = "person.name" | "person.phone" | "caregiver.name" | "caregiver.phone";
export type Welcome = { sent: boolean; reason: string; channel?: string; to?: string; name?: string };

export const RELATIONSHIPS = ["daughter", "son", "spouse", "grandchild", "sibling", "friend", "caregiver", "other"];

export function emptyContacts(): Contacts {
  return { person: { name: "", phone: "" }, caregiver: { name: "", relationship: "", phone: "" } };
}

/** E.164 for a US number, or null. Same rules as the backend's notify.normalize_phone + _can_message. */
export function normalizeUsPhone(raw: string): string | null {
  let digits = (raw || "").replace(/\D/g, "");
  if (digits.length === 11 && digits.startsWith("1")) digits = digits.slice(1);
  if (digits.length !== 10) return null;
  if (digits.startsWith("500") || digits.startsWith("555")) return null; // fictional ranges Gary cannot text
  return "+1" + digits;
}

/** "+14085550123" -> "(408) 555-0123"; anything that is not a valid US number comes back unchanged. */
export function formatPhone(value: string): string {
  const e164 = normalizeUsPhone(value);
  if (!e164) return value;
  const d = e164.slice(2);
  return `(${d.slice(0, 3)}) ${d.slice(3, 6)}-${d.slice(6)}`;
}

/** Copy for form fields: valid numbers formatted, anything else (like the seeded fictional number) blank. */
export function forDisplay(c: Contacts): Contacts {
  const show = (phone: string) => (normalizeUsPhone(phone) ? formatPhone(phone) : "");
  return { person: { ...c.person, phone: show(c.person.phone) }, caregiver: { ...c.caregiver, phone: show(c.caregiver.phone) } };
}

type Check = { ok: true; value: Contacts } | { ok: false; error: string; field?: ContactField };

/** Normalizes and checks a contacts payload. Used by the form before submit and by the API route. */
export function validateContacts(raw: unknown): Check {
  const body = (raw ?? {}) as Partial<Contacts>;
  const personName = String(body.person?.name ?? "").trim().slice(0, 80);
  const caregiverName = String(body.caregiver?.name ?? "").trim().slice(0, 80);
  const relationship = String(body.caregiver?.relationship ?? "").trim().slice(0, 40);
  if (!personName) return { ok: false, error: "Enter their name.", field: "person.name" };
  const personPhone = normalizeUsPhone(String(body.person?.phone ?? ""));
  if (!personPhone) return { ok: false, error: "Enter a 10-digit US phone number Gary can call.", field: "person.phone" };
  if (!caregiverName) return { ok: false, error: "Enter your name.", field: "caregiver.name" };
  const caregiverPhone = normalizeUsPhone(String(body.caregiver?.phone ?? ""));
  if (!caregiverPhone) return { ok: false, error: "Enter a 10-digit US mobile number Gary can text.", field: "caregiver.phone" };
  if (personPhone === caregiverPhone) {
    return { ok: false, error: "Use two different numbers: Gary calls one and texts the other.", field: "caregiver.phone" };
  }
  return {
    ok: true,
    value: { person: { name: personName, phone: personPhone }, caregiver: { name: caregiverName, relationship, phone: caregiverPhone } },
  };
}

export async function loadContacts(): Promise<Contacts> {
  const out = emptyContacts();
  const client = supabase();
  if (!client || !DEMO_USER_ID) return out;
  const user = await client.from("users").select("name,phone").eq("id", DEMO_USER_ID).limit(1);
  if (user.data?.[0]) out.person = { name: user.data[0].name || "", phone: user.data[0].phone || "" };
  const approver = await client
    .from("family_contacts")
    .select("name,relationship,phone")
    .eq("user_id", DEMO_USER_ID)
    .eq("can_approve", true)
    .order("created_at", { ascending: true })
    .limit(1);
  if (approver.data?.[0]) {
    const c = approver.data[0];
    out.caregiver = { name: c.name || "", relationship: c.relationship || "", phone: c.phone || "" };
  }
  return out;
}

type Saved = { contacts: Contacts; caregiverPhoneChanged: boolean } | { error: string; field?: ContactField; status: number };

/** Writes the elder to users and the caregiver to the approver row, updating in place so approval links survive. */
export async function saveContacts(next: Contacts): Promise<Saved> {
  const client = supabase();
  if (!client || !DEMO_USER_ID) return { error: "The care desk is not connected yet.", status: 503 };

  const user = await client
    .from("users")
    .update({ name: next.person.name, phone: next.person.phone })
    .eq("id", DEMO_USER_ID)
    .select("name,phone")
    .single();
  if (user.error) {
    if (user.error.code === "23505") return { error: "That phone number already belongs to another account.", field: "person.phone", status: 409 };
    if (user.error.code === "PGRST116") return { error: "The demo user is missing. Run the seed script first.", status: 404 };
    return { error: user.error.message, status: 500 };
  }

  const existing = await client
    .from("family_contacts")
    .select("id,phone")
    .eq("user_id", DEMO_USER_ID)
    .eq("can_approve", true)
    .order("created_at", { ascending: true })
    .limit(1);
  if (existing.error) return { error: existing.error.message, status: 500 };
  const prev = existing.data?.[0];
  const values = { name: next.caregiver.name, relationship: next.caregiver.relationship, phone: next.caregiver.phone };
  const saved = prev
    ? await client.from("family_contacts").update(values).eq("id", prev.id).select("name,relationship,phone").single()
    : await client.from("family_contacts").insert({ ...values, user_id: DEMO_USER_ID, can_approve: true }).select("name,relationship,phone").single();
  if (saved.error) return { error: saved.error.message, status: 500 };

  return {
    contacts: { person: { name: user.data.name, phone: user.data.phone }, caregiver: saved.data },
    caregiverPhoneChanged: !prev || prev.phone !== next.caregiver.phone,
  };
}

/** Asks the backend to text the caregiver a hello. Server-side only; never fails the save. */
export async function requestWelcome(): Promise<Welcome> {
  const backend = (process.env.BACKEND_URL || "http://localhost:8000").replace(/\/$/, "");
  try {
    const res = await fetch(`${backend}/notify/welcome`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: DEMO_USER_ID }),
      signal: AbortSignal.timeout(5000),
    });
    if (res.ok) return (await res.json()) as Welcome;
    return { sent: false, reason: `backend_${res.status}` };
  } catch {
    return { sent: false, reason: "backend_unreachable" };
  }
}

/** One line for the screen after a save. */
export function welcomeCopy(w: Welcome | undefined, caregiverFirst: string): string {
  if (!w) return "";
  const who = caregiverFirst || "you";
  if (w.sent) return `We sent ${who} a hello on ${w.channel === "whatsapp" ? "WhatsApp" : "text"}.`;
  const base = `Saved. We couldn't send ${who} a hello text right now; approval requests will still go to this number.`;
  if (w.channel === "whatsapp") return `${base} On WhatsApp, ${who} first has to send the join message to Gary's WhatsApp number.`;
  return base;
}
