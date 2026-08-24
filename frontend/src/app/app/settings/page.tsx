"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import {
  Building2,
  Grid3x3,
  Server,
  FileText,
  Video,
  BarChart3,
  Bot,
  MessageSquare,
} from "lucide-react";
import { api } from "@/lib/api";
import { Skeleton } from "@/components/ui/Skeleton";

const MORE_LINKS = [
  { href: "/app/sites", label: "Sites", icon: Building2, description: "Manage locations and site details" },
  { href: "/app/agents", label: "Agents", icon: Bot, description: "Edge boxes and their pairing status" },
  { href: "/app/wall", label: "Video wall", icon: Grid3x3, description: "Multi-camera live view" },
  { href: "/app/fleet", label: "Fleet", icon: Server, description: "Appliance capacity and coverage" },
  { href: "/app/digests", label: "Digests", icon: FileText, description: "Scheduled and on-demand recaps" },
  { href: "/app/test-camera", label: "Test AI", icon: Video, description: "Try detection against a sample clip" },
  { href: "/app/usage", label: "Usage", icon: BarChart3, description: "AI spend and call volume" },
  { href: "/app/chat", label: "Ask (classic)", icon: MessageSquare, description: "The standalone Q&A page, scoped to a camera or event" },
];

export default function SettingsPageV2() {
  const queryClient = useQueryClient();
  const [newNumber, setNewNumber] = useState("");

  const {
    data: org,
    isLoading: orgLoading,
    isError: orgError,
    error: orgErrorObj,
  } = useQuery({
    queryKey: ["my-org"],
    queryFn: () => api.getMyOrg(),
  });

  const {
    data: team,
    isLoading: teamLoading,
    isError: teamError,
    error: teamErrorObj,
  } = useQuery({
    queryKey: ["team"],
    queryFn: () => api.getTeam(),
  });

  const {
    data: contacts,
    isLoading: contactsLoading,
    isError: contactsError,
    error: contactsErrorObj,
  } = useQuery({
    queryKey: ["whatsapp-contacts"],
    queryFn: () => api.getWhatsAppAlertContacts(),
  });

  const addContact = useMutation({
    mutationFn: (number: string) => api.addWhatsAppAlertContact(number),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["whatsapp-contacts"] });
      setNewNumber("");
    },
  });

  const deleteContact = useMutation({
    mutationFn: (id: string) => api.deleteWhatsAppAlertContact(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["whatsapp-contacts"] });
    },
  });

  if (orgLoading || teamLoading) {
    return (
      <div className="max-w-[1040px] mx-auto px-12 py-12">
        <Skeleton className="h-8 w-48 mb-6" />
        <Skeleton className="h-40 w-full mb-8" />
        <Skeleton className="h-40 w-full mb-8" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  return (
    <div className="max-w-[1040px] mx-auto px-12 pt-12 pb-20">
      <div className="text-[28px] font-bold tracking-tight mb-6">Settings</div>

      {orgError && (
        <div className="bg-[oklch(18%_0.2_22)] border border-[oklch(70.4%_0.191_22.216)] rounded-lg px-4 py-3 mb-8 text-sm text-[oklch(70.4%_0.191_22.216)]">
          {orgErrorObj instanceof Error ? orgErrorObj.message : "Could not load organization."}
        </div>
      )}

      <div className="text-base font-bold mb-3">Organization</div>
      {orgError ? (
        <div className="text-sm text-[oklch(55%_0.01_265)] mb-8">Organization data unavailable</div>
      ) : (
        <div className="text-sm text-[oklch(80%_0.005_265)] mb-8">{org?.name}</div>
      )}

      {teamError && (
        <div className="bg-[oklch(18%_0.2_22)] border border-[oklch(70.4%_0.191_22.216)] rounded-lg px-4 py-3 mb-8 text-sm text-[oklch(70.4%_0.191_22.216)]">
          {teamErrorObj instanceof Error ? teamErrorObj.message : "Could not load team."}
        </div>
      )}

      <div className="text-base font-bold mb-3">Team</div>
      <div className="flex flex-col gap-2 mb-8">
        {teamError ? (
          <div className="text-sm text-[oklch(55%_0.01_265)]">Team data unavailable</div>
        ) : (team ?? []).length > 0 ? (
          (team ?? []).map((member) => (
            <div key={member.id} className="text-sm text-[oklch(80%_0.005_265)]">
              {member.name} ({member.role})
            </div>
          ))
        ) : (
          <div className="text-sm text-[oklch(55%_0.01_265)]">No team members yet.</div>
        )}
      </div>

      {contactsError && (
        <div className="bg-[oklch(18%_0.2_22)] border border-[oklch(70.4%_0.191_22.216)] rounded-lg px-4 py-3 mb-8 text-sm text-[oklch(70.4%_0.191_22.216)]">
          {contactsErrorObj instanceof Error ? contactsErrorObj.message : "Could not load WhatsApp contacts."}
        </div>
      )}

      <div className="text-base font-bold mb-3">WhatsApp alert contacts</div>
      {contactsLoading ? (
        <div className="mb-8">
          <Skeleton className="h-6 w-full mb-2" />
          <Skeleton className="h-6 w-3/4" />
        </div>
      ) : (
        <div className="flex flex-col gap-2 mb-3">
          {contactsError ? (
            <div className="text-sm text-[oklch(55%_0.01_265)]">Unable to load contacts</div>
          ) : (contacts ?? []).length > 0 ? (
            (contacts ?? []).map((c) => (
              <div key={c.id} className="flex items-center justify-between text-sm text-[oklch(80%_0.005_265)]">
                <span>
                  {c.number} {c.enabled ? "" : "(disabled)"}
                </span>
                <button
                  onClick={() => deleteContact.mutate(c.id)}
                  disabled={deleteContact.isPending}
                  className="text-xs text-[oklch(70.4%_0.191_22.216)] hover:text-[oklch(80%_0.01_22)] disabled:opacity-50"
                >
                  Remove
                </button>
              </div>
            ))
          ) : (
            <div className="text-sm text-[oklch(55%_0.01_265)]">No WhatsApp contacts yet.</div>
          )}
        </div>
      )}

      <div className="flex gap-2 mb-8">
        <input
          value={newNumber}
          onChange={(e) => setNewNumber(e.target.value)}
          placeholder="+91..."
          disabled={addContact.isPending}
          className="bg-[oklch(17%_0.015_265)] border border-[oklch(30%_0.02_265)] rounded-lg px-3 py-2 text-sm text-[oklch(95%_0.005_265)] outline-none disabled:opacity-50"
        />
        <button
          onClick={() => newNumber && addContact.mutate(newNumber)}
          disabled={!newNumber || addContact.isPending}
          className="text-sm font-semibold px-4 py-2 rounded-lg bg-[oklch(85%_0.16_84)] text-[oklch(18%_0.02_84)] disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {addContact.isPending ? "Adding..." : "Add"}
        </button>
      </div>

      {addContact.isError && (
        <div className="bg-[oklch(18%_0.2_22)] border border-[oklch(70.4%_0.191_22.216)] rounded-lg px-4 py-3 mb-8 text-sm text-[oklch(70.4%_0.191_22.216)]">
          {addContact.error instanceof Error ? addContact.error.message : "Could not add contact."}
        </div>
      )}

      <div className="text-base font-bold mb-3">More</div>
      <div className="text-[13px] text-[oklch(55%_0.01_265)] mb-4 max-w-[62ch] leading-relaxed">
        The sidebar keeps only the daily-use pages. Everything else still lives here.
      </div>
      <div className="grid grid-cols-2 gap-3">
        {MORE_LINKS.map(({ href, label, icon: Icon, description }) => (
          <Link
            key={href}
            href={href}
            className="flex items-start gap-3 bg-[oklch(12%_0.015_265)] border border-[oklch(22%_0.015_265)] rounded-[14px] px-4 py-3.5 hover:border-[oklch(32%_0.015_265)] transition-colors"
          >
            <Icon size={18} className="text-[oklch(72%_0.01_265)] mt-0.5 flex-shrink-0" />
            <div>
              <div className="text-[13.5px] font-semibold text-[oklch(90%_0.005_265)]">{label}</div>
              <div className="text-[12px] text-[oklch(55%_0.01_265)] mt-0.5">{description}</div>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
