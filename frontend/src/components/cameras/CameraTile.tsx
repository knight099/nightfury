"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { VideoOff } from "lucide-react";
import { api } from "@/lib/api";
import type { Camera } from "@/types";

interface CameraTileProps {
  camera: Camera;
  lastEventAt?: string | null;
}

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

export function CameraTile({ camera, lastEventAt }: CameraTileProps) {
  const { data: frame } = useQuery({
    queryKey: ["camera-latest-frame", camera.id],
    queryFn: () => api.getCameraLatestFrame(camera.id),
    refetchInterval: 2000,
    refetchIntervalInBackground: false,
  });

  const online = camera.status === "online";
  const dotColor = online ? "bg-green-400" : "bg-gray-500";

  return (
    <Link
      href={`/cameras/${camera.id}`}
      className="group relative block bg-[#111111] border border-[#2A2A2A] rounded-lg overflow-hidden hover:border-[#1E90FF] transition-colors"
    >
      <div className="relative w-full bg-[#1F1F1F]" style={{ aspectRatio: "16 / 9" }}>
        {frame?.url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={`${frame.url}${frame.url.includes("?") ? "&" : "?"}t=${encodeURIComponent(frame.updated_at)}`}
            alt={camera.name}
            className="absolute inset-0 w-full h-full object-cover"
            draggable={false}
          />
        ) : (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-[#666666]">
            <VideoOff size={32} />
            <span className="text-[10px] uppercase tracking-wider">No signal</span>
          </div>
        )}

        <div className="absolute inset-x-0 bottom-0 flex items-end justify-between p-2 bg-gradient-to-t from-black/80 to-transparent">
          <div className="flex items-center gap-2 min-w-0">
            <span className={`inline-block w-2 h-2 rounded-full ${dotColor}`} />
            <span className="text-xs font-medium text-[#F5F5F5] truncate">{camera.name}</span>
          </div>
          <span className="text-[10px] text-[#A3A3A3] shrink-0 ml-2">
            {lastEventAt ? `last event ${relativeTime(lastEventAt)}` : "no events"}
          </span>
        </div>
      </div>
    </Link>
  );
}
