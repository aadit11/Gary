import { NextResponse } from "next/server";
import { DEMO_USER_ID, supabase } from "@/lib/supabase";
import { loadProfile, saveProfile, TIMEZONES, type CareProfile } from "@/lib/profile";
import { loadContacts, requestWelcome, saveContacts, validateContacts, type Contacts, type Welcome } from "@/lib/contacts";

export const dynamic = "force-dynamic";

export async function GET() {
  const client = supabase();
  let person = { name: "", phone: "", timezone: "America/New_York", address: "" };
  if (client && DEMO_USER_ID) {
    const { data } = await client.from("users").select("name,phone,timezone,address").eq("id", DEMO_USER_ID).limit(1);
    if (data?.[0]) person = data[0] as typeof person;
  }
  return NextResponse.json({ profile: await loadProfile(), person, contacts: await loadContacts() });
}

// PUT {profile?, timezone?, contacts?, welcome?}
// contacts = {person: {name, phone}, caregiver: {name, relationship, phone}} writes users and the
// approver family_contacts row. welcome: true (onboarding) asks the backend to text the caregiver;
// a changed caregiver phone does the same. Sending the hello never fails the save.
export async function PUT(request: Request) {
  const body = await request.json().catch(() => null);
  if (!body || (!body.profile && !body.timezone && !body.contacts)) {
    return NextResponse.json({ error: "nothing to save" }, { status: 400 });
  }
  if (body.profile) {
    const error = await saveProfile(body.profile as CareProfile);
    if (error) return NextResponse.json({ error }, { status: 500 });
  }
  const timezone = body.timezone as string | undefined;
  if (timezone && TIMEZONES.includes(timezone)) {
    const client = supabase();
    if (client && DEMO_USER_ID) {
      const result = await client.from("users").update({ timezone }).eq("id", DEMO_USER_ID);
      if (result.error) return NextResponse.json({ error: result.error.message }, { status: 500 });
    }
  }
  let contacts: Contacts | undefined;
  let welcome: Welcome | undefined;
  if (body.contacts) {
    const check = validateContacts(body.contacts);
    if (!check.ok) return NextResponse.json({ error: check.error, field: check.field }, { status: 400 });
    const saved = await saveContacts(check.value);
    if ("error" in saved) return NextResponse.json({ error: saved.error, field: saved.field }, { status: saved.status });
    contacts = saved.contacts;
    if (body.welcome === true || saved.caregiverPhoneChanged) welcome = await requestWelcome();
  }
  return NextResponse.json({ ok: true, contacts, welcome });
}
