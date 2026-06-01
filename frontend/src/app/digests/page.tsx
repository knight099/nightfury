"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { DigestCard } from "@/components/digests/DigestCard";
import { RangePicker, type Range } from "@/components/digests/RangePicker";
import { DigestSettings } from "@/components/digests/DigestSettings";
import { Skeleton } from "@/components/ui/Skeleton";

export default function DigestsPage() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["digests"],
    queryFn: () => api.getDigests(),
  });

  const create = useMutation({
    mutationFn: (r: Range) =>
      api.createDigest({
        start: r.start.toISOString(),
        end: r.end.toISOString(),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["digests"] }),
  });

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <h1 className="text-2xl font-bold text-[#F5F5F5]">Digests</h1>

      <section className="rounded-lg border border-[#2A2A2A] bg-[#111111] p-4">
        <h2 className="mb-3 text-sm font-semibold text-[#F5F5F5]">
          Generate a digest
        </h2>
        <RangePicker onRange={(r) => create.mutate(r)} />
        {create.isPending && (
          <p className="mt-2 text-xs text-[#A3A3A3]">Generating…</p>
        )}
        {create.isError && (
          <p className="mt-2 text-xs text-[#EF4444]">
            {(create.error as Error).message}
          </p>
        )}
      </section>

      <DigestSettings />

      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-[#F5F5F5]">History</h2>
        {isLoading && (
          <div className="space-y-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-32 rounded-lg" />
            ))}
          </div>
        )}
        {data?.items.length === 0 && (
          <p className="text-[#666666] text-sm">No digests yet.</p>
        )}
        {data?.items.map((d) => (
          <DigestCard key={d.id} digest={d} />
        ))}
      </section>
    </div>
  );
}
