import Onboarding from "@/components/Onboarding";
import { careFirstName } from "@/lib/care";
import { loadProfile } from "@/lib/profile";

export const dynamic = "force-dynamic";

export default async function OnboardingPage({ searchParams }: { searchParams: Promise<{ fresh?: string; start?: string }> }) {
  const [saved, name, params] = await Promise.all([loadProfile(), careFirstName(), searchParams]);
  // ?fresh=1 (the landing page's Get started) always shows the connect flow from the start.
  const profile = params.fresh
    ? { ...saved, connectors: { ...saved.connectors, doordash: { ...saved.connectors.doordash, connected: false }, uber: { ...saved.connectors.uber, connected: false }, groceries: { ...saved.connectors.groceries, connected: false } } }
    : saved;
  const person = name === "them" ? "your person" : name;
  return (
    <>
      <div style={{ textAlign: "center", maxWidth: "36rem", margin: "0 auto 1rem" }}>
        <p className="eyebrow">Connect apps</p>
        <h1>Connect the apps Gary will use for {person}</h1>
        <p className="lede">One at a time. Gary never asks for a password or a card.</p>
      </div>
      <Onboarding initial={profile} person={person} start={params.start} />
    </>
  );
}
