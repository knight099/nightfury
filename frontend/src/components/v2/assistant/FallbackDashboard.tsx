"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Skeleton } from "@/components/ui/Skeleton";
import { HomeCameraTile } from "@/components/v2/HomeCameraTile";
import { ActivityRow } from "@/components/v2/ActivityRow";

/**
 * Offline-safe fallback for the home page's camera + activity view, shown
 * when the assistant is unavailable (daily AI budget exhausted, or Gemini
 * down). Nightwatch is a physical security product — cameras and recent
 * activity must stay visible even when the assistant can't respond.
 *
 * The camera-tile grid and activity list below are extracted from
 * `frontend/src/app/app/page.tsx` UNCHANGED — this is the safety fallback,
 * so it must not carry new bugs. Do not redesign it here; page.tsx is the
 * source of truth and a later task reconciles the two.
 */
export function FallbackDashboard({ reason }: { reason: "budget" | "unavailable" }) {
  const {
    data: cameras,
    isLoading: camsLoading,
    isError: camsError,
    error: camsErrorObj,
  } = useQuery({
    queryKey: ["cameras"],
    queryFn: () => api.getCameras(),
  });

  const {
    data: eventsData,
    isLoading: eventsLoading,
    isError: eventsError,
    error: eventsErrorObj,
  } = useQuery({
    queryKey: ["events", "recent"],
    queryFn: () => api.getEvents({ per_page: "5" }),
    refetchInterval: 10000,
  });

  const cameraName = (id: string) => cameras?.find((c) => c.id === id)?.name ?? "Unknown camera";

  const events = eventsData?.events ?? [];

  return (
    <div>
      <div className="mb-6 rounded-[14px] border border-[oklch(85%_0.16_84)]/40 bg-[oklch(85%_0.16_84)]/8 px-4 py-3 text-[13px]">
        {reason === "budget"
          ? "The assistant is paused — your organisation has reached its daily AI budget. Everything below is live, and every page still works."
          : "The assistant is temporarily unavailable. Everything below is live, and every page still works."}
      </div>

      {camsLoading || eventsLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : (
        <>
          <div className="flex items-baseline justify-between mb-4">
            <div className="text-base font-bold">Your cameras</div>
            <Link href="/app/cameras" className="text-[13px] font-semibold text-[oklch(72%_0.01_265)]">
              See all →
            </Link>
          </div>
          {camsError ? (
            <p className="text-sm text-[oklch(70.4%_0.191_22.216)] mb-10">
              {camsErrorObj instanceof Error ? camsErrorObj.message : "Something went wrong loading cameras."}
            </p>
          ) : cameras && cameras.length > 0 ? (
            <div className="grid grid-cols-4 gap-4 mb-10">
              {cameras.map((cam) => (
                <HomeCameraTile key={cam.id} camera={cam} />
              ))}
            </div>
          ) : (
            <div className="text-sm text-[oklch(55%_0.01_265)] mb-10">No cameras yet.</div>
          )}

          <div className="flex items-baseline justify-between mb-4">
            <div className="text-base font-bold">Recent activity</div>
            <Link href="/app/activity" className="text-[13px] font-semibold text-[oklch(72%_0.01_265)]">
              See all →
            </Link>
          </div>
          <div className="flex flex-col border border-[oklch(22%_0.015_265)] rounded-[14px] overflow-hidden mb-9">
            {eventsError ? (
              <div className="p-6 text-sm text-[oklch(70.4%_0.191_22.216)] text-center">
                {eventsErrorObj instanceof Error ? eventsErrorObj.message : "Something went wrong loading events."}
              </div>
            ) : events.length > 0 ? (
              events.map((ev) => <ActivityRow key={ev.id} event={ev} cameraName={cameraName(ev.camera_id)} />)
            ) : (
              <div className="p-6 text-sm text-[oklch(55%_0.01_265)] text-center">No recent events.</div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
