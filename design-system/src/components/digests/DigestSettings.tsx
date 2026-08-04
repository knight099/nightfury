"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { DigestPreferences } from "@/types";

export function DigestSettings() {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["digest-prefs"],
    queryFn: () => api.getDigestPreferences(),
  });
  const update = useMutation({
    mutationFn: (patch: Partial<DigestPreferences>) =>
      api.updateDigestPreferences(patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["digest-prefs"] }),
  });

  if (!data) return null;
  return (
    <div className="rounded-lg border border-[#2A2A2A] bg-[#111111] p-4 space-y-3">
      <h2 className="text-sm font-semibold text-[#F5F5F5]">Digest schedule</h2>
      <Toggle
        label="Morning recap (last night)"
        checked={data.morning_enabled}
        onChange={(v) => update.mutate({ morning_enabled: v })}
      />
      <TimeField
        label="Morning time"
        value={data.morning_local_time}
        onChange={(v) => update.mutate({ morning_local_time: v })}
      />
      <Toggle
        label="Evening recap (today)"
        checked={data.evening_enabled}
        onChange={(v) => update.mutate({ evening_enabled: v })}
      />
      <TimeField
        label="Evening time"
        value={data.evening_local_time}
        onChange={(v) => update.mutate({ evening_local_time: v })}
      />
      <Toggle
        label="Send via WhatsApp"
        checked={data.whatsapp_enabled}
        onChange={(v) => update.mutate({ whatsapp_enabled: v })}
      />
      <Toggle
        label="Send via Email"
        checked={data.email_enabled}
        onChange={(v) => update.mutate({ email_enabled: v })}
      />
    </div>
  );
}

function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center justify-between text-sm text-[#F5F5F5]">
      <span>{label}</span>
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 accent-[#1E90FF]"
      />
    </label>
  );
}

function TimeField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  const inputValue = value.slice(0, 5);
  return (
    <label className="flex items-center justify-between text-sm text-[#F5F5F5]">
      <span>{label}</span>
      <input
        type="time"
        value={inputValue}
        onChange={(e) => onChange(`${e.target.value}:00`)}
        className="rounded-md border border-[#2A2A2A] bg-[#1F1F1F] px-2 py-1 text-sm text-[#F5F5F5] focus:border-[#1E90FF] outline-none"
      />
    </label>
  );
}
