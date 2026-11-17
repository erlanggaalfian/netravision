import type { NextConfig } from "next";

// Static export: hasil build disajikan Apache sebagai DocumentRoot.
// Tanpa runtime Node di produksi.
const CSP_BASE =
  "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; media-src 'self' blob:; connect-src 'self' wss:; font-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'";
// F6.2: CSP yang sama dengan vhost Apache (deploy/apache/
// netra.mamura.net.id.conf). Header di sini hanya berlaku saat
// `next dev` / `next start` (preview); hasil `output: "export"` yang
// disajikan statis oleh Apache TIDAK membawa header dari sini, jadi
// Apache tetap lapisan yang menentukan di produksi.
// script-src 'unsafe-inline' wajib: HTML static export mengandung
// inline script (bootstrap tema + data flight Next); nonce butuh
// server Node. /embed/ boleh dibingkai domain mana pun (kontrak
// embed v2.0, domain lock ditegakkan per API-key di backend).
const CSP_STRICT = `${CSP_BASE}; frame-ancestors 'self'`;
const CSP_EMBED = `${CSP_BASE}; frame-ancestors *`;

const nextConfig: NextConfig = {
  output: "export",
  images: { unoptimized: true },
  trailingSlash: true,
  async headers() {
    return [
      {
        source: "/embed/:path*",
        headers: [
          { key: "Content-Security-Policy", value: CSP_EMBED },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=()",
          },
        ],
      },
      {
        source: "/:path*",
        headers: [
          { key: "Content-Security-Policy", value: CSP_STRICT },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=()",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
