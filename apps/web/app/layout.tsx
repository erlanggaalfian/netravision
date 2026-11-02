import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "../lib/auth";

export const metadata: Metadata = {
  title: "NetraVision",
  description: "Sistem pemantauan CCTV",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="id">
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
