import type { NextConfig } from "next";

// The browser only ever talks to this origin; /api is proxied to FastAPI, so no CORS and no third-party origin.
const backend = process.env.TRIALMATCH_API_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  // A grounded question waits on the model. The rewrite proxy otherwise closes at 30s.
  experimental: { proxyTimeout: 180_000 },
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
};

export default nextConfig;
