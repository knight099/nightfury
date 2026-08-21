"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { Btn, ErrorBox, inputClass } from "@/components/v2/ui";
import type { DiscoveredDevice } from "@/types";

/**
 * One credential prompt per discovered NVR, then a channel checklist.
 *
 * The password lives only in this component's own useState — never in a
 * query key, never in localStorage — for exactly as long as the two calls
 * that need it (resolve, then register). It is never logged or persisted
 * beyond that.
 */
export function NvrCredentialCard({
  agentId,
  device,
  siteId,
  onRegistered,
}: {
  agentId: string;
  device: DiscoveredDevice;
  siteId: string;
  onRegistered: () => void;
}) {
  const queryClient = useQueryClient();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [resolving, setResolving] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const resolveMutation = useMutation({
    mutationFn: () => api.resolveNvrChannels(agentId, { xaddr: device.xaddr, username, password }),
    onSuccess: () => {
      setResolving(true);
      setErrorMsg(null);
    },
    onError: (e: Error) => setErrorMsg(e.message || "Could not reach the box."),
  });

  const { data: channels } = useQuery({
    queryKey: ["nvr-channels", agentId],
    queryFn: () => api.getNvrChannels(agentId),
    enabled: resolving,
    refetchInterval: (query) => (query.state.data?.channels.length ? false : 2000),
  });

  const registerMutation = useMutation({
    mutationFn: async () => {
      const picks = (channels?.channels ?? []).filter((c) => selected.has(c.profile_token));
      for (const [i, ch] of picks.entries()) {
        await api.registerAgentCameraFromOnvif(agentId, {
          name: ch.name || `Camera ${i + 1}`,
          site_id: siteId || undefined,
          onvif_xaddr: device.xaddr,
          user: username,
          pass: password,
          profile_token: ch.profile_token,
        });
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["onboarding-status", agentId] });
      onRegistered();
    },
    onError: (e: Error) => setErrorMsg(e.message || "Could not add cameras."),
  });

  const toggle = (token: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(token)) next.delete(token);
      else next.add(token);
      return next;
    });
  };

  const foundChannels = channels?.channels ?? [];

  return (
    <div className="border border-[oklch(22%_0.015_265)] bg-[oklch(15%_0.015_265)] rounded-md p-3 space-y-3">
      <div className="text-[12.5px] text-[oklch(97%_0.005_265)] font-medium">
        {device.name !== "unknown" ? device.name : "NVR"}{" "}
        <span className="text-[oklch(55%_0.01_265)] font-mono text-[11px]">{device.xaddr}</span>
      </div>

      {!resolving && (
        <div className="space-y-2">
          <div className="flex gap-2">
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="NVR username"
              className={inputClass}
            />
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="NVR password"
              className={inputClass}
            />
          </div>
          {errorMsg && <ErrorBox message={errorMsg} />}
          <Btn
            variant="primary"
            onClick={() => resolveMutation.mutate()}
            disabled={!username || !password || resolveMutation.isPending}
          >
            {resolveMutation.isPending ? "Connecting…" : "Connect"}
          </Btn>
        </div>
      )}

      {resolving && foundChannels.length === 0 && (
        <div className="flex items-center gap-2 text-[12.5px] text-[oklch(72%_0.01_265)] py-1">
          <Loader2 size={14} className="animate-spin" />
          Reading channels from the NVR…
        </div>
      )}

      {resolving && foundChannels.length > 0 && (
        <div className="space-y-2">
          <div className="text-[11.5px] text-[oklch(72%_0.01_265)]">
            Found {foundChannels.length} channel{foundChannels.length === 1 ? "" : "s"}. Pick which
            ones to protect.
          </div>
          <div className="space-y-1.5 max-h-64 overflow-y-auto">
            {foundChannels.map((ch, i) => (
              <label
                key={ch.profile_token}
                className="flex items-center gap-2 text-[12.5px] text-[oklch(90%_0.005_265)] cursor-pointer"
              >
                <input
                  type="checkbox"
                  checked={selected.has(ch.profile_token)}
                  onChange={() => toggle(ch.profile_token)}
                />
                {ch.name || `Channel ${i + 1}`}
              </label>
            ))}
          </div>
          {errorMsg && <ErrorBox message={errorMsg} />}
          <Btn
            variant="primary"
            onClick={() => registerMutation.mutate()}
            disabled={selected.size === 0 || registerMutation.isPending}
          >
            {registerMutation.isPending
              ? "Adding…"
              : `Protect ${selected.size || ""} camera${selected.size === 1 ? "" : "s"}`}
          </Btn>
        </div>
      )}
    </div>
  );
}
