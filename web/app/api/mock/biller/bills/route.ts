// GET /api/mock/biller/bills -> list of bills the demo user owes (static).
import { NextResponse } from "next/server";
import bills from "@/lib/mock-data/bills.json";

export const dynamic = "force-dynamic";

export async function GET() {
  return NextResponse.json({ bills });
}
