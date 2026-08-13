"use client";

import { use, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Skeleton } from "@/components/ui/Skeleton";

export default function PlaybackPageV2({ params }: { params: Promise<{ cameraId: string }> }) {
  const { cameraId } = use(params);
  const [index, setIndex] = useState(0);

  const { data: cameras } = useQuery({ queryKey: ["cameras"], queryFn: () => api.getCameras() });
  const camera = cameras?.find((c) => c.id === cameraId);

  const { data: eventsData, isLoading, isError, error } = useQuery({
    queryKey: ["events", "camera", cameraId],
    queryFn: () => api.getEvents({ camera_id: cameraId, per_page: "20" }),
  });

  const events = eventsData?.events ?? [];
  const current = events[index];

  if (isLoading) return <Skeleton className="h-96 w-full max-w-[820px] mx-auto mt-12" />;

  if (isError) {
    return (
      <div className="max-w-[820px] mx-auto px-12 py-12">
        <Link href={`/app/cameras/${cameraId}`} className="text-[13px] text-[oklch(62%_0.01_265)] mb-4 inline-block">
          ← Back
        </Link>
        <div className="mt-6 text-sm text-[oklch(70.4%_0.191_22.216)]">
          {error instanceof Error ? error.message : "Failed to load events for this camera."}
        </div>
      </div>
    );
  }

  if (events.length === 0) {
    return (
      <div className="max-w-[820px] mx-auto px-12 py-12">
        <Link href={`/app/cameras/${cameraId}`} className="text-[13px] text-[oklch(62%_0.01_265)] mb-4 inline-block">
          ← Back
        </Link>
        <div className="mt-6 text-sm text-[oklch(55%_0.01_265)]">
          No events to play back for this camera yet.
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-[820px] mx-auto px-12 pt-12 pb-20">
      <Link href={`/app/cameras/${cameraId}`} className="text-[13px] text-[oklch(62%_0.01_265)] mb-4 inline-block">
        ← Back
      </Link>
      <div className="flex items-baseline justify-between mb-4">
        <div className="text-2xl font-bold">{camera?.name ?? "Camera"} · Playback</div>
        <div className="text-[13px] text-[oklch(58%_0.01_265)] font-mono">
          {new Date(current.timestamp).toLocaleString()}
        </div>
      </div>

      <div className="h-[400px] rounded-[18px] overflow-hidden mb-4.5 bg-[oklch(11%_0.015_265)]">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={current.snapshot_url} alt={current.description} className="w-full h-full object-cover" />
      </div>

      <div className="flex items-center gap-3.5 bg-[oklch(13%_0.015_265)] border border-[oklch(22%_0.015_265)] rounded-[14px] px-5 py-4 mb-4.5">
        <div className="flex-1 min-w-0">
          <div className="text-[13.5px] text-[oklch(90%_0.005_265)]">{current.description}</div>
          <div className="text-[11.5px] text-[oklch(55%_0.01_265)] mt-0.5">{current.event_type}</div>
        </div>
      </div>

      <div className="flex items-center gap-4">
        <button
          onClick={() => setIndex((i) => Math.max(0, i - 1))}
          disabled={index === 0}
          className="w-[42px] h-[42px] rounded-full bg-[oklch(15%_0.015_265)] border border-[oklch(26%_0.015_265)] flex items-center justify-center flex-shrink-0 disabled:opacity-30"
        >
          ←
        </button>
        <div className="flex-1 flex items-center justify-center gap-2 overflow-x-auto px-1">
          {events.map((ev, i) => (
            <button
              key={ev.id}
              onClick={() => setIndex(i)}
              className={`w-2 h-2 rounded-full flex-shrink-0 ${i === index ? "bg-[oklch(85%_0.16_84)]" : "bg-[oklch(30%_0.02_265)]"}`}
            />
          ))}
        </div>
        <button
          onClick={() => setIndex((i) => Math.min(events.length - 1, i + 1))}
          disabled={index === events.length - 1}
          className="w-[42px] h-[42px] rounded-full bg-[oklch(15%_0.015_265)] border border-[oklch(26%_0.015_265)] flex items-center justify-center flex-shrink-0 disabled:opacity-30"
        >
          →
        </button>
      </div>
    </div>
  );
}
