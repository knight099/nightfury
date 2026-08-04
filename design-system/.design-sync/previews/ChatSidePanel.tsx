import { ChatSidePanel } from "@nightwatch/design-system";

// Renders expanded (the DS's chat-panel shim defaults collapsed: false) on
// its default "Events" tab, seeded with sample events via the api shim.
export function Default() {
  return <ChatSidePanel />;
}
