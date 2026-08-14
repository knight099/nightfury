"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/lib/store";
import { useHydrated } from "@/lib/useHydrated";
import { api } from "@/lib/api";
import { isNewUiEnabled } from "@/lib/flags";
import { SidebarV2 } from "@/components/v2/SidebarV2";
import { ImpersonationBanner } from "@/components/v2/ImpersonationBanner";

export function AppShellV2({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { token, user } = useAuthStore();
  const hydrated = useHydrated();

  useEffect(() => {
    if (!hydrated) return;
    if (!isNewUiEnabled()) {
      router.replace("/dashboard");
    } else if (!token) {
      router.replace("/login");
    } else if (user?.must_change_password) {
      router.replace("/change-password");
    } else {
      api.setToken(token);
    }
  }, [hydrated, token, user, router]);

  if (!hydrated) return null;
  if (!isNewUiEnabled() || !token || user?.must_change_password) return null;

  api.setToken(token);

  return (
    <div className="flex flex-col min-h-screen bg-[oklch(9%_0.015_265)] text-[oklch(97%_0.005_265)]">
      <ImpersonationBanner />
      <div className="flex flex-1 min-h-0">
        <SidebarV2 />
        <main className="flex-1 overflow-y-auto min-w-0">{children}</main>
      </div>
    </div>
  );
}
