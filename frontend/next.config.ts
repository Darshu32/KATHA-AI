import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Hide the Next.js dev-tools indicator (the floating "N" bottom-left). It
  // overlaps the app's terminal bar in dev and never appears in a prod build.
  devIndicators: false,
};

export default nextConfig;
