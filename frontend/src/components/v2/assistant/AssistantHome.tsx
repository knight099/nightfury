"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { ErrorBox, Page } from "@/components/v2/ui";
import { ProposalCard } from "@/components/v2/assistant/ProposalCard";
import { FallbackDashboard } from "@/components/v2/assistant/FallbackDashboard";
import type { AssistantProposal } from "@/types";

const SUGGESTIONS = [
  "What happened last night?",
  "Which cameras aren't being watched?",
  "Alert me if anyone enters the Loading Bay after 22:00",
  "Show me the map",
];

interface TranscriptMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  proposals?: AssistantProposal[];
}

/**
 * The app's home page. A centred prompt input backed by the assistant's
 * tool-calling endpoint, a running transcript, and inline ProposalCards for
 * anything the assistant proposes.
 *
 * If Gemini is unavailable (503) or the org's daily AI budget is exhausted
 * (429), this renders FallbackDashboard instead — the camera dashboard must
 * never become unreachable because the assistant can't respond. Those two
 * statuses get distinct copy: the budget case is routine and recurring (every
 * org that hits its cap sees it, every day), the outage case is not.
 */
export default function AssistantHome() {
  const router = useRouter();
  const pathname = usePathname();
  const [conversationId, setConversationId] = useState<string | undefined>(undefined);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<TranscriptMessage[]>([]);
  const [fallbackReason, setFallbackReason] = useState<"budget" | "unavailable" | null>(null);
  const transcriptEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const sendMutation = useMutation({
    mutationFn: (message: string) =>
      api.assistantMessage({
        message,
        conversation_id: conversationId,
        current_route: pathname,
      }),
    onSuccess: (response) => {
      setConversationId(response.conversation_id);
      setMessages((prev) => [
        ...prev,
        {
          id: `${response.conversation_id}-${prev.length}`,
          role: "assistant",
          text: response.text,
          proposals: response.proposals,
        },
      ]);
      // Render the answer first, then route — the user should see what the
      // assistant said before the page changes under them.
      if (response.navigate) {
        const target = response.navigate;
        setTimeout(() => router.push(target), 900);
      }
    },
    onError: (error: unknown) => {
      if (error instanceof ApiError && error.status === 429) {
        setFallbackReason("budget");
      } else if (error instanceof ApiError && error.status === 503) {
        setFallbackReason("unavailable");
      } else {
        setMessages((prev) => [
          ...prev,
          {
            id: `error-${prev.length}`,
            role: "assistant",
            text: error instanceof Error ? error.message : "Something went wrong.",
          },
        ]);
      }
    },
  });

  const send = (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || sendMutation.isPending) return;
    setInput("");
    setMessages((prev) => [...prev, { id: `user-${prev.length}`, role: "user", text: trimmed }]);
    sendMutation.mutate(trimmed);
  };

  if (fallbackReason) {
    return (
      <Page>
        <FallbackDashboard reason={fallbackReason} />
      </Page>
    );
  }

  const isEmpty = messages.length === 0 && !sendMutation.isPending;

  return (
    <div className="flex flex-col min-h-[calc(100vh-96px)]">
      {isEmpty ? (
        <div className="flex-1 flex flex-col items-center justify-center px-5 text-center py-24">
          <div className="text-4xl font-bold tracking-tight mb-2.5">What do you want to know?</div>
          <div className="text-[15px] text-[oklch(58%_0.01_265)] mb-8 max-w-[480px]">
            Ask about any camera, event, or moment — or tell it what to watch for.
          </div>
          <div className="flex flex-wrap gap-2 justify-center max-w-[600px]">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                onClick={() => send(s)}
                className="text-[13px] px-4 py-2.5 rounded-full border border-[oklch(24%_0.015_265)] bg-[oklch(13%_0.015_265)] text-[oklch(78%_0.01_265)] hover:bg-[oklch(16%_0.015_265)] transition-colors"
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <div className="flex-1 flex flex-col gap-4 max-w-[680px] mx-auto w-full pt-8 pb-6">
          {messages.map((msg) => (
            <div key={msg.id} className={msg.role === "user" ? "self-end" : "self-start w-full"}>
              {msg.role === "user" ? (
                <div className="rounded-2xl px-4 py-2.5 text-sm max-w-[440px] bg-[oklch(85%_0.16_84)] text-[oklch(18%_0.02_84)]">
                  {msg.text}
                </div>
              ) : (
                <div className="flex flex-col gap-3 max-w-[560px]">
                  <div className="rounded-2xl px-4 py-2.5 text-sm bg-[oklch(15%_0.015_265)] text-[oklch(90%_0.005_265)] w-fit">
                    {msg.text}
                  </div>
                  {msg.proposals && msg.proposals.length > 0 && (
                    <div className="flex flex-col gap-2.5">
                      {msg.proposals.map((p) => (
                        <ProposalCard key={p.id} proposal={p} />
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}

          {sendMutation.isPending && (
            <div className="self-start">
              <div className="rounded-2xl px-4 py-2.5 text-sm max-w-[440px] bg-[oklch(15%_0.015_265)] text-[oklch(58%_0.01_265)]">
                Thinking…
              </div>
            </div>
          )}

          {sendMutation.isError &&
            !(sendMutation.error instanceof ApiError && [429, 503].includes(sendMutation.error.status)) && (
              <ErrorBox
                message={
                  sendMutation.error instanceof Error
                    ? sendMutation.error.message
                    : "Couldn't reach the assistant. Please try again."
                }
              />
            )}

          <div ref={transcriptEndRef} />
        </div>
      )}

      <div className="px-6 pt-5 pb-9 flex flex-col items-center gap-2">
        <div className="flex gap-2.5 w-full max-w-[640px] bg-[oklch(14%_0.015_265)] border border-[oklch(26%_0.015_265)] rounded-full py-2 pl-5.5 pr-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send(input)}
            placeholder="Ask about anything happening right now"
            disabled={sendMutation.isPending}
            className="flex-1 bg-transparent border-none text-[14.5px] text-[oklch(95%_0.005_265)] outline-none disabled:opacity-50"
          />
          <button
            onClick={() => send(input)}
            disabled={sendMutation.isPending || !input.trim()}
            className="bg-[oklch(85%_0.16_84)] text-[oklch(18%_0.02_84)] w-[38px] h-[38px] rounded-full flex items-center justify-center flex-shrink-0 disabled:opacity-50"
          >
            →
          </button>
        </div>
      </div>
    </div>
  );
}
