/** @type {import('next').NextConfig} */
const API_BASE = process.env.BACKEND_ORIGIN || "http://localhost:8000";

const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    // Proxy REST calls to FastAPI. SSE is hit directly via NEXT_PUBLIC_API_BASE
    // (see lib/api.js) to avoid proxy buffering.
    return [{ source: "/api/:path*", destination: `${API_BASE}/api/:path*` }];
  },
};

export default nextConfig;
