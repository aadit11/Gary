// GET /api/mock/services/search?category=plumber  (or ?q=my sink is leaking) -> {category, providers}
import { NextResponse } from "next/server";
import { categoryFor, TASKERS } from "@/lib/taskhare";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const raw = url.searchParams.get("category") || url.searchParams.get("q") || "";
  const category = categoryFor(raw);
  const matches = TASKERS.filter((p) => p.category === category).sort((a, b) => b.rating - a.rating).slice(0, 3);
  return NextResponse.json({ category, providers: matches });
}
