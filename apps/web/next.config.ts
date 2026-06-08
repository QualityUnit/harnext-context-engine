import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emit a self-contained server bundle (.next/standalone) for a slim runtime image.
  output: "standalone",
};

export default nextConfig;
