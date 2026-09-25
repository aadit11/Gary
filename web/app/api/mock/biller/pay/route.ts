// POST /api/mock/biller/pay {bill_id|payee, amount} -> {confirmation_id, paid_at}
import { NextResponse } from "next/server";
import bills from "@/lib/mock-data/bills.json";

export const dynamic = "force-dynamic";

function confirmationId() {
  return "CONF-" + Math.random().toString(36).slice(2, 8).toUpperCase();
}

export async function POST(request: Request) {
  const body = await request.json().catch(() => ({}));
  const bill = bills.find((b) => b.id === body.bill_id || b.payee === body.payee);
  const amount = Number(body.amount ?? bill?.amount ?? 0);
  if (!amount || amount <= 0) {
    return NextResponse.json({ error: "amount required" }, { status: 400 });
  }
  return NextResponse.json({
    confirmation_id: confirmationId(),
    payee: bill?.payee ?? body.payee ?? "unknown",
    amount,
    paid_at: new Date().toISOString(),
  });
}
