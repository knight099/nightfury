"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { StatusDot } from "@/components/shared/status-dot";
import { Skeleton } from "@/components/ui/Skeleton";
import type { FleetAgent, FleetCamera, FleetResponse } from "@/types";

/**
 * Fleet view — how many cameras this site can actually analyse, and which ones
 * nobody is watching.
 *
 * This page is part of the scaling mechanism, not a report: capacity behaviour
 * nobody can see is indistinguishable from a bug. The single most important
 * number here is coverage (analysed / configured), and the most important list
 * is the unassigned one.
 */
export default function FleetPage() {
  const qc = useQueryClient();
  const [siteId, setSiteId] = useState<string | null>(null);

  const { data: sites, isLoading: sitesLoading } = useQuery({
    queryKey: ["sites"],
    queryFn: () => api.getSites(),
  });

  const activeSiteId = siteId ?? sites?.[0]?.id ?? null;

  const { data: fleet, isLoading } = useQuery({
    queryKey: ["fleet", activeSiteId],
    queryFn: () => api.getSiteFleet(activeSiteId as string),
    enabled: !!activeSiteId,
    // Heartbeats land every ~30s, so anything faster just re-renders the same
    // numbers.
    refetchInterval: 30_000,
  });

  const pin = useMutation({
    mutationFn: ({ cameraId, agentId }: { cameraId: string; agentId: string | null }) =>
      api.pinCamera(cameraId, agentId),
    onSuccess: (updated: FleetResponse) => {
      qc.setQueryData(["fleet", activeSiteId], updated);
      qc.invalidateQueries({ queryKey: ["cameras"] });
    },
  });

  if (sitesLoading) return <Skeleton className="h-64 w-full" />;

  if (!sites?.length) {
    return (
      <div className="mx-auto max-w-5xl">
        <h1 className="font-heading text-2xl font-bold text-[#F5F5F5]">Fleet</h1>
        <p className="mt-3 text-sm text-[#A3A3A3]">
          No sites yet. Add a site and pair an appliance to see coverage here.
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-heading text-2xl font-bold text-[#F5F5F5]">Fleet</h1>
          <p className="mt-1 text-sm text-[#A3A3A3]">
            Appliance capacity and camera coverage per site.
          </p>
        </div>
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
      </header>

      {isLoading || !fleet ? (
        <Skeleton className="h-64 w-full" />
      ) : (
        <>
          <CoverageSummary fleet={fleet} />
          <UnassignedPanel
            cameras={fleet.unassigned_cameras}
            agents={fleet.agents}
            onPin={(cameraId, agentId) => pin.mutate({ cameraId, agentId })}
            pinning={pin.isPending}
          />
          <section className="space-y-3">
            <h2 className="font-heading text-lg font-semibold text-[#F5F5F5]">
              Appliances
            </h2>
            {fleet.agents.length === 0 ? (
              <p className="rounded-lg border border-[#2A2A2A] bg-[#111111] p-4 text-sm text-[#A3A3A3]">
                No appliance is paired to this site, so none of its cameras are
                being analysed.
              </p>
            ) : (
              fleet.agents.map((agent) => (
                <AgentCard
                  key={agent.id}
                  agent={agent}
                  onUnpin={(cameraId) => pin.mutate({ cameraId, agentId: null })}
                />
              ))
            )}
          </section>
        </>
      )}
    </div>
  );
}

function CoverageSummary({ fleet }: { fleet: FleetResponse }) {
  const gap = fleet.cameras_total - fleet.cameras_covered;
  return (
    <section className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <Stat
        label="Cameras analysed"
        value={`${fleet.cameras_covered}/${fleet.cameras_total}`}
        // The honest headline. Anything short of full coverage is a problem
        // worth colouring, not a neutral statistic.
        tone={gap > 0 ? "warn" : "ok"}
      />
      <Stat label="Total capacity" value={String(fleet.capacity_total)} />
      <Stat label="Spare capacity" value={String(fleet.capacity_spare)} />
      <Stat
        label="Not being analysed"
        value={String(fleet.unassigned_cameras.length)}
        tone={fleet.unassigned_cameras.length > 0 ? "warn" : "ok"}
      />
    </section>
  );
}

function Stat({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "neutral" | "ok" | "warn";
}) {
  const color =
    tone === "warn"
      ? "text-amber-400"
      : tone === "ok"
        ? "text-green-400"
        : "text-[#F5F5F5]";
  return (
    <div className="rounded-lg border border-[#2A2A2A] bg-[#111111] p-4">
      <div className="text-xs uppercase tracking-wider text-[#666666]">{label}</div>
      <div className={`mt-1 font-mono text-2xl font-bold tabular-nums ${color}`}>
        {value}
      </div>
    </div>
  );
}

function UnassignedPanel({
  cameras,
  agents,
  onPin,
  pinning,
}: {
  cameras: FleetCamera[];
  agents: FleetAgent[];
  onPin: (cameraId: string, agentId: string) => void;
  pinning: boolean;
}) {
  if (cameras.length === 0) return null;

  const withSpare = agents.filter((a) => !a.is_stale && a.spare_capacity > 0);

  return (
    <section className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-4">
      <h2 className="font-heading text-lg font-semibold text-amber-400">
        {cameras.length} camera{cameras.length === 1 ? "" : "s"} not being analysed
      </h2>
      <p className="mt-1 text-sm text-[#A3A3A3]">
        {withSpare.length > 0
          ? "There is spare capacity at this site — assign them to an appliance below."
          : // The remedy, stated as a number rather than a vague "add hardware".
            `No appliance here has spare capacity. One more appliance would cover ${cameras.length} camera${cameras.length === 1 ? "" : "s"}.`}
      </p>
      <ul className="mt-3 space-y-2">
        {cameras.map((camera) => (
          <li
            key={camera.id}
            className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-[#2A2A2A] bg-[#111111] px-3 py-2"
          >
            <span className="flex items-center gap-2 text-sm text-[#F5F5F5]">
              <StatusDot status={camera.status} />
              {camera.name}
            </span>
            {withSpare.length > 0 && (
              <select
                defaultValue=""
                disabled={pinning}
                onChange={(e) => e.target.value && onPin(camera.id, e.target.value)}
                className="rounded-md border border-[#2A2A2A] bg-[#1F1F1F] px-2 py-1 text-xs text-[#F5F5F5] transition-colors focus:border-[#1E90FF] focus:outline-none disabled:opacity-50"
              >
                <option value="">Assign to…</option>
                {withSpare.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.machine_id} ({a.spare_capacity} free)
                  </option>
                ))}
              </select>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function AgentCard({
  agent,
  onUnpin,
}: {
  agent: FleetAgent;
  onUnpin: (cameraId: string) => void;
}) {
  const capacity = agent.capacity_cameras;
  const pct =
    capacity && capacity > 0
      ? Math.min(100, Math.round((agent.assigned_count / capacity) * 100))
      : 0;

  return (
    <article className="rounded-lg border border-[#2A2A2A] bg-[#111111] p-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="flex items-center gap-2 font-medium text-[#F5F5F5]">
            <StatusDot status={agent.is_stale ? "error" : "online"} />
            {agent.machine_id}
            {agent.version && (
              <span className="font-mono text-xs text-[#666666]">{agent.version}</span>
            )}
          </h3>
          <p className="mt-1 font-mono text-xs text-[#666666]">
            {agent.assigned_count}/{capacity ?? "?"} cameras ·{" "}
            {/* Say whether the capacity number is a guess or a measurement —
                an operator should know how much to trust it. */}
            {agent.capacity_source === "measured"
              ? "capacity measured from load"
              : "capacity estimated from hardware"}
          </p>
        </div>
        <LoadBadge agent={agent} />
      </header>

      <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-[#1A1A1A]">
        <div
          className={`h-full transition-all ${pct >= 100 ? "bg-amber-400" : "bg-[#1E90FF]"}`}
          style={{ width: `${pct}%` }}
        />
      </div>

      {agent.load_reason && (
        <p className="mt-2 text-xs text-amber-400">{agent.load_reason}</p>
      )}

      {agent.cameras.length > 0 && (
        <ul className="mt-3 grid gap-1 sm:grid-cols-2">
          {agent.cameras.map((camera) => (
            <li
              key={camera.id}
              className="flex items-center justify-between gap-2 rounded-md px-2 py-1 text-sm text-[#A3A3A3] transition-colors hover:bg-[#1A1A1A]"
            >
              <span className="flex items-center gap-2 truncate">
                <StatusDot status={camera.status} />
                <span className="truncate">{camera.name}</span>
              </span>
              {camera.pinned_agent_id && (
                <button
                  onClick={() => onUnpin(camera.id)}
                  title="Pinned here — click to return it to automatic placement"
                  className="shrink-0 rounded px-1.5 py-0.5 text-xs text-[#1E90FF] transition-colors hover:bg-[#1A1A1A]"
                >
                  pinned
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </article>
  );
}

function LoadBadge({ agent }: { agent: FleetAgent }) {
  // Staleness outranks load: a box that is not reporting is not "ok", whatever
  // its last load reading said.
  const [label, classes] = agent.is_stale
    ? ["not reporting", "border-red-400/40 bg-red-400/10 text-red-400"]
    : agent.load_state === "over_capacity"
      ? ["over capacity", "border-red-400/40 bg-red-400/10 text-red-400"]
      : agent.load_state === "degraded"
        ? ["degraded", "border-amber-400/40 bg-amber-400/10 text-amber-400"]
        : ["healthy", "border-green-400/40 bg-green-400/10 text-green-400"];

  return (
    <span
      className={`rounded-md border px-2 py-1 text-xs uppercase tracking-wider ${classes}`}
    >
      {label}
    </span>
  );
}
