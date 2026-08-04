// Stand-in for frontend/src/lib/chatPanelState.ts — same shape, in-memory
// only (no localStorage persistence needed for a static preview).
import { create } from "zustand";

interface ChatPanelState {
  collapsed: boolean;
  hydrated: boolean;
  toggle: () => void;
  setCollapsed: (v: boolean) => void;
  hydrate: () => void;
}

export const useChatPanelState = create<ChatPanelState>((set, get) => ({
  collapsed: false,
  hydrated: true,
  toggle: () => set({ collapsed: !get().collapsed }),
  setCollapsed: (v: boolean) => set({ collapsed: v }),
  hydrate: () => {},
}));
