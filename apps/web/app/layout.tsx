import type { Metadata } from "next";
import { JetBrains_Mono } from "next/font/google";
import "./globals.css";

const mono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: "MeaningGrid",
  description: "Context engine for agents. One context grid. Every harness.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={mono.variable} suppressHydrationWarning>
      {/* suppressHydrationWarning: browser extensions (ColorZilla, Grammarly,
          Dark Reader, …) inject attributes on <html>/<body> before React
          hydrates, which would otherwise log a spurious mismatch warning. */}
      <body suppressHydrationWarning>{children}</body>
    </html>
  );
}
