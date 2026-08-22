"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { StatusDot } from "@/components/shared/status-dot";
import { Skeleton } from "@/components/ui/Skeleton";
import { Page, PageHeader, Card, EmptyState, inputClass } from "@/components/v2/ui";
import type { FleetAgent, FleetCamera, FleetResponse } from "@/types";

/**
 * Fleet view (V2) — how many cameras this site can actually analyse, and which
 * ones nobody is watching.
 *
 * Ported from the V1 page. This is part of the scaling mechanism, not a report:
 * capacity behaviour nobody can see is indistinguishable from a bug. The single
 * most important number is coverage (analysed / configured), and the most
 * important list is the unassigned one.
 */
export default function FleetPageV2() {
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

  if (sitesLoading) {
    return (
      <Page>
        <Skeleton className="h-64 w-full" />
      </Page>
    );
  }

  if (!sites?.length) {
    return (
      <Page>
        <PageHeader title="Fleet" />
        <EmptyState
          title="No sites yet"
          hint="Add a site and pair an appliance to see coverage here."
        />
      </Page>
    );
  }

  return (
    <Page>
      <PageHeader
        title="Fleet"
        subtitle="Appliance capacity and camera coverage per site."
        action={
          <select
            value={activeSiteId ?? ""}
            onChange={(e) => setSiteId(e.target.value)}
            className={`${inputClass} !w-auto shrink-0`}
          >
            {sites.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        }
      />

      {isLoading || !fleet ? (
        <Skeleton className="h-64 w-full" />
      ) : (
        <div className="space-y-6">
          <CoverageSummary fleet={fleet} />
          <UnassignedPanel
            cameras={fleet.unassigned_cameras}
            agents={fleet.agents}
            onPin={(cameraId, agentId) => pin.mutate({ cameraId, agentId })}
            pinning={pin.isPending}
          />
          <section className="space-y-3">
            <h2 className="text-[17px] font-semibold">Appliances</h2>
            {fleet.agents.length === 0 ? (
              <EmptyState
                title="No appliance is paired to this site"
                hint="None of its cameras are being analysed."
              />
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
        </div>
      )}
    </Page>
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
      ? "text-[oklch(85%_0.16_84)]"
      : tone === "ok"
        ? "text-[oklch(79.2%_0.209_151.711)]"
        : "text-[oklch(97%_0.005_265)]";
  return (
    <Card padded={false} className="p-4">
      <div className="text-[11px] uppercase tracking-[0.04em] text-[oklch(55%_0.01_265)]">
        {label}
      </div>
      <div className={`mt-1 font-mono text-2xl font-bold tabular-nums ${color}`}>{value}</div>
    </Card>
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
    <section className="rounded-[14px] border border-[oklch(85%_0.16_84)]/40 bg-[oklch(85%_0.16_84)]/5 p-4">
      <h2 className="text-[17px] font-semibold text-[oklch(85%_0.16_84)]">
        {cameras.length} camera{cameras.length === 1 ? "" : "s"} not being analysed
      </h2>
      <p className="mt-1 text-[13px] text-[oklch(72%_0.01_265)]">
        {withSpare.length > 0
          ? "There is spare capacity at this site — assign them to an appliance below."
          : // The remedy, stated as a number rather than a vague "add hardware".
            `No appliance here has spare capacity. One more appliance would cover ${cameras.length} camera${cameras.length === 1 ? "" : "s"}.`}
      </p>
      <ul className="mt-3 space-y-2">
        {cameras.map((camera) => (
          <li
            key={camera.id}
            className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-[oklch(22%_0.015_265)] bg-[oklch(12%_0.015_265)] px-3 py-2"
          >
            <span className="flex items-center gap-2 text-[13px] text-[oklch(97%_0.005_265)]">
              <StatusDot status={camera.status} />
              {camera.name}
            </span>
            {withSpare.length > 0 && (
              <select
                defaultValue=""
                disabled={pinning}
                onChange={(e) => e.target.value && onPin(camera.id, e.target.value)}
                className={`${inputClass} !w-auto text-[11.5px] py-1`}
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

function AgentCard({ agent, onUnpin }: { agent: FleetAgent; onUnpin: (cameraId: string) => void }) {
  const capacity = agent.capacity_cameras;
  const pct =
    capacity && capacity > 0
      ? Math.min(100, Math.round((agent.assigned_count / capacity) * 100))
      : 0;

  return (
    <Card>
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="flex items-center gap-2 text-[14px] font-semibold text-[oklch(97%_0.005_265)]">
            <StatusDot status={agent.is_stale ? "error" : "online"} />
            {agent.machine_id}
            {agent.version && (
              <span className="font-mono text-[11px] text-[oklch(42%_0.01_265)]">
                {agent.version}
              </span>
            )}
          </h3>
          <p className="mt-1 font-mono text-[11px] text-[oklch(55%_0.01_265)]">
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

      <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-[oklch(18%_0.015_265)]">
        <div
          className="h-full transition-all"
          style={{
            width: `${pct}%`,
            backgroundColor: pct >= 100 ? "oklch(85% 0.16 84)" : "oklch(70% 0.14 250)",
          }}
        />
      </div>

      {agent.load_reason && (
        <p className="mt-2 text-[11.5px] text-[oklch(85%_0.16_84)]">{agent.load_reason}</p>
      )}

      {agent.cameras.length > 0 && (
        <ul className="mt-3 grid gap-1 sm:grid-cols-2">
          {agent.cameras.map((camera) => (
            <li
              key={camera.id}
              className="flex items-center justify-between gap-2 rounded-md px-2 py-1 text-[13px] text-[oklch(72%_0.01_265)] transition-colors hover:bg-[oklch(15%_0.015_265)]"
            >
              <span className="flex items-center gap-2 truncate">
                <StatusDot status={camera.status} />
                <span className="truncate">{camera.name}</span>
              </span>
              {camera.pinned_agent_id && (
                <button
                  onClick={() => onUnpin(camera.id)}
                  title="Pinned here — click to return it to automatic placement"
                  className="shrink-0 rounded px-1.5 py-0.5 text-[11px] text-[oklch(85%_0.16_84)] transition-colors hover:bg-[oklch(18%_0.015_265)]"
                >
                  pinned
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function LoadBadge({ agent }: { agent: FleetAgent }) {
  // Staleness outranks load: a box that is not reporting is not "ok", whatever
  // its last load reading said.
  const [label, color] = agent.is_stale
    ? ["not reporting", "oklch(70.4% 0.191 22.216)"]
    : agent.load_state === "over_capacity"
      ? ["over capacity", "oklch(70.4% 0.191 22.216)"]
      : agent.load_state === "degraded"
        ? ["degraded", "oklch(85% 0.16 84)"]
        : ["healthy", "oklch(79.2% 0.209 151.711)"];

  return (
    <span
      className="rounded-md border px-2 py-1 text-[11px] uppercase tracking-[0.04em]"
      style={{
        color,
        borderColor: `color-mix(in oklab, ${color} 40%, transparent)`,
        backgroundColor: `color-mix(in oklab, ${color} 10%, transparent)`,
      }}
    >
      {label}
    </span>
  );
}
