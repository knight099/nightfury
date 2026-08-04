// Nightwatch design system — snapshot of frontend/src/components, for design-sync.
// Styles ship separately as dist/styles.css (see the "./styles.css" export) —
// import that alongside these components.

import { createElement, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const dsQueryClient = new QueryClient();

// Several components (CameraTile, SequenceEditor, ZonesEditor, DigestSettings,
// ChatSidePanel) call useQuery/useMutation directly and need an ancestor
// QueryClientProvider — not a browsable component itself, excluded via
// componentSrcMap in .design-sync/config.json.
export function DsQueryProvider({ children }: { children: ReactNode }) {
  return createElement(QueryClientProvider, { client: dsQueryClient }, children);
}

export { Button, buttonVariants } from "./components/ui/button";
export { Toaster } from "./components/ui/sonner";
export { Skeleton } from "./components/ui/Skeleton";

export { SeverityBadge } from "./components/shared/severity-badge";
export { StatusDot } from "./components/shared/status-dot";
export { HelpWidget } from "./components/shared/help-widget";
export { ChatSidePanel } from "./components/shared/chat-panel";

export { Sidebar } from "./components/layout/sidebar";
export { AppShell } from "./components/layout/app-shell";

export { CameraTile } from "./components/cameras/CameraTile";
export { SequenceEditor } from "./components/cameras/SequenceEditor";
export { WebRTCPlayer } from "./components/cameras/WebRTCPlayer";
export { ZonesEditor } from "./components/cameras/ZonesEditor";

export { DigestCard } from "./components/digests/DigestCard";
export { DigestSettings } from "./components/digests/DigestSettings";
export { RangePicker, presetRanges } from "./components/digests/RangePicker";
export type { Range } from "./components/digests/RangePicker";
