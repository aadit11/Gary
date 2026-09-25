// Food mock: GET /search?q=, POST /orders -> {order_id, eta_minutes, total}
import { NextResponse } from "next/server";

export async function GET() {
  return NextResponse.json({});
}

export async function POST() {
  return NextResponse.json({});
}
