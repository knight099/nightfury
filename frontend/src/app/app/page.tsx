"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Skeleton } from "@/components/ui/Skeleton";
import { HomeCameraTile } from "@/components/v2/HomeCameraTile";
import { ActivityRow } from "@/components/v2/ActivityRow";
import { useAuthStore } from "@/lib/store";

export default function HomePage() {
  const { user } = useAuthStore();

  const { data: cameras, isLoading: camsLoading } = useQuery({
    queryKey: ["cameras"],
    queryFn: () => api.getCameras(),
  });

  const { data: eventsData, isLoading: eventsLoading } = useQuery({
    queryKey: ["events", "recent"],
    queryFn: () => api.getEvents({ per_page: "5" }),
  });

  const cameraName = (id: string) => cameras?.find((c) => c.id === id)?.name ?? "Unknown camera";

  if (camsLoading || eventsLoading) {
    return (
      <div className="max-w-[1040px] mx-auto px-12 py-12">
        <Skeleton className="h-8 w-64 mb-6" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  const events = eventsData?.events ?? [];

  return (
    <div className="max-w-[1040px] mx-auto px-12 pt-12 pb-20">
      <div className="text-[28px] font-bold tracking-tight mb-1.5">
        Good afternoon, {user?.name ?? user?.username}
      </div>
      <div className="text-[15px] text-[oklch(65%_0.01_265)] mb-8">
        Here&apos;s how things look right now.
      </div>

      <div className="bg-gradient-to-br from-[oklch(18%_0.03_155)] to-[oklch(13%_0.02_265)] border border-[oklch(30%_0.06_155)] rounded-[20px] px-8 py-7 flex items-center justify-between mb-9">
        <div className="flex items-center gap-4.5">
          <div className="w-12 h-12 rounded-full bg-[oklch(79.2%_0.209_151.711_/_0.15)] flex items-center justify-center flex-shrink-0">
            <div className="w-3.5 h-3.5 rounded-full bg-[oklch(79.2%_0.209_151.711)]" />
          </div>
          <div>
            <div className="text-xl font-bold mb-1">
              {events.length === 0 ? "All quiet" : `${events.length} recent events`}
            </div>
            <div className="text-sm text-[oklch(75%_0.01_265)]">
              {events.length === 0
                ? "Nothing needed you recently."
                : "Here's what's happened lately."}
            </div>
          </div>
        </div>
        <Link href="/app/chat" className="text-[13px] font-semibold text-[oklch(85%_0.06_155)]">
          Ask Nightwatch →
        </Link>
      </div>

      <div className="flex items-baseline justify-between mb-4">
        <div className="text-base font-bold">Your cameras</div>
        <Link href="/app/cameras" className="text-[13px] font-semibold text-[oklch(72%_0.01_265)]">
          See all →
        </Link>
      </div>
      {cameras && cameras.length > 0 ? (
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
        {events.length > 0 ? (
          events.map((ev) => <ActivityRow key={ev.id} event={ev} cameraName={cameraName(ev.camera_id)} />)
        ) : (
          <div className="p-6 text-sm text-[oklch(55%_0.01_265)] text-center">No recent events.</div>
        )}
      </div>

      <Link
        href="/app/cameras"
        className="block border border-dashed border-[oklch(30%_0.02_265)] rounded-2xl px-6.5 py-5.5 flex items-center justify-between"
      >
        <div>
          <div className="text-[15px] font-bold mb-1">Give a camera a new job</div>
          <div className="text-[13px] text-[oklch(62%_0.01_265)]">
            Pick a camera and tell it what to watch for, in plain English.
          </div>
        </div>
        <div className="text-[22px] text-[oklch(72%_0.01_265)]">+</div>
      </Link>
    </div>
  );
}
