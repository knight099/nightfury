"use client";

import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { AlertRuleDraft, Camera, CompileSequenceMessage, StepSequenceStep } from "@/types";

const POSE_OPTIONS: { value: StepSequenceStep["pose"]; label: string }[] = [
  { value: null, label: "any" },
  { value: "standing", label: "standing" },
  { value: "bending", label: "bending" },
  { value: "crouching", label: "crouching" },
  { value: "sitting", label: "sitting" },
  { value: "reaching", label: "reaching" },
];

export function SequenceEditor({ camera, onClose }: { camera: Camera; onClose: () => void }) {
  const queryClient = useQueryClient();
  const zoneNames = camera.detection_zones.map((z) => z.name);

  const [steps, setSteps] = useState<StepSequenceStep[]>(
    () => (camera.step_sequence || []).map((s) => ({ ...s }))
  );
  const [saveError, setSaveError] = useState<string | null>(null);

  // Conversational compiler state — scoped to this modal session only (no
  // cross-refresh rehydration here; closing the modal is the natural reset
  // point, so the persisted-conversation GET endpoint isn't wired into this
  // transient UI).
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [chatMessages, setChatMessages] = useState<CompileSequenceMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [draftAlertRule, setDraftAlertRule] = useState<AlertRuleDraft | null>(null);
  const [genWarnings, setGenWarnings] = useState<string[]>([]);

  const dirty = useMemo(
    () => JSON.stringify(steps) !== JSON.stringify(camera.step_sequence || []),
    [steps, camera.step_sequence]
  );

  const validationError = useMemo(() => {
    if (steps.length === 0) return null;
    for (const [i, step] of steps.entries()) {
      if (!step.name.trim()) return `Step ${i + 1} needs a name.`;
      if (!zoneNames.includes(step.zone)) return `Step ${i + 1}: zone "${step.zone}" doesn't exist. Draw it in Edit Zones first.`;
    }
    return null;
  }, [steps, zoneNames]);

  const alertRuleError = useMemo(() => {
    if (!draftAlertRule) return null;
    if (draftAlertRule.notify_channels.includes("webhook") && !draftAlertRule.webhook_url) {
      return "Add the destination URL for the webhook before saving.";
    }
    if (
      draftAlertRule.notify_channels.includes("email") &&
      !(draftAlertRule.notify_contacts || []).some((c) => c.type === "email" && c.value)
    ) {
      return "Add a destination email address before saving.";
    }
    return null;
  }, [draftAlertRule]);

  const turnMutation = useMutation({
    mutationFn: (message: string) => api.compileSequence(camera.id, conversationId, message),
    onSuccess: (data) => {
      setConversationId(data.conversation_id);
      if (data.type === "question") {
        setChatMessages((prev) => [...prev, { role: "assistant", content: data.message || "Could you clarify that?" }]);
        return;
      }
      setChatMessages((prev) => [
        ...prev,
        { role: "assistant", content: "Here's what I've put together — review it below." },
      ]);
      setSteps(data.steps);
      setDraftAlertRule(data.alert_rule);
      setGenWarnings(data.warnings);
    },
    onError: (err: Error) => {
      setChatMessages((prev) => [...prev, { role: "assistant", content: `Something went wrong: ${err.message}` }]);
    },
  });

  const sendChat = () => {
    const message = chatInput.trim();
    if (!message || turnMutation.isPending) return;
    setChatMessages((prev) => [...prev, { role: "user", content: message }]);
    setChatInput("");
    turnMutation.mutate(message);
  };

  const saveMutation = useMutation({
    mutationFn: async () => {
      await api.updateCamera(camera.id, { step_sequence: steps });
      if (draftAlertRule) {
        await api.createAlertRule({
          name: draftAlertRule.name,
          cameras: draftAlertRule.cameras,
          event_types: draftAlertRule.event_types,
          min_severity: draftAlertRule.min_severity,
          notify_channels: draftAlertRule.notify_channels,
          notify_contacts: draftAlertRule.notify_contacts || [],
          webhook_url: draftAlertRule.webhook_url || null,
        });
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["cameras"] });
      queryClient.invalidateQueries({ queryKey: ["alert-rules"] });
      onClose();
    },
    onError: (err: Error) => setSaveError(err.message),
  });

  const addStep = () => {
    setSteps([...steps, { name: `Step ${steps.length + 1}`, zone: zoneNames[0] || "", pose: null, max_seconds: null }]);
  };

  const removeStep = (index: number) => {
    setSteps(steps.filter((_, i) => i !== index));
  };

  const moveStep = (index: number, direction: -1 | 1) => {
    const target = index + direction;
    if (target < 0 || target >= steps.length) return;
    const next = [...steps];
    [next[index], next[target]] = [next[target], next[index]];
    setSteps(next);
  };

  const updateStep = (index: number, patch: Partial<StepSequenceStep>) => {
    setSteps(steps.map((s, i) => (i === index ? { ...s, ...patch } : s)));
  };

  const canSave = dirty && !validationError && !alertRuleError && !saveMutation.isPending;

  const onBackdropClick = () => {
    if (dirty) {
      if (window.confirm("Discard unsaved sequence changes?")) onClose();
    } else {
      onClose();
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ backgroundColor: "rgba(0,0,0,0.7)" }}
      onClick={onBackdropClick}
    >
      <div
        className="bg-[#111111] border border-[#2A2A2A] rounded-lg w-[95vw] max-w-[1000px] max-h-[90vh] overflow-hidden flex flex-col lg:flex-row"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Conversational compiler */}
        <div className="lg:w-[340px] shrink-0 border-b lg:border-b-0 lg:border-r border-[#2A2A2A] flex flex-col max-h-[40vh] lg:max-h-none">
          <div className="px-4 py-3 border-b border-[#2A2A2A]">
            <h2 className="text-sm font-medium">Describe the procedure</h2>
          </div>
          <div className="flex-1 overflow-y-auto p-3 space-y-2">
            {chatMessages.length === 0 ? (
              <div className="text-xs text-[#666666]">
                e.g. &ldquo;flag if someone leaves without paying at the counter and text the manager&rdquo;
              </div>
            ) : (
              chatMessages.map((m, i) => (
                <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                  <div
                    className={`max-w-[90%] px-3 py-2 rounded-lg text-xs whitespace-pre-wrap break-words ${
                      m.role === "user"
                        ? "bg-[#1A1A1A] border border-[#1E90FF] text-[#F5F5F5]"
                        : "bg-[#1A1A1A] border border-[#2A2A2A] text-[#F5F5F5]"
                    }`}
                  >
                    {m.content}
                  </div>
                </div>
              ))
            )}
            {turnMutation.isPending && (
              <div className="text-xs text-[#666666]">Thinking…</div>
            )}
          </div>
          <div className="border-t border-[#2A2A2A] p-2 flex items-end gap-2">
            <textarea
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  sendChat();
                }
              }}
              disabled={turnMutation.isPending}
              rows={2}
              placeholder="Describe the procedure…"
              className="flex-1 resize-none bg-[#1F1F1F] border border-[#2A2A2A] rounded-md px-2 py-1.5 text-xs text-[#F5F5F5] placeholder:text-[#666666] focus:outline-none focus:border-[#1E90FF]"
            />
            <button
              onClick={sendChat}
              disabled={turnMutation.isPending || !chatInput.trim()}
              className="px-3 py-1.5 bg-[#1E90FF] text-white rounded text-xs hover:bg-[#3BA0FF] transition-colors disabled:opacity-50"
            >
              Send
            </button>
          </div>
        </div>

        {/* Manual editor + review */}
        <div className="flex-1 flex flex-col min-w-0">
          <div className="flex items-center justify-between px-4 py-3 border-b border-[#2A2A2A]">
            <h2 className="text-sm font-medium">Step Sequence — {camera.name}</h2>
            <button onClick={onBackdropClick} className="text-[#A3A3A3] hover:text-[#F5F5F5] text-lg leading-none" aria-label="Close">
              ×
            </button>
          </div>

          <div className="p-4 space-y-3 overflow-auto flex-1">
            {zoneNames.length === 0 && (
              <div className="text-xs text-[#666666]">No zones defined yet — draw zones first via "Edit Zones", then steps can reference them.</div>
            )}

            {steps.map((step, i) => (
              <div key={i} className="bg-[#1A1A1A] border border-[#2A2A2A] rounded p-3 space-y-2">
                <div className="flex items-center gap-2">
                  <span className="text-[10px] text-[#666666] w-5">{i + 1}.</span>
                  <input
                    value={step.name}
                    onChange={(e) => updateStep(i, { name: e.target.value })}
                    placeholder="Step name"
                    className="flex-1 px-2 py-1 bg-[#1F1F1F] border border-[#2A2A2A] rounded text-xs focus:border-[#1E90FF] outline-none"
                  />
                  <button onClick={() => moveStep(i, -1)} disabled={i === 0} className="text-[#A3A3A3] hover:text-[#F5F5F5] disabled:opacity-30 text-xs px-1">↑</button>
                  <button onClick={() => moveStep(i, 1)} disabled={i === steps.length - 1} className="text-[#A3A3A3] hover:text-[#F5F5F5] disabled:opacity-30 text-xs px-1">↓</button>
                  <button onClick={() => removeStep(i)} className="text-[#A3A3A3] hover:text-red-400 text-xs px-1">Delete</button>
                </div>
                <div className="flex flex-wrap gap-2">
                  <select
                    value={step.zone}
                    onChange={(e) => updateStep(i, { zone: e.target.value })}
                    className="px-2 py-1 bg-[#1F1F1F] border border-[#2A2A2A] rounded text-xs focus:border-[#1E90FF] outline-none"
                  >
                    {zoneNames.length === 0 && <option value="">no zones</option>}
                    {zoneNames.map((z) => (
                      <option key={z} value={z}>{z}</option>
                    ))}
                  </select>
                  <select
                    value={step.pose ?? ""}
                    onChange={(e) => updateStep(i, { pose: (e.target.value || null) as StepSequenceStep["pose"] })}
                    className="px-2 py-1 bg-[#1F1F1F] border border-[#2A2A2A] rounded text-xs focus:border-[#1E90FF] outline-none"
                  >
                    {POSE_OPTIONS.map((opt) => (
                      <option key={opt.label} value={opt.value ?? ""}>{opt.label}</option>
                    ))}
                  </select>
                  <input
                    type="number"
                    min={1}
                    value={step.max_seconds ?? ""}
                    onChange={(e) => updateStep(i, { max_seconds: e.target.value ? Number(e.target.value) : null })}
                    placeholder="max seconds (optional)"
                    className="w-40 px-2 py-1 bg-[#1F1F1F] border border-[#2A2A2A] rounded text-xs focus:border-[#1E90FF] outline-none"
                  />
                </div>
              </div>
            ))}

            <button
              onClick={addStep}
              className="px-3 py-1.5 bg-[#1A1A1A] text-[#A3A3A3] border border-[#2A2A2A] rounded text-xs hover:text-[#F5F5F5] transition-colors"
            >
              + Add Step
            </button>

            {validationError && <div className="text-xs text-red-400">{validationError}</div>}

            {genWarnings.length > 0 && (
              <div className="space-y-1">
                {genWarnings.map((w, i) => (
                  <div key={i} className="text-xs text-amber-400">{w}</div>
                ))}
              </div>
            )}

            {draftAlertRule && (
              <div className="bg-[#1A1A1A] border border-[#2A2A2A] rounded p-3 space-y-2">
                <div className="text-xs font-medium flex items-center justify-between">
                  <span>Notification — {draftAlertRule.name}</span>
                  <button
                    onClick={() => setDraftAlertRule(null)}
                    className="text-[10px] text-[#A3A3A3] hover:text-red-400"
                  >
                    Remove
                  </button>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {draftAlertRule.notify_channels.map((ch) => (
                    <span key={ch} className="px-2 py-0.5 bg-[#1F1F1F] border border-[#2A2A2A] rounded-full text-[10px] uppercase tracking-wide text-[#A3A3A3]">
                      {ch}
                    </span>
                  ))}
                </div>
                {draftAlertRule.notify_channels.includes("webhook") && (
                  <input
                    value={draftAlertRule.webhook_url ?? ""}
                    onChange={(e) => setDraftAlertRule({ ...draftAlertRule, webhook_url: e.target.value })}
                    placeholder="Webhook URL"
                    className="w-full px-2 py-1 bg-[#1F1F1F] border border-[#2A2A2A] rounded text-xs focus:border-[#1E90FF] outline-none"
                  />
                )}
                {draftAlertRule.notify_channels.includes("email") && (
                  <input
                    value={(draftAlertRule.notify_contacts || []).find((c) => c.type === "email")?.value ?? ""}
                    onChange={(e) =>
                      setDraftAlertRule({
                        ...draftAlertRule,
                        notify_contacts: [
                          ...(draftAlertRule.notify_contacts || []).filter((c) => c.type !== "email"),
                          { type: "email", value: e.target.value },
                        ],
                      })
                    }
                    placeholder="Destination email address"
                    className="w-full px-2 py-1 bg-[#1F1F1F] border border-[#2A2A2A] rounded text-xs focus:border-[#1E90FF] outline-none"
                  />
                )}
                {alertRuleError && <div className="text-xs text-red-400">{alertRuleError}</div>}
              </div>
            )}

            {saveError && <div className="text-xs text-red-400">Save failed: {saveError}</div>}
          </div>

          <div className="flex justify-end gap-2 p-4 border-t border-[#2A2A2A]">
            <button
              onClick={() => {
                setSaveError(null);
                saveMutation.mutate();
              }}
              disabled={!canSave}
              className="px-3 py-1.5 bg-[#1E90FF] text-white rounded text-xs hover:bg-[#3BA0FF] transition-colors disabled:opacity-50"
            >
              {saveMutation.isPending ? "Saving..." : "Save Sequence"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
