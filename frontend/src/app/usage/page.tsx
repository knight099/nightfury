"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAuthStore } from "@/lib/store";
import { RefreshCw, Trash2 } from "lucide-react";

interface UsageEntry {
  timestamp: string;
  operation?: string;
  prompt_tokens: number;
  output_tokens: number;
  total_tokens: number;
  thoughts_tokens: number;
  latency_ms: number;
  cost_usd: number;
}

interface UsageResponse {
  aggregate: {
    calls: number;
    prompt_tokens: number;
    output_tokens: number;
    total_tokens: number;
    cost_usd: number;
    total_latency_ms: number;
    avg_latency_ms: number;
  };
  history: UsageEntry[];
}

interface OrgUsageRecent {
  id: string;
  timestamp: string;
  username: string;
  model: string;
  operation: string;
  prompt_tokens: number;
  output_tokens: number;
  total_tokens: number;
  latency_ms: number;
  cost_usd: number;
}

interface OrgUsageByUser {
  user_id: string;
  username: string;
  name: string;
  calls: number;
  total_tokens: number;
  cost_usd: number;
}

interface OrgUsageResponse {
  period_days: number;
  aggregate: {
    calls: number;
    prompt_tokens: number;
    output_tokens: number;
    total_tokens: number;
    cost_usd: number;
    avg_latency_ms: number;
  };
  by_user: OrgUsageByUser[];
  recent: OrgUsageRecent[];
}

