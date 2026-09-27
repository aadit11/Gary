import Onboarding from "@/components/Onboarding";
import { loadProfile } from "@/lib/profile";

export const dynamic = "force-dynamic";

export default async function OnboardingPage() {
  const profile = await loadProfile();
  return (
    <>
      <section className="hero">
        <div>
          <p className="eyebrow">Setup</p>
          <h1>A few things Gary should know</h1>
          <p className="lede">Diet, food, rides, groceries, and the bills you want a reminder for. You can change any of this later in the profile.</p>
        </div>
        <img src="/care-morning.png" alt="Soft morning light on a wooden table, with tea and a small sprig of leaves" />
      </section>
      <Onboarding initial={profile} />
    </>
  );
}
