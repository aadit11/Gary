"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const CARE = [
  { href: "/dashboard", label: "What happened" },
  { href: "/dashboard/reminders", label: "Scheduled calls" },
  { href: "/dashboard/approvals", label: "Decisions" },
  { href: "/dashboard/profile", label: "Profile" },
];

function current(href: string, path: string) {
  if (href === "/dashboard") return path === "/dashboard";
  if (href === "/dashboard/profile") return path.startsWith("/dashboard/profile") || path.startsWith("/dashboard/onboarding");
  return path === href || path.startsWith(`${href}/`);
}

export default function SiteHeader({ name }: { name: string }) {
  const path = usePathname() || "/";
  const inCare = path.startsWith("/dashboard");
  return (
    <header className="site">
      <div className="site-bar">
        <Link href={inCare ? "/dashboard" : "/"} className="brand">Gary</Link>
        <p className="site-for">{inCare ? `Caring for ${name}` : "For caregivers"}</p>
        <nav>
          {inCare ? (
            CARE.map((item) => (
              <Link key={item.href} href={item.href} className={current(item.href, path) ? "on" : ""}>
                {item.label}
              </Link>
            ))
          ) : (
            <>
              <Link href="/dashboard/onboarding?fresh=1">Get started</Link>
              <Link href="/dashboard">Sign in</Link>
              <Link href="/mock/biller" className="quiet">Biller demo</Link>
              <Link href="/mock/services" className="quiet">Services demo</Link>
            </>
          )}
        </nav>
      </div>
    </header>
  );
}
