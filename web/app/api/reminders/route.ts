// POST /api/reminders {message, time_of_day, recurrence} -> inserts a reminder for the demo user.
import { NextResponse } from "next/server";
import { rememberWeekday } from "@/lib/profile";
import { supabase, DEMO_USER_ID } from "@/lib/supabase";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const body = await request.json().catch(() => ({}));
  if (!body.message || !body.time_of_day) {
    return NextResponse.json({ error: "message and time_of_day required" }, { status: 400 });
  }
  const client = supabase();
  if (!client) return NextResponse.json({ error: "Supabase not configured" }, { status: 503 });
  const recurrence = body.recurrence || "daily";
  const weekday = Number(body.weekday);
  if (recurrence === "weekly" && (!Number.isInteger(weekday) || weekday < 0 || weekday > 6)) {
    return NextResponse.json({ error: "Choose the day of the week for this call." }, { status: 400 });
  }
  const { data, error } = await client
    .from("reminders")
    .insert({ user_id: DEMO_USER_ID, message: body.message, time_of_day: body.time_of_day, recurrence })
    .select()
    .single();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  if (recurrence === "weekly") {
    const saved = await rememberWeekday(data.id, weekday);
    if (saved) return NextResponse.json({ error: saved }, { status: 500 });
  }
  return NextResponse.json(data);
}
