import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // --- ▼▼▼ 在这里添加图片配置 ▼▼▼ ---
  images: {
    remotePatterns: [
      {
        protocol: 'http',
        hostname: 'localhost',
        port: '8000',
        pathname: '/media/**', // 仅允许 /media/ 路径下的图片，更安全
      },
    ],
  },
  // --- ▲▲▲ 添加结束 ▲▲▲ ---

  async headers() {
    return [
      {
        source: "/api/:path*",
        headers: [
          {
            key: "Access-Control-Allow-Origin",
            value: "*", // 允许所有来源，在生产环境中应该指定具体域名
          },
          {
            key: "Access-Control-Allow-Methods",
            value: "GET, POST, PUT, DELETE, OPTIONS",
          },
          {
            key: "Access-Control-Allow-Headers",
            value: "Content-Type, Authorization",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
