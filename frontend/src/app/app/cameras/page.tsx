"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Skeleton } from "@/components/ui/Skeleton";

export default function CamerasPageV2() {
  const { data: cameras, isLoading, isError, error } = useQuery({
    queryKey: ["cameras"],
    queryFn: () => api.getCameras(),
  });

  if (isLoading) {
    return (
      <div className="max-w-[1040px] mx-auto px-12 py-12">
        <Skeleton className="h-8 w-48 mb-6" />
        <div className="grid grid-cols-2 gap-5">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-40 w-full" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-[1040px] mx-auto px-12 pt-12 pb-20">
      <div className="flex items-baseline justify-between mb-1.5">
        <div className="text-[28px] font-bold tracking-tight">Cameras</div>
        <div className="text-[13px] text-[oklch(58%_0.01_265)]">Click a camera to give it a job.</div>
      </div>
      <div className="text-[15px] text-[oklch(65%_0.01_265)] mb-7">
        Every camera below is on watch. Click one to see what it&apos;s up to.
      </div>

      {isError ? (
        <div className="text-sm text-[oklch(70.4%_0.191_22.216)]">
          {error instanceof Error ? error.message : "Something went wrong loading cameras."}
        </div>
      ) : cameras && cameras.length > 0 ? (
        <div className="grid grid-cols-2 gap-5">
          {cameras.map((cam) => (
            <Link
              key={cam.id}
              href={`/app/cameras/${cam.id}`}
              className="block bg-[oklch(14%_0.015_265)] border border-[oklch(22%_0.015_265)] rounded-2xl overflow-hidden hover:bg-[oklch(16%_0.015_265)] transition-colors"
            >
              <div className="h-[180px] bg-[oklch(11%_0.015_265)]" />
              <div className="px-4 py-3.5">
                <div className="text-sm font-semibold mb-0.5">{cam.name}</div>
                <div className="text-[11px] text-[oklch(58%_0.01_265)] font-mono">{cam.status}</div>
              </div>
            </Link>
          ))}
        </div>
      ) : (
        <div className="text-sm text-[oklch(55%_0.01_265)]">No cameras yet.</div>
      )}
    </div>
  );
}
