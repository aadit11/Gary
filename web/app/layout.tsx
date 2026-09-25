import Link from "next/link";
import "./globals.css";

export const metadata = { title: "Gary", description: "Family dashboard and mock services for the Gary voice assistant" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <nav>
          <span className="brand">Gary</span>
          <Link href="/dashboard">Activity</Link>
          <Link href="/dashboard/reminders">Reminders</Link>
          <Link href="/dashboard/approvals">Approvals</Link>
          <Link href="/mock/biller">Mock biller</Link>
          <Link href="/mock/services">Mock home services</Link>
        </nav>
        <main>{children}</main>
      </body>
    </html>
  );
}
