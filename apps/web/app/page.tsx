"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

// Static export tidak mendukung redirect() server-side, pakai client redirect.
export default function Home() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/login");
  }, [router]);
  return null;
}
