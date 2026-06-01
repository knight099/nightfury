"use client";

import { useCallback, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { api } from "@/lib/api";
import { SeverityBadge } from "@/components/shared/severity-badge";
import { Skeleton } from "@/components/ui/Skeleton";
import { Check, X, ChevronLeft, ChevronRight } from "lucide-react";
import { useAuthStore } from "@/lib/store";
import { useEventsSocket } from "@/lib/useEventsSocket";
import type { Event, PaginatedResponse } from "@/types";

export default function EventsPage() {
  const queryClient = useQueryClient();
  const { user } = useAuthStore();
  const canFeedback = user?.role !== "viewer";
  const [page, setPage] = useState(1);
  const [eventType, setEventType] = useState("");
  const [severity, setSeverity] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["events", page, eventType, severity],
    queryFn: () =>
      api.getEvents({
        page: String(page),
        per_page: "20",
        ...(eventType && { event_type: eventType }),
        ...(severity && { severity }),
      }),
  });

  const handleNewEvent = useCallback(
    (event: Event) => {
      const matchesType = !eventType || event.event_type === eventType;
      const matchesSeverity = !severity || event.severity === severity;
      if (page === 1 && matchesType && matchesSeverity) {
        queryClient.setQueryData<PaginatedResponse<Event>>(
          ["events", page, eventType, severity],
          (old) => {
            const prevEvents = old?.events ?? [];
            if (prevEvents.some((e) => e.id === event.id)) return old;
            const nextEvents = [event, ...prevEvents].slice(0, 20);
            return {
              events: nextEvents,
              total: (old?.total ?? 0) + 1,
              page: old?.page ?? 1,
              pages: old?.pages ?? 1,
            };
          }
        );
      } else {
        queryClient.invalidateQueries({ queryKey: ["events"] });
      }
    },
    [queryClient, page, eventType, severity]
  );

  useEventsSocket(handleNewEvent);

  const feedbackMutation = useMutation({
    mutationFn: ({ id, feedback }: { id: string; feedback: string }) =>
      api.submitFeedback(id, feedback),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["events"] }),
  });

  const events = data?.events || [];
  const totalPages = data?.pages || 1;

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">Events</h1>

      {/* Filters */}
      <div className="flex gap-3">
        <select
          value={eventType}
          onChange={(e) => { setEventType(e.target.value); setPage(1); }}
          className="px-3 py-1.5 bg-[#1F1F1F] border border-[#2A2A2A] rounded-md text-sm text-[#F5F5F5]"
        >
          <option value="">All types</option>
          <option value="person">Person</option>
          <option value="vehicle">Vehicle</option>
          <option value="intrusion">Intrusion</option>
          <option value="loitering">Loitering</option>
          <option value="crowd_spike">Crowd</option>
        </select>
        <select
          value={severity}
          onChange={(e) => { setSeverity(e.target.value); setPage(1); }}
          className="px-3 py-1.5 bg-[#1F1F1F] border border-[#2A2A2A] rounded-md text-sm text-[#F5F5F5]"
        >
          <option value="">All severity</option>
          <option value="critical">Critical</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
      </div>

      {/* Event List */}
      <div className="bg-[#111111] rounded-lg border border-[#2A2A2A] overflow-hidden">
        {isLoading && (
          <div className="p-3 space-y-2">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-20 rounded-md" />
            ))}
          </div>
        )}
        {!isLoading && events.length === 0 && (
          <div className="p-8 text-center text-sm text-[#666666]">No events found</div>
        )}
        <div className="divide-y divide-[#2A2A2A]">
          {events.map((event: Event) => (
            <Link
              key={event.id}
              href={`/events/${event.id}`}
              className="px-4 py-3 flex items-center gap-3 hover:bg-[#1A1A1A] transition-colors"
            >
              <div className="w-20 text-xs text-[#666666] font-mono">
                {new Date(event.timestamp).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}
              </div>
              <div className="w-28 text-sm truncate">{event.event_type.replace("_", " ")}</div>
              <SeverityBadge severity={event.severity} />
              <div className="w-12 text-xs text-[#666666]">{(event.confidence * 100).toFixed(0)}%</div>
              <div className="flex-1 text-xs text-[#A3A3A3] truncate">{event.description}</div>
              <div className="flex items-center gap-1">
                {event.feedback ? (
                  <span className="text-xs text-[#666666] px-2 py-0.5 bg-[#1A1A1A] rounded">
                    {event.feedback}
                  </span>
                ) : canFeedback ? (
                  <>
                    <button
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        feedbackMutation.mutate({ id: event.id, feedback: "approved" });
                      }}
                      className="p-1 rounded hover:bg-green-500/10 text-green-400"
                      title="Approve"
                    >
                      <Check size={14} />
                    </button>
                    <button
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        feedbackMutation.mutate({ id: event.id, feedback: "rejected" });
                      }}
                      className="p-1 rounded hover:bg-red-500/10 text-red-400"
                      title="Reject"
                    >
                      <X size={14} />
                    </button>
                  </>
                ) : (
                  <span className="text-xs text-[#666666]">pending</span>
                )}
              </div>
            </Link>
          ))}
        </div>
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between">
        <span className="text-xs text-[#666666]">
          Page {page} of {totalPages} ({data?.total || 0} events)
        </span>
        <div className="flex gap-2">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="p-1 rounded bg-[#1A1A1A] disabled:opacity-30"
          >
            <ChevronLeft size={16} />
          </button>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
            className="p-1 rounded bg-[#1A1A1A] disabled:opacity-30"
          >
            <ChevronRight size={16} />
          </button>
        </div>
      </div>
    </div>
  );
}
