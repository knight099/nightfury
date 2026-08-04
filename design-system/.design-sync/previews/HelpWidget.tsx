import { HelpWidget } from "@nightwatch/design-system";

// Opens only on click (internal useState) — the floating button is the
// only statically-renderable state; the open panel needs interaction.
export function Default() {
  return (
    <div className="relative h-40 w-40">
      <HelpWidget />
    </div>
  );
}
