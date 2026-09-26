import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Home is the grid view for now; the dashboard page under (dashboard)/page.tsx is kept.
  async redirects() {
    return [{ source: "/", destination: "/grid", permanent: false }];
  },
};

export default nextConfig;
