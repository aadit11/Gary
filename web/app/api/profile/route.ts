import { NextResponse } from "next/server";
import { DEMO_USER_ID, supabase } from "@/lib/supabase";
import { loadProfile, saveProfile, TIMEZONES, type CareProfile } from "@/lib/profile";

export const dynamic = "force-dynamic";

export async function GET() {
  const client = supabase();
  let person = { name: "", phone: "", timezone: "America/New_York", address: "" };
  if (client && DEMO_USER_ID) {
    const { data } = await client.from("users").select("name,phone,timezone,address").eq("id", DEMO_USER_ID).limit(1);
    if (data?.[0]) person = data[0] as typeof person;
  }
  return NextResponse.json({ profile: await loadProfile(), person });
}

export async function PUT(request: Request) {
  const body = await request.json().catch(() => null);
  if (!body?.profile) return NextResponse.json({ error: "profile required" }, { status: 400 });
  const error = await saveProfile(body.profile as CareProfile);
  if (error) return NextResponse.json({ error }, { status: 500 });
  const timezone = body.timezone as string | undefined;
  if (timezone && TIMEZONES.includes(timezone)) {
    const client = supabase();
    if (client && DEMO_USER_ID) {
      const result = await client.from("users").update({ timezone }).eq("id", DEMO_USER_ID);
      if (result.error) return NextResponse.json({ error: result.error.message }, { status: 500 });
    }
  }
  return NextResponse.json({ ok: true });
}
