"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { api } from "@/lib/api";
import { StatusDot } from "@/components/shared/status-dot";
import { Skeleton } from "@/components/ui/Skeleton";
import type { SetupProposal, SetupReviewGroup } from "@/types";

const BATCH_CAP = 50;

/**
 * Agentic camera setup — pick a batch, let the agent propose, review by group.
 *
 * The rationale is shown in full on every card: an operator approving twelve
 * cameras at once needs to know WHY vehicle detection was left off, and a
 * proposal they cannot interrogate is one they will rubber-stamp or ignore.
 */
export default function SetupPage() {
  const qc = useQueryClient();
  const [siteId, setSiteId] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [runId, setRunId] = useState<string | null>(null);

  const { data: sites } = useQuery({ queryKey: ["sites"], queryFn: () => api.getSites() });
  const activeSiteId = siteId ?? sites?.[0]?.id ?? null;

  const { data: cameras } = useQuery({
    queryKey: ["cameras", activeSiteId],
    queryFn: () => api.getCameras({ site_id: activeSiteId as string }),
    enabled: !!activeSiteId,
  });

  // A run's proposals take ~3 minutes to arrive. If the operator refreshes
  // mid-wait, `runId` (React state) is gone — without this, that run is
  // orphaned: unreachable, and its rows stay `pending` forever. On load,
  // adopt the most recent still-pending run for this site so the operator
  // lands back where they were.
  const { data: runSummaries } = useQuery({
    queryKey: ["setup-runs", activeSiteId],
    queryFn: () => api.getSetupRuns(activeSiteId as string),
    enabled: !!activeSiteId && !runId,
  });

  useEffect(() => {
    if (runId || !runSummaries?.length) return;
    const resumable = runSummaries.find((r) => r.pending > 0);
    if (resumable) setRunId(resumable.id);
  }, [runId, runSummaries]);

  const { data: run } = useQuery({
    queryKey: ["setup-run", runId],
    queryFn: () => api.getSetupRun(runId as string),
    enabled: !!runId,
    // Proposals arrive as each box finishes observing, over a few minutes.
    refetchInterval: (q) => ((q.state.data?.pending ?? 0) > 0 ? 10_000 : false),
  });

  const start = useMutation({
    mutationFn: () => api.startSetupRun(activeSiteId as string, [...selected]),
    onSuccess: (r) => { setRunId(r.id); setSelected(new Set()); },
  });

  const approveGroup = useMutation({
    mutationFn: (sceneType: string) => api.approveSetupGroup(runId as string, sceneType),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["setup-run", runId] }),
  });

  const approveOne = useMutation({
    mutationFn: (id: string) => api.approveSetupProposal(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["setup-run", runId] }),
  });

  const cameraName = (id: string) =>
    (cameras ?? []).find((c) => c.id === id)?.name ?? "Unknown camera";

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else if (next.size < BATCH_CAP) next.add(id);
      return next;
    });
  }

  if (!sites?.length) {
    return <p className="text-sm text-[#A3A3A3]">No sites yet.</p>;
  }

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-heading text-2xl font-bold text-[#F5F5F5]">Camera setup</h1>
          <p className="mt-1 max-w-2xl text-sm text-[#A3A3A3]">
            Pick a batch of cameras. Each appliance watches its own cameras for
            a few minutes and proposes what they should detect. Nothing changes
            until you approve it.
          </p>
        </div>
        <select
          value={activeSiteId ?? ""}
          onChange={(e) => { setSiteId(e.target.value); setRunId(null); }}
          className="rounded-md border border-[#2A2A2A] bg-[#1F1F1F] px-3 py-2 text-sm text-[#F5F5F5] transition-colors focus:border-[#1E90FF] focus:outline-none"
        >
          {sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
      </header>

      {!runId && (
        <section className="space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-sm text-[#A3A3A3]">
              {selected.size} of {BATCH_CAP} selected
            </span>
            <button
              disabled={selected.size === 0 || start.isPending}
              onClick={() => start.mutate()}
              className="rounded-md bg-[#1E90FF] px-3 py-2 text-sm text-white transition-colors hover:bg-[#3BA0FF] disabled:opacity-40"
            >
              {start.isPending ? "Starting…" : "Propose setup"}
            </button>
            {start.isError && (
              <span className="text-sm text-amber-400">
                {(start.error as Error).message}
              </span>
            )}
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
            {(cameras ?? []).map((c) => (
              <button
                key={c.id}
                onClick={() => toggle(c.id)}
                className={`flex items-center gap-2 rounded-lg border p-3 text-left text-sm transition-colors ${
                  selected.has(c.id)
                    ? "border-[#1E90FF] bg-[#1E90FF]/10 text-[#F5F5F5]"
                    : "border-[#2A2A2A] bg-[#111111] text-[#A3A3A3] hover:bg-[#1A1A1A]"
                }`}
              >
                <StatusDot status={c.status} />
                <span className="truncate">{c.name}</span>
              </button>
            ))}
          </div>
        </section>
      )}

      {runId && !run && <Skeleton className="h-64 w-full" />}

      {run && (
        <section className="space-y-4">
          {run.pending > 0 && (
            <p className="rounded-md border border-[#2A2A2A] bg-[#111111] px-3 py-2 text-sm text-[#A3A3A3]">
              Watching {run.pending} of {run.camera_count} cameras… proposals
              appear as each appliance finishes.
            </p>
          )}

          {run.groups.map((g: SetupReviewGroup) => (
            <article key={g.scene_type} className="rounded-lg border border-[#2A2A2A] bg-[#111111] p-4">
              <header className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="font-heading text-lg font-semibold text-[#F5F5F5]">
                  {g.label}
                  <span className="ml-2 text-sm font-normal text-[#666666]">
                    {g.proposals.length} camera{g.proposals.length === 1 ? "" : "s"}
                  </span>
                </h2>
                {g.bulk_approvable && (
                  <button
                    onClick={() => approveGroup.mutate(g.scene_type)}
                    disabled={approveGroup.isPending}
                    className="rounded-md bg-[#1E90FF] px-3 py-1.5 text-sm text-white transition-colors hover:bg-[#3BA0FF] disabled:opacity-40"
                  >
                    Approve all {g.proposals.length}
                  </button>
                )}
              </header>

              {g.bulk_approvable && (
                <p className="mt-1 font-mono text-xs text-[#666666]">
                  {String((g.shared_config.enabled_events as string[])?.join(", ") ?? "")}
                  {" · "}
                  {String(g.shared_config.sensitivity ?? "")}
                </p>
              )}

              <ul className="mt-3 space-y-2">
                {[...g.proposals, ...g.differing].map((p: SetupProposal) => (
                  <li key={p.id} className="rounded-md border border-[#2A2A2A] bg-[#0D0D0D] p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="text-sm text-[#F5F5F5]">{cameraName(p.camera_id)}</span>
                      {p.status === "proposed" ? (
                        <button
                          onClick={() => approveOne.mutate(p.id)}
                          className="rounded border border-[#1E90FF]/50 px-2 py-1 text-xs text-[#1E90FF] transition-colors hover:bg-[#1E90FF]/10"
                        >
                          Approve
                        </button>
                      ) : (
                        <span className="text-xs text-[#666666]">{p.status}</span>
                      )}
                    </div>
                    {p.scene_description && (
                      <p className="mt-1 text-xs text-[#A3A3A3]">{p.scene_description}</p>
                    )}
                    {p.rationale && (
                      <p className="mt-1 text-xs text-[#666666]">{p.rationale}</p>
                    )}
                    {p.error && <p className="mt-1 text-xs text-amber-400">{p.error}</p>}
                  </li>
                ))}
              </ul>
            </article>
          ))}

          {run.pending === 0 && (
            <p className="rounded-md border border-[#2A2A2A] bg-[#111111] px-3 py-3 text-sm text-[#A3A3A3]">
              Next: tell Nightwatch which of these cameras are physically
              connected, so it can follow activity between them.{" "}
              <Link href="/map" className="text-[#1E90FF] hover:underline">
                Open the camera map
              </Link>
            </p>
          )}
        </section>
      )}
    </div>
  );
}
