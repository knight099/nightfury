"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/lib/store";
import { api } from "@/lib/api";
import { isNewUiEnabled } from "@/lib/flags";
import { SidebarV2 } from "@/components/v2/SidebarV2";

export function AppShellV2({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { token, user } = useAuthStore();

  useEffect(() => {
    if (!isNewUiEnabled()) {
      router.replace("/dashboard");
    } else if (!token) {
      router.replace("/login");
    } else if (user?.must_change_password) {
      router.replace("/change-password");
    } else {
      api.setToken(token);
    }
  }, [token, user, router]);

  if (!isNewUiEnabled() || !token || user?.must_change_password) return null;

  return (
    <div className="flex min-h-screen bg-[oklch(9%_0.015_265)] text-[oklch(97%_0.005_265)]">
      <SidebarV2 />
      <main className="flex-1 overflow-y-auto min-w-0">{children}</main>
    </div>
  );
}
