"use client";

import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Skeleton } from "@/components/ui/Skeleton";

export default function DigestDetailPage() {
  const params = useParams<{ id: string }>();
  const { data, isLoading, error } = useQuery({
    queryKey: ["digest", params.id],
    queryFn: () => api.getDigest(params.id!),
    enabled: !!params.id,
  });

  if (isLoading) return <div className="space-y-3"><Skeleton className="h-8 w-1/3 rounded-md" /><Skeleton className="h-48 rounded-lg" /></div>;
  if (error)
    return <p className="text-[#EF4444]">{(error as Error).message}</p>;
  if (!data) return null;

  const p = data.payload;
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <header>
        <p className="text-xs uppercase tracking-wide text-[#666666]">
          {p.period}
        </p>
        <h1 className="mt-1 text-2xl font-bold text-[#F5F5F5]">{p.headline}</h1>
        {p.degraded && (
          <p className="mt-2 inline-block rounded bg-[#FBBF24]/20 px-2 py-0.5 text-xs text-[#FBBF24]">
            Limited summary
          </p>
        )}
      </header>

      <section className="grid grid-cols-3 gap-3">
        <Stat label="Events" value={p.total_events} />
        {Object.entries(p.by_severity).map(([k, v]) => (
          <Stat key={k} label={k} value={v} />
        ))}
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-[#F5F5F5]">Summary</h2>
        <p className="text-[#F5F5F5] leading-relaxed">{p.narrative}</p>
      </section>

      {p.highlights.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm font-semibold text-[#F5F5F5]">Highlights</h2>
          <ul className="space-y-2">
            {p.highlights.map((h, i) => (
              <li
                key={i}
                className="rounded border border-[#2A2A2A] bg-[#111111] p-3"
              >
                <div className="text-xs text-[#666666]">
                  {new Date(h.time).toLocaleString()} · {h.camera_name}
                </div>
                <div className="mt-1 text-sm text-[#F5F5F5]">
                  {h.why_notable}
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {p.quiet_periods.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm font-semibold text-[#F5F5F5]">
            Quiet periods
          </h2>
          <ul className="text-sm text-[#A3A3A3] list-disc pl-5">
            {p.quiet_periods.map((q, i) => (
              <li key={i}>{q}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
}: {
  label: string;
  value: number | string;
}) {
  return (
    <div className="rounded border border-[#2A2A2A] bg-[#111111] p-3">
      <div className="text-xs uppercase text-[#666666]">{label}</div>
      <div className="mt-1 text-xl font-semibold text-[#F5F5F5]">{value}</div>
    </div>
  );
}
