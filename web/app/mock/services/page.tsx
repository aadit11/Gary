import Link from "next/link";
import providers from "@/lib/mock-data/providers.json";

export default function MockServices() {
  return (
    <>
      <h1>Home services</h1>
      <p className="muted">
        These taskers are listed on <Link href="/taskhare">TaskHare</Link>. Gary searches and books there in a browser, the same way a person would. There is no API.
      </p>
      <div className="cards">
        {providers.map((p) => (
          <div className="card" key={p.id}>
            <h3>{p.name}</h3>
            <div className="muted">{p.category} · {p.rating} stars · ${p.price} visit</div>
            <div style={{ marginTop: "0.4rem" }}>Next: {p.next_slots.slice(0, 2).map((s) => new Date(s).toLocaleString("en-US", { weekday: "short", hour: "numeric" })).join(", ")}</div>
          </div>
        ))}
      </div>
    </>
  );
}
