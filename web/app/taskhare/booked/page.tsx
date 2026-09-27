import Link from "next/link";

export const metadata = { title: "You're booked · TaskHare" };

export default async function Booked({
  searchParams,
}: {
  searchParams: Promise<{ provider?: string; when?: string; price?: string; category?: string }>;
}) {
  const { provider = "Your tasker", when = "the time you chose", price = "", category = "" } = await searchParams;
  return (
    <div className="hare">
      <header className="hare-bar">
        <Link href="/taskhare" className="hare-brand">TaskHare</Link>
      </header>
      <h1>You&apos;re booked</h1>
      <p>
        {`${provider} will come ${when}${category ? ` for ${category.toLowerCase()}` : ""}.`}
        {price ? ` The visit is $${price}.` : ""}
      </p>
      <p>They will come to the home. No payment is taken on this page.</p>
    </div>
  );
}
