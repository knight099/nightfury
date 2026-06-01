"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Skeleton } from "@/components/ui/Skeleton";
import Link from "next/link";
import { Plus, Trash2, Square, MoreVertical, Link2 } from "lucide-react";
import { useAuthStore } from "@/lib/store";
import { useEventsSocket } from "@/lib/useEventsSocket";
import { CameraTile } from "@/components/cameras/CameraTile";
import { ZonesEditor } from "@/components/cameras/ZonesEditor";
import type { Camera, Event, PaginatedResponse, Site } from "@/types";

export default function CamerasPage() {
  const queryClient = useQueryClient();
  const { user } = useAuthStore();
  const [showAdd, setShowAdd] = useState(false);
  const [zonesCamera, setZonesCamera] = useState<Camera | null>(null);
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const canManage = user?.role === "super_admin" || user?.role === "owner" || user?.role === "admin";

  const { data: cameras, isLoading } = useQuery({
    queryKey: ["cameras"],
    queryFn: () => api.getCameras(),
  });

  const { data: sites } = useQuery({
    queryKey: ["sites"],
    queryFn: () => api.getSites(),
  });

  const { data: latestEvents } = useQuery<PaginatedResponse<Event>>({
    queryKey: ["events", "latest-by-camera"],
    queryFn: () => api.getEvents({ per_page: "100" }),
  });

  const lastEventByCamera = useMemo(() => {
    const map: Record<string, string> = {};
    for (const ev of latestEvents?.events || []) {
      const existing = map[ev.camera_id];
      if (!existing || new Date(ev.timestamp) > new Date(existing)) {
        map[ev.camera_id] = ev.timestamp;
      }
    }
    return map;
  }, [latestEvents]);

  const handleNewEvent = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["events", "latest-by-camera"] });
  }, [queryClient]);

  useEventsSocket(handleNewEvent);

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.deleteCamera(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["cameras"] }),
  });

  useEffect(() => {
    if (!openMenuId) return;
    const close = () => setOpenMenuId(null);
    window.addEventListener("click", close);
    return () => window.removeEventListener("click", close);
  }, [openMenuId]);

  const cameraCount = cameras?.length ?? 0;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-baseline gap-3">
          <h1 className="text-xl font-bold">Cameras</h1>
          <span className="text-xs text-[#666666]">{cameraCount} total</span>
        </div>
        {canManage && (
          <div className="flex items-center gap-2">
            <Link
              href="/cameras/connect"
              className="flex items-center gap-2 px-3 py-1.5 bg-[#1A1A1A] text-[#A3A3A3] border border-[#2A2A2A] rounded-md text-sm hover:text-[#F5F5F5] transition-colors"
            >
              <Link2 size={16} /> Connect Camera
            </Link>
            <button
              onClick={() => setShowAdd(true)}
              className="flex items-center gap-2 px-3 py-1.5 bg-[#1E90FF] text-white rounded-md text-sm hover:bg-[#3BA0FF] transition-colors"
            >
              <Plus size={16} /> Add Camera
            </button>
          </div>
        )}
      </div>

      {showAdd && <AddCameraForm sites={sites || []} onClose={() => setShowAdd(false)} />}

      {isLoading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="w-full" style={{ aspectRatio: "16 / 9" }}>
              <Skeleton className="w-full h-full rounded-lg" />
            </div>
          ))}
        </div>
      ) : cameraCount === 0 ? (
        <div className="bg-[#111111] border border-[#2A2A2A] rounded-lg p-8 text-center space-y-3">
          <div className="text-sm text-[#F5F5F5]">No cameras yet</div>
          <div className="text-xs text-[#A3A3A3]">Connect your first camera to start receiving AI-powered events.</div>
          {canManage && (
            <button
              onClick={() => setShowAdd(true)}
              className="inline-flex items-center gap-2 px-3 py-1.5 bg-[#1E90FF] text-white rounded-md text-sm hover:bg-[#3BA0FF] transition-colors"
            >
              <Plus size={16} /> Add Camera
            </button>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {cameras?.map((cam: Camera) => (
            <div key={cam.id} className="relative">
              <CameraTile camera={cam} lastEventAt={lastEventByCamera[cam.id] ?? null} />
              {canManage && (
                <div className="absolute top-2 right-2">
                  <button
                    onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      setOpenMenuId(openMenuId === cam.id ? null : cam.id);
                    }}
                    className="p-1 rounded bg-black/60 text-[#F5F5F5] hover:bg-black/80 transition-colors"
                    aria-label="Camera actions"
                  >
                    <MoreVertical size={14} />
                  </button>
                  {openMenuId === cam.id && (
                    <div
                      onClick={(e) => e.stopPropagation()}
                      className="absolute right-0 mt-1 w-36 bg-[#1A1A1A] border border-[#2A2A2A] rounded-md shadow-lg z-10 overflow-hidden"
                    >
                      <button
                        onClick={() => {
                          setZonesCamera(cam);
                          setOpenMenuId(null);
                        }}
                        className="flex items-center gap-2 w-full px-3 py-2 text-xs text-[#A3A3A3] hover:bg-[#111111] hover:text-[#F5F5F5] transition-colors"
                      >
                        <Square size={12} /> Edit Zones
                      </button>
                      <button
                        onClick={() => {
                          if (window.confirm(`Delete camera "${cam.name}"?`)) {
                            deleteMutation.mutate(cam.id);
                          }
                          setOpenMenuId(null);
                        }}
                        className="flex items-center gap-2 w-full px-3 py-2 text-xs text-red-400 hover:bg-[#111111] transition-colors"
                      >
                        <Trash2 size={12} /> Delete
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {zonesCamera && (
        <ZonesEditor
          camera={zonesCamera}
          onClose={() => setZonesCamera(null)}
        />
      )}
    </div>
  );
}

function AddCameraForm({ sites, onClose }: { sites: Site[]; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [siteId, setSiteId] = useState(sites[0]?.id || "");
  const [mode, setMode] = useState("rtsp_pull");
  const [rtspUrl, setRtspUrl] = useState("");
  const [events, setEvents] = useState(["person", "vehicle", "intrusion"]);
  const [sensitivity, setSensitivity] = useState("medium");
  const [result, setResult] = useState<{ stream_key?: string; ingest_endpoint?: string } | null>(null);

  const createMutation = useMutation({
    mutationFn: () =>
      api.createCamera({
        name,
        site_id: siteId,
        ingest_mode: mode as "rtsp_pull" | "rtmp_push" | "srt_push",
        ...(mode === "rtsp_pull" && { rtsp_url: rtspUrl }),
        enabled_events: events,
        sensitivity: sensitivity as "low" | "medium" | "high",
      }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["cameras"] });
      if (data.stream_key) {
        setResult(data);
      } else {
        onClose();
      }
    },
  });

  const eventOptions = ["person", "vehicle", "intrusion", "loitering", "crowd_spike", "fire_smoke", "ppe_violation", "object_left"];

  if (result) {
    return (
      <div className="bg-[#111111] border border-[#2A2A2A] rounded-lg p-4 space-y-3">
        <h3 className="text-sm font-medium text-green-400">Camera created! Push your stream to:</h3>
        <div className="text-xs space-y-2">
          <div>Endpoint: <code className="text-[#1E90FF]">{result.ingest_endpoint}</code></div>
          <div>Stream Key: <code className="text-[#1E90FF]">{result.stream_key}</code></div>
        </div>
        <button onClick={onClose} className="text-xs text-[#666666] hover:text-[#F5F5F5]">Close</button>
      </div>
    );
  }

  return (
    <div className="bg-[#111111] border border-[#2A2A2A] rounded-lg p-4 space-y-3">
      <h3 className="text-sm font-medium">Add Camera</h3>
      <div className="grid grid-cols-2 gap-3">
        <input
          placeholder="Camera name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="px-3 py-1.5 bg-[#1F1F1F] border border-[#2A2A2A] rounded text-sm"
        />
        <select
          value={siteId}
          onChange={(e) => setSiteId(e.target.value)}
          className="px-3 py-1.5 bg-[#1F1F1F] border border-[#2A2A2A] rounded text-sm"
        >
          {sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          {sites.length === 0 && <option value="">No sites — create one first</option>}
        </select>
        <select
          value={mode}
          onChange={(e) => setMode(e.target.value)}
          className="px-3 py-1.5 bg-[#1F1F1F] border border-[#2A2A2A] rounded text-sm"
        >
          <option value="rtsp_pull">RTSP Pull (I provide URL)</option>
          <option value="rtmp_push">RTMP Push (give me endpoint)</option>
        </select>
        <select
          value={sensitivity}
          onChange={(e) => setSensitivity(e.target.value)}
          className="px-3 py-1.5 bg-[#1F1F1F] border border-[#2A2A2A] rounded text-sm"
        >
          <option value="low">Low sensitivity</option>
          <option value="medium">Medium sensitivity</option>
          <option value="high">High sensitivity</option>
        </select>
      </div>
      {mode === "rtsp_pull" && (
        <input
          placeholder="rtsp://user:pass@ip:554/stream"
          value={rtspUrl}
          onChange={(e) => setRtspUrl(e.target.value)}
          className="w-full px-3 py-1.5 bg-[#1F1F1F] border border-[#2A2A2A] rounded text-sm"
        />
      )}
      <div className="flex flex-wrap gap-2">
        {eventOptions.map((ev) => (
          <label key={ev} className="flex items-center gap-1 text-xs">
            <input
              type="checkbox"
              checked={events.includes(ev)}
              onChange={(e) =>
                setEvents(e.target.checked ? [...events, ev] : events.filter((x) => x !== ev))
              }
              className="rounded border-[#2A2A2A]"
            />
            {ev.replace("_", " ")}
          </label>
        ))}
      </div>
      <div className="flex gap-2">
        <button
          onClick={() => createMutation.mutate()}
          disabled={!name || !siteId}
          className="px-3 py-1.5 bg-[#1E90FF] text-white rounded text-sm disabled:opacity-50"
        >
          Create
        </button>
        <button onClick={onClose} className="px-3 py-1.5 text-[#666666] text-sm">Cancel</button>
      </div>
    </div>
  );
}
