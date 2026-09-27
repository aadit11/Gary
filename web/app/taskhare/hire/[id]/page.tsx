import Link from "next/link";
import { notFound } from "next/navigation";
import { categoryLabel, slotLabel, taskerById } from "@/lib/taskhare";

export const metadata = { title: "Choose a time · TaskHare" };

export default async function HireTasker({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ q?: string; slot?: string }>;
}) {
  const { id } = await params;
  const { q = "", slot = "" } = await searchParams;
  const tasker = taskerById(id);
  if (!tasker) notFound();
  const chosen = tasker.next_slots.includes(slot) ? slot : "";

  return (
    <div className="hare">
      <header className="hare-bar">
        <Link href="/taskhare" className="hare-brand">TaskHare</Link>
        <p>{categoryLabel(tasker.category)}</p>
      </header>
      <h1>{tasker.name}</h1>
      <p>{tasker.rating} stars · ${tasker.price} for the visit, at the home.</p>
      <h2>Choose a time</h2>
      <ul className="hare-times">
        {tasker.next_slots.map((iso) => (
          <li key={iso}>
            <Link
              href={`/taskhare/hire/${tasker.id}?q=${encodeURIComponent(q)}&slot=${encodeURIComponent(iso)}`}
              className={iso === chosen ? "on" : ""}
            >
              {slotLabel(iso)}
            </Link>
          </li>
        ))}
      </ul>
      {chosen && (
        <Link
          className="hare-confirm"
          href={`/taskhare/booked?provider=${encodeURIComponent(tasker.name)}&when=${encodeURIComponent(slotLabel(chosen))}&price=${tasker.price}&category=${encodeURIComponent(categoryLabel(tasker.category))}`}
        >
          Confirm this visit
        </Link>
      )}
    </div>
  );
}
