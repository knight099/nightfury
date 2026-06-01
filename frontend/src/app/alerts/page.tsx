"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Plus, Trash2, ToggleLeft, ToggleRight } from "lucide-react";
import { Skeleton } from "@/components/ui/Skeleton";
import { useAuthStore } from "@/lib/store";
import type { AlertRule } from "@/types";

export default function AlertsPage() {
  const queryClient = useQueryClient();
  const { user } = useAuthStore();
  const [showAdd, setShowAdd] = useState(false);
  const canManage = user?.role === "super_admin" || user?.role === "owner" || user?.role === "admin";

  const { data: rules, isLoading } = useQuery({
    queryKey: ["alert-rules"],
    queryFn: () => api.getAlertRules(),
  });

  const toggleMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      api.updateAlertRule(id, { enabled }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["alert-rules"] }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.deleteAlertRule(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["alert-rules"] }),
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">Alert Rules</h1>
        {canManage && (
          <button
            onClick={() => setShowAdd(true)}
            className="flex items-center gap-2 px-3 py-1.5 bg-[#1E90FF] text-white rounded-md text-sm hover:bg-[#3BA0FF] transition-colors"
          >
            <Plus size={16} /> New Rule
          </button>
        )}
      </div>

      {showAdd && canManage && <AddRuleForm onClose={() => setShowAdd(false)} />}

      <div className="space-y-3">
        {isLoading && Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-24 rounded-lg" />
        ))}
        {rules?.map((rule: AlertRule) => (
          <div key={rule.id} className="bg-[#111111] border border-[#2A2A2A] rounded-lg p-4">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-3">
                {canManage ? (
                  <button
                    onClick={() => toggleMutation.mutate({ id: rule.id, enabled: !rule.enabled })}
                    className={rule.enabled ? "text-green-400" : "text-[#666666]"}
                  >
                    {rule.enabled ? <ToggleRight size={20} /> : <ToggleLeft size={20} />}
                  </button>
                ) : (
                  <span className={rule.enabled ? "text-green-400" : "text-[#666666]"}>
                    {rule.enabled ? <ToggleRight size={20} /> : <ToggleLeft size={20} />}
                  </span>
                )}
                <span className={`font-medium text-sm ${!rule.enabled ? "text-[#666666]" : ""}`}>
                  {rule.name}
                </span>
              </div>
              {canManage && (
                <button
                  onClick={() => deleteMutation.mutate(rule.id)}
                  className="p-1 text-[#666666] hover:text-red-400"
                >
                  <Trash2 size={14} />
                </button>
              )}
            </div>
            <div className="grid grid-cols-3 gap-2 text-xs text-[#A3A3A3]">
              <div>Events: {rule.event_types.length ? rule.event_types.join(", ") : "All"}</div>
              <div>Min severity: {rule.min_severity}</div>
              <div>Cooldown: {rule.cooldown_seconds}s</div>
              <div>Channels: {rule.notify_channels.join(", ")}</div>
              <div>Contacts: {rule.notify_contacts.length}</div>
              {rule.time_window && <div>Window: {rule.time_window.start}–{rule.time_window.end}</div>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function AddRuleForm({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [minSeverity, setMinSeverity] = useState("medium");
  const [channels, setChannels] = useState<string[]>(["email"]);
  const [contactValue, setContactValue] = useState("");
  const [cooldown, setCooldown] = useState(60);

  const createMutation = useMutation({
    mutationFn: () =>
      api.createAlertRule({
        name,
        min_severity: minSeverity,
        notify_channels: channels,
        notify_contacts: channels.map((ch) => ({ type: ch as "whatsapp" | "email" | "webhook", value: contactValue })),
        cooldown_seconds: cooldown,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["alert-rules"] });
      onClose();
    },
  });

  return (
    <div className="bg-[#111111] border border-[#2A2A2A] rounded-lg p-4 space-y-3">
      <h3 className="text-sm font-medium">Create Alert Rule</h3>
      <div className="grid grid-cols-2 gap-3">
        <input
          placeholder="Rule name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="px-3 py-1.5 bg-[#1F1F1F] border border-[#2A2A2A] rounded text-sm"
        />
        <select
          value={minSeverity}
          onChange={(e) => setMinSeverity(e.target.value)}
          className="px-3 py-1.5 bg-[#1F1F1F] border border-[#2A2A2A] rounded text-sm"
        >
          <option value="low">Low+</option>
          <option value="medium">Medium+</option>
          <option value="high">High+</option>
          <option value="critical">Critical only</option>
        </select>
        <input
          placeholder="Contact (email/phone)"
          value={contactValue}
          onChange={(e) => setContactValue(e.target.value)}
          className="px-3 py-1.5 bg-[#1F1F1F] border border-[#2A2A2A] rounded text-sm"
        />
        <input
          type="number"
          placeholder="Cooldown (sec)"
          value={cooldown}
          onChange={(e) => setCooldown(Number(e.target.value))}
          className="px-3 py-1.5 bg-[#1F1F1F] border border-[#2A2A2A] rounded text-sm"
        />
      </div>
      <div className="flex gap-3">
        {["whatsapp", "email", "webhook"].map((ch) => (
          <label key={ch} className="flex items-center gap-1 text-xs">
            <input
              type="checkbox"
              checked={channels.includes(ch)}
              onChange={(e) =>
                setChannels(e.target.checked ? [...channels, ch] : channels.filter((x) => x !== ch))
              }
            />
            {ch}
          </label>
        ))}
      </div>
      <div className="flex gap-2">
        <button
          onClick={() => createMutation.mutate()}
          disabled={!name || !contactValue}
          className="px-3 py-1.5 bg-[#1E90FF] text-white rounded text-sm disabled:opacity-50"
        >
          Create Rule
        </button>
        <button onClick={onClose} className="px-3 py-1.5 text-[#666666] text-sm">Cancel</button>
      </div>
    </div>
  );
}
