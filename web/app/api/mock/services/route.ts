// Services mock: GET /search?category=, POST /bookings -> {booking_id, provider, time}
import { NextResponse } from "next/server";

export async function GET() {
  return NextResponse.json({});
}

export async function POST() {
  return NextResponse.json({});
}
