// Stand-in for frontend/src/lib/store.ts — same shape as useAuthStore, but
// pre-seeded with a sample signed-in user instead of reading localStorage,
// so auth-gated components (AppShell, Sidebar) render their real content.
import { create } from "zustand";
import type { User } from "../../types";
import { sampleUser } from "./samples";

interface AuthState {
  token: string | null;
  user: User | null;
  setAuth: (token: string, user: User) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  token: "preview-token",
  user: sampleUser,
  setAuth: (token, user) => set({ token, user }),
  logout: () => set({ token: null, user: null }),
}));
