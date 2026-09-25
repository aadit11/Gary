import providers from "@/lib/mock-data/providers.json";

export default function MockServices() {
  return (
    <>
      <h1>Mock home services</h1>
      <p className="muted">GET /api/mock/services/search?category=plumber, POST /api/mock/services/bookings</p>
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
