"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Camera as CameraIcon, X } from "lucide-react";
import { api } from "@/lib/api";
import { StatusDot } from "@/components/shared/status-dot";
import { Skeleton } from "@/components/ui/Skeleton";
import { Page, PageHeader, EmptyState, inputClass } from "@/components/v2/ui";
import { MAP_INTRO_COPY, MAP_PRIVACY_CAVEAT } from "@/components/map/CameraMap";
import type { CameraConnection } from "@/types";

/**
 * Camera map (V2) — a spatial node/edge canvas, matching the original
 * mockup's mapNodes/mapLines design (docs/superpowers/specs/2026-08-13-
 * camera-map-journeys-design.md) rather than the grid-of-buttons-plus-a-list
 * the first V2 port shipped with. Data and mutation logic are unchanged from
 * components/map/CameraMap.tsx; copy is imported from there so the privacy
 * claim can't drift between the two shells.
 *
 * Cameras have no real coordinates, so position is a deterministic grid
 * layout over the panel rather than anything geographic — good enough to
 * turn "which cameras are linked" into something you see, not something you
 * read out of a list.
 */
export default function CameraMapV2() {
  const qc = useQueryClient();
  const [siteId, setSiteId] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  const { data: sites, isLoading: sitesLoading } = useQuery({
    queryKey: ["sites"],
    queryFn: () => api.getSites(),
  });
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

  // Deterministic grid layout in percentage space — stable across
  // re-renders as long as the camera list doesn't reorder.
  const positions = useMemo(() => {
    const ids = (cameras ?? []).map((c) => c.id);
    const n = ids.length;
    const cols = Math.max(1, Math.ceil(Math.sqrt(n)));
    const rows = Math.max(1, Math.ceil(n / cols));
    const pos: Record<string, [number, number]> = {};
    ids.forEach((id, i) => {
      const col = i % cols;
      const row = Math.floor(i / cols);
      const x = cols === 1 ? 50 : 15 + col * (70 / (cols - 1));
      const y = rows === 1 ? 50 : 20 + row * (60 / (rows - 1));
      pos[id] = [x, y];
    });
    return pos;
  }, [cameras]);

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

  if (sitesLoading) {
    return (
      <Page wide>
        <Skeleton className="h-64 w-full" />
      </Page>
    );
  }

  if (!sites?.length) {
    return (
      <Page wide>
        <PageHeader title="Camera map" />
        <EmptyState title="No sites yet" hint="Add a site to start mapping cameras." />
      </Page>
    );
  }

  const hint = selected
    ? `Click another camera to link with ${byId[selected]?.name ?? "it"}`
    : "Click two cameras to connect them";

  return (
    <Page wide>
      <PageHeader
        title="Camera map"
        subtitle={MAP_INTRO_COPY}
        action={
          <select
            value={activeSiteId ?? ""}
            onChange={(e) => {
              setSiteId(e.target.value);
              setSelected(null);
            }}
            className={`${inputClass} !w-auto shrink-0`}
          >
            {sites.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        }
      />

      <p className="-mt-4 mb-6 max-w-2xl text-[12px] leading-relaxed text-[oklch(55%_0.01_265)]">
        {MAP_PRIVACY_CAVEAT}
      </p>

      {camsLoading || connLoading ? (
        <Skeleton className="h-[520px] w-full" />
      ) : (cameras ?? []).length === 0 ? (
        <EmptyState
          title="No cameras at this site yet"
          hint="Add a camera before drawing connections."
        />
      ) : (
        <div
          className="relative h-[520px] overflow-hidden rounded-[20px] border border-[oklch(22%_0.015_265)]"
          style={{
            backgroundColor: "oklch(11% 0.015 265)",
            backgroundImage: "radial-gradient(oklch(22% 0.015 265) 1px, transparent 1px)",
            backgroundSize: "22px 22px",
          }}
        >
          <div className="absolute left-4 top-4 flex items-center gap-2 rounded-full border border-[oklch(24%_0.015_265)] bg-[oklch(15%_0.015_265)]/90 px-3 py-1.5 text-[11.5px] font-semibold text-[oklch(70%_0.01_265)]">
            {hint}
            {selected && (
              <button
                onClick={() => setSelected(null)}
                className="ml-1 text-[oklch(85%_0.16_84)] hover:underline"
              >
                Cancel
              </button>
            )}
          </div>
          <div className="absolute right-4 top-4 rounded-full bg-[oklch(24%_0.06_84)] px-2.5 py-1.5 text-[11px] font-semibold text-[oklch(85%_0.15_84)]">
            {(connections ?? []).length} connected
          </div>

          <svg
            width="100%"
            height="100%"
            viewBox="0 0 100 100"
            preserveAspectRatio="none"
            className="absolute inset-0"
          >
            {(connections ?? []).map((conn: CameraConnection) => {
              const a = positions[conn.camera_a_id];
              const b = positions[conn.camera_b_id];
              if (!a || !b) return null;
              return (
                <line
                  key={conn.id}
                  x1={a[0]}
                  y1={a[1]}
                  x2={b[0]}
                  y2={b[1]}
                  stroke="oklch(38% 0.02 265)"
                  strokeWidth={0.6}
                  strokeDasharray="2,2"
                />
              );
            })}
          </svg>

          {(connections ?? []).map((conn: CameraConnection) => {
            const a = positions[conn.camera_a_id];
            const b = positions[conn.camera_b_id];
            if (!a || !b) return null;
            const midX = (a[0] + b[0]) / 2;
            const midY = (a[1] + b[1]) / 2;
            return (
              <div
                key={conn.id}
                className="absolute flex -translate-x-1/2 -translate-y-1/2 items-center gap-1 rounded-full border border-[oklch(26%_0.015_265)] bg-[oklch(15%_0.015_265)] py-0.5 pl-2.5 pr-0.5"
                style={{ left: `${midX}%`, top: `${midY}%` }}
              >
                <input
                  defaultValue={conn.label ?? ""}
                  placeholder="Label"
                  onBlur={(e) => {
                    if (e.target.value !== (conn.label ?? "")) {
                      relabel.mutate({ id: conn.id, label: e.target.value });
                    }
                  }}
                  className="w-24 bg-transparent text-[11px] text-[oklch(85%_0.005_265)] outline-none placeholder:text-[oklch(45%_0.01_265)]"
                />
                <button
                  onClick={() => remove.mutate(conn.id)}
                  title="Remove this connection"
                  className="flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full text-[oklch(55%_0.01_265)] hover:bg-[oklch(20%_0.015_265)] hover:text-[oklch(90%_0.005_265)]"
                >
                  <X size={11} />
                </button>
              </div>
            );
          })}

          {(cameras ?? []).map((camera) => {
            const [x, y] = positions[camera.id] ?? [50, 50];
            const isSelected = selected === camera.id;
            const isLinked = linkedToSelected.has(camera.id);
            return (
              <button
                key={camera.id}
                onClick={() => handleClick(camera.id)}
                title={camera.name}
                className={`absolute flex w-[104px] -translate-x-1/2 -translate-y-1/2 flex-col items-center gap-2 rounded-[14px] border p-2.5 transition-colors ${
                  isSelected
                    ? "border-[oklch(60%_0.14_84)] bg-[oklch(24%_0.06_84)] text-[oklch(90%_0.1_84)] shadow-[0_0_0_4px_oklch(60%_0.14_84/0.18)]"
                    : "border-[oklch(24%_0.015_265)] bg-[oklch(14%_0.015_265)] text-[oklch(85%_0.005_265)] hover:border-[oklch(34%_0.015_265)]"
                }`}
                style={{ left: `${x}%`, top: `${y}%` }}
              >
                <span
                  className={`relative flex h-[30px] w-[30px] shrink-0 items-center justify-center rounded-[9px] ${
                    isSelected
                      ? "bg-[oklch(30%_0.08_84)] text-[oklch(90%_0.12_84)]"
                      : "bg-[oklch(19%_0.015_265)] text-[oklch(65%_0.01_265)]"
                  }`}
                >
                  <CameraIcon size={15} />
                  <span className="absolute -right-0.5 -top-0.5">
                    <StatusDot status={camera.status} />
                  </span>
                </span>
                <span className="line-clamp-2 text-center text-[12px] font-bold leading-tight break-words">
                  {camera.name}
                </span>
                {selected && isLinked && (
                  <span className="text-center text-[10px] font-normal leading-tight text-[oklch(79.2%_0.209_151.711)]">
                    linked — click to unlink
                  </span>
                )}
              </button>
            );
          })}

          {(connections ?? []).length === 0 && (
            <div className="pointer-events-none absolute inset-x-0 bottom-24 text-center text-[12.5px] text-[oklch(45%_0.01_265)]">
              No connections yet — click two cameras to link them.
            </div>
          )}
        </div>
      )}
    </Page>
  );
}