export default function UsagePage() {
  const queryClient = useQueryClient();
  const { user } = useAuthStore();
  const isOwner = user?.role === "owner" || user?.role === "super_admin";
  const [tab, setTab] = useState<"mine" | "org">("mine");
  const [orgDays, setOrgDays] = useState(30);

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["test-camera-usage"],
    queryFn: () => api.request<UsageResponse>("/api/test-camera/usage"),
  });

  const { data: orgData, isLoading: orgLoading, refetch: orgRefetch } = useQuery({
    queryKey: ["org-ai-usage", orgDays],
    queryFn: () => api.request<OrgUsageResponse>(`/api/settings/ai-usage?days=${orgDays}&limit=200`),
    enabled: isOwner && tab === "org",
  });

  const resetMutation = useMutation({
    mutationFn: () => api.request<{ status: string }>("/api/test-camera/usage", { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["test-camera-usage"] }),
  });

  const agg = data?.aggregate || { calls: 0, prompt_tokens: 0, output_tokens: 0, total_tokens: 0, cost_usd: 0, total_latency_ms: 0, avg_latency_ms: 0 };
  const history = data?.history || [];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-xl font-bold text-[#F5F5F5]">AI Usage</h1>
          <p className="text-xs text-[#666666] mt-1">Token consumption, latency, and estimated cost</p>
        </div>
        <div className="flex gap-2">
          {tab === "org" && (
            <select
              value={orgDays}
              onChange={(e) => setOrgDays(Number(e.target.value))}
              className="px-3 py-1.5 bg-[#1A1A1A] border border-[#2A2A2A] rounded-md text-sm text-[#F5F5F5]"
            >
              <option value={1}>Last 24h</option>
              <option value={7}>Last 7 days</option>
              <option value={30}>Last 30 days</option>
              <option value={90}>Last 90 days</option>
              <option value={365}>Last year</option>
            </select>
          )}
          <button
            onClick={() => tab === "org" ? orgRefetch() : refetch()}
            className="flex items-center gap-2 px-3 py-1.5 bg-[#1A1A1A] text-[#A3A3A3] border border-[#2A2A2A] rounded-md text-sm hover:text-[#F5F5F5] transition-colors"
          >
            <RefreshCw size={14} /> Refresh
          </button>
          {tab === "mine" && (
            <button
              onClick={() => { if (confirm("Reset your Redis cache (DB history is preserved)?")) resetMutation.mutate(); }}
              className="flex items-center gap-2 px-3 py-1.5 bg-[#1A1A1A] text-[#A3A3A3] border border-[#2A2A2A] rounded-md text-sm hover:text-[#EF4444] transition-colors"
            >
              <Trash2 size={14} /> Reset
            </button>
          )}
        </div>
      </div>

      {isOwner && (
        <div className="flex gap-2 border-b border-[#2A2A2A]">
          <button
            onClick={() => setTab("mine")}
            className={`px-4 py-2 text-sm font-medium transition-colors -mb-px ${
              tab === "mine"
                ? "text-[#1E90FF] border-b-2 border-[#1E90FF]"
                : "text-[#A3A3A3] hover:text-[#F5F5F5]"
            }`}
          >
            My Usage (Redis · Test Camera)
          </button>
          <button
            onClick={() => setTab("org")}
            className={`px-4 py-2 text-sm font-medium transition-colors -mb-px ${
              tab === "org"
                ? "text-[#1E90FF] border-b-2 border-[#1E90FF]"
                : "text-[#A3A3A3] hover:text-[#F5F5F5]"
            }`}
          >
            Organization Usage (DB · All users)
          </button>
        </div>
      )}

      {tab === "org" && isOwner && (
        <OrgUsageView data={orgData} loading={orgLoading} days={orgDays} />
      )}

      {tab === "mine" && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
            <Stat label="Total Calls" value={agg.calls.toLocaleString()} />
            <Stat label="Input Tokens" value={agg.prompt_tokens.toLocaleString()} color="#1E90FF" />
            <Stat label="Output Tokens" value={agg.output_tokens.toLocaleString()} color="#FBBF24" />
            <Stat label="Total Tokens" value={agg.total_tokens.toLocaleString()} color="#F5F5F5" />
            <Stat label="Avg Latency" value={`${agg.avg_latency_ms}ms`} color="#A3A3A3" />
            <Stat label="Est. Cost" value={`$${agg.cost_usd.toFixed(4)}`} color="#4ADE80" />
          </div>

          <div className="bg-[#111111] border border-[#2A2A2A] rounded-lg overflow-hidden">
            <div className="p-3 border-b border-[#2A2A2A] flex items-center justify-between">
              <h2 className="text-sm font-semibold text-[#F5F5F5]">Recent Calls ({history.length})</h2>
              <span className="text-xs text-[#666666]">Last 100 calls (Redis)</span>
            </div>

            {isLoading ? (
              <div className="p-6 text-center text-sm text-[#666666]">Loading...</div>
            ) : history.length === 0 ? (
              <div className="p-6 text-center text-sm text-[#666666]">No usage yet. Try the <a href="/test-camera" className="text-[#1E90FF] hover:underline">Test Camera</a>.</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="bg-[#0D0D0D] text-[#666666] uppercase text-[10px]">
                    <tr>
                      <th className="text-left p-3">Time</th>
                      <th className="text-left p-3">Op</th>
                      <th className="text-right p-3">Input</th>
                      <th className="text-right p-3">Output</th>
                      <th className="text-right p-3">Total</th>
                      <th className="text-right p-3">Latency</th>
                      <th className="text-right p-3">Cost</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.map((entry, idx) => (
                      <tr key={idx} className="border-t border-[#2A2A2A] hover:bg-[#1A1A1A]">
                        <td className="p-3 text-[#A3A3A3]">{new Date(entry.timestamp).toLocaleString()}</td>
                        <td className="p-3 text-[#666666]">{entry.operation || "—"}</td>
                        <td className="p-3 text-right text-[#1E90FF]">{entry.prompt_tokens.toLocaleString()}</td>
                        <td className="p-3 text-right text-[#FBBF24]">{entry.output_tokens.toLocaleString()}</td>
                        <td className="p-3 text-right text-[#F5F5F5]">{entry.total_tokens.toLocaleString()}</td>
                        <td className="p-3 text-right text-[#A3A3A3]">{entry.latency_ms}ms</td>
                        <td className="p-3 text-right text-[#4ADE80]">${entry.cost_usd.toFixed(5)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}

      <div className="bg-[#111111] border border-[#2A2A2A] rounded-lg p-4">
        <h3 className="text-sm font-semibold text-[#F5F5F5] mb-2">Pricing</h3>
        <div className="text-xs text-[#A3A3A3] space-y-1">
          <p>Model: <span className="text-[#1E90FF]">gemini-2.5-flash</span> (Vertex AI / gebra-ai / us-central1)</p>
          <p>Input (text + image): <span className="text-[#F5F5F5]">$0.30 per 1M tokens</span></p>
          <p>Output: <span className="text-[#F5F5F5]">$2.50 per 1M tokens</span></p>
          <p className="text-[#666666] pt-1">Cost is an estimate — actual billing may differ. Adjust pricing constants in backend if Google updates rates.</p>
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value, color = "#F5F5F5" }: { label: string; value: string; color?: string }) {
  return (
    <div className="bg-[#111111] border border-[#2A2A2A] rounded-lg p-3">
      <div className="text-xs text-[#666666] uppercase">{label}</div>
      <div className="text-xl font-bold mt-1" style={{ color }}>{value}</div>
    </div>
  );
}

function OrgUsageView({ data, loading, days }: { data: OrgUsageResponse | undefined; loading: boolean; days: number }) {
  if (loading) return <p className="text-sm text-[#666666]">Loading...</p>;
  if (!data) return <p className="text-sm text-[#666666]">No data.</p>;

  const agg = data.aggregate;
  const totalCost = agg.cost_usd;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <Stat label="Total Calls" value={agg.calls.toLocaleString()} />
        <Stat label="Input Tokens" value={agg.prompt_tokens.toLocaleString()} color="#1E90FF" />
        <Stat label="Output Tokens" value={agg.output_tokens.toLocaleString()} color="#FBBF24" />
        <Stat label="Total Tokens" value={agg.total_tokens.toLocaleString()} />
        <Stat label="Avg Latency" value={`${agg.avg_latency_ms}ms`} color="#A3A3A3" />
        <Stat label="Total Cost" value={`$${agg.cost_usd.toFixed(4)}`} color="#4ADE80" />
      </div>

      <div className="bg-[#111111] border border-[#2A2A2A] rounded-lg overflow-hidden">
        <div className="p-3 border-b border-[#2A2A2A] flex items-center justify-between">
          <h2 className="text-sm font-semibold text-[#F5F5F5]">By User ({data.by_user.length})</h2>
          <span className="text-xs text-[#666666]">Last {days} day{days === 1 ? "" : "s"}</span>
        </div>
        {data.by_user.length === 0 ? (
          <div className="p-6 text-center text-sm text-[#666666]">No usage in this period.</div>
        ) : (
          <table className="w-full text-xs">
            <thead className="bg-[#0D0D0D] text-[#666666] uppercase text-[10px]">
              <tr>
                <th className="text-left p-3">User</th>
                <th className="text-right p-3">Calls</th>
                <th className="text-right p-3">Tokens</th>
                <th className="text-right p-3">Cost</th>
                <th className="text-right p-3">% of Org</th>
              </tr>
            </thead>
            <tbody>
              {data.by_user.map((u) => (
                <tr key={u.user_id} className="border-t border-[#2A2A2A] hover:bg-[#1A1A1A]">
                  <td className="p-3">
                    <div className="text-[#F5F5F5]">{u.name}</div>
                    <div className="text-[#666666] text-[10px]">@{u.username}</div>
                  </td>
                  <td className="p-3 text-right text-[#A3A3A3]">{u.calls.toLocaleString()}</td>
                  <td className="p-3 text-right text-[#F5F5F5]">{u.total_tokens.toLocaleString()}</td>
                  <td className="p-3 text-right text-[#4ADE80]">${u.cost_usd.toFixed(4)}</td>
                  <td className="p-3 text-right text-[#1E90FF]">
                    {totalCost > 0 ? ((u.cost_usd / totalCost) * 100).toFixed(1) : "0.0"}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="bg-[#111111] border border-[#2A2A2A] rounded-lg overflow-hidden">
        <div className="p-3 border-b border-[#2A2A2A] flex items-center justify-between">
          <h2 className="text-sm font-semibold text-[#F5F5F5]">Recent Calls ({data.recent.length})</h2>
          <span className="text-xs text-[#666666]">Postgres · audit trail</span>
        </div>
        {data.recent.length === 0 ? (
          <div className="p-6 text-center text-sm text-[#666666]">No calls in this period.</div>
        ) : (
          <div className="overflow-x-auto max-h-[600px]">
            <table className="w-full text-xs">
              <thead className="bg-[#0D0D0D] text-[#666666] uppercase text-[10px] sticky top-0">
                <tr>
                  <th className="text-left p-3">Time</th>
                  <th className="text-left p-3">User</th>
                  <th className="text-left p-3">Op</th>
                  <th className="text-left p-3">Model</th>
                  <th className="text-right p-3">Input</th>
                  <th className="text-right p-3">Output</th>
                  <th className="text-right p-3">Total</th>
                  <th className="text-right p-3">Latency</th>
                  <th className="text-right p-3">Cost</th>
                </tr>
              </thead>
              <tbody>
                {data.recent.map((entry) => (
                  <tr key={entry.id} className="border-t border-[#2A2A2A] hover:bg-[#1A1A1A]">
                    <td className="p-3 text-[#A3A3A3]">{new Date(entry.timestamp).toLocaleString()}</td>
                    <td className="p-3 text-[#F5F5F5]">@{entry.username}</td>
                    <td className="p-3 text-[#666666]">{entry.operation}</td>
                    <td className="p-3 text-[#666666]">{entry.model}</td>
                    <td className="p-3 text-right text-[#1E90FF]">{entry.prompt_tokens.toLocaleString()}</td>
                    <td className="p-3 text-right text-[#FBBF24]">{entry.output_tokens.toLocaleString()}</td>
                    <td className="p-3 text-right text-[#F5F5F5]">{entry.total_tokens.toLocaleString()}</td>
                    <td className="p-3 text-right text-[#A3A3A3]">{entry.latency_ms}ms</td>
                    <td className="p-3 text-right text-[#4ADE80]">${entry.cost_usd.toFixed(5)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
