import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async redirects() {
    // The GTM page is home; the old list (/leads) and Need map (/need) live there now.
    return [
      { source: "/", destination: "/gtm", permanent: false },
      { source: "/leads", destination: "/gtm", permanent: false },
      // The lead drawer on the GTM page has everything the old full page had.
      { source: "/leads/:id", destination: "/gtm?lead=:id", permanent: false },
      { source: "/need", destination: "/gtm", permanent: false },
    ];
  },
};

export default nextConfig;
