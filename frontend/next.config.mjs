/** @type {import('next').NextConfig} */

// Where the Next.js server forwards same-origin API calls. Inside Docker this
// is the backend service; locally it is localhost. The browser never needs to
// know the backend's address - it calls /api/... on the same origin and these
// rewrites proxy to the API, so the whole app works behind one public URL.
const API_ORIGIN =
  process.env.API_BASE_URL_INTERNAL ??
  process.env.NEXT_PUBLIC_API_BASE_URL ??
  "http://localhost:8000";

const nextConfig = {
  reactStrictMode: true,
  // Emit a self-contained server bundle (.next/standalone) so the Docker
  // runtime image can ship just the traced dependencies.
  output: "standalone",
  env: {
    NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL ?? "",
  },
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` },
      { source: "/health", destination: `${API_ORIGIN}/health` },
    ];
  },
};

export default nextConfig;