"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { StatusDot } from "@/components/shared/status-dot";
import { Skeleton } from "@/components/ui/Skeleton";
import type { Camera, CameraConnection } from "@/types";

/**
 * Shared with the V2-styled shell (components/v2/CameraMapV2.tsx) so the two
 * renderings of this page can look different without the privacy claim
 * drifting between them.
 */
export const MAP_INTRO_COPY =
  "Click two cameras to mark them as physically connected — a doorway, hallway or gate. Nightwatch uses these links to spot activity moving between cameras.";
export const MAP_PRIVACY_CAVEAT =
  "This links events by location and timing only. It does not recognise faces or identify people, so a linked path may or may not be the same person.";

/**
 * Camera map — draw which cameras are physically connected.
 *
 * Click two cameras to link them ("joined by a hallway"). Those links are the
 * entire basis of journeys: events on connected cameras, close in time, get
 * correlated into a path.
 *
 * This is NOT face recognition or person tracking, and the copy on this page
 * has to keep saying so. It is adjacency the operator drew plus timing — a
 * plausibility signal, never an identity claim.
 */
export function CameraMap({ className }: { className?: string }) {
  const qc = useQueryClient();
  const [siteId, setSiteId] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  const { data: sites } = useQuery({ queryKey: ["sites"], queryFn: () => api.getSites() });
  const activeSiteId = siteId ?? sites?.[0]?.id ?? null;

  const { data: cameras, isLoading: camsLoading } = useQuery({
    queryKey: ["cameras", activeSiteId],
    queryFn: () => api.getCameras({ site_id: activeSiteId as string }),
    enabled: !!activeSiteId,
  });

  const { data: connections, isLoading: connLoading } = useQuery({
    queryKey: ["camera-connections", activeSiteId],
    queryFn: () => api.getCameraConnections(activeSiteId as string),
    enabled: !!activeSiteId,
  });

  const invalidate = () =>
    qc.invalidateQueries({ queryKey: ["camera-connections", activeSiteId] });

  const create = useMutation({
    mutationFn: (v: { a: string; b: string }) =>
      api.createCameraConnection(activeSiteId as string, {
        camera_a_id: v.a,
        camera_b_id: v.b,
      }),
    onSuccess: invalidate,
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.deleteCameraConnection(activeSiteId as string, id),
    onSuccess: invalidate,
  });

  const relabel = useMutation({
    mutationFn: (v: { id: string; label: string }) =>
      api.updateCameraConnection(activeSiteId as string, v.id, v.label || null),
    onSuccess: invalidate,
  });

  const byId = useMemo(
    () => Object.fromEntries((cameras ?? []).map((c) => [c.id, c])),
    [cameras]
  );

  // Which cameras the selected one is already linked to — so the grid can
  // show what clicking again would remove rather than duplicate.
  const linkedToSelected = useMemo(() => {
    if (!selected) return new Set<string>();
    const s = new Set<string>();
    for (const c of connections ?? []) {
      if (c.camera_a_id === selected) s.add(c.camera_b_id);
      if (c.camera_b_id === selected) s.add(c.camera_a_id);
    }
    return s;
  }, [connections, selected]);

  function handleClick(cameraId: string) {
    if (!selected) {
      setSelected(cameraId);
      return;
    }
    if (selected === cameraId) {
      setSelected(null);
      return;
    }
    const existing = (connections ?? []).find(
      (c) =>
        (c.camera_a_id === selected && c.camera_b_id === cameraId) ||
        (c.camera_b_id === selected && c.camera_a_id === cameraId)
    );
    if (existing) {
      remove.mutate(existing.id);
    } else {
      create.mutate({ a: selected, b: cameraId });
    }
    setSelected(null);
  }

  if (!sites?.length) {
    return <p className="text-sm text-[#A3A3A3]">No sites yet.</p>;
  }

  return (
    <div className={className}>
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-heading text-2xl font-bold text-[#F5F5F5]">Camera map</h1>
          <p className="mt-1 max-w-2xl text-sm text-[#A3A3A3]">{MAP_INTRO_COPY}</p>
          <p className="mt-1 max-w-2xl text-xs text-[#666666]">{MAP_PRIVACY_CAVEAT}</p>
        </div>
        <select
          value={activeSiteId ?? ""}
          onChange={(e) => {
            setSiteId(e.target.value);
            setSelected(null);
          }}
          className="rounded-md border border-[#2A2A2A] bg-[#1F1F1F] px-3 py-2 text-sm text-[#F5F5F5] transition-colors focus:border-[#1E90FF] focus:outline-none"
        >
          {sites.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </header>

      {selected && (
        <div className="mb-3 flex items-center gap-3 rounded-md border border-[#1E90FF]/40 bg-[#1E90FF]/5 px-3 py-2">
          <span className="text-sm text-[#F5F5F5]">
            Now click the camera that <strong>{byId[selected]?.name}</strong> connects to.
          </span>
          <button
            onClick={() => setSelected(null)}
            className="ml-auto text-xs text-[#A3A3A3] transition-colors hover:text-[#F5F5F5]"
          >
            Cancel
          </button>
        </div>
      )}

      {camsLoading || connLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : (cameras ?? []).length === 0 ? (
        <p className="rounded-lg border border-[#2A2A2A] bg-[#111111] p-6 text-sm text-[#A3A3A3]">
          No cameras at this site yet.
        </p>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {(cameras ?? []).map((camera: Camera) => {
            const isSelected = selected === camera.id;
            const isLinked = linkedToSelected.has(camera.id);
            return (
              <button
                key={camera.id}
                onClick={() => handleClick(camera.id)}
                className={`flex flex-col items-start gap-1 rounded-lg border p-3 text-left transition-colors ${
                  isSelected
                    ? "border-[#1E90FF] bg-[#1E90FF]/10"
                    : isLinked
                      ? "border-green-400/50 bg-green-400/5 hover:bg-green-400/10"
                      : "border-[#2A2A2A] bg-[#111111] hover:bg-[#1A1A1A]"
                }`}
              >
                <span className="flex items-center gap-2 text-sm text-[#F5F5F5]">
                  <StatusDot status={camera.status} />
                  <span className="truncate">{camera.name}</span>
                </span>
                {selected && isLinked && (
                  <span className="text-xs text-green-400">
                    connected — click to unlink
                  </span>
                )}
              </button>
            );
          })}
        </div>
      )}

      <section className="mt-6">
        <h2 className="font-heading text-lg font-semibold text-[#F5F5F5]">
          Connections
        </h2>
        {(connections ?? []).length === 0 ? (
          <p className="mt-2 text-sm text-[#666666]">
            No connections yet — click two cameras above to link them.
          </p>
        ) : (
          <ul className="mt-2 space-y-2">
            {(connections ?? []).map((conn: CameraConnection) => (
              <li
                key={conn.id}
                className="flex flex-wrap items-center gap-2 rounded-md border border-[#2A2A2A] bg-[#111111] px-3 py-2"
              >
                <span className="text-sm text-[#F5F5F5]">
                  {byId[conn.camera_a_id]?.name ?? "?"}
                  <span className="mx-2 text-[#666666]">↔</span>
                  {byId[conn.camera_b_id]?.name ?? "?"}
                </span>
                <input
                  defaultValue={conn.label ?? ""}
                  placeholder="Label (e.g. Back hallway)"
                  onBlur={(e) => {
                    if (e.target.value !== (conn.label ?? "")) {
                      relabel.mutate({ id: conn.id, label: e.target.value });
                    }
                  }}
                  className="ml-auto w-48 rounded-md border border-[#2A2A2A] bg-[#1F1F1F] px-2 py-1 text-xs text-[#F5F5F5] transition-colors focus:border-[#1E90FF] focus:outline-none"
                />
                <button
                  onClick={() => remove.mutate(conn.id)}
                  className="rounded px-2 py-1 text-xs text-red-400 transition-colors hover:bg-red-400/10"
                  title="Remove this connection"
                >
                  ✕
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
