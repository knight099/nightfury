"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { WebRTCPlayer } from "@/components/cameras/WebRTCPlayer";
import { StatusDot } from "@/components/shared/status-dot";
import { Skeleton } from "@/components/ui/Skeleton";
import type { Camera } from "@/types";

/**
 * Video wall — many cameras live at once, for a control room.
 *
 * The load discipline here matters more than the layout. Each live tile holds
 * a real WebRTC session on the customer's appliance, and that appliance exists
 * to run detection; live view is the convenience running beside it. So:
 *
 *  - Only tiles actually on screen hold a session (IntersectionObserver).
 *    Scrolling a tile out of view tears its session down and returns the slot.
 *  - The appliance enforces its own concurrent-session cap and answers 503
 *    when full. This page reports that honestly rather than retrying into it.
 */
export default function WallPage() {
  const [siteId, setSiteId] = useState<string | null>(null);
  const [cols, setCols] = useState(3);

  const { data: sites } = useQuery({ queryKey: ["sites"], queryFn: () => api.getSites() });
  const activeSiteId = siteId ?? sites?.[0]?.id ?? null;

  const { data: cameras, isLoading } = useQuery({
    queryKey: ["cameras", activeSiteId],
    queryFn: () => api.getCameras({ site_id: activeSiteId as string }),
    enabled: !!activeSiteId,
  });

  const online = useMemo(
    () => (cameras ?? []).filter((c) => c.status === "online"),
    [cameras]
  );
  const offline = useMemo(
    () => (cameras ?? []).filter((c) => c.status !== "online"),
    [cameras]
  );

  if (!sites?.length) {
    return (
      <div className="space-y-2">
        <h1 className="font-heading text-2xl font-bold text-[#F5F5F5]">Video wall</h1>
        <p className="text-sm text-[#A3A3A3]">No sites yet.</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-heading text-2xl font-bold text-[#F5F5F5]">Video wall</h1>
          <p className="mt-1 text-sm text-[#A3A3A3]">
            Live tiles connect only while on screen — scroll away and the
            appliance gets the capacity back.
          </p>
        </div>
        <div className="flex gap-2">
          <select
            value={activeSiteId ?? ""}
            onChange={(e) => setSiteId(e.target.value)}
            className="rounded-md border border-[#2A2A2A] bg-[#1F1F1F] px-3 py-2 text-sm text-[#F5F5F5] transition-colors focus:border-[#1E90FF] focus:outline-none"
          >
            {sites.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
          <select
            value={cols}
            onChange={(e) => setCols(Number(e.target.value))}
            className="rounded-md border border-[#2A2A2A] bg-[#1F1F1F] px-3 py-2 text-sm text-[#F5F5F5] transition-colors focus:border-[#1E90FF] focus:outline-none"
          >
            <option value={2}>2 across</option>
            <option value={3}>3 across</option>
            <option value={4}>4 across</option>
          </select>
        </div>
      </header>

      {isLoading ? (
        <Skeleton className="h-96 w-full" />
      ) : online.length === 0 ? (
        <p className="rounded-lg border border-[#2A2A2A] bg-[#111111] p-6 text-sm text-[#A3A3A3]">
          No cameras are online at this site.
        </p>
      ) : (
        <div
          className="grid gap-3"
          style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}
        >
          {online.map((camera) => (
            <WallTile key={camera.id} camera={camera} />
          ))}
        </div>
      )}

      {offline.length > 0 && (
        <section className="rounded-lg border border-[#2A2A2A] bg-[#111111] p-4">
          <h2 className="text-sm font-medium text-[#A3A3A3]">
            Not available for live view ({offline.length})
          </h2>
          <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
            {offline.map((c) => (
              <li key={c.id} className="flex items-center gap-2 text-xs text-[#666666]">
                <StatusDot status={c.status} />
                {c.name}
                <span className="text-[#444]">({c.status})</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function WallTile({ camera }: { camera: Camera }) {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        // Unmounting the player closes its PeerConnection, which is what
        // actually releases the slot on the appliance. Without this the wall
        // would hold every camera's session for as long as the page is open,
        // whether anyone can see it or not.
        setVisible(entry.isIntersecting);
        if (!entry.isIntersecting) setError(null);
      },
      // A little margin so a tile is connected by the time it scrolls in,
      // rather than showing black for a beat.
      { rootMargin: "200px" }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const atCapacity =
    !!error && /too many|503|limit/i.test(error);

  return (
    <div
      ref={ref}
      className="relative aspect-video overflow-hidden rounded-lg border border-[#2A2A2A] bg-black"
    >
      {visible && !error && (
        <WebRTCPlayer
          cameraId={camera.id}
          className="h-full w-full object-cover"
          onError={(reason) => setError(reason || "Live view unavailable")}
        />
      )}

      {error && (
        <div className="flex h-full flex-col items-center justify-center gap-2 p-3 text-center">
          <p className={`text-xs ${atCapacity ? "text-amber-400" : "text-[#666666]"}`}>
            {atCapacity
              ? // Distinguished on purpose: this is a capacity limit the
                // operator can act on (close tiles / show fewer), not a
                // broken camera.
                "Appliance is at its live-viewer limit — close some tiles"
              : "Live view unavailable"}
          </p>
          <button
            onClick={() => setError(null)}
            className="rounded border border-[#2A2A2A] px-2 py-1 text-xs text-[#A3A3A3] transition-colors hover:bg-[#1A1A1A]"
          >
            Retry
          </button>
        </div>
      )}

      <div className="pointer-events-none absolute inset-x-0 bottom-0 flex items-center gap-2 bg-gradient-to-t from-black/80 to-transparent px-2 py-1.5">
        <StatusDot status={camera.status} />
        <span className="truncate text-xs text-[#F5F5F5]">{camera.name}</span>
      </div>
    </div>
  );
}
