"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  LayoutDashboard,
  Camera,
  AlertTriangle,
  Bell,
  LogOut,
  Shield,
  Settings,
  HelpCircle,
  Video,
  BarChart3,
  FileText,
  MoreHorizontal,
  X,
  MessageSquare,
} from "lucide-react";
import { useAuthStore } from "@/lib/store";
import { api } from "@/lib/api";
import { isNewUiEnabled } from "@/lib/flags";
import { cn } from "@/lib/utils";
import { startOnboardingTour } from "@/lib/tour";
import { Sidebar } from "@/components/layout/sidebar";
import { HelpWidget } from "@/components/shared/help-widget";
import { ChatSidePanel } from "@/components/shared/chat-panel";
import { useChatPanelState } from "@/lib/chatPanelState";

const primaryTabs = [
  { href: "/dashboard", label: "Home", icon: LayoutDashboard },
  { href: "/events", label: "Events", icon: AlertTriangle },
  { href: "/cameras", label: "Cameras", icon: Camera },
  { href: "/alerts", label: "Alerts", icon: Bell },
];

const moreItems = [
  { href: "/digests", label: "Digests", icon: FileText },
  { href: "/test-camera", label: "Test AI", icon: Video },
  { href: "/usage", label: "Usage", icon: BarChart3 },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function AppShell({
  children,
  requireRole,
}: {
  children: React.ReactNode;
  requireRole?: "super_admin";
}) {
  const router = useRouter();
  const pathname = usePathname();
  const { token, user, logout } = useAuthStore();
  const collapsed = useChatPanelState((s) => s.collapsed);
  const toggleChat = useChatPanelState((s) => s.toggle);
  const [moreOpen, setMoreOpen] = useState(false);

  useEffect(() => {
    if (!token) {
      router.replace("/login");
    } else if (isNewUiEnabled()) {
      router.replace("/app");
    } else if (user?.must_change_password) {
      router.replace("/change-password");
    } else if (requireRole && user?.role !== requireRole) {
      router.replace("/dashboard");
    } else {
      api.setToken(token);
    }
  }, [token, user, router, requireRole]);

  useEffect(() => {
    setMoreOpen(false);
  }, [pathname]);

  if (!token || user?.must_change_password) return null;
  if (requireRole && user?.role !== requireRole) return null;

  return (
    <div className="flex min-h-screen">
      <div className="hidden lg:block">
        <Sidebar />
      </div>

      {/* Mobile top bar */}
      <header className="lg:hidden fixed top-0 inset-x-0 z-40 h-14 flex items-center justify-between px-4 bg-[#0D0D0D]/90 backdrop-blur border-b border-[#2A2A2A]">
        <h1 className="text-base font-bold font-heading">
          <span className="text-[#1E90FF]">N</span>IGHTWATCH
        </h1>
        <div className="flex items-center gap-1">
          <button
            onClick={toggleChat}
            aria-label="Open chat"
            className="p-2.5 rounded-md text-[#A3A3A3] hover:text-[#F5F5F5] hover:bg-[#1A1A1A] transition-colors"
          >
            <MessageSquare size={20} />
          </button>
          <button
            onClick={() => setMoreOpen(true)}
            aria-label="More options"
            className="p-2.5 rounded-md text-[#A3A3A3] hover:text-[#F5F5F5] hover:bg-[#1A1A1A] transition-colors"
          >
            <MoreHorizontal size={20} />
          </button>
        </div>
      </header>

      <main
        className={cn(
          "flex-1 p-4 pt-[72px] pb-24 lg:p-6 lg:ml-56 transition-[padding] duration-200 min-w-0",
          !collapsed && "lg:pr-[360px]"
        )}
      >
        {children}
      </main>

      {/* Mobile bottom tab bar */}
      <nav className="lg:hidden fixed bottom-0 inset-x-0 z-40 bg-[#0D0D0D]/95 backdrop-blur border-t border-[#2A2A2A] pb-safe">
        <div className="grid grid-cols-4 h-16">
          {primaryTabs.map((tab) => {
            const Icon = tab.icon;
            const active = pathname.startsWith(tab.href);
            return (
              <Link
                key={tab.href}
                href={tab.href}
                className={cn(
                  "flex flex-col items-center justify-center gap-1 text-[11px] transition-colors",
                  active ? "text-[#1E90FF]" : "text-[#A3A3A3] active:text-[#F5F5F5]"
                )}
              >
                <Icon size={22} strokeWidth={active ? 2.4 : 2} />
                {tab.label}
              </Link>
            );
          })}
        </div>
      </nav>

      {/* Mobile "More" sheet */}
      {moreOpen && (
        <div className="lg:hidden fixed inset-0 z-50">
          <div
            className="absolute inset-0 bg-black/60"
            onClick={() => setMoreOpen(false)}
          />
          <div className="absolute bottom-0 inset-x-0 bg-[#111111] border-t border-[#2A2A2A] rounded-t-2xl p-4 pb-safe fade-up">
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm font-semibold">More</span>
              <button
                onClick={() => setMoreOpen(false)}
                aria-label="Close"
                className="p-2 rounded-md text-[#A3A3A3] hover:text-[#F5F5F5]"
              >
                <X size={18} />
              </button>
            </div>
            <div className="grid grid-cols-2 gap-2">
              {moreItems.map((item) => {
                const Icon = item.icon;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className="flex items-center gap-3 px-4 py-3.5 rounded-lg bg-[#1A1A1A] text-sm text-[#F5F5F5] active:bg-[#222222] transition-colors"
                  >
                    <Icon size={18} className="text-[#1E90FF]" />
                    {item.label}
                  </Link>
                );
              })}
              {user?.role === "super_admin" && (
                <Link
                  href="/admin"
                  className="flex items-center gap-3 px-4 py-3.5 rounded-lg bg-[#1A1A1A] text-sm text-[#F5F5F5] active:bg-[#222222] transition-colors"
                >
                  <Shield size={18} className="text-[#1E90FF]" />
                  Admin
                </Link>
              )}
              <button
                onClick={() => {
                  setMoreOpen(false);
                  startOnboardingTour();
                }}
                className="flex items-center gap-3 px-4 py-3.5 rounded-lg bg-[#1A1A1A] text-sm text-[#F5F5F5] active:bg-[#222222] transition-colors"
              >
                <HelpCircle size={18} className="text-[#1E90FF]" />
                Quick Tour
              </button>
              <button
                onClick={() => {
                  api.logout().catch(() => {});
                  logout();
                }}
                className="flex items-center gap-3 px-4 py-3.5 rounded-lg bg-[#1A1A1A] text-sm text-[#EF4444] active:bg-[#222222] transition-colors"
              >
                <LogOut size={18} />
                Logout
              </button>
            </div>
            <div className="mt-3 px-1 text-xs text-[#666666]">
              Signed in as {user?.username}
            </div>
          </div>
        </div>
      )}

      <HelpWidget />
      <ChatSidePanel />
    </div>
  );
}
