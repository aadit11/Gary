import { DEMO_USER_ID, supabase } from "@/lib/supabase";

export async function careFirstName(): Promise<string> {
  const client = supabase();
  if (!client || !DEMO_USER_ID) return "them";
  const { data } = await client.from("users").select("name").eq("id", DEMO_USER_ID).limit(1);
  const name = data?.[0]?.name as string | undefined;
  return name?.split(" ")[0] || "them";
}

export type ActivityRow = {
  id: string;
  kind: string;
  summary?: string | null;
  created_at: string;
  data?: Record<string, unknown> | null;
};

// Every event kind the backend writes, in sentence case. Anything new falls back to sentence case too.
const KIND_LABEL: Record<string, string> = {
  call_started: "Call started",
  call_ended: "Call finished",
  call_error: "Call problem",
  tool_called: "During the call",
  reminder_confirmed: "Reminder confirmed",
  reminder_unconfirmed: "Reminder not confirmed",
  appointment_reminded: "Appointment reminder",
  expense_reminded: "Bill reminder",
  family_summary: "Note for you",
  family_welcomed: "Hello text sent",
  ride_requested: "Ride requested",
  ride: "Ride booked",
  order_requested: "Order sent",
  order_staged: "Order ready to place",
  order: "Order placed",
  order_stage_failed: "Order not ready",
  restaurant_checked: "Restaurant checked",
  service_search: "Looked for home help",
  service_search_failed: "Home help search failed",
  service_requested: "Booking started",
  service_booking: "Home help booked",
  scam_check: "Scam check",
  scam_flagged: "Suspicious email flagged",
  bill_paid: "Bill paid",
  person_paid: "Money sent",
  approval_requested: "Asked you first",
  approval_approved: "You said yes",
  approval_denied: "You said no",
  browser_job_started: "Gary opened a website",
  browser_job_finished: "Gary finished on the website",
};

// When the outcome is an error the title should say so.
const FAILED_LABEL: Record<string, string> = {
  ride: "Ride not booked",
  order: "Order not placed",
  service_booking: "Home help not booked",
  browser_job_finished: "Gary could not finish on the website",
};

const TOOL_LABEL: Record<string, string> = {
  get_daily_briefing: "Shared how the day looks",
  get_upcoming_appointments: "Looked up appointments",
  confirm_reminder: "Marked a reminder confirmed",
  summarize_for_family: "Wrote you a short note",
  prepare_caregiver_transfer: "Offered to connect the call to you",
  confirm_caregiver_transfer: "Connected the call to you",
  list_bills_due: "Looked up bills",
  prepare_bill_payment: "Read a bill back",
  confirm_bill_payment: "Paid a bill",
  prepare_payment_to_person: "Read a payment back",
  confirm_payment_to_person: "Sent money",
  check_message_for_scam: "Checked a message for scams",
  list_suspicious_emails: "Looked for suspicious emails",
  get_favorite_orders: "Looked up the usual orders",
  search_food_and_groceries: "Looked up a restaurant",
  prepare_order: "Read an order back",
  confirm_order: "Placed an order",
  find_home_service: "Looked for home help",
  prepare_service_booking: "Read a booking back",
  confirm_service_booking: "Booked home help",
  suggest_ride_for_appointment: "Offered a ride",
  prepare_ride: "Read a ride back",
  confirm_ride: "Booked a ride",
  get_ride_status: "Checked on a ride",
};

const OUTCOME_LABEL: Record<string, string> = {
  resolved: "Finished without anything waiting on you.",
  summarized_to_family: "A short note was prepared for you.",
  transferred: "The call was connected to you.",
  transfer_skipped: "The call could not be connected, so a note was left instead.",
  unconfirmed: "The reminder was not confirmed.",
  safety_stop: "Personal numbers were stopped before they were repeated.",
  needs_approval: "Something is waiting on your okay.",
  booking: "A booking was still in progress when the call ended.",
  booked: "A booking went through.",
  placed: "An order went through.",
  error: "Something went wrong on the call.",
  unknown: "The call ended.",
};

const SITE_NAME: Record<string, string> = { udriver: "Udriver", dashdish: "DashDish", taskhare: "TaskHare" };

function sentenceCase(text: string): string {
  const plain = text.replaceAll("_", " ").trim();
  return plain ? plain[0].toUpperCase() + plain.slice(1) : plain;
}

export function eventTitle(kind: string, data?: Record<string, unknown> | null): string {
  const tool = typeof data?.tool === "string" ? data.tool : "";
  if (kind === "tool_called" && tool) return TOOL_LABEL[tool] ?? sentenceCase(tool);
  if (data?.outcome === "error" && FAILED_LABEL[kind]) return FAILED_LABEL[kind];
  return KIND_LABEL[kind] ?? sentenceCase(kind);
}

const STARTED: Record<string, (person: string) => string> = {
  inbound: (person) => `${person} called Gary.`,
  appointment: (person) => `Gary called ${person} about an appointment.`,
  reminder: (person) => `Gary called ${person} with a reminder.`,
  morning_briefing: (person) => `Gary called ${person} with the morning check-in.`,
};

export function callReason(started?: ActivityRow | null): string {
  return (started?.summary || "").replace(/ call started$/, "").trim() || "inbound";
}

export function callTitle(reason: string, person: string): string {
  const line = (STARTED[reason] ?? (() => "A call."))(person);
  return line.replace(/\.$/, "");
}

