"use client";

import { Loader2, TriangleAlert } from "lucide-react";
import { Card } from "@/components/v2/ui";
import type { OnboardingStatusResponse } from "@/types";

/**
 * "Stream verified" means a decoded frame, not an opened stream object —
 * see Camera.last_frame_at gating in backend/app/api/internal.py. This is
 * the step that catches a wrong NVR password, so it deliberately does not
 * advance until at least one camera actually verifies; WizardHost picks up
 * the state change on its next poll.
 */
export function StepVerifyStream({
  status,
}: {
  agentId: string;
  status: OnboardingStatusResponse;
}) {
  return (
    <Card className="space-y-4">
      <div>
        <h2 className="text-[15px] font-semibold">Verifying your cameras</h2>
        <p className="text-[13px] text-[oklch(72%_0.01_265)] mt-1">
          Waiting for a real decoded frame from each camera — this proves the stream actually
          works, not just that it opened.
        </p>
      </div>

      <div className="space-y-2">
        {status.cameras.map((cam) => (
          <div
            key={cam.camera_id}
            className="flex items-center gap-3 border border-[oklch(22%_0.015_265)] bg-[oklch(15%_0.015_265)] rounded-md p-3"
          >
            {cam.snapshot_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={cam.snapshot_url}
                alt={cam.name}
                className="w-16 h-10 object-cover rounded border border-[oklch(22%_0.015_265)]"
              />
            ) : (
              <div className="w-16 h-10 rounded border border-[oklch(22%_0.015_265)] bg-[oklch(9%_0.015_265)] flex items-center justify-center">
                <Loader2 size={14} className="animate-spin text-[oklch(55%_0.01_265)]" />
              </div>
            )}
            <div className="flex-1 min-w-0">
              <div className="text-[13px] text-[oklch(97%_0.005_265)] truncate">{cam.name}</div>
              {cam.first_frame_at ? (
                <div className="text-[11.5px] text-[oklch(79.2%_0.209_151.711)]">
                  Camera connected
                </div>
              ) : cam.failure_reason ? (
                <div className="text-[11.5px] text-[oklch(70.4%_0.191_22.216)] flex items-center gap-1">
                  <TriangleAlert size={11} /> {cam.failure_reason}
                </div>
              ) : (
                <div className="text-[11.5px] text-[oklch(55%_0.01_265)]">Waiting for video…</div>
              )}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}
