"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { Btn, Card, ErrorBox } from "@/components/v2/ui";
import type { OnboardingStatusResponse } from "@/types";

const WALK_TEST_TIMEOUT_MS = 2 * 60 * 1000;
const WALK_TEST_POLL_MS = 4000;

export function StepProtected({
  agentId,
  status,
}: {
  agentId: string;
  status: OnboardingStatusResponse;
}) {
  const queryClient = useQueryClient();
  const [since, setSince] = useState<string | null>(null);
  const [timedOut, setTimedOut] = useState(false);

  const alreadyVerified = status.state === "alert_verified" || status.state === "protected";

  const notifyMutation = useMutation({
    mutationFn: () => api.sendTestNotification(),
    onSuccess: () => {
      setTimedOut(false);
      setSince(new Date().toISOString());
    },
  });

  useEffect(() => {
    if (!since || alreadyVerified) return;
    const t = setTimeout(() => setTimedOut(true), WALK_TEST_TIMEOUT_MS);
    return () => clearTimeout(t);
  }, [since, alreadyVerified]);

  const walkTestQuery = useQuery({
    queryKey: ["walk-test", agentId, since],
    queryFn: () => api.getWalkTest(agentId, since!),
    enabled: !!since && !alreadyVerified && !timedOut,
    refetchInterval: (query) => (query.state.data?.passed ? false : WALK_TEST_POLL_MS),
  });

  const walkPassed = alreadyVerified || walkTestQuery.data?.passed;

  if (walkPassed) {
    return (
      <Card className="space-y-3">
        <div className="flex flex-col items-center gap-3 py-4 text-center">
          <div className="h-12 w-12 rounded-full bg-[oklch(85%_0.16_84)]/15 border border-[oklch(85%_0.16_84)] flex items-center justify-center">
            <Check size={24} className="text-[oklch(85%_0.16_84)]" />
          </div>
          <div className="text-[15px] font-semibold text-[oklch(97%_0.005_265)]">
            Person detected — you&apos;re protected
          </div>
          <p className="text-[13px] text-[oklch(72%_0.01_265)] max-w-[46ch]">
            Nightwatch is watching and will alert your configured contacts when it sees activity.
          </p>
        </div>
      </Card>
    );
  }

  return (
    <Card className="space-y-4">
      <div>
        <h2 className="text-[15px] font-semibold">Test your alerts</h2>
        <p className="text-[13px] text-[oklch(72%_0.01_265)] mt-1">
          Two quick checks: does the notification reach you, and does a real event get detected.
        </p>
      </div>

      <div className="space-y-1.5 font-mono text-[12.5px]">
        {!since ? (
          <Btn
            variant="primary"
            onClick={() => notifyMutation.mutate()}
            disabled={notifyMutation.isPending}
            className="inline-flex items-center gap-1.5"
          >
            {notifyMutation.isPending && <Loader2 size={12} className="animate-spin" />}
            {notifyMutation.isPending ? "Sending…" : "Send test notification"}
          </Btn>
        ) : (
          <>
            <div
              className={
                notifyMutation.data?.delivered
                  ? "text-[oklch(79.2%_0.209_151.711)]"
                  : "text-[oklch(70.4%_0.191_22.216)]"
              }
            >
              {notifyMutation.data?.delivered ? "✓" : "✗"} {notifyMutation.data?.detail}
            </div>
            <div className="text-[oklch(90%_0.005_265)]">Now walk through your watch area.</div>
            {timedOut ? (
              <div className="text-[oklch(70.4%_0.191_22.216)]">
                No event detected in 2 minutes.
              </div>
            ) : (
              <div className="flex items-center gap-2 text-[oklch(72%_0.01_265)]">
                <Loader2 size={12} className="animate-spin" /> Waiting for a real camera event…
              </div>
            )}
          </>
        )}
      </div>

      {notifyMutation.isError && (
        <ErrorBox message={(notifyMutation.error as Error).message || "Could not send test."} />
      )}

      {timedOut && (
        <Btn
          onClick={() => {
            setTimedOut(false);
            setSince(new Date().toISOString());
            queryClient.invalidateQueries({ queryKey: ["walk-test", agentId] });
          }}
        >
          Retry
        </Btn>
      )}
    </Card>
  );
}
