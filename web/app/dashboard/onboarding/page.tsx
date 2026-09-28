import Onboarding from "@/components/Onboarding";
import { careFirstName } from "@/lib/care";
import { loadContacts } from "@/lib/contacts";
import { loadProfile } from "@/lib/profile";

export const dynamic = "force-dynamic";

export default async function OnboardingPage({ searchParams }: { searchParams: Promise<{ fresh?: string; start?: string }> }) {
  const [saved, contacts, name, params] = await Promise.all([loadProfile(), loadContacts(), careFirstName(), searchParams]);
  // ?fresh=1 (the landing page's Get started) always shows the flow from the start.
  const profile = params.fresh
    ? { ...saved, connectors: { ...saved.connectors, doordash: { ...saved.connectors.doordash, connected: false }, uber: { ...saved.connectors.uber, connected: false }, groceries: { ...saved.connectors.groceries, connected: false } } }
    : saved;
  const person = name === "them" ? "your person" : name;
  return <Onboarding initial={profile} contacts={contacts} person={person} start={params.start} />;
}
