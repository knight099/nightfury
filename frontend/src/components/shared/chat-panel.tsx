"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight, ChevronLeft, Send, Plus, X } from "lucide-react";
import { api } from "@/lib/api";
import { useEventsSocket } from "@/lib/useEventsSocket";
import { useChatContextStore } from "@/lib/chatContext";
import { useChatPanelState } from "@/lib/chatPanelState";
import { useAuthStore } from "@/lib/store";
import type { ChatMessage, Event, Camera } from "@/types";

const SEVERITY_COLOR: Record<string, string> = {
  low: "#4ADE80",
  medium: "#FBBF24",
  high: "#F97316",
  critical: "#EF4444",
};

function relativeTime(iso: string): string {
  const ts = new Date(iso).getTime();
  if (Number.isNaN(ts)) return "";
  const diff = Math.max(0, Date.now() - ts);
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}

export function ChatSidePanel() {
  const token = useAuthStore((s) => s.token);
  const { collapsed, toggle, hydrate } = useChatPanelState();
  const { cameraId, eventId, setCameraContext, setEventContext } = useChatContextStore();

  const [tab, setTab] = useState<"events" | "ask">("events");
  const [liveEvents, setLiveEvents] = useState<Event[]>([]);
  const [unread, setUnread] = useState(0);
  const seededRef = useRef(false);

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    hydrate();
  }, [hydrate]);

  useEffect(() => {
    setMessages([]);
    setCurrentConversationId(null);
    setChatError(null);
  }, [cameraId, eventId]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        toggle();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [toggle]);

  useEffect(() => {
    if (!collapsed) setUnread(0);
  }, [collapsed]);

  const { data: camerasData } = useQuery({
    queryKey: ["cameras"],
    queryFn: () => api.getCameras(),
    staleTime: Infinity,
    enabled: !!token,
  });

  const cameraNameById = useMemo(() => {
    const map: Record<string, string> = {};
    (camerasData || []).forEach((c: Camera) => {
      map[c.id] = c.name;
    });
    return map;
  }, [camerasData]);

  const { data: seedEvents } = useQuery({
    queryKey: ["events", { per_page: "20" }],
    queryFn: () => api.getEvents({ per_page: "20" }),
    enabled: !!token,
  });

  useEffect(() => {
    if (seededRef.current) return;
    if (!seedEvents?.events) return;
    seededRef.current = true;
    setLiveEvents((prev) => {
      const existing = new Set(prev.map((e) => e.id));
      const merged = [...prev];
      for (const ev of seedEvents.events) {
        if (!existing.has(ev.id)) merged.push(ev);
      }
      merged.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
      return merged.slice(0, 50);
    });
  }, [seedEvents]);

  const handleNewEvent = useCallback((event: Event) => {
    setLiveEvents((prev) => {
      if (prev.some((e) => e.id === event.id)) return prev;
      return [event, ...prev].slice(0, 50);
    });
    if (useChatPanelState.getState().collapsed) {
      setUnread((u) => Math.min(u + 1, 99));
    }
  }, []);

  const { connected } = useEventsSocket(handleNewEvent);

  useEffect(() => {
    if (tab === "ask") {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, tab]);

  const contextLabel = (() => {
    if (eventId) return "About this event";
    if (cameraId) {
      const name = cameraNameById[cameraId];
      return name ? `About camera ${name}` : "About camera";
    }
    return "General";
  })();

  const clearContext = () => {
    setCameraContext(null);
    setEventContext(null);
  };

  const startNewConversation = () => {
    setMessages([]);
    setCurrentConversationId(null);
    setChatError(null);
  };

  const sendMessage = async () => {
    const content = input.trim();
    if (!content || sending) return;
    setChatError(null);
    setSending(true);

    const tempId = `temp-${Date.now()}`;
    const now = new Date().toISOString();
    const userMsg: ChatMessage = {
      id: tempId,
      role: "user",
      content,
      conversation_id: currentConversationId ?? "",
      created_at: now,
      camera_id: cameraId,
      event_id: eventId,
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");

    try {
      const reply = await api.chatSend({
        message: content,
        conversation_id: currentConversationId ?? undefined,
        camera_id: cameraId ?? undefined,
        event_id: eventId ?? undefined,
      });
      setCurrentConversationId(reply.conversation_id);
      setMessages((prev) => [...prev, reply]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Request failed";
      if (/429/.test(msg) || /quota/i.test(msg)) {
        setChatError("Daily AI quota reached.");
      } else if (/503/.test(msg) || /unavailable/i.test(msg)) {
        setChatError("AI is temporarily unavailable, try again.");
      } else {
        setChatError(msg);
      }
    } finally {
      setSending(false);
    }
  };

  const handleKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  if (!token) return null;

  if (collapsed) {
    return (
      <button
        onClick={toggle}
        aria-label="Open chat panel"
        className="fixed right-0 top-1/2 -translate-y-1/2 z-40 w-8 h-24 bg-[#111111] border border-r-0 border-[#2A2A2A] rounded-l-md flex flex-col items-center justify-center gap-1 hover:bg-[#1A1A1A] transition-colors"
      >
        <ChevronLeft size={16} className="text-[#A3A3A3]" />
        {unread > 0 && (
          <span className="text-[10px] px-1.5 py-0.5 bg-[#1E90FF] text-white rounded-full font-mono">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>
    );
  }

  return (
    <aside className="fixed right-0 top-0 h-screen w-[360px] bg-[#111111] border-l border-[#2A2A2A] z-40 flex flex-col">
      <div className="flex items-center justify-between px-3 py-2 border-b border-[#2A2A2A]">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-[#F5F5F5]">
            {tab === "events" ? "Events" : "Ask"}
          </span>
          {tab === "events" && (
            <span className="flex items-center gap-1 text-[10px] text-[#A3A3A3]">
              <span
                className="inline-block w-1.5 h-1.5 rounded-full"
                style={{ backgroundColor: connected ? "#4ADE80" : "#666666" }}
              />
              {connected ? "live" : "reconnecting"}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {tab === "ask" && (
            <button
              onClick={startNewConversation}
              title="New conversation"
              className="p-1 rounded text-[#A3A3A3] hover:text-[#F5F5F5] hover:bg-[#1A1A1A] transition-colors"
            >
              <Plus size={14} />
            </button>
          )}
          <button
            onClick={toggle}
            aria-label="Collapse chat panel"
            className="p-1 rounded text-[#A3A3A3] hover:text-[#F5F5F5] hover:bg-[#1A1A1A] transition-colors"
          >
            <ChevronRight size={16} />
          </button>
        </div>
      </div>

      <div className="flex border-b border-[#2A2A2A]">
        <button
          onClick={() => setTab("events")}
          className={`flex-1 py-2 text-xs font-medium transition-colors ${
            tab === "events"
              ? "text-[#F5F5F5] border-b-2 border-[#1E90FF]"
              : "text-[#A3A3A3] hover:text-[#F5F5F5]"
          }`}
        >
          Events
        </button>
        <button
          onClick={() => setTab("ask")}
          className={`flex-1 py-2 text-xs font-medium transition-colors ${
            tab === "ask"
              ? "text-[#F5F5F5] border-b-2 border-[#1E90FF]"
              : "text-[#A3A3A3] hover:text-[#F5F5F5]"
          }`}
        >
          Ask
        </button>
      </div>

      {tab === "events" ? (
        <div className="flex-1 overflow-y-auto">
          {liveEvents.length === 0 ? (
            <div className="p-4 text-xs text-[#666666] text-center">
              No events yet — they&apos;ll appear here when detected.
            </div>
          ) : (
            <ul className="divide-y divide-[#2A2A2A]">
              {liveEvents.map((ev) => {
                const name = cameraNameById[ev.camera_id];
                const color = SEVERITY_COLOR[ev.severity] || "#A3A3A3";
                return (
                  <li key={ev.id}>
                    <Link
                      href={`/events/${ev.id}`}
                      className="block px-3 py-2 hover:bg-[#1A1A1A] transition-colors"
                    >
                      <div className="flex items-center gap-2">
                        <span
                          className="inline-block w-2 h-2 rounded-full flex-shrink-0"
                          style={{ backgroundColor: color }}
                        />
                        <span className="text-xs font-medium text-[#F5F5F5] capitalize truncate">
                          {ev.event_type.replace(/_/g, " ")}
                        </span>
                        <span className="ml-auto text-[10px] text-[#666666] flex-shrink-0">
                          {relativeTime(ev.timestamp)}
                        </span>
                      </div>
                      <div className="mt-0.5 pl-4 text-[11px] text-[#A3A3A3] truncate">
                        {name || ev.camera_id.slice(0, 8)}
                      </div>
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      ) : (
        <div className="flex-1 flex flex-col min-h-0">
          <div className="px-3 py-2 border-b border-[#2A2A2A] flex items-center justify-between gap-2">
            <span className="text-[11px] px-2 py-0.5 rounded-full bg-[#1A1A1A] border border-[#2A2A2A] text-[#A3A3A3] truncate">
              {contextLabel}
            </span>
            {(cameraId || eventId) && (
              <button
                onClick={clearContext}
                className="text-[10px] text-[#A3A3A3] hover:text-[#F5F5F5] flex items-center gap-1"
              >
                <X size={10} /> Clear
              </button>
            )}
          </div>

          <div className="flex-1 overflow-y-auto p-3 space-y-2">
            {messages.length === 0 ? (
              <div className="text-xs text-[#666666] text-center pt-8">
                Ask Gemini anything about your cameras or events.
              </div>
            ) : (
              messages.map((m) => (
                <div
                  key={m.id}
                  className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
                >
                  <div
                    className={`max-w-[85%] px-3 py-2 rounded-lg text-xs whitespace-pre-wrap break-words ${
                      m.role === "user"
                        ? "bg-[#1A1A1A] border border-[#1E90FF] text-[#F5F5F5]"
                        : "bg-[#1A1A1A] border border-[#2A2A2A] text-[#F5F5F5]"
                    }`}
                  >
                    {m.content}
                  </div>
                </div>
              ))
            )}
            {sending && (
              <div className="flex justify-start">
                <div className="px-3 py-2 rounded-lg text-xs bg-[#1A1A1A] border border-[#2A2A2A] text-[#A3A3A3]">
                  Thinking…
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          <div className="border-t border-[#2A2A2A] p-2 space-y-1">
            {chatError && (
              <p className="text-[11px] text-red-400 px-1">{chatError}</p>
            )}
            <div className="flex items-end gap-2">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKey}
                disabled={sending}
                rows={1}
                placeholder="Ask a question…"
                className="flex-1 resize-none bg-[#1F1F1F] border border-[#2A2A2A] rounded-md px-2 py-1.5 text-xs text-[#F5F5F5] placeholder:text-[#666666] focus:outline-none focus:border-[#1E90FF] max-h-24"
                style={{ minHeight: "32px" }}
              />
              <button
                onClick={sendMessage}
                disabled={sending || !input.trim()}
                className="p-1.5 bg-[#1E90FF] hover:bg-[#3BA0FF] disabled:opacity-40 disabled:cursor-not-allowed rounded-md text-white transition-colors"
                aria-label="Send"
              >
                <Send size={14} />
              </button>
            </div>
          </div>
        </div>
      )}
    </aside>
  );
}
