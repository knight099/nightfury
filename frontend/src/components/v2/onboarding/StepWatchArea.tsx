"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Btn, Card } from "@/components/v2/ui";
import { ZonesEditor } from "@/components/cameras/ZonesEditor";
import type { OnboardingStatusResponse } from "@/types";
import { StepProtected } from "./StepProtected";

/**
 * Wraps the existing ZonesEditor as a single guided "Watch area" step.
 * Constrained to one zone per pilot: the state machine only needs one
 * camera zoned to move past this step (see `_derive` in
 * onboarding_status_service.py), so drawing more is left for the regular
 * camera settings page later, not forced here.
 */
export function StepWatchArea({
  agentId,
  status,
}: {
  agentId: string;
  status: OnboardingStatusResponse;
}) {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<"prompt" | "drawing" | "skipped">("prompt");

  const target = status.cameras.find((c) => c.first_frame_at && c.zones_count === 0);

  const { data: cameras } = useQuery({
    queryKey: ["cameras"],
    queryFn: () => api.getCameras(),
    enabled: mode === "drawing" && !!target,
  });
  const camera = cameras?.find((c) => c.id === target?.camera_id);

  if (mode === "skipped") {
    return <StepProtected agentId={agentId} status={status} />;
  }

  if (mode === "drawing" && camera) {
    return (
      <ZonesEditor
        camera={camera}
        onClose={() => {
          queryClient.invalidateQueries({ queryKey: ["onboarding-status", agentId] });
          setMode("prompt");
        }}
      />
    );
  }

  return (
    <Card className="space-y-4">
      <div>
        <h2 className="text-[15px] font-semibold">Which area should Nightwatch watch?</h2>
        <p className="text-[13px] text-[oklch(72%_0.01_265)] mt-1">
          Recommended: draw only entrances, gates, doors, and restricted areas.
        </p>
      </div>
      <div className="flex gap-2">
        <Btn variant="primary" onClick={() => setMode("drawing")} disabled={!target}>
          Draw area
        </Btn>
        <Btn onClick={() => setMode("skipped")}>Skip for now</Btn>
      </div>
    </Card>
  );
}
