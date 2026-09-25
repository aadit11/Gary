// GET /api/mock/services/search?category=plumber  (or ?q=my sink is leaking) -> {category, providers}
import { NextResponse } from "next/server";
import providers from "@/lib/mock-data/providers.json";

export const dynamic = "force-dynamic";

const KEYWORDS: Record<string, string[]> = {
  plumber: ["sink", "leak", "pipe", "toilet", "faucet", "drain", "water heater", "plumb"],
  electrician: ["light", "outlet", "power", "breaker", "electric", "wiring", "switch"],
  handyman: ["door", "shelf", "hang", "fix", "repair", "window", "fence", "handyman"],
  cleaner: ["clean", "cleaning", "tidy", "vacuum", "dust"],
};

export function categoryFor(text: string): string {
  const t = text.toLowerCase();
  if (t in KEYWORDS) return t;
  for (const [cat, words] of Object.entries(KEYWORDS)) {
    if (words.some((w) => t.includes(w))) return cat;
  }
  return "handyman";
}

export async function GET(request: Request) {
  const url = new URL(request.url);
  const raw = url.searchParams.get("category") || url.searchParams.get("q") || "";
  const category = categoryFor(raw);
  const matches = providers.filter((p) => p.category === category).sort((a, b) => b.rating - a.rating).slice(0, 3);
  return NextResponse.json({ category, providers: matches });
}
