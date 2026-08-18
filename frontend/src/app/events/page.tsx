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
  // Defaults to "open" — a control room opens this page to see what still
  // needs attention, not to browse everything that ever happened.
  const [status, setStatus] = useState("open");

  const { data, isLoading } = useQuery({
    queryKey: ["events", page, eventType, severity, status],
    queryFn: () =>
      api.getEvents({
        page: String(page),
        per_page: "20",
        ...(eventType && { event_type: eventType }),
        ...(severity && { severity }),
        ...(status && { status }),
      }),
  });

  const handleNewEvent = useCallback(
    (event: Event) => {
      const matchesType = !eventType || event.event_type === eventType;
      const matchesSeverity = !severity || event.severity === severity;
      // A newly-created event is always status "new", so it belongs in the
      // list under "open" or "new" — but not under "resolved"/"dismissed".
      const matchesStatus = !status || status === "open" || status === "new";
      if (page === 1 && matchesType && matchesSeverity && matchesStatus) {
        queryClient.setQueryData<PaginatedResponse<Event>>(
          ["events", page, eventType, severity, status],
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
    [queryClient, page, eventType, severity, status]
  );

  useEventsSocket(handleNewEvent);

  const statusMutation = useMutation({
    mutationFn: ({ id, status: next }: { id: string; status: string }) =>
      api.setEventStatus(id, next),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["events"] }),
  });

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
      <div className="flex flex-wrap gap-2 sm:gap-3">
        <select
          value={eventType}
          onChange={(e) => { setEventType(e.target.value); setPage(1); }}
          className="flex-1 sm:flex-none min-h-[44px] sm:min-h-0 px-3 py-1.5 bg-[#1F1F1F] border border-[#2A2A2A] rounded-md text-sm text-[#F5F5F5]"
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
          className="flex-1 sm:flex-none min-h-[44px] sm:min-h-0 px-3 py-1.5 bg-[#1F1F1F] border border-[#2A2A2A] rounded-md text-sm text-[#F5F5F5]"
        >
          <option value="">All severity</option>
          <option value="critical">Critical</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
        <select
          value={status}
          onChange={(e) => { setStatus(e.target.value); setPage(1); }}
          className="flex-1 sm:flex-none min-h-[44px] sm:min-h-0 px-3 py-1.5 bg-[#1F1F1F] border border-[#2A2A2A] rounded-md text-sm text-[#F5F5F5]"
        >
          <option value="open">Open (needs attention)</option>
          <option value="new">Unacknowledged</option>
          <option value="acknowledged">Acknowledged</option>
          <option value="resolved">Resolved</option>
          <option value="dismissed">Dismissed</option>
          <option value="">All statuses</option>
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
          <div className="p-10 text-center">
            <p className="text-sm text-[#A3A3A3]">Nothing here yet.</p>
            <p className="mt-1 text-xs text-[#666666]">
              When a camera spots something, it shows up here with a snapshot and description.
            </p>
          </div>
        )}
        <div className="divide-y divide-[#2A2A2A]">
          {events.map((event: Event) => (
            <Link
              key={event.id}
              href={`/events/${event.id}`}
              className="px-4 py-3 flex flex-wrap sm:flex-nowrap items-center gap-x-3 gap-y-1 hover:bg-[#1A1A1A] transition-colors"
            >
              <div className="w-20 text-xs text-[#666666] font-mono shrink-0">
                {new Date(event.timestamp).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}
              </div>
              <div className="w-28 text-sm capitalize truncate shrink-0">{event.event_type.replace("_", " ")}</div>
              <SeverityBadge severity={event.severity} />
              <div className="hidden md:block w-12 text-xs text-[#666666]">{(event.confidence * 100).toFixed(0)}%</div>
              <div className="basis-full sm:basis-auto sm:flex-1 text-xs text-[#A3A3A3] truncate order-last sm:order-none">{event.description}</div>
              {/* Workflow lane — "did somebody deal with it?". Deliberately
                  separate from the feedback lane below, which answers the
                  different question of whether the DETECTION was right. */}
              <div className="flex items-center gap-1 ml-auto sm:ml-0">
                {event.status === "new" ? (
                  canFeedback ? (
                    <button
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        statusMutation.mutate({ id: event.id, status: "acknowledged" });
                      }}
                      className="px-2 py-1 rounded text-xs text-amber-400 border border-amber-400/40 hover:bg-amber-400/10 transition-colors"
                      title="I am dealing with this — stops the escalation ladder"
                    >
                      Ack
                    </button>
                  ) : (
                    <span className="px-2 py-0.5 rounded text-xs text-amber-400 bg-amber-400/10">
                      unacknowledged
                    </span>
                  )
                ) : event.status === "acknowledged" ? (
                  canFeedback ? (
                    <button
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        statusMutation.mutate({ id: event.id, status: "resolved" });
                      }}
                      className="px-2 py-1 rounded text-xs text-green-400 border border-green-400/40 hover:bg-green-400/10 transition-colors"
                      title="Dealt with — closes this event"
                    >
                      Resolve
                    </button>
                  ) : (
                    <span className="px-2 py-0.5 rounded text-xs text-[#A3A3A3] bg-[#1A1A1A]">
                      acknowledged
                    </span>
                  )
                ) : (
                  <span className="px-2 py-0.5 rounded text-xs text-[#666666] bg-[#1A1A1A]">
                    {event.status}
                  </span>
                )}
              </div>
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
                      className="p-2.5 sm:p-1 rounded hover:bg-green-500/10 text-green-400"
                      title="Approve"
                    >
                      <Check size={16} />
                    </button>
                    <button
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        feedbackMutation.mutate({ id: event.id, feedback: "rejected" });
                      }}
                      className="p-2.5 sm:p-1 rounded hover:bg-red-500/10 text-red-400"
                      title="Reject"
                    >
                      <X size={16} />
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
            className="p-2.5 sm:p-1.5 rounded bg-[#1A1A1A] disabled:opacity-30 transition-colors hover:bg-[#222222]"
            aria-label="Previous page"
          >
            <ChevronLeft size={18} />
          </button>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
            className="p-2.5 sm:p-1.5 rounded bg-[#1A1A1A] disabled:opacity-30 transition-colors hover:bg-[#222222]"
            aria-label="Next page"
          >
            <ChevronRight size={18} />
          </button>
        </div>
      </div>
    </div>
  );
}
