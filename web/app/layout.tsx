import SiteHeader from "@/components/SiteHeader";
import { careFirstName } from "@/lib/care";
import "./globals.css";

export const metadata = { title: "Gary", description: "A quiet desk for the people who look after someone Gary calls" };

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const name = await careFirstName();
  return (
    <html lang="en">
      <body>
        <SiteHeader name={name} />
        <main>{children}</main>
      </body>
    </html>
  );
}
