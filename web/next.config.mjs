// Reads the repo-root .env so one file configures backend and web. Only NEXT_PUBLIC_* values
// are exposed to the browser; the anon (publishable) key is safe there, the service key is not.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

function loadRootEnv() {
  try {
    const text = readFileSync(resolve(process.cwd(), "../.env"), "utf8");
    const out = {};
    for (const line of text.split("\n")) {
      const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*(#.*)?$/);
      if (m) out[m[1]] = m[2];
    }
    return out;
  } catch {
    return {};
  }
}
const root = loadRootEnv();

/** @type {import('next').NextConfig} */
const nextConfig = {
  allowedDevOrigins: ["127.0.0.1"],
  env: {
    NEXT_PUBLIC_SUPABASE_URL: process.env.NEXT_PUBLIC_SUPABASE_URL || root.SUPABASE_URL || "",
    NEXT_PUBLIC_SUPABASE_ANON_KEY: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || root.SUPABASE_ANON_KEY || "",
    NEXT_PUBLIC_DEMO_USER_ID: process.env.NEXT_PUBLIC_DEMO_USER_ID || root.DEMO_USER_ID || "",
    BACKEND_URL: process.env.BACKEND_URL || root.BACKEND_URL || "http://localhost:8000",  // local backend; PUBLIC_BASE_URL is for Twilio
  },
};
export default nextConfig;
