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
  const [showDeleted, setShowDeleted] = useState(false);
  const isSuperAdmin = user?.role === "super_admin";
  const canManage = isSuperAdmin || user?.role === "owner" || user?.role === "admin";

  const { data: rules, isLoading } = useQuery({
    queryKey: ["alert-rules", showDeleted],
    queryFn: () => api.getAlertRules({ include_deleted: showDeleted }),
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

  const restoreMutation = useMutation({
    mutationFn: (id: string) => api.restoreAlertRule(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["alert-rules"] }),
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-bold">Alert Rules</h1>
          {isSuperAdmin && (
            <label className="flex items-center gap-2 text-xs text-[#A3A3A3]">
              <input
                type="checkbox"
                checked={showDeleted}
                onChange={(e) => setShowDeleted(e.target.checked)}
                className="rounded"
              />
              Show deleted
            </label>
          )}
        </div>
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
        {!isLoading && (!rules || rules.length === 0) && (
          <div className="bg-[#111111] border border-[#2A2A2A] rounded-lg p-10 text-center space-y-3">
            <div className="text-base font-medium text-[#F5F5F5]">Get notified when it matters</div>
            <div className="text-sm text-[#A3A3A3] max-w-sm mx-auto">
              Create a rule to receive a WhatsApp or email the moment a camera sees something —
              like a person at night or a vehicle in the driveway.
            </div>
            {canManage && (
              <button
                onClick={() => setShowAdd(true)}
                className="inline-flex items-center gap-2 px-5 py-3 bg-[#1E90FF] text-white rounded-md text-sm font-medium hover:bg-[#3BA0FF] glow-accent transition-colors"
              >
                <Plus size={16} /> Create your first rule
              </button>
            )}
          </div>
        )}
        {rules?.map((rule: AlertRule) => (
          <div key={rule.id} className="bg-[#111111] border border-[#2A2A2A] rounded-lg p-4 card-lift">
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
                {rule.deleted_at && (
                  <span className="text-xs px-2 py-0.5 rounded bg-[#EF4444]/20 text-[#EF4444]">deleted</span>
                )}
              </div>
              {rule.deleted_at ? (
                canManage && (
                  <button
                    onClick={() => restoreMutation.mutate(rule.id)}
                    className="text-xs px-2 py-1 text-[#A3A3A3] hover:text-[#4ADE80] transition-colors"
                  >
                    Restore
                  </button>
                )
              ) : (
                canManage && (
                  <button
                    onClick={() => deleteMutation.mutate(rule.id)}
                    className="p-2.5 sm:p-1 text-[#666666] hover:text-red-400"
                  >
                    <Trash2 size={14} />
                  </button>
                )
              )}
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2 text-xs text-[#A3A3A3]">
              <div>Events: {rule.event_types.length ? rule.event_types.join(", ") : "All"}</div>
              <div>Min severity: {rule.min_severity}</div>
              <div>Quiet time: {rule.cooldown_seconds}s between alerts</div>
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

interface RuleTemplate {
  id: string;
  title: string;
  description: string;
  emoji: string;
  rule: {
    name: string;
    event_types: string[];
    min_severity: string;
    cooldown_seconds: number;
    time_window: { start: string; end: string; days: string[] } | null;
  };
}

const RULE_TEMPLATES: RuleTemplate[] = [
  {
    id: "person-night",
    title: "Person at night",
    description: "Someone shows up between 10 PM and 6 AM",
    emoji: "🌙",
    rule: {
      name: "Person at night",
      event_types: ["person"],
      min_severity: "medium",
      cooldown_seconds: 300,
      time_window: { start: "22:00", end: "06:00", days: [] },
    },
  },
  {
    id: "vehicle",
    title: "Vehicle arrives",
    description: "A car or bike enters the camera view",
    emoji: "🚗",
    rule: {
      name: "Vehicle arrives",
      event_types: ["vehicle"],
      min_severity: "medium",
      cooldown_seconds: 300,
      time_window: null,
    },
  },
  {
    id: "intrusion",
    title: "Intrusion",
    description: "Someone enters a restricted area",
    emoji: "🚨",
    rule: {
      name: "Intrusion alert",
      event_types: ["intrusion"],
      min_severity: "high",
      cooldown_seconds: 60,
      time_window: null,
    },
  },
  {
    id: "critical",
    title: "Anything critical",
    description: "Only the most serious events, any type",
    emoji: "⚠️",
    rule: {
      name: "Critical events",
      event_types: [],
      min_severity: "critical",
      cooldown_seconds: 60,
      time_window: null,
    },
  },
];

const QUIET_TIME_OPTIONS = [
  { value: 60, label: "1 minute" },
  { value: 300, label: "5 minutes" },
  { value: 900, label: "15 minutes" },
  { value: 3600, label: "1 hour" },
];

function AddRuleForm({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [template, setTemplate] = useState<RuleTemplate | null>(null);
  const [name, setName] = useState("");
  const [minSeverity, setMinSeverity] = useState("medium");
  const [channels, setChannels] = useState<string[]>(["whatsapp"]);
  const [contactValue, setContactValue] = useState("");
  const [cooldown, setCooldown] = useState(300);

  const applyTemplate = (t: RuleTemplate) => {
    setTemplate(t);
    setName(t.rule.name);
    setMinSeverity(t.rule.min_severity);
    setCooldown(t.rule.cooldown_seconds);
  };

  const createMutation = useMutation({
    mutationFn: () =>
      api.createAlertRule({
        name,
        min_severity: minSeverity,
        notify_channels: channels,
        notify_contacts: channels.map((ch) => ({ type: ch as "whatsapp" | "email" | "webhook", value: contactValue })),
        cooldown_seconds: cooldown,
        ...(template && {
          event_types: template.rule.event_types,
          time_window: template.rule.time_window,
        }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["alert-rules"] });
      onClose();
    },
  });

  return (
    <div className="bg-[#111111] border border-[#2A2A2A] rounded-lg p-4 space-y-4">
      <h3 className="text-sm font-medium">New alert</h3>

      <div>
        <p className="text-xs text-[#A3A3A3] mb-2">Start from a template, or fill in the details yourself:</p>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
          {RULE_TEMPLATES.map((t) => (
            <button
              key={t.id}
              onClick={() => applyTemplate(t)}
              className={`text-left p-3 rounded-lg border transition-colors ${
                template?.id === t.id
                  ? "border-[#1E90FF] bg-[#1E90FF]/10"
                  : "border-[#2A2A2A] bg-[#1A1A1A] hover:border-[#3A3A3A]"
              }`}
            >
              <div className="text-lg mb-1">{t.emoji}</div>
              <div className="text-xs font-medium text-[#F5F5F5]">{t.title}</div>
              <div className="mt-0.5 text-[11px] text-[#A3A3A3] leading-snug">{t.description}</div>
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <label className="block">
          <span className="text-[11px] text-[#A3A3A3]">Alert name</span>
          <input
            placeholder="e.g. Person at front gate"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="mt-1 w-full px-3 py-2.5 sm:py-2 bg-[#1F1F1F] border border-[#2A2A2A] rounded text-sm focus:outline-none focus:border-[#1E90FF]"
          />
        </label>
        <label className="block">
          <span className="text-[11px] text-[#A3A3A3]">Alert me about</span>
          <select
            value={minSeverity}
            onChange={(e) => setMinSeverity(e.target.value)}
            className="mt-1 w-full px-3 py-2.5 sm:py-2 bg-[#1F1F1F] border border-[#2A2A2A] rounded text-sm focus:outline-none focus:border-[#1E90FF]"
          >
            <option value="low">Everything (most alerts)</option>
            <option value="medium">Normal and serious events</option>
            <option value="high">Serious events only</option>
            <option value="critical">Critical events only (fewest alerts)</option>
          </select>
        </label>
        <label className="block">
          <span className="text-[11px] text-[#A3A3A3]">Send alerts to (phone or email)</span>
          <input
            placeholder="+91 98765 43210 or you@example.com"
            value={contactValue}
            onChange={(e) => setContactValue(e.target.value)}
            className="mt-1 w-full px-3 py-2.5 sm:py-2 bg-[#1F1F1F] border border-[#2A2A2A] rounded text-sm focus:outline-none focus:border-[#1E90FF]"
          />
        </label>
        <label className="block">
          <span className="text-[11px] text-[#A3A3A3]">Quiet time between repeat alerts</span>
          <select
            value={cooldown}
            onChange={(e) => setCooldown(Number(e.target.value))}
            className="mt-1 w-full px-3 py-2.5 sm:py-2 bg-[#1F1F1F] border border-[#2A2A2A] rounded text-sm focus:outline-none focus:border-[#1E90FF]"
          >
            {QUIET_TIME_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </label>
      </div>

      <div>
        <span className="text-[11px] text-[#A3A3A3]">How should we reach you?</span>
        <div className="mt-1.5 flex flex-wrap gap-2">
          {[
            { id: "whatsapp", label: "WhatsApp" },
            { id: "email", label: "Email" },
            { id: "webhook", label: "Webhook (advanced)" },
          ].map((ch) => (
            <button
              key={ch.id}
              type="button"
              onClick={() =>
                setChannels(
                  channels.includes(ch.id)
                    ? channels.filter((x) => x !== ch.id)
                    : [...channels, ch.id]
                )
              }
              className={`px-3 py-2 rounded-full text-xs border transition-colors ${
                channels.includes(ch.id)
                  ? "border-[#1E90FF] bg-[#1E90FF]/10 text-[#1E90FF]"
                  : "border-[#2A2A2A] bg-[#1A1A1A] text-[#A3A3A3] hover:text-[#F5F5F5]"
              }`}
            >
              {ch.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex gap-2">
        <button
          onClick={() => createMutation.mutate()}
          disabled={!name || !contactValue || channels.length === 0 || createMutation.isPending}
          className="px-5 py-2.5 bg-[#1E90FF] text-white rounded-md text-sm font-medium hover:bg-[#3BA0FF] glow-accent-hover disabled:opacity-50 transition-colors"
        >
          {createMutation.isPending ? "Creating…" : "Create alert"}
        </button>
        <button onClick={onClose} className="px-4 py-2.5 text-[#A3A3A3] hover:text-[#F5F5F5] text-sm transition-colors">
          Cancel
        </button>
      </div>
    </div>
  );
}