/** The browser-job summaries are written for the log; turn them into a sentence a family member can read. */
function browserJobBody(kind: string, summary: string): string {
  const m = summary.match(/^(\w+)(?: (done|failed|infeasible|cancelled))?:\s*(.*)$/s);
  const site = m ? SITE_NAME[m[1]] ?? sentenceCase(m[1]) : "the website";
  const status = m?.[2] ?? "";
  let text = (m ? m[3] : summary).replace(/^DONE:\s*/i, "").trim();
  if (kind === "browser_job_started") {
    text = text.split(/(?<=\.)\s/)[0];  // the first sentence is the request; the rest are instructions
    return `Opened ${site}. ${text}`;
  }
  if (status && status !== "done") return `Could not finish on ${site}. ${text}`;
  return `On ${site}: ${text}`;
}

export function eventBody(row: ActivityRow, person = "They"): string {
  const data = row.data ?? {};
  const summary = row.summary || "";
  if (row.kind === "tool_called" && typeof data.say === "string" && data.say) return data.say;
  if (row.kind === "call_started") return (STARTED[callReason(row)] ?? (() => "A call started."))(person);
  if (row.kind === "call_ended") return (typeof data.outcome === "string" && OUTCOME_LABEL[data.outcome]) || "The call finished.";
  if (row.kind.startsWith("browser_job")) return browserJobBody(row.kind, summary);
  if (row.kind === "approval_approved" || row.kind === "approval_denied") {
    const action = summary.replace(/^(Approved|Denied):\s*/, "").replaceAll("_", " ");
    return row.kind === "approval_approved" ? `You approved: ${action}.` : `You declined: ${action}.`;
  }
  return sentenceCase(summary);
}

export function tone(kind: string, outcome?: string | null): string {
  if (kind === "reminder_unconfirmed" || kind === "call_error" || outcome === "error" || outcome === "unconfirmed") return "attention";
  if (kind === "family_summary" || kind.startsWith("approval") || outcome === "summarized_to_family" || outcome === "transfer_skipped" || outcome === "needs_approval") return "note";
  if (kind.startsWith("browser_job")) return "backstage";
  return "quiet";
}

// ---- grouping the log into calls -------------------------------------------------------

export type CallGroup = {
  id: string;  // the call_started log row: unique even when the Twilio SID is not (console calls share one)
  sid: string;
  reason: string;
  started: ActivityRow;
  ended?: ActivityRow;
  events: ActivityRow[]; // everything that happened during the call, oldest first (call_started/ended excluded)
  startMs: number;
  endMs: number | null;
};

const AFTER_CALL_MS = 3 * 60 * 1000; // a booking that finishes shortly after the hangup still belongs to the call
const HIGHLIGHT_KINDS = new Set(["ride", "order", "service_booking", "bill_paid", "person_paid", "family_summary", "approval_requested",
  "reminder_confirmed", "reminder_unconfirmed", "scam_check", "service_search", "order_staged"]);

function sidOf(row: ActivityRow): string {
  const sid = row.data?.call_sid;
  return typeof sid === "string" ? sid : "";
}

/** Splits log rows into calls (with the events that happened during each) and loose events outside any call. */
export function groupCalls(rows: ActivityRow[]): { calls: CallGroup[]; loose: ActivityRow[] } {
  const asc = [...rows].sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at));
  const calls: CallGroup[] = [];
  const bySid = new Map<string, CallGroup>();
  const loose: ActivityRow[] = [];
  for (const row of asc) {
    const t = Date.parse(row.created_at);
    if (row.kind === "call_started") {
      const sid = sidOf(row) || row.id;
      const group: CallGroup = { id: row.id, sid, reason: callReason(row), started: row, events: [], startMs: t, endMs: null };
      calls.push(group);
      bySid.set(sid, group);
      continue;
    }
    const sid = sidOf(row);
    let group = sid ? bySid.get(sid) : undefined;
    if (!group && !sid) {
      const last = calls[calls.length - 1];
      if (last && t >= last.startMs && (last.endMs === null || t <= last.endMs + AFTER_CALL_MS)) group = last;
    }
    if (!group) {
      loose.push(row);
      continue;
    }
    if (row.kind === "call_ended") {
      group.ended = row;
      group.endMs = t;
    } else {
      group.events.push(row);
    }
  }
  return { calls, loose };
}

const BOOKED_LINE: Record<string, string> = { ride: "A ride was booked.", order: "An order was placed.", service_booking: "Home help was booked." };

export function callOutcome(group: CallGroup): string {
  // A booking that went through (even after the hangup) says more than the state at hangup did.
  const booked = [...group.events].reverse().find((e) => BOOKED_LINE[e.kind] && e.data?.outcome !== "error");
  if (booked) return BOOKED_LINE[booked.kind];
  if (group.events.some((e) => e.kind === "approval_denied")) return "Held for you, and you said no.";
  if (group.events.some((e) => e.kind === "approval_approved")) return "Held for you, and you said yes.";
  if (!group.ended) return "In progress";
  const outcome = group.ended.data?.outcome;
  return (typeof outcome === "string" && OUTCOME_LABEL[outcome]) || "The call finished.";
}

export function callHighlights(group: CallGroup, person: string, max = 2): string[] {
  return group.events
    .filter((e) => HIGHLIGHT_KINDS.has(e.kind))
    .slice(-max)
    .map((e) => eventBody(e, person));
}

export function durationLabel(startMs: number, endMs: number | null): string {
  if (endMs === null) return "still on the line";
  const mins = Math.max(1, Math.round((endMs - startMs) / 60000));
  return mins === 1 ? "about a minute" : `about ${mins} minutes`;
}
