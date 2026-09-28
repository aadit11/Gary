import { DEMO_USER_ID, supabase } from "@/lib/supabase";

export async function careFirstName(): Promise<string> {
  const client = supabase();
  if (!client || !DEMO_USER_ID) return "them";
  const { data } = await client.from("users").select("name").eq("id", DEMO_USER_ID).limit(1);
  const name = data?.[0]?.name as string | undefined;
  return name?.split(" ")[0] || "them";
}

const KIND_LABEL: Record<string, string> = {
  call_started: "Call started",
  call_ended: "Call finished",
  tool_called: "During the call",
  call_error: "Call problem",
  reminder_confirmed: "Reminder confirmed",
  reminder_unconfirmed: "Reminder not confirmed",
  appointment_reminded: "Appointment reminder",
  expense_reminded: "Bill reminder",
  family_summary: "Note for you",
  family_welcomed: "Hello text sent",
};

const TOOL_LABEL: Record<string, string> = {
  get_daily_briefing: "Shared how the day looks",
  get_upcoming_appointments: "Looked up appointments",
  confirm_reminder: "Marked a reminder confirmed",
  summarize_for_family: "Wrote you a short note",
  prepare_caregiver_transfer: "Offered to connect the call to you",
  confirm_caregiver_transfer: "Connected the call to you",
};

const OUTCOME_LABEL: Record<string, string> = {
  resolved: "Finished without anything waiting on you.",
  summarized_to_family: "A short note was prepared for you.",
  transferred: "The call was connected to you.",
  transfer_skipped: "The call could not be connected, so a note was left instead.",
  unconfirmed: "The reminder was not confirmed.",
  safety_stop: "Personal numbers were stopped before they were repeated.",
  error: "Something went wrong on the call.",
  unknown: "The call ended.",
};

export function eventTitle(kind: string, data?: { tool?: string } | null): string {
  if (kind.includes("approval")) return "A decision";
  if (kind === "tool_called" && data?.tool && TOOL_LABEL[data.tool]) return TOOL_LABEL[data.tool];
  return KIND_LABEL[kind] ?? kind.replaceAll("_", " ");
}

const STARTED: Record<string, (person: string) => string> = {
  inbound: (person) => `${person} called Gary.`,
  appointment: (person) => `Gary called ${person} about an appointment.`,
  reminder: (person) => `Gary called ${person} with a reminder.`,
  morning_briefing: (person) => `Gary called ${person} with the morning check-in.`,
};

export function eventBody(
  row: { kind: string; summary?: string | null; data?: { say?: string; outcome?: string; tool?: string } | null },
  person = "They",
): string {
  const data = row.data ?? {};
  if (row.kind === "tool_called" && data.say) return data.say;
  if (row.kind === "call_started") {
    const reason = (row.summary || "").replace(/ call started$/, "");
    return (STARTED[reason] ?? (() => "A call started."))(person);
  }
  if (row.kind === "call_ended") return (data.outcome && OUTCOME_LABEL[data.outcome]) || "The call finished.";
  return (row.summary || "").replaceAll("_", " ");
}

export function tone(kind: string, outcome?: string | null): string {
  if (kind === "reminder_unconfirmed" || kind === "call_error" || outcome === "error" || outcome === "unconfirmed") return "attention";
  if (kind === "family_summary" || outcome === "summarized_to_family" || outcome === "transfer_skipped") return "note";
  return "quiet";
}
