"use client";

import { use, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Skeleton } from "@/components/ui/Skeleton";
import { ActivityRow } from "@/components/v2/ActivityRow";
import { ComingSoon } from "@/components/v2/ComingSoon";
import { WebRTCPlayer } from "@/components/cameras/WebRTCPlayer";

export default function CameraDetailPageV2({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [webrtcFailed, setWebrtcFailed] = useState(false);
  const [streamFailed, setStreamFailed] = useState(false);

  const {
    data: cameras,
    isLoading: camsLoading,
    isError: camsError,
    error: camsErrorObj,
  } = useQuery({
    queryKey: ["cameras"],
    queryFn: () => api.getCameras(),
  });
  const camera = cameras?.find((c) => c.id === id);

  const { data: streamUrl } = useQuery({
    queryKey: ["camera-stream-url", id],
    queryFn: () => api.getCameraStreamUrl(id),
    refetchInterval: 10 * 60 * 1000,
    enabled: !!camera && webrtcFailed && !streamFailed,
  });

  const { data: frame } = useQuery({
    queryKey: ["camera-latest-frame", id],
    queryFn: () => api.getCameraLatestFrame(id),
    refetchInterval: 1000,
    enabled: !!camera && webrtcFailed && streamFailed,
  });

  const {
    data: eventsData,
    isLoading: eventsLoading,
    isError: eventsError,
    error: eventsErrorObj,
  } = useQuery({
    queryKey: ["events", "camera", id],
    queryFn: () => api.getEvents({ camera_id: id, per_page: "20" }),
    enabled: !!camera,
  });

  if (camsLoading) {
    return (
      <div className="max-w-[1040px] mx-auto px-12 py-12">
        <Skeleton className="h-8 w-64 mb-6" />
        <Skeleton className="h-[400px] w-full" />
      </div>
    );
  }

  if (camsError) {
    return (
      <div className="max-w-[1040px] mx-auto px-12 py-12">
        <Link href="/app/cameras" className="text-[13px] text-[oklch(62%_0.01_265)] mb-4 inline-block">
          ← Cameras
        </Link>
        <div className="text-sm text-[oklch(70.4%_0.191_22.216)]">
          {camsErrorObj instanceof Error ? camsErrorObj.message : "Something went wrong loading this camera."}
        </div>
      </div>
    );
  }

  if (!camera) {
    return (
      <div className="max-w-[1040px] mx-auto px-12 py-12 text-sm text-[oklch(55%_0.01_265)]">
        Camera not found.
      </div>
    );
  }

  return (
    <div className="max-w-[1040px] mx-auto px-12 pt-12 pb-20">
      <Link href="/app/cameras" className="text-[13px] text-[oklch(62%_0.01_265)] mb-4 inline-block">
        ← Cameras
      </Link>
      <div className="text-[28px] font-bold tracking-tight mb-6">{camera.name}</div>

      <div className="rounded-[18px] overflow-hidden mb-6 bg-[oklch(11%_0.015_265)] h-[400px] relative">
        {!webrtcFailed ? (
          <WebRTCPlayer cameraId={id} className="w-full h-full object-cover" onError={() => setWebrtcFailed(true)} />
        ) : !streamFailed && streamUrl?.url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={streamUrl.url}
            alt={camera.name}
            className="w-full h-full object-cover"
            onError={() => setStreamFailed(true)}
          />
        ) : frame?.url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={frame.url} alt={camera.name} className="w-full h-full object-cover" />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-sm text-[oklch(55%_0.01_265)]">
            Live view unavailable
          </div>
        )}
      </div>

      <div className="text-base font-bold mb-3.5">Jobs</div>
      <ComingSoon title="Camera jobs are coming soon" />

      <div className="text-base font-bold mb-3.5 mt-2">Recent events</div>
      {eventsLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : eventsError ? (
        <div className="text-sm text-[oklch(70.4%_0.191_22.216)]">
          {eventsErrorObj instanceof Error ? eventsErrorObj.message : "Something went wrong loading events."}
        </div>
      ) : (
        <div className="flex flex-col border border-[oklch(22%_0.015_265)] rounded-[14px] overflow-hidden">
          {(eventsData?.events ?? []).length > 0 ? (
            eventsData!.events.map((ev) => <ActivityRow key={ev.id} event={ev} cameraName={camera.name} />)
          ) : (
            <div className="p-6 text-sm text-[oklch(55%_0.01_265)] text-center">No events yet.</div>
          )}
        </div>
      )}
    </div>
  );
}
