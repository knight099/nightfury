"use client";

import { create } from "zustand";

interface ChatPanelState {
  collapsed: boolean;
  hydrated: boolean;
  toggle: () => void;
  setCollapsed: (v: boolean) => void;
  hydrate: () => void;
}

const STORAGE_KEY = "nightwatch-chat-collapsed";

export const useChatPanelState = create<ChatPanelState>((set, get) => ({
  collapsed: true,
  hydrated: false,
  toggle: () => {
    const next = !get().collapsed;
    set({ collapsed: next });
    if (typeof window !== "undefined") {
      try {
        window.localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
      } catch {}
    }
  },
  setCollapsed: (v: boolean) => {
    set({ collapsed: v });
    if (typeof window !== "undefined") {
      try {
        window.localStorage.setItem(STORAGE_KEY, v ? "1" : "0");
      } catch {}
    }
  },
  hydrate: () => {
    if (get().hydrated) return;
    if (typeof window === "undefined") return;
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw === "0") set({ collapsed: false, hydrated: true });
      else set({ hydrated: true });
    } catch {
      set({ hydrated: true });
    }
  },
}));
