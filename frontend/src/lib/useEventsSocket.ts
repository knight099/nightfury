"use client";

import { useEffect, useRef, useState } from "react";
import { useAuthStore } from "@/lib/store";
import type { Event } from "@/types";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "https://nightfury-backend.vercel.app";

function buildWsUrl(token: string): string {
  const wsBase = BASE_URL.replace(/^http/i, (m) => (m.toLowerCase() === "https" ? "wss" : "ws"));
  return `${wsBase}/ws/events?token=${encodeURIComponent(token)}`;
}

export function useEventsSocket(onEvent: (event: Event) => void): { connected: boolean } {
  const token = useAuthStore((s) => s.token);
  const [connected, setConnected] = useState(false);

  const onEventRef = useRef(onEvent);
  useEffect(() => {
    onEventRef.current = onEvent;
  }, [onEvent]);

  useEffect(() => {
    if (!token) return;

    let cancelled = false;
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let backoff = 1000;

    const clearReconnect = () => {
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
    };

    const connect = () => {
      if (cancelled) return;
      try {
        ws = new WebSocket(buildWsUrl(token));
      } catch {
        scheduleReconnect();
        return;
      }

      ws.onopen = () => {
        if (cancelled) return;
        backoff = 1000;
        setConnected(true);
      };

      ws.onmessage = (ev) => {
        try {
          const data = JSON.parse(typeof ev.data === "string" ? ev.data : "");
          if (data && data.type === "event.created" && data.event) {
            onEventRef.current(data.event as Event);
          }
        } catch {
          // ignore malformed messages
        }
      };

      ws.onerror = () => {
        // onclose will follow; reconnection handled there
      };

      ws.onclose = () => {
        setConnected(false);
        if (cancelled) return;
        scheduleReconnect();
      };
    };

    const scheduleReconnect = () => {
      clearReconnect();
      const delay = Math.min(backoff, 30000);
      reconnectTimer = setTimeout(() => {
        backoff = Math.min(backoff * 2, 30000);
        connect();
      }, delay);
    };

    connect();

    return () => {
      cancelled = true;
      clearReconnect();
      if (ws) {
        try {
          ws.onopen = null;
          ws.onmessage = null;
          ws.onerror = null;
          ws.onclose = null;
          ws.close(1000, "unmount");
        } catch {
          // ignore
        }
        ws = null;
      }
      setConnected(false);
    };
  }, [token]);

  return { connected };
}
