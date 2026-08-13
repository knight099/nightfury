"use client";

import { useEffect, useState } from "react";

/**
 * Returns false on the very first (hydration) render and true afterwards.
 *
 * The zustand `persist` store rehydrates from localStorage synchronously at
 * module load, but React's `useSyncExternalStore` serves `getServerSnapshot`
 * (the pre-persist initial state) for the hydration render. Auth guards that
 * run in an effect would therefore see `token === null` for a genuinely
 * authenticated user and redirect to /login. Gating on this hook defers the
 * guard until the store's real state has propagated.
 */
export function useHydrated(): boolean {
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => setHydrated(true), []);
  return hydrated;
}
