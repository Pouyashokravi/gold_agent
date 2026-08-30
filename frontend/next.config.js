const path = require("path");

/** @type {import('next').NextConfig} */
const nextConfig = {
  webpack: (config) => {
    config.resolve.alias["@"] = path.resolve(__dirname);
    return config;
  },
  async rewrites() {
    if (process.env.NODE_ENV !== "development") {
      return [];
    }
    return [
      { source: "/api/:path*", destination: "http://localhost:8000/api/:path*" },
    ];
  },
};

module.exports = nextConfig;
