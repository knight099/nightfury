// Stand-in for frontend/src/lib/chatSeed.ts — same shape, in-memory only.
import { create } from "zustand";
import type { ChatMessage } from "../../types";

interface ChatSeedState {
  conversationId: string | null;
  seedMessages: ChatMessage[];
  setSeed: (conversationId: string, seedMessages: ChatMessage[]) => void;
  consume: () => { conversationId: string; seedMessages: ChatMessage[] } | null;
}

export const useChatSeedStore = create<ChatSeedState>((set, get) => ({
  conversationId: null,
  seedMessages: [],
  setSeed: (conversationId, seedMessages) => set({ conversationId, seedMessages }),
  consume: () => {
    const { conversationId, seedMessages } = get();
    if (!conversationId) return null;
    set({ conversationId: null, seedMessages: [] });
    return { conversationId, seedMessages };
  },
}));
