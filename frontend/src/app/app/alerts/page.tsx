"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, ToggleLeft, ToggleRight } from "lucide-react";
import { api } from "@/lib/api";
import { useAuthStore } from "@/lib/store";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  Page,
  PageHeader,
  Card,
  Btn,
  EmptyState,
  Field,
  Pill,
  inputClass,
} from "@/components/v2/ui";
import type { AlertRule } from "@/types";

export default function AlertsPageV2() {
  const queryClient = useQueryClient();
  const { user } = useAuthStore();
  const [showAdd, setShowAdd] = useState(false);
  const [showDeleted, setShowDeleted] = useState(false);
  const isSuperAdmin = user?.role === "super_admin";
  const canManage = isSuperAdmin || user?.role === "owner" || user?.role === "admin";

  const { data: rules, isLoading, isError, error } = useQuery({
    queryKey: ["alert-rules", showDeleted],
    queryFn: () => api.getAlertRules({ include_deleted: showDeleted }),
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["alert-rules"] });

  const toggleMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      api.updateAlertRule(id, { enabled }),
    onSuccess: invalidate,
  });
  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.deleteAlertRule(id),
    onSuccess: invalidate,
  });
  const restoreMutation = useMutation({
    mutationFn: (id: string) => api.restoreAlertRule(id),
    onSuccess: invalidate,
  });

  return (
    <Page>
      <PageHeader
        title="Alerts"
        subtitle="Rules decide when a detection reaches a person. Unacknowledged events climb the escalation ladder to the next contact."
        action={
          canManage ? (
            <Btn variant="primary" onClick={() => setShowAdd(true)} className="inline-flex items-center gap-2 shrink-0">
              <Plus size={15} /> New rule
            </Btn>
          ) : undefined
        }
      />

      {isSuperAdmin && (
        <label className="flex items-center gap-2 text-[12px] text-[oklch(55%_0.01_265)] mb-4">
          <input
            type="checkbox"
            checked={showDeleted}
            onChange={(e) => setShowDeleted(e.target.checked)}
            className="rounded"
          />
          Show deleted
        </label>
      )}

      {showAdd && canManage && <AddRuleForm onClose={() => setShowAdd(false)} />}

      <div className="space-y-3 mt-4">
        {isLoading &&
          Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-24 rounded-[14px]" />)}

        {isError && (
          <div className="p-6 text-sm text-center text-[oklch(70.4%_0.191_22.216)] border border-[oklch(70.4%_0.191_22.216)] rounded-[14px] bg-[oklch(18%_0.2_22)]">
            Failed to load alert rules: {(error as Error).message}
          </div>
        )}

        {!isLoading && !isError && (!rules || rules.length === 0) && (
          <EmptyState
            title="Get notified when it matters"
            hint="Create a rule to receive a WhatsApp or email the moment a camera sees something — like a person at night, or a vehicle in the driveway."
          />
        )}

        {rules?.map((rule: AlertRule) => (
          <Card key={rule.id}>
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-3">
                {canManage ? (
                  <button
                    onClick={() => toggleMutation.mutate({ id: rule.id, enabled: !rule.enabled })}
                    className={rule.enabled ? "text-[oklch(79.2%_0.209_151.711)]" : "text-[oklch(42%_0.01_265)]"}
                    aria-label={rule.enabled ? "Disable rule" : "Enable rule"}
                  >
                    {rule.enabled ? <ToggleRight size={20} /> : <ToggleLeft size={20} />}
                  </button>
                ) : (
                  <span className={rule.enabled ? "text-[oklch(79.2%_0.209_151.711)]" : "text-[oklch(42%_0.01_265)]"}>
                    {rule.enabled ? <ToggleRight size={20} /> : <ToggleLeft size={20} />}
                  </span>
                )}
                <span
                  className={`text-[14px] font-semibold ${
                    !rule.enabled ? "text-[oklch(42%_0.01_265)]" : "text-[oklch(97%_0.005_265)]"
                  }`}
                >
                  {rule.name}
                </span>
                {rule.deleted_at && <Pill tone="red">deleted</Pill>}
              </div>
              {rule.deleted_at
                ? canManage && (
                    <Btn onClick={() => restoreMutation.mutate(rule.id)}>Restore</Btn>
                  )
                : canManage && (
                    <button
                      onClick={() => deleteMutation.mutate(rule.id)}
                      className="p-2 text-[oklch(42%_0.01_265)] hover:text-[oklch(70.4%_0.191_22.216)] transition-colors"
                      aria-label="Delete rule"
                    >
                      <Trash2 size={15} />
                    </button>
                  )}
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2 text-[12px] text-[oklch(72%_0.01_265)]">
              <div>Events: {rule.event_types.length ? rule.event_types.join(", ") : "All"}</div>
              <div>Min severity: {rule.min_severity}</div>
              <div>Quiet time: {rule.cooldown_seconds}s between alerts</div>
              <div>Channels: {rule.notify_channels.join(", ")}</div>
              <div>Contacts: {rule.notify_contacts.length}</div>
              {rule.time_window && (
                <div>
                  Window: {rule.time_window.start}–{rule.time_window.end}
                </div>
              )}
            </div>
          </Card>
        ))}
      </div>
    </Page>
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

const CHANNELS = [
  { id: "whatsapp", label: "WhatsApp" },
  { id: "email", label: "Email" },
  { id: "webhook", label: "Webhook (advanced)" },
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
        notify_contacts: channels.map((ch) => ({
          type: ch as "whatsapp" | "email" | "webhook",
          value: contactValue,
        })),
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
    <Card className="space-y-5">
      <div className="text-[15px] font-semibold">New alert</div>

      <div>
        <p className="text-[12px] text-[oklch(55%_0.01_265)] mb-2.5">
          Start from a template, or fill in the details yourself:
        </p>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
          {RULE_TEMPLATES.map((t) => (
            <button
              key={t.id}
              onClick={() => applyTemplate(t)}
              className={`text-left p-3 rounded-[10px] border transition-colors ${
                template?.id === t.id
                  ? "border-[oklch(85%_0.16_84)] bg-[oklch(85%_0.16_84)]/10"
                  : "border-[oklch(24%_0.02_265)] bg-[oklch(15%_0.015_265)] hover:border-[oklch(34%_0.02_265)]"
              }`}
            >
              <div className="text-lg mb-1">{t.emoji}</div>
              <div className="text-[12px] font-semibold text-[oklch(97%_0.005_265)]">{t.title}</div>
              <div className="mt-0.5 text-[11px] text-[oklch(55%_0.01_265)] leading-snug">
                {t.description}
              </div>
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <Field label="Alert name">
          <input
            placeholder="e.g. Person at front gate"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className={inputClass}
          />
        </Field>
        <Field label="Alert me about">
          <select
            value={minSeverity}
            onChange={(e) => setMinSeverity(e.target.value)}
            className={inputClass}
          >
            <option value="low">Everything (most alerts)</option>
            <option value="medium">Normal and serious events</option>
            <option value="high">Serious events only</option>
            <option value="critical">Critical events only (fewest alerts)</option>
          </select>
        </Field>
        <Field label="Send alerts to (phone or email)">
          <input
            placeholder="+91 98765 43210 or you@example.com"
            value={contactValue}
            onChange={(e) => setContactValue(e.target.value)}
            className={inputClass}
          />
        </Field>
        <Field label="Quiet time between repeat alerts">
          <select
            value={cooldown}
            onChange={(e) => setCooldown(Number(e.target.value))}
            className={inputClass}
          >
            {QUIET_TIME_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </Field>
      </div>

      <div>
        <span className="block text-[11px] uppercase tracking-[0.04em] text-[oklch(55%_0.01_265)] mb-2">
          How should we reach you?
        </span>
        <div className="flex flex-wrap gap-2">
          {CHANNELS.map((ch) => (
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
              className={`px-3 py-2 rounded-full text-[12px] border transition-colors ${
                channels.includes(ch.id)
                  ? "border-[oklch(85%_0.16_84)] bg-[oklch(85%_0.16_84)]/10 text-[oklch(85%_0.16_84)]"
                  : "border-[oklch(24%_0.02_265)] bg-[oklch(15%_0.015_265)] text-[oklch(72%_0.01_265)] hover:text-[oklch(97%_0.005_265)]"
              }`}
            >
              {ch.label}
            </button>
          ))}
        </div>
      </div>

      {createMutation.isError && (
        <p className="text-[12px] text-[oklch(70.4%_0.191_22.216)]">
          {(createMutation.error as Error).message}
        </p>
      )}

      <div className="flex gap-2">
        <Btn
          variant="primary"
          onClick={() => createMutation.mutate()}
          disabled={!name || !contactValue || channels.length === 0 || createMutation.isPending}
        >
          {createMutation.isPending ? "Creating…" : "Create alert"}
        </Btn>
        <Btn onClick={onClose}>Cancel</Btn>
      </div>
    </Card>
  );
}
