"use client";

import { useState, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Play, ChevronDown } from "lucide-react";
import { api } from "@/lib/api";
import { useAuthStore } from "@/lib/store";
import { useChatContextStore } from "@/lib/chatContext";
import { JourneyCard } from "@/components/map/JourneyCard";
import { Skeleton } from "@/components/ui/Skeleton";
import { Page, Card, ErrorBox, Btn, BackLink, Pill, inputClass } from "@/components/v2/ui";
import type { Event } from "@/types";

const severityTone: Record<Event["severity"], "green" | "amber" | "red"> = {
  low: "green",
  medium: "amber",
  high: "amber",
  critical: "red",
};

const STATUSES = ["new", "acknowledged", "resolved", "dismissed"] as const;

export default function EventDetailPageV2() {
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

  const { data: event, isLoading, error } = useQuery({
    queryKey: ["event", id],
    queryFn: () => api.getEvent(id as string),
    enabled: !!id,
    retry: false,
  });

  useEffect(() => {
    if (error && /401/.test(error.message)) router.replace("/login");
  }, [error, router]);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["event", id] });
    queryClient.invalidateQueries({ queryKey: ["events"] });
  };

  const feedbackMutation = useMutation({
    mutationFn: ({ feedback, label }: { feedback: string; label?: string }) =>
      api.submitFeedback(id as string, feedback, label),
    onSuccess: () => {
      invalidate();
      setReclassifyOpen(false);
      setReclassifyLabel("");
    },
  });

  // Incident status is kept strictly orthogonal to the detection-quality
  // feedback above — one is "what should the operator do about this", the
  // other is "did the model get it right". Do not merge them.
  const statusMutation = useMutation({
    mutationFn: (status: string) => api.setEventStatus(id as string, status),
    onSuccess: invalidate,
  });

  if (isLoading) {
    return (
      <Page>
        <BackLink href="/app/activity" label="Back to activity" />
        <Skeleton className="h-8 w-64 mb-5" />
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Skeleton className="md:col-span-2 w-full aspect-video rounded-[14px]" />
          <Card className="space-y-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-4 w-full" />
            ))}
          </Card>
        </div>
      </Page>
    );
  }

  if (error) {
    const is404 = /404/.test(error.message) || /not found/i.test(error.message);
    return (
      <Page>
        <BackLink href="/app/activity" label="Back to activity" />
        <ErrorBox
          message={
            is404
              ? "Event not found. It may have been deleted, or you may not have access to it."
              : `Failed to load event: ${error.message}`
          }
        />
      </Page>
    );
  }

  if (!event) return null;

  const ts = new Date(event.timestamp);

  return (
    <Page>
      <BackLink href="/app/activity" label="Back to activity" />

      <div className="flex items-center gap-3 flex-wrap mb-5">
        <h1 className="text-[26px] font-bold tracking-tight capitalize">
          {event.event_type.replace(/_/g, " ")}
        </h1>
        <Pill tone={severityTone[event.severity]}>{event.severity.toUpperCase()}</Pill>
        <span className="text-[12.5px] text-[oklch(55%_0.01_265)] font-mono">
          {ts.toLocaleString("en-IN")}
        </span>
        <span className="text-[12.5px] text-[oklch(55%_0.01_265)]">
          {(event.confidence * 100).toFixed(0)}% confidence
        </span>
      </div>

      {/* Renders nothing unless this event correlates with activity on a
          connected camera. Journeys are adjacency + timing, never re-ID. */}
      <div className="mb-4">
        <JourneyCard eventId={event.id} />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card className="md:col-span-2 space-y-3">
          {event.snapshot_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={event.snapshot_url}
              alt={event.event_type}
              className="w-full rounded-[10px] border border-[oklch(22%_0.015_265)]"
            />
          ) : (
            <div className="w-full aspect-video rounded-[10px] border border-[oklch(22%_0.015_265)] bg-[oklch(15%_0.015_265)] flex items-center justify-center text-[13px] text-[oklch(55%_0.01_265)]">
              No snapshot available
            </div>
          )}

          {event.clip_url && (
            <div className="space-y-3">
              <Btn onClick={() => setShowClip((v) => !v)} className="inline-flex items-center gap-2">
                {showClip ? <ChevronDown size={14} /> : <Play size={14} />}
                {showClip ? "Hide clip" : "Play clip"}
              </Btn>
              {showClip && (
                <video
                  controls
                  preload="metadata"
                  src={event.clip_url}
                  className="w-full rounded-[10px] border border-[oklch(22%_0.015_265)] bg-black"
                />
              )}
            </div>
          )}
        </Card>

        <Card className="space-y-4">
          <Section label="Description">
            <p className="text-[13px] text-[oklch(90%_0.005_265)] leading-relaxed">
              {event.description}
            </p>
          </Section>

          <Section label="Status">
            <div className="flex flex-wrap gap-1.5">
              {STATUSES.map((s) => {
                const active = (event.status ?? "new") === s;
                return (
                  <button
                    key={s}
                    onClick={() => !active && statusMutation.mutate(s)}
                    disabled={statusMutation.isPending || !canFeedback}
                    className={`text-[11px] px-2.5 py-1 rounded-full capitalize transition-colors disabled:opacity-50 ${
                      active
                        ? "bg-[oklch(85%_0.16_84)] text-[oklch(18%_0.02_84)] font-semibold"
                        : "bg-[oklch(15%_0.015_265)] text-[oklch(72%_0.01_265)] hover:bg-[oklch(18%_0.015_265)]"
                    }`}
                  >
                    {s}
                  </button>
                );
              })}
            </div>
            {statusMutation.isError && (
              <p className="text-[11.5px] text-[oklch(70.4%_0.191_22.216)] mt-2">
                {(statusMutation.error as Error).message}
              </p>
            )}
          </Section>

          <Section label="Camera">
            <p className="text-[11.5px] font-mono text-[oklch(72%_0.01_265)] break-all">
              {event.camera_id}
            </p>
          </Section>

          <Section label="AI model">
            <p className="text-[13px] text-[oklch(90%_0.005_265)]">{event.ai_model || "—"}</p>
            <p className="text-[11.5px] text-[oklch(55%_0.01_265)] mt-1">
              Raw confidence: {event.confidence.toFixed(4)}
            </p>
          </Section>

          <Section label="Detection feedback">
            {event.feedback ? (
              <div className="space-y-1">
                <Pill tone="neutral">Marked as {event.feedback}</Pill>
                {event.feedback_label && (
                  <p className="text-[11.5px] text-[oklch(55%_0.01_265)]">
                    Label: {event.feedback_label}
                  </p>
                )}
                {event.feedback_at && (
                  <p className="text-[11.5px] text-[oklch(55%_0.01_265)]">
                    {new Date(event.feedback_at).toLocaleString("en-IN")}
                  </p>
                )}
              </div>
            ) : canFeedback ? (
              <div className="space-y-2">
                <div className="flex flex-wrap gap-2">
                  <Btn
                    onClick={() => feedbackMutation.mutate({ feedback: "approved" })}
                    disabled={feedbackMutation.isPending}
                  >
                    Approve
                  </Btn>
                  <Btn
                    variant="danger"
                    onClick={() => feedbackMutation.mutate({ feedback: "rejected" })}
                    disabled={feedbackMutation.isPending}
                  >
                    Reject
                  </Btn>
                  <Btn
                    onClick={() => setReclassifyOpen((v) => !v)}
                    disabled={feedbackMutation.isPending}
                  >
                    Reclassify
                  </Btn>
                </div>
                {reclassifyOpen && (
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={reclassifyLabel}
                      onChange={(e) => setReclassifyLabel(e.target.value)}
                      placeholder="New label"
                      className={inputClass}
                    />
                    <Btn
                      variant="primary"
                      onClick={() =>
                        reclassifyLabel.trim() &&
                        feedbackMutation.mutate({
                          feedback: "reclassified",
                          label: reclassifyLabel.trim(),
                        })
                      }
                      disabled={!reclassifyLabel.trim() || feedbackMutation.isPending}
                    >
                      Save
                    </Btn>
                  </div>
                )}
                {feedbackMutation.isError && (
                  <p className="text-[11.5px] text-[oklch(70.4%_0.191_22.216)]">
                    {(feedbackMutation.error as Error).message}
                  </p>
                )}
              </div>
            ) : (
              <p className="text-[11.5px] text-[oklch(55%_0.01_265)]">No feedback yet</p>
            )}
          </Section>
        </Card>
      </div>
    </Page>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-[0.04em] text-[oklch(55%_0.01_265)] mb-1.5">
        {label}
      </p>
      {children}
    </div>
  );
}
