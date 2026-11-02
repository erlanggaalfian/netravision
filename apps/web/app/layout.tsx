import type { Metadata } from "next";
import "./globals.css";

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
      <body className="bg-neutral-100 text-neutral-900 dark:bg-neutral-950 dark:text-neutral-100">
        {children}
      </body>
    </html>
  );
}
