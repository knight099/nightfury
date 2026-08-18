"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { SeverityBadge } from "@/components/shared/severity-badge";

/**
 * Shows an event's correlated path across connected cameras.
 *
 * Renders nothing when there is no journey — which is the case for most
 * events, and is a normal outcome rather than an empty state worth showing.
 */
export function JourneyCard({ eventId }: { eventId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["journey", eventId],
    // Fetched on demand rather than eagerly for every row in a feed: at mall
    // volumes an eager fetch per event would be hundreds of requests to
    // usually answer "no journey".
    queryFn: () => api.getEventJourney(eventId),
  });

  if (isLoading || !data?.has_journey) return null;

  return (
    <section className="rounded-lg border border-[#2A2A2A] bg-[#111111] p-4">
      <h3 className="font-heading text-sm font-semibold text-[#F5F5F5]">
        Seen on connected cameras
      </h3>

      <ol className="mt-3 space-y-0">
        {data.steps.map((step, i) => (
          <li key={step.event_id} className="flex gap-3">
            <div className="flex flex-col items-center">
              <span
                className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${
                  i === 0 ? "bg-[#1E90FF]" : "bg-[#2A2A2A]"
                }`}
              />
              {i < data.steps.length - 1 && (
                <span className="my-1 w-px flex-1 bg-[#2A2A2A]" />
              )}
            </div>
            <div className="flex-1 pb-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm text-[#F5F5F5]">{step.camera_name}</span>
                <SeverityBadge severity={step.severity} />
                <span className="font-mono text-xs text-[#666666]">
                  {new Date(step.timestamp).toLocaleTimeString("en-IN", {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </span>
              </div>
              {step.via && (
                <div className="mt-0.5 text-xs text-[#666666]">via {step.via}</div>
              )}
            </div>
          </li>
        ))}
      </ol>

      {/* The caveat travels with the feature. Without it a timeline like the
          one above reads as "we tracked this person", which is a claim the
          system cannot make and deliberately does not make. */}
      <p className="mt-1 border-t border-[#2A2A2A] pt-3 text-xs text-[#666666]">
        Linked by camera location and timing only — no face recognition is
        used, so this may or may not be the same person.
      </p>
    </section>
  );
}
