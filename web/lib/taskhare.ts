import providers from "@/lib/mock-data/providers.json";

export type Tasker = {
  id: string;
  name: string;
  category: string;
  rating: number;
  price: number;
  next_slots: string[];
};

export const TASKERS = providers as Tasker[];

export const CATEGORIES: { id: string; label: string; words: string[] }[] = [
  { id: "plumber", label: "Plumbing", words: ["sink", "leak", "pipe", "toilet", "faucet", "drain", "water heater", "plumb"] },
  { id: "electrician", label: "Electrical", words: ["light", "outlet", "power", "breaker", "electric", "wiring", "switch"] },
  { id: "handyman", label: "Handyman", words: ["door", "shelf", "hang", "fix", "repair", "window", "fence", "handyman"] },
  { id: "cleaner", label: "House cleaning", words: ["clean", "cleaning", "tidy", "vacuum", "dust"] },
  { id: "yard", label: "Yard work", words: ["yard", "lawn", "mow", "leaves", "garden", "hedge"] },
  { id: "assembly", label: "Furniture assembly", words: ["assemble", "assembly", "furniture", "ikea", "crib", "desk"] },
];

export function categoryFor(text: string): string {
  const t = text.toLowerCase();
  const named = CATEGORIES.find((c) => c.id === t || c.label.toLowerCase() === t);
  if (named) return named.id;
  for (const category of CATEGORIES) {
    if (category.words.some((word) => t.includes(word))) return category.id;
  }
  return "handyman";
}

export function categoryLabel(id: string): string {
  return CATEGORIES.find((c) => c.id === id)?.label ?? id;
}

export function taskersFor(query: string): { category: string; taskers: Tasker[] } {
  const category = categoryFor(query);
  const taskers = TASKERS.filter((p) => p.category === category).sort((a, b) => b.rating - a.rating);
  return { category, taskers };
}

export function taskerById(id: string): Tasker | undefined {
  return TASKERS.find((p) => p.id === id);
}

export function slotLabel(iso: string): string {
  const date = new Date(iso);
  const day = date.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
  const time = date.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }).replace(":00", "");
  return `${day} at ${time}`;
}
