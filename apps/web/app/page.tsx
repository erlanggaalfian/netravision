"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "../lib/auth";

// Static export tidak mendukung redirect() server-side, pakai client redirect.
// Pengguna yang sudah login langsung ke /live, bukan mampir ke /login dulu.
export default function Home() {
  const router = useRouter();
  const { user, loading } = useAuth();
  useEffect(() => {
    if (loading) return;
    router.replace(user ? "/live" : "/login");
  }, [loading, user, router]);
  return null;
}
