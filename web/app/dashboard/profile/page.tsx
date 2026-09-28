import ProfileEditor from "@/components/ProfileEditor";
import { careFirstName } from "@/lib/care";
import { loadContacts } from "@/lib/contacts";
import { loadProfile } from "@/lib/profile";
import { DEMO_USER_ID, supabase } from "@/lib/supabase";

export const dynamic = "force-dynamic";

export default async function ProfilePage({ searchParams }: { searchParams: Promise<{ tab?: string }> }) {
  const name = await careFirstName();
  const personName = name === "them" ? "your person" : name;
  const params = await searchParams;
  const tab = params.tab === "expenses" || params.tab === "connections" || params.tab === "diet" || params.tab === "settings" ? params.tab : "settings";
  const client = supabase();
  let person = { name: "", phone: "", timezone: "America/New_York", address: "" };
  if (client && DEMO_USER_ID) {
    const { data } = await client.from("users").select("name,phone,timezone,address").eq("id", DEMO_USER_ID).limit(1);
    if (data?.[0]) person = data[0] as typeof person;
  }
  const [profile, contacts] = await Promise.all([loadProfile(), loadContacts()]);
  return (
    <>
      <p className="eyebrow">Profile</p>
      <h1>{personName}&apos;s care profile</h1>
      <p className="lede">Settings, the bills you want reminded about, saved places, and food notes. Nothing here asks for a card, a password, or a bank login.</p>
      <ProfileEditor initial={profile} contacts={contacts} person={person} startTab={tab} />
    </>
  );
}
