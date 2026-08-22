"use client";

import AssistantHome from "@/components/v2/assistant/AssistantHome";

// The assistant is the app's primary interface. AssistantHome renders
// FallbackDashboard itself when Gemini is unavailable or the daily AI budget
// is exhausted, so a security dashboard is never unreachable because a token
// budget ran out.
export default function HomePage() {
  return <AssistantHome />;
}
