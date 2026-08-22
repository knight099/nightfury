"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Btn, Pill } from "@/components/v2/ui";
import type { AssistantProposal } from "@/types";

const KIND_LABEL: Record<AssistantProposal["kind"], string> = {
  alert_rule: "Alert rule",
  camera_connection: "Camera connection",
};

function payloadDetails(payload: Record<string, unknown>): [string, string][] {
  return Object.entries(payload)
    .filter(([, v]) => v !== null && v !== undefined && v !== "")
    .map(([k, v]) => [k, typeof v === "object" ? JSON.stringify(v) : String(v)]);
}

/**
 * Renders one proposal from the assistant (a proposed alert rule or camera
 * connection). `proposal.summary` is the server-templated sentence and is
 * rendered verbatim as the headline — never re-derive card text from
 * `payload` on the client, that reintroduces the exact divergence (card says
 * one thing, system does another) the server-side template exists to
 * prevent. Payload fields are shown only as supplementary detail below it.
 */
export function ProposalCard({
  proposal,
  onApplied,
}: {
  proposal: AssistantProposal;
  onApplied?: () => void;
}) {
  const qc = useQueryClient();

  const applyMutation = useMutation({
    mutationFn: () => api.applyProposal(proposal.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["alert-rules"] });
      qc.invalidateQueries({ queryKey: ["camera-connections"] });
      onApplied?.();
    },
  });

  const rejectMutation = useMutation({
    mutationFn: () => api.rejectProposal(proposal.id),
    onSuccess: () => {
      onApplied?.();
    },
  });

  const isPending = applyMutation.isPending || rejectMutation.isPending;
  const details = payloadDetails(proposal.payload);
  const isReadOnly = proposal.status !== "pending";

  return (
    <div
      className="rounded-[14px] border bg-[oklch(12%_0.015_265)] p-4"
      style={{
        borderColor: isReadOnly ? "oklch(22% 0.015 265)" : "oklch(85% 0.16 84)",
      }}
    >
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="text-[11px] uppercase tracking-[0.04em] text-[oklch(55%_0.01_265)]">
          {KIND_LABEL[proposal.kind]}
        </div>
        {isReadOnly && (
          <Pill
            tone={
              proposal.status === "applied" ? "green" : proposal.status === "rejected" ? "red" : "amber"
            }
          >
            {proposal.status}
          </Pill>
        )}
      </div>

      <div className="text-[14px] text-[oklch(97%_0.005_265)] leading-relaxed mb-3">
        {proposal.summary}
      </div>

      {details.length > 0 && (
        <div className="text-[12.5px] text-[oklch(55%_0.01_265)] space-y-1 mb-4">
          {details.map(([key, value]) => (
            <div key={key} className="flex gap-2">
              <span className="text-[oklch(72%_0.01_265)]">{key}:</span>
              <span className="truncate">{value}</span>
            </div>
          ))}
        </div>
      )}

      {(applyMutation.isError || rejectMutation.isError) && (
        <div className="text-[12.5px] text-[oklch(70.4%_0.191_22.216)] mb-3">
          {(applyMutation.error ?? rejectMutation.error) instanceof Error
            ? (applyMutation.error ?? rejectMutation.error)!.message
            : "Something went wrong."}
        </div>
      )}

      {!isReadOnly && (
        <div className="flex gap-2">
          <Btn
            variant="primary"
            disabled={isPending}
            onClick={() => applyMutation.mutate()}
          >
            {applyMutation.isPending ? "Applying…" : "Apply"}
          </Btn>
          <Btn
            variant="ghost"
            disabled={isPending}
            onClick={() => rejectMutation.mutate()}
          >
            {rejectMutation.isPending ? "Dismissing…" : "Dismiss"}
          </Btn>
        </div>
      )}
    </div>
  );
}
