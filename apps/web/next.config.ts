import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async redirects() {
    return [{ source: "/", destination: "/gtm", permanent: false }];
  },
};

export default nextConfig;
