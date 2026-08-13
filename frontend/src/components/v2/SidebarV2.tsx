"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Home, Camera, Map, Bot, Activity, FileText, Settings, LogOut, Video } from "lucide-react";
import { useAuthStore } from "@/lib/store";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

const navItems = [
  { href: "/app", label: "Home", icon: Home },
  { href: "/app/cameras", label: "Cameras", icon: Camera },
  { href: "/app/map", label: "Map", icon: Map },
  { href: "/app/agents", label: "Agents", icon: Bot },
  { href: "/app/activity", label: "Activity", icon: Activity },
  { href: "/app/digests", label: "Digests", icon: FileText },
  { href: "/app/settings", label: "Settings", icon: Settings },
  { href: "/app/test-camera", label: "Test AI", icon: Video },
];

export function SidebarV2() {
  const pathname = usePathname();
  const { user, logout } = useAuthStore();

  const { data: cameras } = useQuery({
    queryKey: ["cameras"],
    queryFn: () => api.getCameras(),
  });

  const camerasTotalCount = cameras?.length ?? 0;
  const camerasWatchingCount =
    cameras?.filter((c) => c.status === "online").length ?? 0;

  return (
    <aside className="w-[232px] shrink-0 bg-[oklch(12%_0.015_265)] border-r border-[oklch(22%_0.015_265)] flex flex-col p-6 px-4">
      <div className="flex items-center gap-2.5 px-2 pb-7">
        <div className="w-2.5 h-2.5 rounded-full bg-[oklch(79.2%_0.209_151.711)] shadow-[0_0_0_4px_oklch(79.2%_0.209_151.711/0.15)]" />
        <div className="text-[17px] font-bold tracking-[-0.01em]">Nightwatch</div>
      </div>

      <nav className="flex flex-col gap-0.5">
        {navItems.map((item) => {
          const Icon = item.icon;
          const active =
            item.href === "/app"
              ? pathname === "/app"
              : pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors",
                active
                  ? "bg-[oklch(97%_0.005_265)]/10 text-[oklch(97%_0.005_265)]"
                  : "text-[oklch(58%_0.01_265)] hover:text-[oklch(97%_0.005_265)] hover:bg-[oklch(18%_0.015_265)]"
              )}
            >
              <Icon size={18} />
              <span>{item.label}</span>
            </Link>
          );
        })}
      </nav>

      <div className="flex-1" />

      <div className="bg-[oklch(15%_0.02_265)] border border-[oklch(24%_0.02_265)] rounded-xl p-3.5 flex flex-col gap-2">
        <div className="flex items-center gap-1.5">
          <div className="w-1.5 h-1.5 rounded-full bg-[oklch(79.2%_0.209_151.711)] animate-pulse" />
          <div className="text-[11px] font-semibold tracking-[0.04em] text-[oklch(72%_0.01_265)] uppercase">
            On watch
          </div>
        </div>
        <div className="text-[13px] text-[oklch(85%_0.005_265)] leading-snug">
          {camerasWatchingCount} of {camerasTotalCount} cameras working right now.
        </div>
      </div>

      {user?.role === "super_admin" && (
        <Link
          href="/app/admin"
          className="mt-3.5 text-center text-[11.5px] text-[oklch(42%_0.01_265)] hover:text-[oklch(58%_0.01_265)] transition-colors"
        >
          Admin &rarr;
        </Link>
      )}

      <div className="mt-3.5 pt-3.5 border-t border-[oklch(22%_0.015_265)] flex flex-col gap-1">
        {user?.username && (
          <div className="px-3 py-1 text-[11.5px] text-[oklch(50%_0.01_265)] truncate">
            {user.username}
          </div>
        )}
        <button
          onClick={() => {
            api.logout().catch(() => {});
            logout();
          }}
          className="flex items-center gap-3 px-3 py-2 rounded-md text-sm text-[oklch(58%_0.01_265)] hover:text-[oklch(70.4%_0.191_22.216)] hover:bg-[oklch(18%_0.015_265)] w-full transition-colors"
        >
          <LogOut size={18} />
          Logout
        </button>
      </div>
    </aside>
  );
}
