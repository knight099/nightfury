"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

interface PairCodeResponse {
  code: string;
  expires_at: string;
}

interface AgentSummary {
  id: string;
  machine_id: string;
  version: string | null;
  transport: string | null;
  status: string;
  last_seen_at: string | null;
  created_at: string;
}

interface AgentListResponse {
  agents: AgentSummary[];
}

export function PairStep({ onPaired }: { onPaired: (agentId: string) => void }) {
  const [code, setCode] = useState<string | null>(null);
  const [, setExpiresAt] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .request<PairCodeResponse>("/api/agents/pair-codes", {
        method: "POST",
        body: JSON.stringify({}),
      })
      .then((r) => {
        setCode(r.code);
        setExpiresAt(new Date(r.expires_at));
      })
      .catch((e: unknown) => {
        const msg = e instanceof Error ? e.message : "failed to mint code";
        setError(msg);
      });
  }, []);

  useEffect(() => {
    const t = setInterval(async () => {
      try {
        const r = await api.request<AgentListResponse>("/api/agents");
        const fresh = r.agents.find(
          (a) => new Date(a.created_at) > new Date(Date.now() - 5 * 60 * 1000)
        );
        if (fresh) {
          clearInterval(t);
          onPaired(fresh.id);
        }
      } catch {
        // ignore poll errors
      }
    }, 3000);
    return () => clearInterval(t);
  }, [onPaired]);

  if (error) return <p className="text-[#EF4444]">{error}</p>;
  if (!code) return <p className="text-[#A3A3A3]">Generating code…</p>;

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">Pair your agent</h2>
      <p className="text-[#A3A3A3]">
        Open the agent&apos;s web UI (
        <code className="bg-[#1a1a1a] px-1 rounded">http://&lt;device-ip&gt;:8765</code>
        ) and enter this code:
      </p>
      <div className="text-6xl font-mono tracking-widest text-center py-8 bg-[#1a1a1a] border border-[#2A2A2A] rounded">
        {code}
      </div>
      <p className="text-sm text-[#A3A3A3]">
        Expires in 10 minutes. Waiting for agent…
      </p>
    </div>
  );
}
