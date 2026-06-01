"use client";

import Link from "next/link";
import type { Digest } from "@/types";

export function DigestCard({ digest }: { digest: Digest }) {
  const date = new Date(digest.created_at).toLocaleString();
  return (
    <Link
      href={`/digests/${digest.id}`}
      className="block rounded-lg border border-[#2A2A2A] bg-[#111111] p-4 hover:border-[#1E90FF] transition-colors"
    >
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-base font-semibold text-[#F5F5F5]">
            {digest.payload.headline}
          </h3>
          <p className="mt-1 text-sm text-[#A3A3A3]">
            {digest.payload.period} · {digest.event_count} event
            {digest.event_count === 1 ? "" : "s"}
          </p>
        </div>
        <span className="text-xs text-[#666666]">{date}</span>
      </div>
      {digest.payload.degraded && (
        <p className="mt-2 text-xs text-[#FBBF24]">Limited summary</p>
      )}
      {digest.payload.narrative && (
        <p className="mt-3 text-sm text-[#A3A3A3] line-clamp-2">
          {digest.payload.narrative}
        </p>
      )}
    </Link>
  );
}
