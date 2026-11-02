import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "../lib/auth";
import { SWRegister } from "../components/SWRegister";

export const metadata: Metadata = {
  title: "NetraVision",
  description: "Sistem pemantauan CCTV",
  manifest: "/manifest.webmanifest",
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
        <SWRegister />
      </body>
    </html>
  );
}
