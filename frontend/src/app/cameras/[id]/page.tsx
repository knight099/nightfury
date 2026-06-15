"use client";

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { ArrowLeft, Square, Trash2, VideoOff } from "lucide-react";
import { api } from "@/lib/api";
import { Skeleton } from "@/components/ui/Skeleton";
import { SeverityBadge } from "@/components/shared/severity-badge";
import { StatusDot } from "@/components/shared/status-dot";
import { useAuthStore } from "@/lib/store";
import { useEventsSocket } from "@/lib/useEventsSocket";
import { useChatContextStore } from "@/lib/chatContext";
import { ZonesEditor } from "@/components/cameras/ZonesEditor";
import type { Camera, Event, PaginatedResponse } from "@/types";

function relativeTime(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  if (diffMs < 0) return "just now";
  const sec = Math.floor(diffMs / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.floor(hr / 24);
  return `${day}d ago`;
}

export default function CameraDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const queryClient = useQueryClient();
  const { user } = useAuthStore();
  const setCameraContext = useChatContextStore((s) => s.setCameraContext);
  const canManage = user?.role === "super_admin" || user?.role === "owner" || user?.role === "admin";

  const { data: cameras, isLoading: camsLoading } = useQuery({
    queryKey: ["cameras"],
    queryFn: () => api.getCameras(),
  });

  const camera: Camera | undefined = cameras?.find((c) => c.id === id);

  useEffect(() => {
    setCameraContext(id);
    return () => setCameraContext(null);
  }, [id, setCameraContext]);

  const [showZones, setShowZones] = useState(false);

  const { data: frame } = useQuery({
    queryKey: ["camera-latest-frame", id],
    queryFn: () => api.getCameraLatestFrame(id),
    refetchInterval: 1000,
    refetchIntervalInBackground: false,
    enabled: !!camera,
  });

  const { data: eventsData, isLoading: eventsLoading } = useQuery<PaginatedResponse<Event>>({
    queryKey: ["events", "camera", id],
    queryFn: () => api.getEvents({ camera_id: id, per_page: "20" }),
    enabled: !!camera,
  });

  const [liveEvents, setLiveEvents] = useState<Event[]>([]);

  useEffect(() => {
    setLiveEvents(eventsData?.events ?? []);
  }, [eventsData]);

  const handleNewEvent = useCallback(
    (event: Event) => {
      if (event.camera_id !== id) return;
      setLiveEvents((prev) => {
        if (prev.some((e) => e.id === event.id)) return prev;
        return [event, ...prev].slice(0, 20);
      });
    },
    [id]
  );

  useEventsSocket(handleNewEvent);

  const deleteMutation = useMutation({
    mutationFn: () => api.deleteCamera(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["cameras"] });
      router.replace("/cameras");
    },
  });

  if (camsLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2">
            <div className="w-full" style={{ aspectRatio: "16 / 9" }}>
              <Skeleton className="w-full h-full rounded-lg" />
            </div>
          </div>
          <Skeleton className="h-64 rounded-lg" />
        </div>
      </div>
    );
  }

  if (!camera) {
    return (
      <div className="space-y-4">
        <Link href="/cameras" className="inline-flex items-center gap-1 text-xs text-[#A3A3A3] hover:text-[#F5F5F5] transition-colors">
          <ArrowLeft size={14} /> Back to cameras
        </Link>
        <div className="bg-[#111111] border border-[#2A2A2A] rounded-lg p-8 text-center">
          <div className="text-sm text-[#F5F5F5]">Camera not found</div>
          <div className="text-xs text-[#A3A3A3] mt-2">It may have been deleted or you don&apos;t have access.</div>
        </div>
      </div>
    );
  }

  const lastFrameLabel = frame?.updated_at
    ? `Last frame: ${relativeTime(frame.updated_at)}`
    : camera.last_frame_at
    ? `Last frame: ${relativeTime(camera.last_frame_at)}`
    : "No frames received";

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3 min-w-0">
          <Link href="/cameras" className="inline-flex items-center gap-1 text-xs text-[#A3A3A3] hover:text-[#F5F5F5] transition-colors">
            <ArrowLeft size={14} /> Back
          </Link>
          <h1 className="text-xl font-bold truncate">{camera.name}</h1>
          <span className="inline-flex items-center gap-1.5 px-2 py-0.5 bg-[#1A1A1A] border border-[#2A2A2A] rounded text-[10px] text-[#A3A3A3] uppercase tracking-wider">
            <StatusDot status={camera.status} />
            {camera.status}
          </span>
        </div>
        {canManage && (
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowZones(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-[#1A1A1A] text-[#A3A3A3] border border-[#2A2A2A] rounded-md text-xs hover:text-[#F5F5F5] hover:border-[#1E90FF] transition-colors"
            >
              <Square size={12} /> Edit Zones
            </button>
            <button
              onClick={() => {
                if (window.confirm(`Delete camera "${camera.name}"?`)) {
                  deleteMutation.mutate();
                }
              }}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-[#1A1A1A] text-red-400 border border-[#2A2A2A] rounded-md text-xs hover:bg-red-500/10 transition-colors"
            >
              <Trash2 size={12} /> Delete
            </button>
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 space-y-3">
          <div className="relative w-full bg-[#111111] border border-[#2A2A2A] rounded-lg overflow-hidden" style={{ aspectRatio: "16 / 9" }}>
            {frame?.url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={
                  frame.url.startsWith("data:")
                    ? frame.url
                    : `${frame.url}${frame.url.includes("?") ? "&" : "?"}t=${encodeURIComponent(frame.updated_at)}`
                }
                alt={camera.name}
                className="absolute inset-0 w-full h-full object-contain bg-black"
                draggable={false}
              />
            ) : (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-[#666666]">
                <VideoOff size={48} />
                <span className="text-xs uppercase tracking-wider">No signal</span>
              </div>
            )}
          </div>
          <div className="text-[10px] text-[#666666]">{lastFrameLabel}</div>
        </div>

        <aside className="space-y-3">
          <div className="bg-[#111111] border border-[#2A2A2A] rounded-lg p-4 space-y-3">
            <div className="text-xs font-medium text-[#F5F5F5]">Camera</div>
            <div className="space-y-2 text-xs text-[#A3A3A3]">
              <div className="flex justify-between gap-3">
                <span>Mode</span>
                <span className="text-[#F5F5F5]">{camera.ingest_mode.replace("_", " ")}</span>
              </div>
              <div className="flex justify-between gap-3">
                <span>Sensitivity</span>
                <span className="text-[#F5F5F5]">{camera.sensitivity}</span>
              </div>
              <div className="flex justify-between gap-3">
                <span>Zones</span>
                <span className="text-[#F5F5F5]">{camera.detection_zones?.length ?? 0}</span>
              </div>
              <div className="flex justify-between gap-3">
                <span>Idle / Active fps</span>
                <span className="text-[#F5F5F5]">{camera.idle_fps} / {camera.active_fps}</span>
              </div>
              {camera.stream_key && (
                <div className="space-y-1">
                  <div>Stream key</div>
                  <code className="block text-[10px] text-[#1E90FF] break-all">{camera.stream_key}</code>
                </div>
              )}
            </div>
          </div>

          <div className="bg-[#111111] border border-[#2A2A2A] rounded-lg p-4 space-y-2">
            <div className="text-xs font-medium text-[#F5F5F5]">Enabled events</div>
            <div className="flex flex-wrap gap-1.5">
              {camera.enabled_events.length === 0 && (
                <span className="text-[10px] text-[#666666]">None enabled</span>
              )}
              {camera.enabled_events.map((ev) => (
                <span
                  key={ev}
                  className="px-2 py-0.5 bg-[#1A1A1A] border border-[#2A2A2A] rounded text-[10px] text-[#A3A3A3]"
                >
                  {ev.replace("_", " ")}
                </span>
              ))}
            </div>
          </div>
        </aside>
      </div>

      <div className="bg-[#111111] border border-[#2A2A2A] rounded-lg overflow-hidden">
        <div className="px-4 py-3 border-b border-[#2A2A2A] text-sm font-medium">
          Recent events
        </div>
        {eventsLoading ? (
          <div className="p-3 space-y-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-16 rounded-md" />
            ))}
          </div>
        ) : liveEvents.length === 0 ? (
          <div className="p-8 text-center text-sm text-[#666666]">No events for this camera yet</div>
        ) : (
          <div className="divide-y divide-[#2A2A2A]">
            {liveEvents.map((event) => (
              <Link
                key={event.id}
                href={`/events/${event.id}`}
                className="flex items-center gap-3 px-4 py-3 hover:bg-[#1A1A1A] transition-colors"
              >
                <div className="w-16 h-10 bg-[#1F1F1F] rounded overflow-hidden shrink-0">
                  {event.snapshot_url && (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={event.snapshot_url}
                      alt=""
                      className="w-full h-full object-cover"
                      draggable={false}
                    />
                  )}
                </div>
                <div className="w-20 text-xs text-[#666666] font-mono shrink-0">
                  {new Date(event.timestamp).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}
                </div>
                <div className="w-28 text-sm truncate shrink-0">{event.event_type.replace("_", " ")}</div>
                <SeverityBadge severity={event.severity} />
                <div className="w-12 text-xs text-[#666666] shrink-0">{(event.confidence * 100).toFixed(0)}%</div>
                <div className="flex-1 text-xs text-[#A3A3A3] truncate">{event.description}</div>
              </Link>
            ))}
          </div>
        )}
      </div>

      {showZones && (
        <ZonesEditor camera={camera} onClose={() => setShowZones(false)} />
      )}
    </div>
  );
}
