"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, RadarIcon } from "lucide-react";
import { api } from "@/lib/api";
import { Btn, Card, ErrorBox, Field, inputClass } from "@/components/v2/ui";
import type { OnboardingStatusResponse, Site } from "@/types";
import { NvrCredentialCard } from "./StepSelectCameras";

function useSites() {
  const { data, isLoading } = useQuery({ queryKey: ["sites"], queryFn: () => api.getSites() });
  return { sites: data ?? [], isLoading, hasSites: (data?.length ?? 0) > 0 };
}

function SiteSelect({ sites, siteId, setSiteId }: { sites: Site[]; siteId: string; setSiteId: (v: string) => void }) {
  return (
    <Field label="Site">
      <select value={siteId} onChange={(e) => setSiteId(e.target.value)} className={inputClass}>
        {sites.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name}
          </option>
        ))}
      </select>
    </Field>
  );
}

export function StepScanning({
  agentId,
  status,
}: {
  agentId: string;
  status: OnboardingStatusResponse;
}) {
  const queryClient = useQueryClient();
  const { sites, hasSites } = useSites();
  const [siteId, setSiteId] = useState("");
  const [scanError, setScanError] = useState<string | null>(null);

  useEffect(() => {
    if (!siteId && sites.length > 0) setSiteId(sites[0].id);
  }, [sites, siteId]);

  const { data: discovered, isFetching: discovering } = useQuery({
    queryKey: ["agent-discover", agentId],
    queryFn: () => api.discoverAgentCameras(agentId),
    refetchInterval: 5000,
  });

  const scanMutation = useMutation({
    mutationFn: () => api.scanNow(agentId),
    onError: (e: Error) => setScanError(e.message || "The box is not connected right now."),
    onSuccess: () => setScanError(null),
  });

  const devices = discovered?.devices ?? [];

  return (
    <Card className="space-y-4">
      <div>
        <h2 className="text-[15px] font-semibold">Finding your cameras</h2>
        <p className="text-[13px] text-[oklch(72%_0.01_265)] mt-1">
          Nightwatch looks for your NVR automatically over the local network.
        </p>
      </div>

      <div className="space-y-1.5 font-mono text-[12.5px]">
        <div className="text-[oklch(79.2%_0.209_151.711)]">✓ Nightwatch box connected</div>
        {devices.length === 0 ? (
          <div className="flex items-center gap-2 text-[oklch(72%_0.01_265)]">
            <Loader2 size={12} className="animate-spin" /> Looking for your NVR…
          </div>
        ) : (
          devices.map((d) => (
            <div key={d.uuid} className="text-[oklch(79.2%_0.209_151.711)]">
              ✓ Found {d.name !== "unknown" ? d.name : "a device"} — {d.xaddr}
            </div>
          ))
        )}
      </div>

      <div className="flex items-center gap-2">
        <Btn
          onClick={() => scanMutation.mutate()}
          disabled={scanMutation.isPending || discovering}
          className="inline-flex items-center gap-1.5"
        >
          <RadarIcon size={12} />
          {scanMutation.isPending ? "Scanning…" : "Scan again"}
        </Btn>
      </div>
      {scanError && <ErrorBox message={scanError} />}

      {devices.length > 0 && hasSites && (
        <div className="space-y-3 pt-2 border-t border-[oklch(22%_0.015_265)]">
          <SiteSelect sites={sites} siteId={siteId} setSiteId={setSiteId} />
          <div className="space-y-2">
            {devices.map((d) => (
              <NvrCredentialCard
                key={d.uuid}
                agentId={agentId}
                device={d}
                siteId={siteId}
                onRegistered={() =>
                  queryClient.invalidateQueries({ queryKey: ["onboarding-status", agentId] })
                }
              />
            ))}
          </div>
        </div>
      )}

      {devices.length > 0 && !hasSites && (
        <div className="text-[13px] text-[oklch(72%_0.01_265)]">
          Create a site under Sites before adding cameras.
        </div>
      )}

      {status.discovered_count === 0 && devices.length === 0 && (
        <p className="text-[11.5px] text-[oklch(55%_0.01_265)]">
          Make sure your NVR is on the same network as the Nightwatch box. This can take up to a
          minute on the first scan.
        </p>
      )}
    </Card>
  );
}
