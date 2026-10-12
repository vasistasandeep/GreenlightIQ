/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Emit a self-contained server bundle (.next/standalone) so the Docker
  // runtime image can ship just the traced dependencies instead of the whole
  // node_modules tree (see frontend/Dockerfile). Harmless for `next dev`.
  output: "standalone",
  env: {
    // Base URL for the FastAPI backend; overridden per environment.
    NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000",
  },
};

export default nextConfig;
