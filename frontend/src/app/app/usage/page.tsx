"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { useAuthStore } from "@/lib/store";
import { Skeleton } from "@/components/ui/Skeleton";
import { Page, PageHeader, Card, Btn, EmptyState, inputClass, V2 } from "@/components/v2/ui";

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

const BLUE = "oklch(70% 0.14 250)";

export default function UsagePageV2() {
  const queryClient = useQueryClient();
  const { user } = useAuthStore();
  const isOwner = user?.role === "owner" || user?.role === "super_admin";
  const [tab, setTab] = useState<"mine" | "org">("mine");
  const [orgDays, setOrgDays] = useState(30);

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["test-camera-usage"],
    queryFn: () => api.request<UsageResponse>("/api/test-camera/usage"),
  });

  const {
    data: orgData,
    isLoading: orgLoading,
    refetch: orgRefetch,
  } = useQuery({
    queryKey: ["org-ai-usage", orgDays],
    queryFn: () => api.request<OrgUsageResponse>(`/api/settings/ai-usage?days=${orgDays}&limit=200`),
    enabled: isOwner && tab === "org",
  });

  const resetMutation = useMutation({
    mutationFn: () =>
      api.request<{ status: string }>("/api/test-camera/usage", { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["test-camera-usage"] }),
  });

  const agg = data?.aggregate ?? {
    calls: 0,
    prompt_tokens: 0,
    output_tokens: 0,
    total_tokens: 0,
    cost_usd: 0,
    total_latency_ms: 0,
    avg_latency_ms: 0,
  };
  const history = data?.history ?? [];

  return (
    <Page wide>
      <PageHeader
        title="AI usage"
        subtitle="Token consumption, latency, and estimated cost."
        action={
          <div className="flex gap-2 shrink-0">
            {tab === "org" && (
              <select
                value={orgDays}
                onChange={(e) => setOrgDays(Number(e.target.value))}
                className={`${inputClass} !w-auto`}
              >
                <option value={1}>Last 24h</option>
                <option value={7}>Last 7 days</option>
                <option value={30}>Last 30 days</option>
                <option value={90}>Last 90 days</option>
                <option value={365}>Last year</option>
              </select>
            )}
            <Btn
              onClick={() => (tab === "org" ? orgRefetch() : refetch())}
              className="inline-flex items-center gap-2"
            >
              <RefreshCw size={14} /> Refresh
            </Btn>
            {tab === "mine" && (
              <Btn
                variant="danger"
                onClick={() => {
                  if (confirm("Reset your Redis cache (DB history is preserved)?"))
                    resetMutation.mutate();
                }}
                className="inline-flex items-center gap-2"
              >
                <Trash2 size={14} /> Reset
              </Btn>
            )}
          </div>
        }
      />

      {isOwner && (
        <div className="flex gap-2 border-b border-[oklch(22%_0.015_265)] mb-5">
          {(
            [
              ["mine", "My usage (Redis · Test AI)"],
              ["org", "Organization usage (DB · all users)"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={`px-4 py-2 text-[13px] font-semibold transition-colors -mb-px ${
                tab === id
                  ? "text-[oklch(85%_0.16_84)] border-b-2 border-[oklch(85%_0.16_84)]"
                  : "text-[oklch(55%_0.01_265)] hover:text-[oklch(97%_0.005_265)]"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      )}

      {tab === "org" && isOwner && (
        <OrgUsageView data={orgData} loading={orgLoading} days={orgDays} />
      )}

      {tab === "mine" && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
            <Stat label="Total calls" value={agg.calls.toLocaleString()} />
            <Stat label="Input tokens" value={agg.prompt_tokens.toLocaleString()} color={BLUE} />
            <Stat label="Output tokens" value={agg.output_tokens.toLocaleString()} color={V2.amber} />
            <Stat label="Total tokens" value={agg.total_tokens.toLocaleString()} />
            <Stat label="Avg latency" value={`${agg.avg_latency_ms}ms`} color={V2.muted} />
            <Stat label="Est. cost" value={`$${agg.cost_usd.toFixed(4)}`} color={V2.green} />
          </div>

          <Card padded={false} className="overflow-hidden">
            <div className="p-3.5 border-b border-[oklch(22%_0.015_265)] flex items-center justify-between">
              <h2 className="text-[13px] font-semibold">Recent calls ({history.length})</h2>
              <span className="text-[11.5px] text-[oklch(55%_0.01_265)]">Last 100 calls (Redis)</span>
            </div>
            {isLoading ? (
              <div className="p-4 space-y-2">
                {Array.from({ length: 5 }).map((_, i) => (
                  <Skeleton key={i} className="h-8 rounded-md" />
                ))}
              </div>
            ) : history.length === 0 ? (
              <div className="p-6 text-center text-[13px] text-[oklch(55%_0.01_265)]">
                No usage yet. Try the{" "}
                <a href="/app/test-camera" className="text-[oklch(85%_0.16_84)] hover:underline">
                  Test AI
                </a>{" "}
                page.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-[11.5px]">
                  <TableHead
                    cols={["Time", "Op", "Input", "Output", "Total", "Latency", "Cost"]}
                    rightFrom={2}
                  />
                  <tbody>
                    {history.map((entry, idx) => (
                      <tr
                        key={idx}
                        className="border-t border-[oklch(19%_0.015_265)] hover:bg-[oklch(15%_0.015_265)]"
                      >
                        <td className="p-3 text-[oklch(72%_0.01_265)]">
                          {new Date(entry.timestamp).toLocaleString()}
                        </td>
                        <td className="p-3 text-[oklch(55%_0.01_265)]">{entry.operation || "—"}</td>
                        <td className="p-3 text-right" style={{ color: BLUE }}>
                          {entry.prompt_tokens.toLocaleString()}
                        </td>
                        <td className="p-3 text-right" style={{ color: V2.amber }}>
                          {entry.output_tokens.toLocaleString()}
                        </td>
                        <td className="p-3 text-right text-[oklch(97%_0.005_265)]">
                          {entry.total_tokens.toLocaleString()}
                        </td>
                        <td className="p-3 text-right text-[oklch(72%_0.01_265)]">
                          {entry.latency_ms}ms
                        </td>
                        <td className="p-3 text-right" style={{ color: V2.green }}>
                          ${entry.cost_usd.toFixed(5)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </div>
      )}

      <Card className="mt-4">
        <h3 className="text-[13px] font-semibold mb-2">Pricing</h3>
        <div className="text-[12px] text-[oklch(72%_0.01_265)] space-y-1">
          <p>
            Model: <span className="text-[oklch(85%_0.16_84)]">gemini-2.5-flash</span> (Vertex AI ·
            us-central1)
          </p>
          <p>
            Input (text + image):{" "}
            <span className="text-[oklch(97%_0.005_265)]">$0.30 per 1M tokens</span>
          </p>
          <p>
            Output: <span className="text-[oklch(97%_0.005_265)]">$2.50 per 1M tokens</span>
          </p>
          <p className="text-[oklch(55%_0.01_265)] pt-1">
            Cost is an estimate — actual billing may differ. Adjust the pricing constants in the
            backend if Google updates rates.
          </p>
        </div>
      </Card>
    </Page>
  );
}

function TableHead({ cols, rightFrom }: { cols: string[]; rightFrom: number }) {
  return (
    <thead className="bg-[oklch(9%_0.015_265)] text-[oklch(55%_0.01_265)] uppercase text-[10px]">
      <tr>
        {cols.map((c, i) => (
          <th key={c} className={`p-3 ${i >= rightFrom ? "text-right" : "text-left"}`}>
            {c}
          </th>
        ))}
      </tr>
    </thead>
  );
}

function Stat({ label, value, color = V2.ink }: { label: string; value: string; color?: string }) {
  return (
    <Card padded={false} className="p-3.5">
      <div className="text-[11px] uppercase tracking-[0.04em] text-[oklch(55%_0.01_265)]">
        {label}
      </div>
      <div className="text-xl font-bold mt-1 tabular-nums" style={{ color }}>
        {value}
      </div>
    </Card>
  );
}

function OrgUsageView({
  data,
  loading,
  days,
}: {
  data: OrgUsageResponse | undefined;
  loading: boolean;
  days: number;
}) {
  if (loading)
    return (
      <div className="space-y-3">
        <Skeleton className="h-20 rounded-[14px]" />
        <Skeleton className="h-40 rounded-[14px]" />
      </div>
    );
  if (!data) return <EmptyState title="No data." />;

  const agg = data.aggregate;
  const totalCost = agg.cost_usd;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <Stat label="Total calls" value={agg.calls.toLocaleString()} />
        <Stat label="Input tokens" value={agg.prompt_tokens.toLocaleString()} color={BLUE} />
        <Stat label="Output tokens" value={agg.output_tokens.toLocaleString()} color={V2.amber} />
        <Stat label="Total tokens" value={agg.total_tokens.toLocaleString()} />
        <Stat label="Avg latency" value={`${agg.avg_latency_ms}ms`} color={V2.muted} />
        <Stat label="Total cost" value={`$${agg.cost_usd.toFixed(4)}`} color={V2.green} />
      </div>

      <Card padded={false} className="overflow-hidden">
        <div className="p-3.5 border-b border-[oklch(22%_0.015_265)] flex items-center justify-between">
          <h2 className="text-[13px] font-semibold">By user ({data.by_user.length})</h2>
          <span className="text-[11.5px] text-[oklch(55%_0.01_265)]">
            Last {days} day{days === 1 ? "" : "s"}
          </span>
        </div>
        {data.by_user.length === 0 ? (
          <div className="p-6 text-center text-[13px] text-[oklch(55%_0.01_265)]">
            No usage in this period.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[11.5px]">
              <TableHead cols={["User", "Calls", "Tokens", "Cost", "% of org"]} rightFrom={1} />
              <tbody>
                {data.by_user.map((u) => (
                  <tr
                    key={u.user_id}
                    className="border-t border-[oklch(19%_0.015_265)] hover:bg-[oklch(15%_0.015_265)]"
                  >
                    <td className="p-3">
                      <div className="text-[oklch(97%_0.005_265)]">{u.name}</div>
                      <div className="text-[oklch(55%_0.01_265)] text-[10px]">@{u.username}</div>
                    </td>
                    <td className="p-3 text-right text-[oklch(72%_0.01_265)]">
                      {u.calls.toLocaleString()}
                    </td>
                    <td className="p-3 text-right text-[oklch(97%_0.005_265)]">
                      {u.total_tokens.toLocaleString()}
                    </td>
                    <td className="p-3 text-right" style={{ color: V2.green }}>
                      ${u.cost_usd.toFixed(4)}
                    </td>
                    <td className="p-3 text-right" style={{ color: BLUE }}>
                      {totalCost > 0 ? ((u.cost_usd / totalCost) * 100).toFixed(1) : "0.0"}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card padded={false} className="overflow-hidden">
        <div className="p-3.5 border-b border-[oklch(22%_0.015_265)] flex items-center justify-between">
          <h2 className="text-[13px] font-semibold">Recent calls ({data.recent.length})</h2>
          <span className="text-[11.5px] text-[oklch(55%_0.01_265)]">Postgres · audit trail</span>
        </div>
        {data.recent.length === 0 ? (
          <div className="p-6 text-center text-[13px] text-[oklch(55%_0.01_265)]">
            No calls in this period.
          </div>
        ) : (
          <div className="overflow-x-auto max-h-[600px]">
            <table className="w-full text-[11.5px]">
              <TableHead
                cols={[
                  "Time",
                  "User",
                  "Op",
                  "Model",
                  "Input",
                  "Output",
                  "Total",
                  "Latency",
                  "Cost",
                ]}
                rightFrom={4}
              />
              <tbody>
                {data.recent.map((entry) => (
                  <tr
                    key={entry.id}
                    className="border-t border-[oklch(19%_0.015_265)] hover:bg-[oklch(15%_0.015_265)]"
                  >
                    <td className="p-3 text-[oklch(72%_0.01_265)]">
                      {new Date(entry.timestamp).toLocaleString()}
                    </td>
                    <td className="p-3 text-[oklch(97%_0.005_265)]">@{entry.username}</td>
                    <td className="p-3 text-[oklch(55%_0.01_265)]">{entry.operation}</td>
                    <td className="p-3 text-[oklch(55%_0.01_265)]">{entry.model}</td>
                    <td className="p-3 text-right" style={{ color: BLUE }}>
                      {entry.prompt_tokens.toLocaleString()}
                    </td>
                    <td className="p-3 text-right" style={{ color: V2.amber }}>
                      {entry.output_tokens.toLocaleString()}
                    </td>
                    <td className="p-3 text-right text-[oklch(97%_0.005_265)]">
                      {entry.total_tokens.toLocaleString()}
                    </td>
                    <td className="p-3 text-right text-[oklch(72%_0.01_265)]">
                      {entry.latency_ms}ms
                    </td>
                    <td className="p-3 text-right" style={{ color: V2.green }}>
                      ${entry.cost_usd.toFixed(5)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
