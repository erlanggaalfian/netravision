import type { Metadata, Viewport } from "next";
import { Plus_Jakarta_Sans } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "../lib/auth";
import { ThemeProvider } from "../hooks/useTheme";
import { SWRegister } from "../components/SWRegister";

const jakarta = Plus_Jakarta_Sans({
  subsets: ["latin"],
  variable: "--font-jakarta",
  display: "swap",
});

export const metadata: Metadata = {
  title: "NetraVision",
  description: "Sistem pemantauan CCTV",
  manifest: "/manifest.webmanifest",
  icons: { icon: "/favicon.ico", apple: "/icons/icon.svg" },
};

/* WAJIB untuk mobile: tanpa ini browser memakai layout viewport ~980px,
   breakpoint md: ikut aktif di HP, dan halaman terlihat ter-zoom. */
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

/* Menetapkan data-theme sebelum paint pertama (tanpa kedip):
   preferensi tersimpan > prefers-color-scheme > gelap. */
const THEME_SCRIPT = `(function(){try{var t=localStorage.getItem('nv-theme');if(t!=='dark'&&t!=='light'){t=window.matchMedia('(prefers-color-scheme: light)').matches?'light':'dark'}document.documentElement.setAttribute('data-theme',t)}catch(e){document.documentElement.setAttribute('data-theme','dark')}})();`;

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="id" data-theme="dark" className={jakarta.variable}>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body>
        <ThemeProvider>
          <AuthProvider>{children}</AuthProvider>
        </ThemeProvider>
        <SWRegister />
      </body>
    </html>
  );
}
