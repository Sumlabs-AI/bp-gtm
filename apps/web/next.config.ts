import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async redirects() {
    // The GTM page is home; the old list (/leads) and Need map (/need) live there now.
    return [
      { source: "/", destination: "/gtm", permanent: false },
      { source: "/leads", destination: "/gtm", permanent: false },
      { source: "/need", destination: "/gtm", permanent: false },
    ];
  },
};

export default nextConfig;
