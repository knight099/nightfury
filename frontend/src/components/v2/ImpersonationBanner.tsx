"use client";

import { useRouter } from "next/navigation";
import { useAuthStore } from "@/lib/store";
import { api } from "@/lib/api";

export function ImpersonationBanner() {
  const router = useRouter();
  const { user, originalToken, exitImpersonation } = useAuthStore();

  if (!originalToken) return null;

  const handleExit = () => {
    api.logout().catch(() => {});
    exitImpersonation();
    router.push("/app/admin");
  };

  return (
    <div className="w-full flex-shrink-0 bg-[oklch(70.4%_0.191_22.216)] text-[oklch(9%_0.015_265)] text-sm font-semibold px-4 py-2 flex items-center justify-center gap-3">
      <span>Viewing as {user?.username}</span>
      <button onClick={handleExit} className="underline">Exit</button>
    </div>
  );
}
