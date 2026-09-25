// POST /api/mock/services/bookings {provider_id, time, problem} -> {booking_id, provider, time, price}
import { NextResponse } from "next/server";
import providers from "@/lib/mock-data/providers.json";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const body = await request.json().catch(() => ({}));
  const provider = providers.find((p) => p.id === body.provider_id || p.name === body.provider);
  if (!provider) {
    return NextResponse.json({ error: "unknown provider" }, { status: 404 });
  }
  const time = body.time || provider.next_slots[0];
  return NextResponse.json({
    booking_id: "BK-" + Math.random().toString(36).slice(2, 8).toUpperCase(),
    provider: provider.name,
    category: provider.category,
    time,
    price: provider.price,
    problem: body.problem ?? "",
  });
}
