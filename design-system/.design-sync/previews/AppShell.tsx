import { AppShell } from "@nightwatch/design-system";

// The auth-gated shell — the shim's useAuthStore is pre-seeded with a
// signed-in sample user, so this renders the real dashboard chrome (sidebar,
// main content, chat panel) instead of the null/redirect it shows when
// signed out.
export function Default() {
  return (
    <AppShell>
      <div className="space-y-4">
        <h1 className="text-xl font-bold">Dashboard</h1>
        <div className="rounded-lg border border-[#2A2A2A] bg-[#111111] p-4 text-sm text-[#A3A3A3]">
          Page content renders here.
        </div>
      </div>
    </AppShell>
  );
}
