"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAuthStore } from "@/lib/store";
import { useEventsSocket } from "@/lib/useEventsSocket";
import { useChatPanelState } from "@/lib/chatPanelState";
import { useChatSeedStore } from "@/lib/chatSeed";
import { SeverityBadge } from "@/components/shared/severity-badge";
import { StatusDot } from "@/components/shared/status-dot";
import { Skeleton } from "@/components/ui/Skeleton";
import { AlertTriangle, Camera, Send } from "lucide-react";
import { startOnboardingTour, shouldShowTour } from "@/lib/tour";
import type { ChatMessage, Event, Camera as CameraType, EventStatsTimeBucket, PaginatedResponse } from "@/types";

const ACCENT = "#1E90FF";

function relativeTime(iso: string): string {
  const ts = new Date(iso).getTime();
  if (Number.isNaN(ts)) return "";
  const diff = Math.max(0, Date.now() - ts);
  const s = Math.floor(diff / 1000);
  if (s < 60) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}

export default function DashboardPage() {
  const { user } = useAuthStore();
  const queryClient = useQueryClient();

  useEffect(() => {
    if (shouldShowTour() && window.innerWidth >= 1024) {
      const timer = setTimeout(() => startOnboardingTour(), 800);
      return () => clearTimeout(timer);
    }
  }, []);

  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ["events", "stats"],
    queryFn: () => api.getEventStats("24h"),
    refetchInterval: 30000,
  });

  const { data: eventsData, isLoading: eventsLoading } = useQuery({
    queryKey: ["events", "recent"],
    queryFn: () => api.getEvents({ per_page: "10", page: "1" }),
  });

  const handleNewEvent = useCallback(
    (event: Event) => {
      queryClient.setQueryData<PaginatedResponse<Event>>(["events", "recent"], (old) => {
        const prevEvents = old?.events ?? [];
        if (prevEvents.some((e) => e.id === event.id)) return old;
        const nextEvents = [event, ...prevEvents].slice(0, 10);
        return {
          events: nextEvents,
          total: (old?.total ?? 0) + 1,
          page: old?.page ?? 1,
          pages: old?.pages ?? 1,
        };
      });
      queryClient.invalidateQueries({ queryKey: ["events", "stats"] });
    },
    [queryClient]
  );

  useEventsSocket(handleNewEvent);

  const { data: cameras } = useQuery({
    queryKey: ["cameras"],
    queryFn: () => api.getCameras(),
  });

  const cameraNameById = useMemo(() => {
    const map: Record<string, string> = {};
    (cameras || []).forEach((c: CameraType) => {
      map[c.id] = c.name;
    });
    return map;
  }, [cameras]);

  const events = eventsData?.events || [];
  const onlineCameras = cameras?.filter((c: CameraType) => c.status === "online").length || 0;
  const totalCameras = cameras?.length || 0;

  return (
    <div className="space-y-4 lg:space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-bold">Dashboard</h1>
        <span className="text-xs text-[#666666]">
          Welcome, {user?.name}
          {user?.role === "super_admin" && (
            <span className="ml-2 px-2 py-0.5 bg-[#1E90FF]/10 text-[#1E90FF] rounded text-xs">
              SUPER ADMIN
            </span>
          )}
        </span>
      </div>

      {/* System status strip */}
      {cameras && cameras.length > 0 && (
        <div
          className={`flex items-center gap-3 px-4 py-3 rounded-lg border text-sm ${
            onlineCameras === totalCameras
              ? "bg-[#4ADE80]/5 border-[#4ADE80]/20 text-[#4ADE80]"
              : "bg-[#FBBF24]/5 border-[#FBBF24]/20 text-[#FBBF24]"
          }`}
        >
          <span
            className={`inline-block w-2 h-2 rounded-full pulse-live ${
              onlineCameras === totalCameras ? "bg-[#4ADE80]" : "bg-[#FBBF24]"
            }`}
          />
          {onlineCameras === totalCameras
            ? `All ${totalCameras} camera${totalCameras === 1 ? "" : "s"} watching`
            : `${totalCameras - onlineCameras} camera${totalCameras - onlineCameras === 1 ? "" : "s"} offline — check power and Wi-Fi`}
        </div>
      )}

      <AskBar />

      {/* Analytics */}
      {statsLoading && !stats ? (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 lg:gap-4">
          <Skeleton className="h-56 rounded-lg lg:col-span-2" />
          <Skeleton className="h-56 rounded-lg" />
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 lg:gap-4">
          <div className="lg:col-span-2 bg-[#111111] rounded-lg border border-[#2A2A2A] p-4">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-medium">Event volume — last 24h</h2>
              <span className="flex items-center gap-1.5 text-[10px] text-[#666666] font-mono tabular-nums">
                <AlertTriangle size={12} className="text-[#1E90FF]" />
                {stats?.total_events ?? 0} total
              </span>
            </div>
            <TrendChart buckets={stats?.time_series || []} />
          </div>
          <div className="bg-[#111111] rounded-lg border border-[#2A2A2A] p-4">
            <div className="flex items-center gap-2 mb-3">
              <Camera size={14} className="text-[#1E90FF]" />
              <h2 className="text-sm font-medium">Busiest cameras</h2>
            </div>
            <CameraBreakdown rows={stats?.by_camera || []} />
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <MiniStat label="Cameras online" value={`${onlineCameras}/${totalCameras}`} />
        <MiniStat label="Critical (24h)" value={stats?.by_severity?.critical || 0} tone="critical" />
        <MiniStat label="Feedback rate" value={`${((stats?.feedback_rate || 0) * 100).toFixed(0)}%`} />
        <MiniStat label="Accuracy" value={`${(100 - (stats?.false_positive_rate || 0) * 100).toFixed(0)}%`} />
      </div>

      {/* Narrative event feed */}
      <div className="bg-[#111111] rounded-lg border border-[#2A2A2A]">
        <div className="px-4 py-3 border-b border-[#2A2A2A] flex items-center gap-2">
          <h2 className="text-sm font-medium">What's been happening</h2>
          <span className="flex items-center gap-1.5 text-[10px] text-[#4ADE80] uppercase tracking-wider font-mono">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-[#4ADE80] pulse-live" />
            Live
          </span>
        </div>
        <div className="divide-y divide-[#2A2A2A]">
          {eventsLoading && !eventsData && (
            <div className="p-4 space-y-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-12 rounded-md" />
              ))}
            </div>
          )}
          {!eventsLoading && events.length === 0 && (
            <div className="px-4 py-10 text-center">
              <p className="text-sm text-[#A3A3A3]">All quiet for now.</p>
              <p className="mt-1 text-xs text-[#666666]">
                Events show up here the moment your cameras spot something.
              </p>
            </div>
          )}
          {events.map((event: Event) => {
            const cameraName = cameraNameById[event.camera_id] || "Unknown camera";
            return (
              <div
                key={event.id}
                className="px-4 py-3 flex items-start gap-3 hover:bg-[#1A1A1A] transition-colors fade-up"
              >
                <SeverityBadge severity={event.severity} />
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-[#F5F5F5] truncate">{event.description}</p>
                  <p className="text-xs text-[#666666] mt-0.5">
                    {cameraName} · {relativeTime(event.timestamp)}
                  </p>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Camera Grid */}
      {cameras && cameras.length > 0 && (
        <div className="bg-[#111111] rounded-lg border border-[#2A2A2A]">
          <div className="px-4 py-3 border-b border-[#2A2A2A]">
            <h2 className="text-sm font-medium">Cameras</h2>
          </div>
          <div className="p-4 grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-3">
            {cameras.map((cam: CameraType) => (
              <div key={cam.id} className="flex items-center gap-2 px-3 py-2 bg-[#1A1A1A] rounded-md">
                <StatusDot status={cam.status} />
                <span className="text-xs truncate">{cam.name}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function AskBar() {
  const [question, setQuestion] = useState("");
  const [exchange, setExchange] = useState<{ q: string; a: string; conversationId: string } | null>(null);
  const setCollapsed = useChatPanelState((s) => s.setCollapsed);

  const askMutation = useMutation({
    mutationFn: (q: string) => api.chatSend({ message: q }),
    onSuccess: (reply, q) => {
      setExchange({ q, a: reply.content, conversationId: reply.conversation_id });
      setQuestion("");
    },
  });

  const continueInChat = () => {
    if (!exchange) return;
    const now = new Date().toISOString();
    const seedMessages: ChatMessage[] = [
      { id: "seed-user", role: "user", content: exchange.q, conversation_id: exchange.conversationId, created_at: now },
      { id: "seed-assistant", role: "assistant", content: exchange.a, conversation_id: exchange.conversationId, created_at: now },
    ];
    useChatSeedStore.getState().setSeed(exchange.conversationId, seedMessages);
    setCollapsed(false);
  };

  return (
    <div className="bg-[#111111] rounded-lg border border-[#2A2A2A] p-3">
      <div className="flex items-center gap-2">
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && question.trim() && !askMutation.isPending) askMutation.mutate(question.trim());
          }}
          placeholder="Ask about your cameras… e.g. 'any unusual activity overnight?'"
          className="flex-1 bg-[#1F1F1F] border border-[#2A2A2A] rounded-md px-3 py-2 text-sm text-[#F5F5F5] placeholder:text-[#666666] focus:outline-none focus:border-[#1E90FF]"
        />
        <button
          onClick={() => question.trim() && askMutation.mutate(question.trim())}
          disabled={!question.trim() || askMutation.isPending}
          className="p-2 bg-[#1E90FF] hover:bg-[#3BA0FF] disabled:opacity-40 rounded-md text-white transition-colors"
          aria-label="Ask"
        >
          <Send size={16} />
        </button>
      </div>
      {askMutation.isPending && <p className="mt-2 text-xs text-[#666666]">Thinking…</p>}
      {exchange && !askMutation.isPending && (
        <div className="mt-3 bg-[#1A1A1A] border border-[#2A2A2A] rounded-md p-3">
          <p className="text-sm text-[#F5F5F5] whitespace-pre-wrap">{exchange.a}</p>
          <button
            onClick={continueInChat}
            className="mt-2 text-xs text-[#1E90FF] hover:text-[#3BA0FF] transition-colors"
          >
            Continue in chat →
          </button>
        </div>
      )}
      {askMutation.isError && (
        <p className="mt-2 text-xs text-red-400">Couldn't get an answer — try again.</p>
      )}
    </div>
  );
}

function TrendChart({ buckets }: { buckets: EventStatsTimeBucket[] }) {
  const width = 560;
  const height = 160;
  const padding = { top: 8, right: 8, bottom: 20, left: 8 };
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);

  if (buckets.length === 0) {
    return (
      <div className="h-40 flex items-center justify-center text-xs text-[#666666]">
        No events in this window yet.
      </div>
    );
  }

  const maxCount = Math.max(1, ...buckets.map((b) => b.count));
  const innerW = width - padding.left - padding.right;
  const innerH = height - padding.top - padding.bottom;
  const stepX = buckets.length > 1 ? innerW / (buckets.length - 1) : 0;

  const points = buckets.map((b, i) => ({
    x: padding.left + i * stepX,
    y: padding.top + innerH - (b.count / maxCount) * innerH,
    bucket: b,
  }));

  const linePath = points.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ");
  const areaPath = `${linePath} L ${points[points.length - 1].x.toFixed(1)} ${padding.top + innerH} L ${points[0].x.toFixed(1)} ${padding.top + innerH} Z`;

  const handleMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const relX = ((e.clientX - rect.left) / rect.width) * width;
    let nearest = 0;
    let best = Infinity;
    points.forEach((p, i) => {
      const d = Math.abs(p.x - relX);
      if (d < best) {
        best = d;
        nearest = i;
      }
    });
    setHoverIdx(nearest);
  };

  const hovered = hoverIdx !== null ? points[hoverIdx] : null;
  const firstLabel = new Date(buckets[0].bucket).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
  const lastLabel = new Date(buckets[buckets.length - 1].bucket).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });

  return (
    <div ref={containerRef} className="relative w-full overflow-x-auto">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full h-40"
        onMouseMove={handleMove}
        onMouseLeave={() => setHoverIdx(null)}
        role="img"
        aria-label="Event volume over the last 24 hours"
      >
        <line
          x1={padding.left}
          y1={padding.top + innerH}
          x2={width - padding.right}
          y2={padding.top + innerH}
          stroke="#2A2A2A"
          strokeWidth={1}
        />
        <path d={areaPath} fill={ACCENT} fillOpacity={0.12} stroke="none" />
        <path d={linePath} fill="none" stroke={ACCENT} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
        <circle cx={points[points.length - 1].x} cy={points[points.length - 1].y} r={3} fill={ACCENT} />
        {hovered && (
          <>
            <line x1={hovered.x} y1={padding.top} x2={hovered.x} y2={padding.top + innerH} stroke="#2A2A2A" strokeWidth={1} />
            <circle cx={hovered.x} cy={hovered.y} r={4} fill={ACCENT} stroke="#111111" strokeWidth={2} />
          </>
        )}
      </svg>
      <div className="flex justify-between text-[10px] text-[#666666] font-mono px-1">
        <span>{firstLabel}</span>
        <span>{lastLabel}</span>
      </div>
      {hovered && (
        <div
          className="absolute -top-1 px-2 py-1 bg-[#1A1A1A] border border-[#2A2A2A] rounded text-[10px] text-[#F5F5F5] whitespace-nowrap tabular-nums pointer-events-none"
          style={{ left: `${(hovered.x / width) * 100}%`, transform: "translate(-50%, -100%)" }}
        >
          {new Date(hovered.bucket.bucket).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })} · {hovered.bucket.count} events
        </div>
      )}
    </div>
  );
}

function CameraBreakdown({ rows }: { rows: { camera_id: string | null; camera_name: string; count: number }[] }) {
  if (rows.length === 0) {
    return <div className="text-xs text-[#666666]">No events in this window yet.</div>;
  }
  const max = Math.max(1, ...rows.map((r) => r.count));
  return (
    <div className="space-y-2">
      {rows.map((r) => (
        <div key={r.camera_id ?? "other"}>
          <div className="flex items-center justify-between text-xs mb-1">
            <span className="text-[#A3A3A3] truncate">{r.camera_name}</span>
            <span className="text-[#F5F5F5] font-mono tabular-nums">{r.count}</span>
          </div>
          <div className="h-1.5 bg-[#1A1A1A] rounded-full overflow-hidden">
            <div
              className="h-full rounded-full"
              style={{ width: `${(r.count / max) * 100}%`, backgroundColor: ACCENT }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

function useCountUp(target: number, durationMs = 600): number {
  const [display, setDisplay] = useState(target);
  const fromRef = useRef(target);

  useEffect(() => {
    const from = fromRef.current;
    if (from === target) return;
    let raf = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / durationMs);
      const eased = 1 - (1 - t) * (1 - t);
      setDisplay(Math.round(from + (target - from) * eased));
      if (t < 1) raf = requestAnimationFrame(tick);
      else fromRef.current = target;
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, durationMs]);

  return display;
}

function MiniStat({ label, value, tone }: { label: string; value: string | number; tone?: "critical" }) {
  const numeric = typeof value === "number";
  const animated = useCountUp(numeric ? value : 0);
  return (
    <div className="bg-[#111111] rounded-lg border border-[#2A2A2A] p-3 card-lift">
      <div className="text-[10px] text-[#666666] uppercase tracking-wide mb-1">{label}</div>
      <div className={`text-lg font-bold font-heading tabular-nums ${tone === "critical" ? "text-red-400" : ""}`}>
        {numeric ? animated : value}
      </div>
    </div>
  );
}
