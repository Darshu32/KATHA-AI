import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "KATHA AI",
  description: "Architecture Knowledge Intelligence Platform",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
