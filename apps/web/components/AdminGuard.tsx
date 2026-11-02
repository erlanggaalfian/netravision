"use client";

import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { useAuth } from "../lib/auth";
import { Spinner } from "./ui";

/* Penjaga halaman admin: hanya peran admin yang boleh masuk. */
export function AdminGuard({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && user?.role !== "admin") router.replace("/live");
  }, [loading, user, router]);

  if (loading || user?.role !== "admin") {
    return (
      <div className="min-h-screen bg-ink-950">
        <Spinner />
      </div>
    );
  }
  return <>{children}</>;
}
