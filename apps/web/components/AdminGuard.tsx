"use client";

import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { isAdminRole, useAuth } from "../lib/auth";
import { Spinner } from "./ui";

/* Penjaga halaman admin: peran admin & super_admin yang boleh masuk. */
export function AdminGuard({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();
  const allowed = isAdminRole(user?.role);

  useEffect(() => {
    if (!loading && !allowed) router.replace("/live");
  }, [loading, allowed, router]);

  if (loading || !allowed) {
    return (
      <div className="min-h-screen bg-ink-950">
        <Spinner />
      </div>
    );
  }
  return <>{children}</>;
}
