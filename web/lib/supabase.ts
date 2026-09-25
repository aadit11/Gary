// Supabase client for the dashboard (publishable key). Returns null when not configured so pages
// can render an empty state instead of crashing.
import { createClient, SupabaseClient } from "@supabase/supabase-js";

export const DEMO_USER_ID = process.env.NEXT_PUBLIC_DEMO_USER_ID || "";

export function supabase(): SupabaseClient | null {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !key) return null;
  return createClient(url, key, { auth: { persistSession: false } });
}

export function fmtTime(iso: string | null | undefined) {
  if (!iso) return "";
  return new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}
