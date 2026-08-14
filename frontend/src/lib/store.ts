import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { User } from "@/types";

interface AuthState {
  token: string | null;
  user: User | null;
  originalToken: string | null;
  originalUser: User | null;
  setAuth: (token: string, user: User) => void;
  logout: () => void;
  startImpersonation: (token: string, user: User) => void;
  exitImpersonation: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      user: null,
      originalToken: null,
      originalUser: null,
      setAuth: (token, user) => set({ token, user }),
      logout: () => set({ token: null, user: null, originalToken: null, originalUser: null }),
      startImpersonation: (token, user) => {
        const { token: currentToken, user: currentUser } = get();
        set({ originalToken: currentToken, originalUser: currentUser, token, user });
      },
      exitImpersonation: () => {
        const { originalToken, originalUser } = get();
        set({ token: originalToken, user: originalUser, originalToken: null, originalUser: null });
      },
    }),
    { name: "nightwatch-auth" }
  )
);
