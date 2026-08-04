// Stand-in for frontend/src/lib/useEventsSocket.ts — no-op, never opens a
// real WebSocket. Previews are static; live events aren't part of the snapshot.
import type { Event } from "../../types";

export function useEventsSocket(_onEvent: (event: Event) => void): { connected: boolean } {
  return { connected: false };
}
