"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAuthStore } from "@/lib/store";
import { useEventsSocket } from "@/lib/useEventsSocket";
import { SeverityBadge } from "@/components/shared/severity-badge";
import { StatusDot } from "@/components/shared/status-dot";
import { Skeleton } from "@/components/ui/Skeleton";
import { AlertTriangle, Camera, Activity, TrendingDown } from "lucide-react";
import { startOnboardingTour, shouldShowTour } from "@/lib/tour";
import type { Event, Camera as CameraType, PaginatedResponse } from "@/types";

export default function DashboardPage() {
  const { user } = useAuthStore();
  const queryClient = useQueryClient();

  useEffect(() => {
    if (shouldShowTour() && window.innerWidth >= 1024) {
      const timer = setTimeout(() => startOnboardingTour(), 800);
      return () => clearTimeout(timer);
    }
  }, []);

  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ["events", "stats"],
    queryFn: () => api.getEventStats("24h"),
    refetchInterval: 30000,
  });

  const { data: eventsData, isLoading: eventsLoading } = useQuery({
    queryKey: ["events", "recent"],
    queryFn: () => api.getEvents({ per_page: "10", page: "1" }),
  });

  const handleNewEvent = useCallback(
    (event: Event) => {
      queryClient.setQueryData<PaginatedResponse<Event>>(["events", "recent"], (old) => {
        const prevEvents = old?.events ?? [];
        if (prevEvents.some((e) => e.id === event.id)) return old;
        const nextEvents = [event, ...prevEvents].slice(0, 10);
        return {
          events: nextEvents,
          total: (old?.total ?? 0) + 1,
          page: old?.page ?? 1,
          pages: old?.pages ?? 1,
        };
      });
      queryClient.invalidateQueries({ queryKey: ["events", "stats"] });
    },
    [queryClient]
  );

  useEventsSocket(handleNewEvent);

  const { data: cameras } = useQuery({
    queryKey: ["cameras"],
    queryFn: () => api.getCameras(),
  });

  const events = eventsData?.events || [];
  const onlineCameras = cameras?.filter((c: CameraType) => c.status === "online").length || 0;
  const totalCameras = cameras?.length || 0;

  return (
    <div className="space-y-4 lg:space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-bold">Dashboard</h1>
        <span className="text-xs text-[#666666]">
          Welcome, {user?.name}
          {user?.role === "super_admin" && (
            <span className="ml-2 px-2 py-0.5 bg-[#1E90FF]/10 text-[#1E90FF] rounded text-xs">
              SUPER ADMIN
            </span>
          )}
        </span>
      </div>

      {/* System status strip */}
      {cameras && cameras.length > 0 && (
        <div
          className={`flex items-center gap-3 px-4 py-3 rounded-lg border text-sm ${
            onlineCameras === totalCameras
              ? "bg-[#4ADE80]/5 border-[#4ADE80]/20 text-[#4ADE80]"
              : "bg-[#FBBF24]/5 border-[#FBBF24]/20 text-[#FBBF24]"
          }`}
        >
          <span
            className={`inline-block w-2 h-2 rounded-full pulse-live ${
              onlineCameras === totalCameras ? "bg-[#4ADE80]" : "bg-[#FBBF24]"
            }`}
          />
          {onlineCameras === totalCameras
            ? `All ${totalCameras} camera${totalCameras === 1 ? "" : "s"} watching`
            : `${totalCameras - onlineCameras} camera${totalCameras - onlineCameras === 1 ? "" : "s"} offline — check power and Wi-Fi`}
        </div>
      )}

      {/* Stats Row */}
      {statsLoading && !stats ? (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 lg:gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24 rounded-lg" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 lg:gap-4">
          <StatCard
            icon={<AlertTriangle size={18} className="text-[#1E90FF]" />}
            label="Events Today"
            value={stats?.total_events || 0}
          />
          <StatCard
            icon={<Activity size={18} className="text-red-400" />}
            label="Critical"
            value={stats?.by_severity?.critical || 0}
          />
          <StatCard
            icon={<Camera size={18} className="text-green-400" />}
            label="Cameras Online"
            value={`${onlineCameras}/${totalCameras}`}
          />
          <StatCard
            icon={<TrendingDown size={18} className="text-amber-400" />}
            label="Accuracy"
            value={`${(100 - (stats?.false_positive_rate || 0) * 100).toFixed(0)}%`}
          />
        </div>
      )}

      {/* Event Feed */}
      <div className="bg-[#111111] rounded-lg border border-[#2A2A2A]">
        <div className="px-4 py-3 border-b border-[#2A2A2A] flex items-center gap-2">
          <h2 className="text-sm font-medium">Recent Events</h2>
          <span className="flex items-center gap-1.5 text-[10px] text-[#4ADE80] uppercase tracking-wider font-mono">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-[#4ADE80] pulse-live" />
            Live
          </span>
        </div>
        <div className="divide-y divide-[#2A2A2A]">
          {eventsLoading && !eventsData && (
            <div className="p-4 space-y-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-16 rounded-md" />
              ))}
            </div>
          )}
          {!eventsLoading && events.length === 0 && (
            <div className="px-4 py-10 text-center">
              <p className="text-sm text-[#A3A3A3]">All quiet for now.</p>
              <p className="mt-1 text-xs text-[#666666]">
                Events show up here the moment your cameras spot something.
              </p>
            </div>
          )}
          {events.map((event: Event) => (
            <div
              key={event.id}
              className="px-4 py-3 flex flex-wrap sm:flex-nowrap items-center gap-x-4 gap-y-1 hover:bg-[#1A1A1A] transition-colors fade-up"
            >
              <span className="text-xs text-[#666666] font-mono w-16 shrink-0">
                {new Date(event.timestamp).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
              </span>
              <span className="text-sm font-medium w-24 capitalize shrink-0">{event.event_type.replace("_", " ")}</span>
              <SeverityBadge severity={event.severity} />
              <span className="hidden sm:block text-sm text-[#A3A3A3] w-32 truncate">{event.camera_id.slice(0, 8)}…</span>
              <span className="hidden md:block text-xs text-[#666666]">{(event.confidence * 100).toFixed(0)}%</span>
              <span className="basis-full sm:basis-auto sm:flex-1 text-xs text-[#A3A3A3] truncate">{event.description}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Camera Grid */}
      {cameras && cameras.length > 0 && (
        <div className="bg-[#111111] rounded-lg border border-[#2A2A2A]">
          <div className="px-4 py-3 border-b border-[#2A2A2A]">
            <h2 className="text-sm font-medium">Cameras</h2>
          </div>
          <div className="p-4 grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-3">
            {cameras.map((cam: CameraType) => (
              <div key={cam.id} className="flex items-center gap-2 px-3 py-2 bg-[#1A1A1A] rounded-md">
                <StatusDot status={cam.status} />
                <span className="text-xs truncate">{cam.name}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function useCountUp(target: number, durationMs = 600): number {
  const [display, setDisplay] = useState(target);
  const fromRef = useRef(target);

  useEffect(() => {
    const from = fromRef.current;
    if (from === target) return;
    let raf = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / durationMs);
      const eased = 1 - (1 - t) * (1 - t);
      setDisplay(Math.round(from + (target - from) * eased));
      if (t < 1) raf = requestAnimationFrame(tick);
      else fromRef.current = target;
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, durationMs]);

  return display;
}

function StatCard({ icon, label, value }: { icon: React.ReactNode; label: string; value: string | number }) {
  const numeric = typeof value === "number";
  const animated = useCountUp(numeric ? value : 0);
  return (
    <div className="bg-[#111111] rounded-lg border border-[#2A2A2A] p-4 card-lift">
      <div className="flex items-center gap-2 mb-2">{icon}<span className="text-xs text-[#666666]">{label}</span></div>
      <div className="text-2xl font-bold font-heading tabular-nums">{numeric ? animated : value}</div>
    </div>
  );
}
