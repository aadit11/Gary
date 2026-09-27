// POST /api/approvals/:id {approved: boolean}
// Forwards to the backend, which runs the action and tells the caller mid-call, exactly like a
// YES/NO text. If the backend is unreachable, the approval row is updated directly so the demo
// dashboard still works.
import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";

export const dynamic = "force-dynamic";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = await request.json().catch(() => ({}));
  const approved = Boolean(body.approved);
  const backend = (process.env.BACKEND_URL || "http://localhost:8000").replace(/\/$/, "");
  try {
    const res = await fetch(`${backend}/webhooks/approvals/${id}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved }),
      signal: AbortSignal.timeout(8000),
    });
    if (res.ok) return NextResponse.json({ ok: true, ...(await res.json()) });
  } catch {
    // fall through to the direct update
  }
  const client = supabase();
  if (!client) return NextResponse.json({ error: "Backend unreachable and Supabase not configured" }, { status: 503 });
  const { error } = await client
    .from("approvals")
    .update({ status: approved ? "approved" : "denied", resolved_at: new Date().toISOString() })
    .eq("id", id)
    .eq("status", "pending");
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ ok: true, fallback: true, message: approved ? "Approved." : "Denied." });
}
