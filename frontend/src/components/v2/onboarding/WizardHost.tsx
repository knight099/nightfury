"use client";

import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { Card, V2 } from "@/components/v2/ui";
import type { OnboardingState, OnboardingStatusResponse } from "@/types";
import { StepScanning } from "./StepScanning";
import { StepVerifyStream } from "./StepVerifyStream";
import { StepWatchArea } from "./StepWatchArea";
import { StepProtected } from "./StepProtected";

const STATES: OnboardingState[] = [
  "waiting_claim",
  "paired",
  "scanning",
  "cameras_selected",
  "stream_verified",
  "zones_saved",
  "alert_verified",
  "protected",
];

const STATE_LABELS: Record<OnboardingState, string> = {
  waiting_claim: "Waiting for box",
  paired: "Box connected",
  scanning: "Finding cameras",
  cameras_selected: "Cameras selected",
  stream_verified: "Stream verified",
  zones_saved: "Watch area set",
  alert_verified: "Alerts tested",
  protected: "Protected",
};

function ProgressRail({ state }: { state: OnboardingState }) {
  const idx = STATES.indexOf(state);
  return (
    <div className="mb-6 space-y-1.5">
      <div className="flex items-center gap-1.5">
        {STATES.map((s, i) => (
          <span
            key={s}
            title={STATE_LABELS[s]}
            className="h-1.5 flex-1 rounded-full transition-colors"
            style={{ backgroundColor: i <= idx ? V2.amber : V2.border }}
          />
        ))}
      </div>
      <div className="text-[11.5px] text-[oklch(55%_0.01_265)]">{STATE_LABELS[state]}</div>
    </div>
  );
}

/**
 * Renders whatever GET /api/agents/{id}/onboarding-status returns, and
 * nothing else. Holds no step state of its own: a refresh, or a customer
 * resuming on their phone after starting on a laptop, lands on the same
 * step because the server — not this component — owns the current state.
 */
export function WizardHost({ agentId }: { agentId: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["onboarding-status", agentId],
    queryFn: () => api.getOnboardingStatus(agentId),
    refetchInterval: 3000,
  });

  if (isLoading && !data) {
    return (
      <Card className="flex items-center justify-center gap-3 py-8">
        <Loader2 size={18} className="animate-spin text-[oklch(85%_0.16_84)]" />
        <div className="text-[13px] text-[oklch(72%_0.01_265)]">Loading setup status…</div>
      </Card>
    );
  }

  if (error || !data) {
    return (
      <Card>
        <div className="text-[13px] text-[oklch(70.4%_0.191_22.216)]">
          Could not load setup status. Refresh to try again.
        </div>
      </Card>
    );
  }

  return (
    <div>
      <ProgressRail state={data.state} />
      <WizardStep agentId={agentId} status={data} />
      {!data.agent_online && data.state !== "waiting_claim" && (
        <div className="mt-4 text-[11.5px] text-[oklch(70.4%_0.191_22.216)]">
          {data.failure_reason ?? "Box is not reporting in."}
        </div>
      )}
    </div>
  );
}

function WizardStep({ agentId, status }: { agentId: string; status: OnboardingStatusResponse }) {
  switch (status.state) {
    case "waiting_claim":
      return (
        <Card className="space-y-2">
          <div className="text-[15px] font-semibold">Waiting for your box</div>
          <p className="text-[13px] text-[oklch(72%_0.01_265)] leading-relaxed">
            Once it powers on and reaches the internet, this page updates on its own — no need to
            refresh.
          </p>
        </Card>
      );
    case "paired":
    case "scanning":
      return <StepScanning agentId={agentId} status={status} />;
    case "cameras_selected":
      return <StepVerifyStream agentId={agentId} status={status} />;
    case "stream_verified":
      return <StepWatchArea agentId={agentId} status={status} />;
    case "zones_saved":
    case "alert_verified":
    case "protected":
      return <StepProtected agentId={agentId} status={status} />;
    default:
      return null;
  }
}
