import { create } from "zustand";

interface ChatContextState {
  cameraId: string | null;
  eventId: string | null;
  setCameraContext: (id: string | null) => void;
  setEventContext: (id: string | null) => void;
}

export const useChatContextStore = create<ChatContextState>((set) => ({
  cameraId: null,
  eventId: null,
  setCameraContext: (id) => set({ cameraId: id }),
  setEventContext: (id) => set({ eventId: id }),
}));
