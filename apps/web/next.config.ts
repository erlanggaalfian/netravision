import type { NextConfig } from "next";

// Static export: hasil build disajikan Apache sebagai DocumentRoot.
// Tanpa runtime Node di produksi.
const nextConfig: NextConfig = {
  output: "export",
  images: { unoptimized: true },
  trailingSlash: true,
};

export default nextConfig;
