import type { NextConfig } from "next";

const backendOrigin = process.env.BACKEND_ORIGIN || "http://localhost:8000";

const nextConfig: NextConfig = {  
  skipTrailingSlashRedirect: true,
  images: {
    remotePatterns: [
      { protocol: 'http', hostname: 'localhost', port: '8000', pathname: '/media/**' },
      { protocol: 'http', hostname: '127.0.0.1', port: '8000', pathname: '/media/**' },
    ],
  },

  async rewrites() {
    return [
      { source: "/api", destination: `${backendOrigin}/api/` },
      { source: "/api/", destination: `${backendOrigin}/api/` },
      {
        source: "/api/:path*/",
        destination: `${backendOrigin}/api/:path*/`,
      },
      {
        source: "/api/:path*",
        destination: `${backendOrigin}/api/:path*/`,
      },
      { source: "/media", destination: `${backendOrigin}/media/` },
      { source: "/media/", destination: `${backendOrigin}/media/` },
      { source: "/media/:path*/", destination: `${backendOrigin}/media/:path*/` },
      { source: "/media/:path*", destination: `${backendOrigin}/media/:path*/` }
    ];
  },
};

export default nextConfig;
