import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "MeaningGrid — Sources",
  description: "Connect sources and watch them flow into the context engine.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="border-b border-neutral-800">
          <div className="mx-auto flex max-w-5xl items-center gap-3 px-6 py-4">
            <Link href="/sources" className="text-lg font-semibold tracking-tight">
              MeaningGrid
            </Link>
            <span className="text-sm text-neutral-500">Context Engine — Sources</span>
          </div>
        </header>
        <main className="mx-auto max-w-5xl px-6 py-8">{children}</main>
      </body>
    </html>
  );
}
