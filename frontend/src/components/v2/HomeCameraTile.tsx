"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Camera } from "@/types";

export function HomeCameraTile({ camera }: { camera: Camera }) {
  const { data: frame } = useQuery({
    queryKey: ["camera-latest-frame", camera.id],
    queryFn: () => api.getCameraLatestFrame(camera.id),
    refetchInterval: 10000,
  });

  const dotColor =
    camera.status === "online" ? "oklch(79.2% 0.209 151.711)" : "oklch(70.4% 0.191 22.216)";

  return (
    <Link
      href={`/app/cameras/${camera.id}`}
      className="block bg-[oklch(14%_0.015_265)] border border-[oklch(22%_0.015_265)] rounded-[14px] overflow-hidden"
    >
      <div className="h-[100px] relative bg-[oklch(11%_0.015_265)]">
        {frame?.url && (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={frame.url} alt={camera.name} className="w-full h-full object-cover" />
        )}
        <div
          className="absolute top-2.5 right-2.5 w-[9px] h-[9px] rounded-full"
          style={{ background: dotColor, boxShadow: "0 0 0 3px oklch(9% 0.015 265 / 0.6)" }}
        />
      </div>
      <div className="px-3.5 py-3">
        <div className="text-[13px] font-semibold mb-0.5">{camera.name}</div>
        <div className="text-[11px] text-[oklch(58%_0.01_265)] font-mono">{camera.status}</div>
      </div>
    </Link>
  );
}
