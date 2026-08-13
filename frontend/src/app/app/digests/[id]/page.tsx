"use client";

import { use } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Skeleton } from "@/components/ui/Skeleton";

export default function DigestDetailPageV2({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);

  const {
    data: digest,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ["digest", id],
    queryFn: () => api.getDigest(id),
    enabled: !!id,
  });

  if (isLoading) {
    return (
      <div className="max-w-[820px] mx-auto px-12 pt-12 pb-20">
        <Skeleton className="h-8 w-48 mb-6" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="max-w-[820px] mx-auto px-12 pt-12 pb-20">
        <Link href="/app/digests" className="text-[13px] text-[oklch(62%_0.01_265)] mb-4 inline-block">
          ← Digests
        </Link>
        <div className="p-6 text-sm text-center text-[oklch(70.4%_0.191_22.216)] border border-[oklch(70.4%_0.191_22.216)] rounded-[14px] bg-[oklch(18%_0.2_22)]">
          {error instanceof Error ? error.message : "Couldn't load this digest."}
        </div>
      </div>
    );
  }

  if (!digest) {
    return (
      <div className="max-w-[820px] mx-auto px-12 pt-12 pb-20">
        <Link href="/app/digests" className="text-[13px] text-[oklch(62%_0.01_265)] mb-4 inline-block">
          ← Digests
        </Link>
        <div className="text-sm text-[oklch(55%_0.01_265)]">Digest not found.</div>
      </div>
    );
  }

  const p = digest.payload;

  return (
    <div className="max-w-[820px] mx-auto px-12 pt-12 pb-20">
      <Link href="/app/digests" className="text-[13px] text-[oklch(62%_0.01_265)] mb-4 inline-block">
        ← Digests
      </Link>

      <div className="text-[11px] uppercase tracking-wide text-[oklch(55%_0.01_265)] mb-1">
        {p.period}
      </div>
      <div className="text-[26px] font-bold tracking-tight mb-2">{p.headline}</div>
      {p.degraded && (
        <div className="inline-block text-[11px] font-semibold px-2.5 py-1 rounded-full bg-[oklch(82.8%_0.189_84.429_/_0.16)] text-[oklch(82.8%_0.189_84.429)] mb-4">
          Limited summary
        </div>
      )}

      <div className="grid grid-cols-3 gap-3 my-6">
        <Stat label="Events" value={p.total_events} />
        {Object.entries(p.by_severity).map(([k, v]) => (
          <Stat key={k} label={k} value={v} />
        ))}
      </div>

      <div className="mb-6">
        <div className="text-base font-bold mb-2">Summary</div>
        <div className="text-sm text-[oklch(85%_0.005_265)] leading-relaxed">{p.narrative}</div>
      </div>

      {p.highlights.length > 0 && (
        <div className="mb-6">
          <div className="text-base font-bold mb-3">Highlights</div>
          <div className="flex flex-col gap-2">
            {p.highlights.map((h, i) => (
              <div
                key={i}
                className="bg-[oklch(13%_0.015_265)] border border-[oklch(22%_0.015_265)] rounded-[14px] px-4 py-3"
              >
                <div className="text-[11.5px] text-[oklch(55%_0.01_265)] font-mono mb-1">
                  {new Date(h.time).toLocaleString()} · {h.camera_name}
                </div>
                <div className="text-[13px] text-[oklch(90%_0.005_265)]">{h.why_notable}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {p.quiet_periods.length > 0 && (
        <div>
          <div className="text-base font-bold mb-2">Quiet periods</div>
          <ul className="text-sm text-[oklch(65%_0.01_265)] list-disc pl-5">
            {p.quiet_periods.map((q, i) => (
              <li key={i}>{q}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="bg-[oklch(13%_0.015_265)] border border-[oklch(22%_0.015_265)] rounded-[14px] p-3.5">
      <div className="text-[11px] uppercase text-[oklch(55%_0.01_265)]">{label}</div>
      <div className="text-xl font-bold mt-1">{value}</div>
    </div>
  );
}
