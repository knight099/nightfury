"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/lib/store";
import { api } from "@/lib/api";
import { Sidebar } from "@/components/layout/sidebar";
import { HelpWidget } from "@/components/shared/help-widget";
import { ChatSidePanel } from "@/components/shared/chat-panel";
import { useChatPanelState } from "@/lib/chatPanelState";

export default function UsageLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { token, user } = useAuthStore();
  const collapsed = useChatPanelState((s) => s.collapsed);

  useEffect(() => {
    if (!token) router.replace("/login");
    else if (user?.must_change_password) router.replace("/change-password");
    else api.setToken(token);
  }, [token, user, router]);

  if (!token || user?.must_change_password) return null;

  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <main
        className={`ml-56 flex-1 p-6 transition-[padding] duration-200 ${
          collapsed ? "" : "pr-[360px]"
        }`}
      >
        {children}
      </main>
      <HelpWidget />
      <ChatSidePanel />
    </div>
  );
}
