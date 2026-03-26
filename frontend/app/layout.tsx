import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "KATHA AI",
  description: "Architecture-aware design intelligence platform",
};

function Nav() {
  return (
    <nav className="border-b border-black/5 bg-white/40 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-3">
        <Link href="/" className="font-display text-xl font-bold text-ink">
          KATHA<span className="text-clay">.AI</span>
        </Link>
        <div className="flex items-center gap-6 text-sm">
          <Link href="/dashboard" className="text-ink/60 transition-colors hover:text-ink">
            Dashboard
          </Link>
          <Link
            href="/project/new"
            className="rounded-lg bg-ink px-4 py-1.5 text-white transition-colors hover:bg-ink/90"
          >
            New Project
          </Link>
        </div>
      </div>
    </nav>
  );
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <Nav />
        {children}
      </body>
    </html>
  );
}
