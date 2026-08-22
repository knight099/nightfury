"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { WebRTCPlayer } from "@/components/cameras/WebRTCPlayer";
import { StatusDot } from "@/components/shared/status-dot";
import { Skeleton } from "@/components/ui/Skeleton";
import { Page, PageHeader, Card, EmptyState, inputClass } from "@/components/v2/ui";
import type { Camera } from "@/types";

/**
 * Video wall (V2) — many cameras live at once, for a control room.
 *
 * Ported from V1. The load discipline here matters more than the layout. Each
 * live tile holds a real WebRTC session on the customer's appliance, and that
 * appliance exists to run detection; live view is the convenience running
 * beside it. So:
 *
 *  - Only tiles actually on screen hold a session (IntersectionObserver).
 *    Scrolling a tile out of view tears its session down and returns the slot.
 *  - The appliance enforces its own concurrent-session cap and answers 503
 *    when full. This page reports that honestly rather than retrying into it.
 */
export default function WallPageV2() {
  const [siteId, setSiteId] = useState<string | null>(null);
  const [cols, setCols] = useState(3);

  const { data: sites } = useQuery({ queryKey: ["sites"], queryFn: () => api.getSites() });
  const activeSiteId = siteId ?? sites?.[0]?.id ?? null;

  const { data: cameras, isLoading } = useQuery({
    queryKey: ["cameras", activeSiteId],
    queryFn: () => api.getCameras({ site_id: activeSiteId as string }),
    enabled: !!activeSiteId,
  });

  const online = useMemo(() => (cameras ?? []).filter((c) => c.status === "online"), [cameras]);
  const offline = useMemo(() => (cameras ?? []).filter((c) => c.status !== "online"), [cameras]);

  if (!sites?.length) {
    return (
      <Page wide>
        <PageHeader title="Video wall" />
        <EmptyState title="No sites yet" hint="Add a site and pair cameras to use the wall." />
      </Page>
    );
  }

  return (
    <Page wide>
      <PageHeader
        title="Video wall"
        subtitle="Live tiles connect only while on screen — scroll away and the appliance gets the capacity back."
        action={
          <div className="flex gap-2 shrink-0">
            <select
              value={activeSiteId ?? ""}
              onChange={(e) => setSiteId(e.target.value)}
              className={`${inputClass} !w-auto`}
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
              className={`${inputClass} !w-auto`}
            >
              <option value={2}>2 across</option>
              <option value={3}>3 across</option>
              <option value={4}>4 across</option>
            </select>
          </div>
        }
      />

      {isLoading ? (
        <Skeleton className="h-96 w-full" />
      ) : online.length === 0 ? (
        <EmptyState title="No cameras are online at this site." />
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
        <Card className="mt-4">
          <h2 className="text-[13px] font-semibold text-[oklch(72%_0.01_265)]">
            Not available for live view ({offline.length})
          </h2>
          <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
            {offline.map((c) => (
              <li
                key={c.id}
                className="flex items-center gap-2 text-[11.5px] text-[oklch(55%_0.01_265)]"
              >
                <StatusDot status={c.status} />
                {c.name}
                <span className="text-[oklch(42%_0.01_265)]">({c.status})</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </Page>
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

  const atCapacity = !!error && /too many|503|limit/i.test(error);

  return (
    <div
      ref={ref}
      className="relative aspect-video overflow-hidden rounded-[10px] border border-[oklch(22%_0.015_265)] bg-black"
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
          <p
            className={`text-[11.5px] ${
              atCapacity ? "text-[oklch(85%_0.16_84)]" : "text-[oklch(55%_0.01_265)]"
            }`}
          >
            {atCapacity
              ? // Distinguished on purpose: this is a capacity limit the
                // operator can act on (close tiles / show fewer), not a
                // broken camera.
                "Appliance is at its live-viewer limit — close some tiles"
              : "Live view unavailable"}
          </p>
          <button
            onClick={() => setError(null)}
            className="rounded border border-[oklch(24%_0.02_265)] px-2 py-1 text-[11.5px] text-[oklch(72%_0.01_265)] transition-colors hover:bg-[oklch(18%_0.015_265)]"
          >
            Retry
          </button>
        </div>
      )}

      <div className="pointer-events-none absolute inset-x-0 bottom-0 flex items-center gap-2 bg-gradient-to-t from-black/80 to-transparent px-2 py-1.5">
        <StatusDot status={camera.status} />
        <span className="truncate text-[11.5px] text-[oklch(97%_0.005_265)]">{camera.name}</span>
      </div>
    </div>
  );
}
