"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Skeleton } from "@/components/ui/Skeleton";
import { ActivityRow } from "@/components/v2/ActivityRow";

const FILTERS = ["all", "low", "medium", "high", "critical"] as const;

export default function ActivityPageV2() {
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("all");

  const { data: cameras } = useQuery({ queryKey: ["cameras"], queryFn: () => api.getCameras() });
  const { data: eventsData, isLoading, isError, error } = useQuery({
    queryKey: ["events", "activity", filter],
    queryFn: () => api.getEvents({ per_page: "50", ...(filter !== "all" && { severity: filter }) }),
  });

  const cameraName = (id: string) => cameras?.find((c) => c.id === id)?.name ?? "Unknown camera";

  return (
    <div className="max-w-[1040px] mx-auto px-12 pt-12 pb-20">
      <div className="text-[28px] font-bold tracking-tight mb-6">Activity</div>
      <div className="flex gap-2 mb-6">
        {FILTERS.map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`text-[12px] font-semibold px-3 py-1.5 rounded-full ${
              filter === f
                ? "bg-[oklch(85%_0.16_84)] text-[oklch(18%_0.02_84)]"
                : "bg-[oklch(15%_0.015_265)] text-[oklch(72%_0.01_265)]"
            }`}
          >
            {f}
          </button>
        ))}
      </div>
      {isLoading ? (
        <Skeleton className="h-96 w-full" />
      ) : isError ? (
        <div className="p-6 text-sm text-red-400 text-center border border-red-900 rounded-[14px] bg-red-950/20">
          Failed to load events: {error?.message || "Unknown error"}
        </div>
      ) : (
        <div className="flex flex-col border border-[oklch(22%_0.015_265)] rounded-[14px] overflow-hidden">
          {(eventsData?.events ?? []).length > 0 ? (
            eventsData!.events.map((ev) => <ActivityRow key={ev.id} event={ev} cameraName={cameraName(ev.camera_id)} />)
          ) : (
            <div className="p-6 text-sm text-[oklch(55%_0.01_265)] text-center">No events match this filter.</div>
          )}
        </div>
      )}
    </div>
  );
}
