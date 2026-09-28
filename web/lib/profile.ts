import { DEMO_USER_ID, supabase } from "@/lib/supabase";

export const PROFILE_GMAIL_ID = "caregiver-profile";

export const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

export const DIET_OPTIONS = [
  { id: "low-sodium", label: "Low sodium" },
  { id: "diabetic-friendly", label: "Diabetic-friendly" },
  { id: "soft-foods", label: "Soft foods" },
  { id: "no-nuts", label: "No nuts" },
  { id: "vegetarian", label: "Vegetarian" },
  { id: "gluten-free", label: "Gluten-free" },
  { id: "lactose-free", label: "Lactose-free" },
];

export const EXPENSE_CATEGORIES = [
  { id: "rent", label: "Rent" },
  { id: "utilities", label: "Utilities" },
  { id: "groceries", label: "Groceries" },
  { id: "pharmacy", label: "Pharmacy" },
  { id: "phone", label: "Phone" },
  { id: "insurance", label: "Insurance" },
];

export const BANKS = [
  { id: "chase", label: "Chase", logo: "https://cdn.simpleicons.org/chase/117ACA" },
  { id: "bankofamerica", label: "Bank of America", logo: "https://cdn.simpleicons.org/bankofamerica/012169" },
  { id: "wellsfargo", label: "Wells Fargo", logo: "https://cdn.simpleicons.org/wellsfargo/D71E28" },
  { id: "other", label: "Another bank", logo: "/brands/bank.svg" },
];

export const TIMEZONES = ["America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles"];

export type ExpenseChoice = { category: string; due_day: number; active: boolean };
export type Place = { label: string; address: string };

export type CareProfile = {
  dietary: string[];
  expenses: ExpenseChoice[];
  notify_expenses: boolean;
  connectors: {
    doordash: { connected: boolean; usual: string };
    uber: { connected: boolean; home: string; hospital: string; places: Place[] };
    groceries: { connected: boolean; store: string; restrictions: string[] };
    taskrabbit: { connected: boolean; notes: string };
    banking: { connected: boolean };
    gmail: { connected: boolean; address: string };
    bank: { connected: boolean; institution: string; last4: string };
  };
  weekly_days: Record<string, number>;
  onboarded: boolean;
};

export function emptyProfile(home = ""): CareProfile {
  return {
    dietary: [],
    expenses: EXPENSE_CATEGORIES.map((item) => ({ category: item.id, due_day: 1, active: false })),
    notify_expenses: true,
    connectors: {
      doordash: { connected: false, usual: "" },
      uber: { connected: false, home, hospital: "", places: [] },
      groceries: { connected: false, store: "", restrictions: [] },
      taskrabbit: { connected: false, notes: "" },
      banking: { connected: false },
      gmail: { connected: false, address: "" },
      bank: { connected: false, institution: "", last4: "" },
    },
    weekly_days: {},
    onboarded: false,
  };
}

function cleanList(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((v) => String(v ?? "").trim()).filter(Boolean).slice(0, 20);
}

function cleanPlaces(raw: unknown, legacyHospital?: unknown): Place[] {
  const places = Array.isArray(raw)
    ? raw
        .map((v) => ({ label: String((v as Place)?.label ?? "").trim(), address: String((v as Place)?.address ?? "").trim() }))
        .filter((v) => v.label || v.address)
        .slice(0, 20)
    : [];
  // Older profiles stored a single "hospital" field; carry it over as the first place.
  if (!places.length && typeof legacyHospital === "string" && legacyHospital.trim()) {
    places.push({ label: "Doctor or hospital", address: legacyHospital.trim() });
  }
  return places;
}

function asProfile(raw: unknown, home = ""): CareProfile {
  const base = emptyProfile(home);
  if (!raw || typeof raw !== "object") return base;
  const body = raw as Partial<CareProfile>;
  const expenses = EXPENSE_CATEGORIES.map((item) => {
    const found = (body.expenses || []).find((row) => row.category === item.id);
    const day = Number(found?.due_day);
    return {
      category: item.id,
      due_day: day >= 1 && day <= 28 ? day : 1,
      active: Boolean(found?.active),
    };
  });
  return {
    dietary: (body.dietary || []).filter((id) => DIET_OPTIONS.some((option) => option.id === id)),
    expenses,
    notify_expenses: body.notify_expenses !== false,
    connectors: {
      doordash: { connected: Boolean(body.connectors?.doordash?.connected), usual: body.connectors?.doordash?.usual || "" },
      uber: {
        connected: Boolean(body.connectors?.uber?.connected),
        home: body.connectors?.uber?.home || home,
        hospital: body.connectors?.uber?.hospital || "",
        places: cleanPlaces(body.connectors?.uber?.places, body.connectors?.uber?.hospital),
      },
      groceries: {
        connected: Boolean(body.connectors?.groceries?.connected),
        store: body.connectors?.groceries?.store || "",
        restrictions: cleanList(body.connectors?.groceries?.restrictions),
      },
      taskrabbit: { connected: Boolean(body.connectors?.taskrabbit?.connected), notes: String(body.connectors?.taskrabbit?.notes || "").slice(0, 200) },
      banking: { connected: Boolean(body.connectors?.banking?.connected) },
      gmail: { connected: Boolean(body.connectors?.gmail?.connected), address: String(body.connectors?.gmail?.address || "") },
      bank: {
        connected: Boolean(body.connectors?.bank?.connected),
        institution: BANKS.some((b) => b.id === body.connectors?.bank?.institution) ? String(body.connectors?.bank?.institution) : "",
        last4: String(body.connectors?.bank?.last4 || "").replace(/\D/g, "").slice(-4),
      },
    },
    weekly_days: body.weekly_days && typeof body.weekly_days === "object" ? body.weekly_days : {},
    onboarded: Boolean(body.onboarded),
  };
}

export async function loadProfile(): Promise<CareProfile> {
  const client = supabase();
  let home = "";
  if (client && DEMO_USER_ID) {
    const user = await client.from("users").select("address").eq("id", DEMO_USER_ID).limit(1);
    home = (user.data?.[0]?.address as string) || "";
  }
  if (!client) return emptyProfile(home);
  const { data } = await client.from("emails").select("extracted").eq("gmail_id", PROFILE_GMAIL_ID).limit(1);
  return asProfile(data?.[0]?.extracted, home);
}

export async function saveProfile(next: CareProfile): Promise<string | null> {
  const client = supabase();
  if (!client || !DEMO_USER_ID) return "The care desk is not connected yet.";
  const profile = asProfile(next);
  const row = {
    user_id: DEMO_USER_ID,
    gmail_id: PROFILE_GMAIL_ID,
    sender: "caregiver",
    subject: "Care profile",
    snippet: "Saved places, diet, and bill reminders.",
    classification: "other",
    extracted: profile,
  };
  const existing = await client.from("emails").select("id").eq("gmail_id", PROFILE_GMAIL_ID).limit(1);
  const id = existing.data?.[0]?.id as string | undefined;
  const result = id
    ? await client.from("emails").update({ extracted: profile, snippet: row.snippet }).eq("id", id)
    : await client.from("emails").insert(row);
  return result.error?.message || null;
}

export async function rememberWeekday(reminderId: string, weekday: number): Promise<string | null> {
  const profile = await loadProfile();
  profile.weekly_days = { ...profile.weekly_days, [reminderId]: weekday };
  return saveProfile(profile);
}
