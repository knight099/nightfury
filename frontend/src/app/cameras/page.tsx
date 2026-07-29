"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Skeleton } from "@/components/ui/Skeleton";
import Link from "next/link";
import { Plus, Trash2, Square, MoreVertical, Link2, RotateCcw } from "lucide-react";
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
  const [showDeleted, setShowDeleted] = useState(false);
  const isSuperAdmin = user?.role === "super_admin";
  const canManage = isSuperAdmin || user?.role === "owner" || user?.role === "admin";

  const { data: cameras, isLoading } = useQuery({
    queryKey: ["cameras", showDeleted],
    queryFn: () => api.getCameras({ include_deleted: showDeleted }),
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

  const restoreMutation = useMutation({
    mutationFn: (id: string) => api.restoreCamera(id),
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
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-baseline gap-3">
          <h1 className="text-xl font-bold">Cameras</h1>
          <span className="text-xs text-[#666666]">{cameraCount} total</span>
          {isSuperAdmin && (
            <label className="flex items-center gap-2 text-xs text-[#A3A3A3]">
              <input
                type="checkbox"
                checked={showDeleted}
                onChange={(e) => setShowDeleted(e.target.checked)}
                className="rounded"
              />
              Show deleted
            </label>
          )}
        </div>
        {canManage && (
          <div className="flex items-center gap-2 w-full sm:w-auto">
            <Link
              href="/cameras/connect"
              className="flex-1 sm:flex-none justify-center flex items-center gap-2 px-3 py-2.5 sm:py-1.5 bg-[#1A1A1A] text-[#A3A3A3] border border-[#2A2A2A] rounded-md text-sm hover:text-[#F5F5F5] transition-colors"
            >
              <Link2 size={16} /> Connect Camera
            </Link>
            <button
              onClick={() => setShowAdd(true)}
              className="flex-1 sm:flex-none justify-center flex items-center gap-2 px-3 py-2.5 sm:py-1.5 bg-[#1E90FF] text-white rounded-md text-sm hover:bg-[#3BA0FF] glow-accent-hover transition-colors"
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
        <div className="bg-[#111111] border border-[#2A2A2A] rounded-lg p-10 text-center space-y-4">
          <div className="mx-auto w-14 h-14 rounded-full bg-[#1E90FF]/10 flex items-center justify-center">
            <Plus size={26} className="text-[#1E90FF]" />
          </div>
          <div className="text-base font-medium text-[#F5F5F5]">Add your first camera</div>
          <div className="text-sm text-[#A3A3A3] max-w-sm mx-auto">
            Once connected, Nightwatch watches it 24/7 and tells you the moment something happens.
          </div>
          {canManage && (
            <Link
              href="/cameras/connect"
              className="inline-flex items-center gap-2 px-5 py-3 bg-[#1E90FF] text-white rounded-md text-sm font-medium hover:bg-[#3BA0FF] glow-accent transition-colors"
            >
              <Link2 size={16} /> Connect a camera
            </Link>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {cameras?.map((cam: Camera) => (
            <div key={cam.id} className="relative">
              {cam.deleted_at ? (
                <div className="w-full h-full flex flex-col items-center justify-center gap-2 bg-[#111111] border border-dashed border-[#2A2A2A] rounded-lg p-6" style={{ aspectRatio: "16 / 9" }}>
                  <span className="text-sm font-medium text-[#A3A3A3]">{cam.name}</span>
                  <span className="text-xs px-2 py-0.5 rounded bg-[#EF4444]/20 text-[#EF4444]">deleted</span>
                  <button
                    onClick={() => restoreMutation.mutate(cam.id)}
                    className="mt-1 flex items-center gap-1 text-xs px-3 py-1.5 bg-[#1A1A1A] text-[#A3A3A3] border border-[#2A2A2A] rounded-md hover:text-[#4ADE80] transition-colors"
                  >
                    <RotateCcw size={12} /> Restore
                  </button>
                </div>
              ) : (
                <CameraTile camera={cam} lastEventAt={lastEventByCamera[cam.id] ?? null} />
              )}
              {canManage && !cam.deleted_at && (
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
    <div className="bg-[#111111] border border-[#2A2A2A] rounded-lg p-4 space-y-4">
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-sm font-medium">Add Camera (advanced)</h3>
        <Link href="/cameras/connect" className="text-xs text-[#1E90FF] hover:text-[#3BA0FF] transition-colors shrink-0">
          Not technical? Use the guided setup →
        </Link>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <input
          placeholder="Camera name (e.g. Front Gate)"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="px-3 py-2.5 sm:py-2 bg-[#1F1F1F] border border-[#2A2A2A] rounded text-sm focus:outline-none focus:border-[#1E90FF]"
        />
        <select
          value={siteId}
          onChange={(e) => setSiteId(e.target.value)}
          className="px-3 py-2.5 sm:py-2 bg-[#1F1F1F] border border-[#2A2A2A] rounded text-sm focus:outline-none focus:border-[#1E90FF]"
        >
          {sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          {sites.length === 0 && <option value="">No sites — create one first</option>}
        </select>
        <select
          value={mode}
          onChange={(e) => setMode(e.target.value)}
          className="px-3 py-2.5 sm:py-2 bg-[#1F1F1F] border border-[#2A2A2A] rounded text-sm focus:outline-none focus:border-[#1E90FF]"
        >
          <option value="rtsp_pull">RTSP Pull (I provide URL)</option>
          <option value="rtmp_push">RTMP Push (give me endpoint)</option>
        </select>
      </div>
      {mode === "rtsp_pull" && (
        <input
          placeholder="rtsp://user:pass@ip:554/stream"
          value={rtspUrl}
          onChange={(e) => setRtspUrl(e.target.value)}
          className="w-full px-3 py-2.5 sm:py-2 bg-[#1F1F1F] border border-[#2A2A2A] rounded text-sm font-mono focus:outline-none focus:border-[#1E90FF]"
        />
      )}
      <div>
        <span className="text-[11px] text-[#A3A3A3]">How alert should this camera be?</span>
        <div className="mt-1.5 grid grid-cols-1 sm:grid-cols-3 gap-2">
          {[
            { value: "low", title: "Fewer alerts", desc: "Only clear, obvious activity" },
            { value: "medium", title: "Balanced", desc: "Good for most homes & shops" },
            { value: "high", title: "Catch everything", desc: "More alerts, some may be minor" },
          ].map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => setSensitivity(opt.value)}
              className={`text-left p-3 rounded-lg border transition-colors ${
                sensitivity === opt.value
                  ? "border-[#1E90FF] bg-[#1E90FF]/10"
                  : "border-[#2A2A2A] bg-[#1A1A1A] hover:border-[#3A3A3A]"
              }`}
            >
              <div className="text-xs font-medium text-[#F5F5F5]">{opt.title}</div>
              <div className="mt-0.5 text-[11px] text-[#A3A3A3]">{opt.desc}</div>
            </button>
          ))}
        </div>
      </div>
      <div>
        <span className="text-[11px] text-[#A3A3A3]">What should this camera watch for?</span>
        <div className="mt-1.5 flex flex-wrap gap-2">
          {eventOptions.map((ev) => (
            <button
              key={ev}
              type="button"
              onClick={() =>
                setEvents(events.includes(ev) ? events.filter((x) => x !== ev) : [...events, ev])
              }
              className={`px-3 py-2 rounded-full text-xs capitalize border transition-colors ${
                events.includes(ev)
                  ? "border-[#1E90FF] bg-[#1E90FF]/10 text-[#1E90FF]"
                  : "border-[#2A2A2A] bg-[#1A1A1A] text-[#A3A3A3] hover:text-[#F5F5F5]"
              }`}
            >
              {ev.replace(/_/g, " ")}
            </button>
          ))}
        </div>
      </div>
      <div className="flex gap-2">
        <button
          onClick={() => createMutation.mutate()}
          disabled={!name || !siteId}
          className="px-5 py-2.5 bg-[#1E90FF] text-white rounded-md text-sm font-medium hover:bg-[#3BA0FF] glow-accent-hover disabled:opacity-50 transition-colors"
        >
          Create camera
        </button>
        <button onClick={onClose} className="px-4 py-2.5 text-[#A3A3A3] hover:text-[#F5F5F5] text-sm transition-colors">Cancel</button>
      </div>
    </div>
  );
}
