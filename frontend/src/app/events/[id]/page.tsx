"use client";

import { useState, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Play, ChevronDown } from "lucide-react";
import { api } from "@/lib/api";
import { useAuthStore } from "@/lib/store";
import { useChatContextStore } from "@/lib/chatContext";
import { SeverityBadge } from "@/components/shared/severity-badge";
import { JourneyCard } from "@/components/map/JourneyCard";
import { Skeleton } from "@/components/ui/Skeleton";

export default function EventDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { user } = useAuthStore();
  const canFeedback = user?.role !== "viewer";

  const [showClip, setShowClip] = useState(false);
  const [reclassifyOpen, setReclassifyOpen] = useState(false);
  const [reclassifyLabel, setReclassifyLabel] = useState("");

  const id = params?.id;
  const setEventContext = useChatContextStore((s) => s.setEventContext);

  useEffect(() => {
    if (!id) return;
    setEventContext(id);
    return () => setEventContext(null);
  }, [id, setEventContext]);

  const { data, isLoading, error } = useQuery({
    queryKey: ["event", id],
    queryFn: () => api.getEvent(id as string),
    enabled: !!id,
    retry: false,
  });

  useEffect(() => {
    if (error && /401/.test(error.message)) {
      router.replace("/login");
    }
  }, [error, router]);

  const feedbackMutation = useMutation({
    mutationFn: ({ feedback, label }: { feedback: string; label?: string }) =>
      api.submitFeedback(id as string, feedback, label),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["event", id] });
      queryClient.invalidateQueries({ queryKey: ["events"] });
      setReclassifyOpen(false);
      setReclassifyLabel("");
    },
  });

  if (isLoading) {
    return (
      <div className="space-y-4">
        <BackLink />
        <Skeleton className="h-8 w-64" />
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="md:col-span-2 space-y-3">
            <Skeleton className="w-full aspect-video rounded-lg" />
          </div>
          <div className="space-y-3 bg-[#111111] border border-[#2A2A2A] rounded-lg p-4">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-4 w-full" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    const is404 = /404/.test(error.message) || /not found/i.test(error.message);
    return (
      <div className="space-y-4">
        <BackLink />
        <div className="bg-[#111111] border border-[#2A2A2A] rounded-lg p-8 text-center">
          <p className="text-[#F5F5F5] text-lg mb-2">
            {is404 ? "Event not found" : "Failed to load event"}
          </p>
          <p className="text-[#A3A3A3] text-sm mb-4">
            {is404 ? "This event may have been deleted or you may not have access." : error.message}
          </p>
          <Link
            href="/events"
            className="inline-block px-3 py-1.5 bg-[#1E90FF] text-white rounded-md text-sm hover:bg-[#3BA0FF] transition-colors"
          >
            Back to events
          </Link>
        </div>
      </div>
    );
  }

  const event = data;
  if (!event) return null;

  const ts = new Date(event.timestamp);
  const dateStr = ts.toLocaleDateString("en-IN", { year: "numeric", month: "short", day: "2-digit" });
  const timeStr = ts.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

  return (
    <div className="space-y-4">
      <BackLink />

      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-xl font-bold capitalize">{event.event_type.replace(/_/g, " ")}</h1>
        <SeverityBadge severity={event.severity} />
        <span className="text-sm text-[#A3A3A3] font-mono">
          {dateStr} {timeStr}
        </span>
        <span className="text-sm text-[#666666]">
          {(event.confidence * 100).toFixed(0)}% confidence
        </span>
      </div>

      {/* Renders nothing unless this event correlates with activity on a
          connected camera — which is the case for most events. */}
      <JourneyCard eventId={event.id} />

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Media */}
        <div className="md:col-span-2 bg-[#111111] border border-[#2A2A2A] rounded-lg p-4 space-y-3">
          {event.snapshot_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={event.snapshot_url}
              alt={event.event_type}
              className="w-full rounded-lg border border-[#2A2A2A]"
            />
          ) : (
            <div className="w-full aspect-video rounded-lg border border-[#2A2A2A] bg-[#1A1A1A] flex items-center justify-center text-sm text-[#666666]">
              No snapshot available
            </div>
          )}

          {event.clip_url && (
            <div className="space-y-3">
              <button
                onClick={() => setShowClip((v) => !v)}
                className="inline-flex items-center gap-2 px-3 py-1.5 bg-[#1A1A1A] border border-[#2A2A2A] rounded-md text-sm text-[#F5F5F5] hover:bg-[#1F1F1F] transition-colors"
              >
                {showClip ? <ChevronDown size={14} /> : <Play size={14} />}
                {showClip ? "Hide clip" : "Play clip"}
              </button>
              {showClip && (
                <video
                  controls
                  preload="metadata"
                  src={event.clip_url}
                  className="w-full rounded-lg border border-[#2A2A2A] bg-black"
                />
              )}
            </div>
          )}
        </div>

        {/* Metadata */}
        <div className="bg-[#111111] border border-[#2A2A2A] rounded-lg p-4 space-y-4">
          <Section label="Description">
            <p className="text-sm text-[#F5F5F5] leading-relaxed">{event.description}</p>
          </Section>

          <Section label="Camera">
            <p className="text-xs font-mono text-[#A3A3A3] break-all">{event.camera_id}</p>
          </Section>

          <Section label="Site">
            <p className="text-xs font-mono text-[#A3A3A3] break-all">{event.site_id}</p>
          </Section>

          <Section label="AI Model">
            <p className="text-sm text-[#F5F5F5]">{event.ai_model || "—"}</p>
            <p className="text-xs text-[#666666] mt-1">
              Raw confidence: {event.confidence.toFixed(4)}
            </p>
          </Section>

          <Section label="Feedback">
            {event.feedback ? (
              <div className="space-y-1">
                <span className="inline-block px-2 py-0.5 text-xs rounded-full bg-[#1A1A1A] border border-[#2A2A2A] text-[#A3A3A3]">
                  Marked as {event.feedback}
                </span>
                {event.feedback_label && (
                  <p className="text-xs text-[#666666]">Label: {event.feedback_label}</p>
                )}
                {event.feedback_at && (
                  <p className="text-xs text-[#666666]">
                    {new Date(event.feedback_at).toLocaleString("en-IN")}
                  </p>
                )}
              </div>
            ) : canFeedback ? (
              <div className="space-y-2">
                <div className="flex flex-wrap gap-2">
                  <button
                    onClick={() => feedbackMutation.mutate({ feedback: "approved" })}
                    disabled={feedbackMutation.isPending}
                    className="px-3 py-1.5 text-xs rounded-md bg-green-500/10 text-green-400 border border-green-500/20 hover:bg-green-500/20 transition-colors disabled:opacity-50"
                  >
                    Approve
                  </button>
                  <button
                    onClick={() => feedbackMutation.mutate({ feedback: "rejected" })}
                    disabled={feedbackMutation.isPending}
                    className="px-3 py-1.5 text-xs rounded-md bg-red-500/10 text-red-400 border border-red-500/20 hover:bg-red-500/20 transition-colors disabled:opacity-50"
                  >
                    Reject
                  </button>
                  <button
                    onClick={() => setReclassifyOpen((v) => !v)}
                    disabled={feedbackMutation.isPending}
                    className="px-3 py-1.5 text-xs rounded-md bg-[#1A1A1A] text-[#A3A3A3] border border-[#2A2A2A] hover:bg-[#1F1F1F] transition-colors disabled:opacity-50"
                  >
                    Reclassify
                  </button>
                </div>
                {reclassifyOpen && (
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={reclassifyLabel}
                      onChange={(e) => setReclassifyLabel(e.target.value)}
                      placeholder="New label"
                      className="flex-1 px-2 py-1.5 text-xs bg-[#1F1F1F] border border-[#2A2A2A] rounded-md text-[#F5F5F5] focus:outline-none focus:border-[#1E90FF]"
                    />
                    <button
                      onClick={() =>
                        reclassifyLabel.trim() &&
                        feedbackMutation.mutate({
                          feedback: "reclassified",
                          label: reclassifyLabel.trim(),
                        })
                      }
                      disabled={!reclassifyLabel.trim() || feedbackMutation.isPending}
                      className="px-3 py-1.5 text-xs rounded-md bg-[#1E90FF] text-white hover:bg-[#3BA0FF] transition-colors disabled:opacity-50"
                    >
                      Save
                    </button>
                  </div>
                )}
                {feedbackMutation.isError && (
                  <p className="text-xs text-red-400">
                    {(feedbackMutation.error as Error).message}
                  </p>
                )}
              </div>
            ) : (
              <p className="text-xs text-[#666666]">No feedback yet</p>
            )}
          </Section>
        </div>
      </div>
    </div>
  );
}

function BackLink() {
  return (
    <Link
      href="/events"
      className="inline-flex items-center gap-1 text-sm text-[#A3A3A3] hover:text-[#F5F5F5] transition-colors"
    >
      <ArrowLeft size={14} /> Back to events
    </Link>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-[#666666] mb-1">{label}</p>
      {children}
    </div>
  );
}
