import Link from "next/link";
import { CATEGORIES, categoryLabel, slotLabel, taskersFor } from "@/lib/taskhare";

export const metadata = { title: "TaskHare" };

export default async function TaskHareHome({ searchParams }: { searchParams: Promise<{ q?: string }> }) {
  const query = ((await searchParams).q || "").trim();
  const found = query ? taskersFor(query) : null;

  return (
    <div className="hare">
      <header className="hare-bar">
        <Link href="/taskhare" className="hare-brand">TaskHare</Link>
        <p>Household help, booked for the home.</p>
      </header>

      <form className="hare-search" action="/taskhare" method="get">
        <label htmlFor="job">Describe the job</label>
        <div>
          <input id="job" name="q" defaultValue={query} placeholder="My sink is leaking" aria-label="Describe the job" />
          <button type="submit">Search</button>
        </div>
      </form>

      <nav className="hare-cats" aria-label="Job types">
        {CATEGORIES.map((category) => (
          <Link key={category.id} href={`/taskhare?q=${encodeURIComponent(category.label)}`}>
            {category.label}
          </Link>
        ))}
      </nav>

      {found && (
        <section>
          <h1>{categoryLabel(found.category)}</h1>
          {found.taskers.length === 0 ? (
            <p>No taskers for that yet. Try plumbing, electrical, handyman, or house cleaning.</p>
          ) : (
            <ul className="hare-list">
              {found.taskers.map((tasker) => (
                <li key={tasker.id}>
                  <h2>{tasker.name}</h2>
                  <p>{tasker.rating} stars · ${tasker.price} visit · next {slotLabel(tasker.next_slots[0])}</p>
                  <Link className="hare-choose" href={`/taskhare/hire/${tasker.id}?q=${encodeURIComponent(query)}`}>
                    Choose {tasker.name}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}
