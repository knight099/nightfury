"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { ChatMessage } from "@/types";

const SUGGESTIONS = [
  "What happened today?",
  "Is everything okay at the shop?",
  "Show me anything urgent",
  "Summarize this week",
];

export default function ChatPageV2() {
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [pendingUserMessage, setPendingUserMessage] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const { data: messages } = useQuery<ChatMessage[]>({
    queryKey: ["chat-messages", conversationId],
    queryFn: () => api.chatGetMessages(conversationId!),
    enabled: !!conversationId,
  });

  const sendMutation = useMutation({
    mutationFn: (message: string) => api.chatSend({ message, conversation_id: conversationId ?? undefined }),
    onSuccess: (msg) => {
      setPendingUserMessage(null);
      if (!conversationId) setConversationId(msg.conversation_id);
      queryClient.invalidateQueries({ queryKey: ["chat-messages", msg.conversation_id] });
    },
    onError: (_err, variables) => {
      setPendingUserMessage(null);
      // Restore the failed message so the user can retry, unless they've
      // already started typing something new.
      setInput((current) => (current === "" ? variables : current));
    },
  });

  const send = (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || sendMutation.isPending) return;
    setInput("");
    setPendingUserMessage(trimmed);
    sendMutation.mutate(trimmed);
  };

  const isEmpty = !conversationId && !pendingUserMessage && !sendMutation.isPending && !sendMutation.isError;

  return (
    <div className="h-full flex flex-col relative bg-[radial-gradient(circle_at_50%_0%,oklch(20%_0.05_84_/_0.25),transparent_55%)]">
      <div className="text-center pt-7 px-6">
        <div className="text-xs font-bold tracking-widest uppercase text-[oklch(52%_0.01_265)]">
          Master control
        </div>
      </div>

      {isEmpty ? (
        <div className="flex-1 flex flex-col items-center justify-center px-5 text-center">
          <div className="text-4xl font-bold tracking-tight mb-2.5">What do you want to know?</div>
          <div className="text-[15px] text-[oklch(58%_0.01_265)] mb-8 max-w-[440px]">
            Ask about any camera, event, or moment — across everything Nightwatch is watching.
          </div>
          <div className="flex flex-wrap gap-2 justify-center max-w-[580px]">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                onClick={() => send(s)}
                className="text-[13px] px-4 py-2.5 rounded-full border border-[oklch(24%_0.015_265)] bg-[oklch(13%_0.015_265)] text-[oklch(78%_0.01_265)]"
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto flex flex-col gap-4 px-6 pt-6 pb-3 max-w-[680px] mx-auto w-full">
          {(messages ?? []).map((msg) => (
            <div key={msg.id} className={msg.role === "user" ? "self-end" : "self-start"}>
              <div
                className={`rounded-2xl px-4 py-2.5 text-sm max-w-[440px] ${
                  msg.role === "user"
                    ? "bg-[oklch(85%_0.16_84)] text-[oklch(18%_0.02_84)]"
                    : "bg-[oklch(15%_0.015_265)] text-[oklch(90%_0.005_265)]"
                }`}
              >
                {msg.content}
              </div>
            </div>
          ))}

          {pendingUserMessage && (
            <div className="self-end">
              <div className="rounded-2xl px-4 py-2.5 text-sm max-w-[440px] bg-[oklch(85%_0.16_84)] text-[oklch(18%_0.02_84)]">
                {pendingUserMessage}
              </div>
            </div>
          )}

          {sendMutation.isPending && (
            <div className="self-start">
              <div className="rounded-2xl px-4 py-2.5 text-sm max-w-[440px] bg-[oklch(15%_0.015_265)] text-[oklch(58%_0.01_265)]">
                Thinking…
              </div>
            </div>
          )}

          {sendMutation.isError && (
            <div className="self-start">
              <div className="rounded-2xl px-4 py-2.5 text-sm max-w-[440px] bg-[oklch(27%_0.1_25)] text-[oklch(88%_0.05_25)]">
                {sendMutation.error instanceof Error
                  ? sendMutation.error.message
                  : "Couldn't send that message. Please try again."}
              </div>
            </div>
          )}
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
            disabled={sendMutation.isPending}
            className="bg-[oklch(85%_0.16_84)] text-[oklch(18%_0.02_84)] w-[38px] h-[38px] rounded-full flex items-center justify-center flex-shrink-0 disabled:opacity-50"
          >
            →
          </button>
        </div>
      </div>
    </div>
  );
}
