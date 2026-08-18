"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
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
  Server,
  Grid3x3,
  Waypoints,
} from "lucide-react";
import { useAuthStore } from "@/lib/store";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { startOnboardingTour } from "@/lib/tour";

const navItems = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard, tourId: "nav-dashboard" },
  { href: "/events", label: "Events", icon: AlertTriangle, tourId: "nav-events" },
  { href: "/digests", label: "Digests", icon: FileText, tourId: "nav-digests" },
  { href: "/cameras", label: "Cameras", icon: Camera, tourId: "nav-cameras" },
  { href: "/alerts", label: "Alerts", icon: Bell, tourId: "nav-alerts" },
  { href: "/wall", label: "Video wall", icon: Grid3x3, tourId: "nav-wall" },
  { href: "/map", label: "Camera map", icon: Waypoints, tourId: "nav-map" },
  { href: "/fleet", label: "Fleet", icon: Server, tourId: "nav-fleet" },
  { href: "/test-camera", label: "Test AI", icon: Video, tourId: "nav-test" },
  { href: "/usage", label: "Usage", icon: BarChart3, tourId: "nav-usage" },
];

export function Sidebar() {
  const pathname = usePathname();
  const { user, logout } = useAuthStore();

  return (
    <aside className="fixed left-0 top-0 z-40 h-screen w-56 border-r border-[#2A2A2A] bg-[#0D0D0D] flex flex-col">
      <div className="p-4 border-b border-[#2A2A2A]">
        <h1 className="text-lg font-bold text-[#F5F5F5]" data-tour="logo">
          <span className="text-[#1E90FF]">N</span>IGHTWATCH
        </h1>
      </div>

      <nav className="flex-1 p-3 space-y-1">
        {navItems.map((item) => {
          const Icon = item.icon;
          const active = pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              data-tour={item.tourId}
              className={cn(
                "flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors",
                active
                  ? "bg-[#1E90FF]/10 text-[#1E90FF]"
                  : "text-[#A3A3A3] hover:text-[#F5F5F5] hover:bg-[#1A1A1A]"
              )}
            >
              <Icon size={18} />
              {item.label}
            </Link>
          );
        })}

        {user?.role !== undefined && (
          <Link
            href="/settings"
            className={cn(
              "flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors",
              pathname.startsWith("/settings")
                ? "bg-[#1E90FF]/10 text-[#1E90FF]"
                : "text-[#A3A3A3] hover:text-[#F5F5F5] hover:bg-[#1A1A1A]"
            )}
          >
            <Settings size={18} />
            Settings
          </Link>
        )}

        {user?.role === "super_admin" && (
          <Link
            href="/admin"
            data-tour="nav-admin"
            className={cn(
              "flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors",
              pathname.startsWith("/admin")
                ? "bg-[#1E90FF]/10 text-[#1E90FF]"
                : "text-[#A3A3A3] hover:text-[#F5F5F5] hover:bg-[#1A1A1A]"
            )}
          >
            <Shield size={18} />
            Admin
          </Link>
        )}
      </nav>

      <div className="p-3 border-t border-[#2A2A2A] space-y-1">
        <button
          onClick={() => startOnboardingTour()}
          className="flex items-center gap-3 px-3 py-2 rounded-md text-sm text-[#A3A3A3] hover:text-[#1E90FF] hover:bg-[#1A1A1A] w-full transition-colors"
        >
          <HelpCircle size={18} />
          Quick Tour
        </button>
        <div className="px-3 py-1 text-xs text-[#666666]">
          {user?.username}
        </div>
        <button
          onClick={() => { api.logout().catch(() => {}); logout(); }}
          className="flex items-center gap-3 px-3 py-2 rounded-md text-sm text-[#A3A3A3] hover:text-[#EF4444] hover:bg-[#1A1A1A] w-full transition-colors"
        >
          <LogOut size={18} />
          Logout
        </button>
      </div>
    </aside>
  );
}
