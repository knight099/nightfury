"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Skeleton } from "@/components/ui/Skeleton";
import { useAuthStore } from "@/lib/store";

export default function AdminAiPageV2() {
  const { user } = useAuthStore();
  const [orgId, setOrgId] = useState("");

  const { data: orgs } = useQuery({
    queryKey: ["admin", "orgs"],
    queryFn: () => api.adminGetOrgs(),
    enabled: user?.role === "super_admin",
  });

  const {
    data: usage,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ["admin", "ai-usage", orgId],
    queryFn: () => api.adminGetAiUsage(orgId),
    enabled: !!orgId,
  });

  if (user?.role !== "super_admin") {
    return (
      <div className="max-w-[1040px] mx-auto px-12 py-12 text-sm text-[oklch(55%_0.01_265)]">
        Not authorized.
      </div>
    );
  }

  return (
    <div className="max-w-[1040px] mx-auto px-12 pt-12 pb-20">
      <div className="text-[28px] font-bold tracking-tight mb-6">AI usage</div>

      <select
        value={orgId}
        onChange={(e) => setOrgId(e.target.value)}
        className="bg-[oklch(17%_0.015_265)] border border-[oklch(30%_0.02_265)] rounded-lg px-3 py-2 text-sm text-[oklch(95%_0.005_265)] mb-6"
      >
        <option value="">Select an org</option>
        {(orgs ?? []).map((o: { id: string; name: string }) => (
          <option key={o.id} value={o.id}>
            {o.name}
          </option>
        ))}
      </select>

      {!orgId ? (
        <div className="text-sm text-[oklch(55%_0.01_265)]">Select an org to view its AI usage.</div>
      ) : isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : isError ? (
        <div className="bg-[oklch(18%_0.2_22)] border border-[oklch(70.4%_0.191_22.216)] rounded-lg px-4 py-3 text-sm text-[oklch(70.4%_0.191_22.216)]">
          {error instanceof Error ? error.message : "Could not load AI usage."}
        </div>
      ) : usage ? (
        <>
          <div className="grid grid-cols-3 gap-4 mb-8">
            <div className="bg-[oklch(13%_0.015_265)] border border-[oklch(22%_0.015_265)] rounded-[14px] p-4">
              <div className="text-2xl font-bold">{usage.aggregate.calls}</div>
              <div className="text-xs text-[oklch(58%_0.01_265)]">calls (30d)</div>
            </div>
            <div className="bg-[oklch(13%_0.015_265)] border border-[oklch(22%_0.015_265)] rounded-[14px] p-4">
              <div className="text-2xl font-bold">${usage.aggregate.cost_usd.toFixed(2)}</div>
              <div className="text-xs text-[oklch(58%_0.01_265)]">cost (30d)</div>
            </div>
            <div className="bg-[oklch(13%_0.015_265)] border border-[oklch(22%_0.015_265)] rounded-[14px] p-4">
              <div className="text-2xl font-bold">{usage.aggregate.avg_latency_ms}ms</div>
              <div className="text-xs text-[oklch(58%_0.01_265)]">avg latency</div>
            </div>
          </div>
          {usage.recent.length > 0 ? (
            <div className="flex flex-col gap-2">
              {usage.recent.map((r) => (
                <div key={r.id} className="text-sm text-[oklch(80%_0.005_265)] flex justify-between">
                  <span>
                    {r.username} · {r.operation}
                  </span>
                  <span className="text-[oklch(58%_0.01_265)]">${r.cost_usd.toFixed(4)}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-sm text-[oklch(55%_0.01_265)]">No AI usage recorded for this org yet.</div>
          )}
        </>
      ) : null}
    </div>
  );
}
