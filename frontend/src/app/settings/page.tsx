"use client";

import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ToggleLeft, ToggleRight } from "lucide-react";
import { api } from "@/lib/api";
import { useAuthStore } from "@/lib/store";
import type { User, WhatsAppAlertContact } from "@/types";

type SettingsTab = "organization" | "sites" | "team" | "whatsapp-alerts";

const TABS: { id: SettingsTab; label: string }[] = [
  { id: "organization", label: "Organization" },
  { id: "sites", label: "Sites" },
  { id: "team", label: "Team" },
  { id: "whatsapp-alerts", label: "WhatsApp Alerts" },
];

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const { user } = useAuthStore();
  const isSuperAdmin = user?.role === "super_admin";
  const isOwner = user?.role === "owner" || isSuperAdmin;
  const canViewTeam = !!user?.org_id;
  const [activeTab, setActiveTab] = useState<SettingsTab>("organization");
  const [showDeletedSites, setShowDeletedSites] = useState(false);

  const { data: org } = useQuery({
    queryKey: ["settings", "org"],
    queryFn: () => api.getMyOrg(),
    enabled: !!user?.org_id,
  });

  const { data: team } = useQuery({
    queryKey: ["settings", "team"],
    queryFn: () => api.getTeam(),
    enabled: canViewTeam,
  });

  const { data: sites } = useQuery({
    queryKey: ["settings", "sites", showDeletedSites],
    queryFn: () => api.getSites({ include_deleted: showDeletedSites }),
    enabled: !!user?.org_id,
  });

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-bold text-[#F5F5F5]">Settings</h1>

      {isSuperAdmin && (
        <div className="p-4 bg-[#111111] border border-[#2A2A2A] rounded-lg">
          <p className="text-sm text-[#F5F5F5] mb-1">You are signed in as <span className="text-[#EF4444]">super_admin</span> (no org).</p>
          <p className="text-xs text-[#A3A3A3]">Use the <a href="/admin" className="text-[#1E90FF] hover:underline">Admin Panel</a> to manage all organizations and users across the platform.</p>
        </div>
      )}

      {user?.org_id && (
        <div className="space-y-4">
          <div className="flex gap-1 p-1 bg-[#111111] border border-[#2A2A2A] rounded-lg w-fit">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => setActiveTab(t.id)}
                className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
                  activeTab === t.id
                    ? "bg-[#1E90FF] text-white"
                    : "text-[#A3A3A3] hover:text-[#F5F5F5]"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          {activeTab === "organization" && org && <OrgSection org={org} canEdit={isOwner} />}

          {activeTab === "sites" && org && sites && isOwner && (
            <SiteSection
              sites={sites}
              isSuperAdmin={isSuperAdmin}
              showDeleted={showDeletedSites}
              onToggleShowDeleted={setShowDeletedSites}
              onMutate={() => queryClient.invalidateQueries({ queryKey: ["settings", "sites"] })}
            />
          )}

          {activeTab === "team" && canViewTeam && team && (
            <TeamSection
              team={team}
              currentUserId={user?.id || ""}
              canManage={isOwner}
              onMutate={() => queryClient.invalidateQueries({ queryKey: ["settings", "team"] })}
            />
          )}

          {activeTab === "whatsapp-alerts" && <WhatsAppAlertsSection canManage={isOwner} />}
        </div>
      )}
    </div>
  );
}

function OrgSection({ org, canEdit }: { org: { id: string; name: string; slug: string; plan: string; created_at: string }; canEdit: boolean }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(org.name);

  const updateMutation = useMutation({
    mutationFn: (data: { name?: string }) => api.updateMyOrg(data),
    onSuccess: () => { setEditing(false); queryClient.invalidateQueries({ queryKey: ["settings", "org"] }); },
  });

  return (
    <div className="p-4 bg-[#111111] border border-[#2A2A2A] rounded-lg space-y-3">
      <h2 className="text-lg font-semibold text-[#F5F5F5]">Organization</h2>
      {editing ? (
        <form onSubmit={(e) => { e.preventDefault(); updateMutation.mutate({ name }); }} className="flex gap-2">
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="flex-1 px-3 py-1.5 text-sm bg-[#1F1F1F] border border-[#2A2A2A] rounded text-[#F5F5F5] focus:outline-none focus:border-[#1E90FF]"
            required
          />
          <button type="submit" className="px-3 py-1.5 bg-[#1E90FF] text-white text-sm rounded hover:bg-[#3BA0FF]">Save</button>
          <button type="button" onClick={() => { setEditing(false); setName(org.name); }} className="px-3 py-1.5 text-sm text-[#666666]">Cancel</button>
        </form>
      ) : (
        <div className="flex items-center justify-between">
          <div className="space-y-1">
            <div className="text-sm text-[#F5F5F5]">{org.name}</div>
            <div className="text-xs text-[#666666]">Slug: {org.slug} · Plan: <span className="text-[#1E90FF]">{org.plan}</span> · Created: {new Date(org.created_at).toLocaleDateString()}</div>
          </div>
          {canEdit && (
            <button onClick={() => setEditing(true)} className="text-xs px-3 py-1 text-[#A3A3A3] hover:text-[#1E90FF] transition-colors">
              Edit
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function SiteSection({
  sites,
  isSuperAdmin,
  showDeleted,
  onToggleShowDeleted,
  onMutate,
}: {
  sites: { id: string; org_id: string; name: string; address: string | null; timezone: string; created_at: string; deleted_at?: string | null }[];
  isSuperAdmin: boolean;
  showDeleted: boolean;
  onToggleShowDeleted: (v: boolean) => void;
  onMutate: () => void;
}) {
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [editingSiteId, setEditingSiteId] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const createMutation = useMutation({
    mutationFn: (data: { name: string; address?: string; timezone?: string }) => api.createSite(data),
    onSuccess: () => {
      setErrorMsg(null);
      setShowCreate(false);
      queryClient.invalidateQueries({ queryKey: ["settings", "sites"] });
      onMutate();
    },
    onError: (e: Error) => setErrorMsg(e.message || "Could not create site."),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: { name?: string; address?: string; timezone?: string } }) =>
      api.updateSite(id, data),
    onSuccess: () => {
      setErrorMsg(null);
      setEditingSiteId(null);
      queryClient.invalidateQueries({ queryKey: ["settings", "sites"] });
      onMutate();
    },
    onError: (e: Error) => setErrorMsg(e.message || "Could not update site."),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.deleteSite(id),
    onSuccess: () => {
      setErrorMsg(null);
      queryClient.invalidateQueries({ queryKey: ["settings", "sites"] });
      onMutate();
    },
    onError: (e: Error) => setErrorMsg(e.message || "Could not delete site."),
  });

  const restoreMutation = useMutation({
    mutationFn: (id: string) => api.restoreSite(id),
    onSuccess: () => {
      setErrorMsg(null);
      queryClient.invalidateQueries({ queryKey: ["settings", "sites"] });
      onMutate();
    },
    onError: (e: Error) => setErrorMsg(e.message || "Could not restore site."),
  });

  return (
    <div className="p-4 bg-[#111111] border border-[#2A2A2A] rounded-lg space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-[#F5F5F5]">Sites</h2>
          <p className="text-xs text-[#A3A3A3]">Create locations like Home, Office, or Warehouse to group cameras.</p>
          {isSuperAdmin && (
            <label className="mt-1 flex items-center gap-2 text-xs text-[#A3A3A3]">
              <input
                type="checkbox"
                checked={showDeleted}
                onChange={(e) => onToggleShowDeleted(e.target.checked)}
                className="rounded"
              />
              Show deleted
            </label>
          )}
        </div>
        <button
          onClick={() => setShowCreate((v) => !v)}
          className="px-3 py-1.5 bg-[#1E90FF] text-white text-sm rounded-md hover:bg-[#3BA0FF] transition-colors"
        >
          {showCreate ? "Close" : "+ Create Site"}
        </button>
      </div>

      {showCreate && (
        <SiteEditor
          mode="create"
          onCancel={() => setShowCreate(false)}
          onSave={(data) => createMutation.mutate(data)}
          loading={createMutation.isPending}
        />
      )}

      {errorMsg && (
        <div className="text-xs text-red-400 bg-[#1A1A1A] border border-[#2A2A2A] rounded-md p-2">
          {errorMsg}
        </div>
      )}

      <div className="space-y-2">
        {sites.length === 0 ? (
          <div className="text-sm text-[#A3A3A3] border border-dashed border-[#2A2A2A] rounded-lg p-4">
            No sites created yet. Add one so cameras can be organized by location.
          </div>
        ) : (
          sites.map((site) => (
            <div key={site.id} className="p-3 rounded-lg border border-[#2A2A2A] bg-[#1A1A1A] space-y-3">
              {editingSiteId === site.id ? (
                <SiteEditor
                  mode="edit"
                  initialSite={site}
                  onCancel={() => setEditingSiteId(null)}
                  onSave={(data) => updateMutation.mutate({ id: site.id, data })}
                  loading={updateMutation.isPending}
                />
              ) : (
                <div className="flex items-start justify-between gap-4">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-[#F5F5F5]">{site.name}</span>
                      {site.deleted_at && (
                        <span className="text-xs px-2 py-0.5 rounded bg-[#EF4444]/20 text-[#EF4444]">deleted</span>
                      )}
                    </div>
                    <div className="text-xs text-[#A3A3A3]">
                      {site.address ? site.address : "No address set"} · {site.timezone} · Created {new Date(site.created_at).toLocaleDateString()}
                    </div>
                  </div>
                  <div className="flex gap-2 shrink-0">
                    {site.deleted_at ? (
                      <button
                        onClick={() => restoreMutation.mutate(site.id)}
                        className="text-xs px-3 py-1.5 text-[#A3A3A3] hover:text-[#4ADE80] transition-colors"
                      >
                        Restore
                      </button>
                    ) : (
                      <>
                        <button
                          onClick={() => setEditingSiteId(site.id)}
                          className="text-xs px-3 py-1.5 text-[#A3A3A3] hover:text-[#1E90FF] transition-colors"
                        >
                          Edit
                        </button>
                        <button
                          onClick={() => {
                            if (window.confirm(`Delete site "${site.name}"? Cameras assigned to this site will also be affected.`)) {
                              deleteMutation.mutate(site.id);
                            }
                          }}
                          className="text-xs px-3 py-1.5 text-[#A3A3A3] hover:text-[#EF4444] transition-colors"
                        >
                          Delete
                        </button>
                      </>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function SiteEditor({
  mode,
  initialSite,
  onSave,
  onCancel,
  loading,
}: {
  mode: "create" | "edit";
  initialSite?: { name: string; address: string | null; timezone: string };
  onSave: (data: { name: string; address?: string; timezone?: string }) => void;
  onCancel: () => void;
  loading: boolean;
}) {
  const [name, setName] = useState(initialSite?.name ?? "");
  const [address, setAddress] = useState(initialSite?.address ?? "");
  const [timezone, setTimezone] = useState(initialSite?.timezone ?? "Asia/Kolkata");

  useEffect(() => {
    if (mode === "edit" && initialSite) {
      setName(initialSite.name);
      setAddress(initialSite.address ?? "");
      setTimezone(initialSite.timezone);
    }
  }, [initialSite, mode]);

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSave({
          name,
          address: address.trim() || undefined,
          timezone: timezone.trim() || undefined,
        });
      }}
      className="space-y-3"
    >
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Site name"
          className="px-3 py-1.5 text-sm bg-[#1F1F1F] border border-[#2A2A2A] rounded text-[#F5F5F5] focus:outline-none focus:border-[#1E90FF]"
          required
        />
        <input
          value={address}
          onChange={(e) => setAddress(e.target.value)}
          placeholder="Address"
          className="px-3 py-1.5 text-sm bg-[#1F1F1F] border border-[#2A2A2A] rounded text-[#F5F5F5] focus:outline-none focus:border-[#1E90FF]"
        />
        <input
          value={timezone}
          onChange={(e) => setTimezone(e.target.value)}
          placeholder="Asia/Kolkata"
          className="px-3 py-1.5 text-sm bg-[#1F1F1F] border border-[#2A2A2A] rounded text-[#F5F5F5] focus:outline-none focus:border-[#1E90FF]"
          required
        />
      </div>
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={loading}
          className="px-3 py-1.5 bg-[#1E90FF] text-white text-sm rounded hover:bg-[#3BA0FF] disabled:opacity-50"
        >
          {loading ? "Saving..." : mode === "create" ? "Create" : "Save"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="px-3 py-1.5 text-sm text-[#666666] hover:text-[#F5F5F5]"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

function TeamSection({ team, currentUserId, canManage, onMutate }: { team: User[]; currentUserId: string; canManage: boolean; onMutate: () => void }) {
  const [showInvite, setShowInvite] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editRole, setEditRole] = useState("");
  const [resetPasswordId, setResetPasswordId] = useState<string | null>(null);
  const [newPassword, setNewPassword] = useState("");

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: { role?: string; is_active?: boolean } }) => api.updateTeamMember(id, data),
    onSuccess: () => { setEditingId(null); onMutate(); },
  });

  const removeMutation = useMutation({
    mutationFn: (id: string) => api.removeTeamMember(id),
    onSuccess: onMutate,
  });

  const resetPasswordMutation = useMutation({
    mutationFn: ({ id, password }: { id: string; password: string }) => api.resetTeamMemberPassword(id, password),
    onSuccess: () => { setResetPasswordId(null); setNewPassword(""); },
  });

  const inviteMutation = useMutation({
    mutationFn: (data: { username: string; password: string; name: string; role: string }) =>
      api.request<User>("/api/auth/invite", { method: "POST", body: JSON.stringify(data) }),
    onSuccess: () => { setShowInvite(false); onMutate(); },
  });

  return (
    <div className="p-4 bg-[#111111] border border-[#2A2A2A] rounded-lg space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-[#F5F5F5]">Team ({team.length})</h2>
        {canManage && (
          <button
            onClick={() => setShowInvite(true)}
            className="px-3 py-1.5 bg-[#1E90FF] text-white text-sm rounded-md hover:bg-[#3BA0FF] transition-colors"
          >
            + Invite User
          </button>
        )}
      </div>

      {showInvite && canManage && <InviteForm onClose={() => setShowInvite(false)} onInvite={(data) => inviteMutation.mutate(data)} loading={inviteMutation.isPending} />}

      <div className="space-y-2">
        {team.map((member) => (
          <div key={member.id} className="flex items-center justify-between p-2 rounded-md hover:bg-[#1A1A1A]">
            <div className="flex items-center gap-3">
              <span className="text-sm text-[#F5F5F5]">{member.name}</span>
              <span className="text-xs text-[#666666]">@{member.username}</span>
              <span className={`text-xs px-2 py-0.5 rounded ${
                member.role === "owner" ? "bg-[#FBBF24]/20 text-[#FBBF24]" :
                member.role === "admin" ? "bg-[#F97316]/20 text-[#F97316]" :
                member.role === "operator" ? "bg-[#1E90FF]/20 text-[#1E90FF]" :
                "bg-[#666666]/20 text-[#666666]"
              }`}>
                {member.role}
              </span>
              {!member.is_active && <span className="text-xs px-2 py-0.5 rounded bg-[#EF4444]/20 text-[#EF4444]">disabled</span>}
              {member.must_change_password && <span className="text-xs px-2 py-0.5 rounded bg-[#F97316]/20 text-[#F97316]">temp pass</span>}
              {member.id === currentUserId && <span className="text-xs text-[#1E90FF]">(you)</span>}
            </div>

            {canManage && member.id !== currentUserId && member.role !== "owner" && (
              <div className="flex items-center gap-1">
                {editingId === member.id ? (
                  <form onSubmit={(e) => { e.preventDefault(); updateMutation.mutate({ id: member.id, data: { role: editRole } }); }} className="flex gap-1">
                    <select value={editRole} onChange={(e) => setEditRole(e.target.value)} className="px-2 py-1 text-xs bg-[#1F1F1F] border border-[#2A2A2A] rounded text-[#F5F5F5]">
                      <option value="admin">Admin</option>
                      <option value="operator">Operator</option>
                      <option value="viewer">Viewer</option>
                    </select>
                    <button type="submit" className="text-xs px-2 py-1 bg-[#1E90FF] text-white rounded">Save</button>
                    <button type="button" onClick={() => setEditingId(null)} className="text-xs px-1 text-[#666666]">✕</button>
                  </form>
                ) : resetPasswordId === member.id ? (
                  <form onSubmit={(e) => { e.preventDefault(); resetPasswordMutation.mutate({ id: member.id, password: newPassword }); }} className="flex gap-1">
                    <input
                      type="text"
                      placeholder="New password"
                      value={newPassword}
                      onChange={(e) => setNewPassword(e.target.value)}
                      className="px-2 py-1 text-xs bg-[#1F1F1F] border border-[#2A2A2A] rounded text-[#F5F5F5] w-28"
                      required
                      minLength={8}
                    />
                    <button type="submit" className="text-xs px-2 py-1 bg-[#1E90FF] text-white rounded">Set</button>
                    <button type="button" onClick={() => { setResetPasswordId(null); setNewPassword(""); }} className="text-xs px-1 text-[#666666]">✕</button>
                  </form>
                ) : (
                  <>
                    <button onClick={() => { setEditingId(member.id); setEditRole(member.role); }} className="text-xs px-2 py-1 text-[#A3A3A3] hover:text-[#1E90FF] transition-colors">Role</button>
                    <button onClick={() => setResetPasswordId(member.id)} className="text-xs px-2 py-1 text-[#A3A3A3] hover:text-[#FBBF24] transition-colors">Password</button>
                    <button
                      onClick={() => { if (confirm(`Remove @${member.username} from your org?`)) removeMutation.mutate(member.id); }}
                      className="text-xs px-2 py-1 text-[#A3A3A3] hover:text-[#EF4444] transition-colors"
                    >
                      Remove
                    </button>
                  </>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function InviteForm({ onClose, onInvite, loading }: { onClose: () => void; onInvite: (data: { username: string; password: string; name: string; role: string }) => void; loading: boolean }) {
  const [username, setUsername] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("viewer");

  return (
    <div className="p-3 bg-[#1A1A1A] border border-[#2A2A2A] rounded-lg">
      <form
        onSubmit={(e) => { e.preventDefault(); onInvite({ username, password, name, role }); }}
        className="grid grid-cols-1 sm:grid-cols-2 gap-2"
      >
        <input
          placeholder="Username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          className="px-3 py-1.5 text-sm bg-[#1F1F1F] border border-[#2A2A2A] rounded text-[#F5F5F5] placeholder-[#666666] focus:outline-none focus:border-[#1E90FF]"
          required
        />
        <input
          placeholder="Display name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="px-3 py-1.5 text-sm bg-[#1F1F1F] border border-[#2A2A2A] rounded text-[#F5F5F5] placeholder-[#666666] focus:outline-none focus:border-[#1E90FF]"
          required
        />
        <input
          placeholder="One-time password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="px-3 py-1.5 text-sm bg-[#1F1F1F] border border-[#2A2A2A] rounded text-[#F5F5F5] placeholder-[#666666] focus:outline-none focus:border-[#1E90FF]"
          required
          minLength={8}
        />
        <select
          value={role}
          onChange={(e) => setRole(e.target.value)}
          className="px-3 py-1.5 text-sm bg-[#1F1F1F] border border-[#2A2A2A] rounded text-[#F5F5F5]"
        >
          <option value="admin">Admin</option>
          <option value="operator">Operator</option>
          <option value="viewer">Viewer</option>
        </select>
        <div className="col-span-2 flex gap-2">
          <button type="submit" disabled={loading} className="px-3 py-1.5 bg-[#1E90FF] text-white text-sm rounded hover:bg-[#3BA0FF] disabled:opacity-50">
            {loading ? "..." : "Invite"}
          </button>
          <button type="button" onClick={onClose} className="px-3 py-1.5 text-sm text-[#666666] hover:text-[#F5F5F5]">Cancel</button>
          <span className="text-xs text-[#F97316] self-center">User must change password on first login</span>
        </div>
      </form>
    </div>
  );
}

function WhatsAppAlertsSection({ canManage }: { canManage: boolean }) {
  const queryClient = useQueryClient();
  const [showAdd, setShowAdd] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const { data: contacts } = useQuery({
    queryKey: ["settings", "whatsapp-alerts"],
    queryFn: () => api.getWhatsAppAlertContacts(),
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["settings", "whatsapp-alerts"] });

  const addMutation = useMutation({
    mutationFn: (number: string) => api.addWhatsAppAlertContact(number),
    onSuccess: () => { setErrorMsg(null); setShowAdd(false); invalidate(); },
    onError: (e: Error) => setErrorMsg(e.message || "Could not add number."),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: { number?: string; enabled?: boolean } }) =>
      api.updateWhatsAppAlertContact(id, data),
    onSuccess: () => { setErrorMsg(null); setEditingId(null); invalidate(); },
    onError: (e: Error) => setErrorMsg(e.message || "Could not update number."),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.deleteWhatsAppAlertContact(id),
    onSuccess: () => { setErrorMsg(null); invalidate(); },
    onError: (e: Error) => setErrorMsg(e.message || "Could not remove number."),
  });

  const atMax = (contacts?.length ?? 0) >= 4;

  return (
    <div className="p-4 bg-[#111111] border border-[#2A2A2A] rounded-lg space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-[#F5F5F5]">WhatsApp Alerts</h2>
          <p className="text-xs text-[#A3A3A3]">Enabled numbers instantly receive every real-time event alert.</p>
        </div>
        {canManage && (
          <button
            onClick={() => setShowAdd((v) => !v)}
            disabled={atMax}
            className="px-3 py-1.5 bg-[#1E90FF] text-white text-sm rounded-md hover:bg-[#3BA0FF] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {showAdd ? "Close" : "+ Add Number"}
          </button>
        )}
      </div>

      {showAdd && canManage && (
        <WhatsAppContactForm
          onCancel={() => setShowAdd(false)}
          onSave={(number) => addMutation.mutate(number)}
          loading={addMutation.isPending}
        />
      )}

      {errorMsg && (
        <div className="text-xs text-red-400 bg-[#1A1A1A] border border-[#2A2A2A] rounded-md p-2">
          {errorMsg}
        </div>
      )}

      <div className="space-y-2">
        {!contacts || contacts.length === 0 ? (
          <div className="text-sm text-[#A3A3A3] border border-dashed border-[#2A2A2A] rounded-lg p-4">
            No WhatsApp numbers added yet.
          </div>
        ) : (
          contacts.map((contact: WhatsAppAlertContact) => (
            <div key={contact.id} className="p-3 rounded-lg border border-[#2A2A2A] bg-[#1A1A1A]">
              {editingId === contact.id ? (
                <WhatsAppContactForm
                  initialNumber={contact.number}
                  onCancel={() => setEditingId(null)}
                  onSave={(number) => updateMutation.mutate({ id: contact.id, data: { number } })}
                  loading={updateMutation.isPending}
                />
              ) : (
                <div className="flex items-center justify-between gap-4">
                  <span className="text-sm font-mono text-[#F5F5F5]">{contact.number}</span>
                  <div className="flex items-center gap-3">
                    {canManage && (
                      <button
                        onClick={() => updateMutation.mutate({ id: contact.id, data: { enabled: !contact.enabled } })}
                        className={contact.enabled ? "text-green-400" : "text-[#666666]"}
                        title={contact.enabled ? "Disable instant alerts" : "Enable instant alerts"}
                      >
                        {contact.enabled ? <ToggleRight size={20} /> : <ToggleLeft size={20} />}
                      </button>
                    )}
                    {canManage && (
                      <>
                        <button
                          onClick={() => setEditingId(contact.id)}
                          className="text-xs px-2 py-1 text-[#A3A3A3] hover:text-[#1E90FF] transition-colors"
                        >
                          Edit
                        </button>
                        <button
                          onClick={() => { if (window.confirm(`Remove ${contact.number} from instant alerts?`)) deleteMutation.mutate(contact.id); }}
                          className="text-xs px-2 py-1 text-[#A3A3A3] hover:text-[#EF4444] transition-colors"
                        >
                          Delete
                        </button>
                      </>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function WhatsAppContactForm({
  initialNumber,
  onSave,
  onCancel,
  loading,
}: {
  initialNumber?: string;
  onSave: (number: string) => void;
  onCancel: () => void;
  loading: boolean;
}) {
  const [number, setNumber] = useState(initialNumber ?? "");

  return (
    <form
      onSubmit={(e) => { e.preventDefault(); onSave(number.trim()); }}
      className="flex gap-2"
    >
      <input
        value={number}
        onChange={(e) => setNumber(e.target.value)}
        placeholder="+911234567890"
        pattern="^\+\d{8,15}$"
        title="Format: + followed by country code and number, e.g. +911234567890"
        className="flex-1 px-3 py-1.5 text-sm bg-[#1F1F1F] border border-[#2A2A2A] rounded text-[#F5F5F5] focus:outline-none focus:border-[#1E90FF]"
        required
      />
      <button type="submit" disabled={loading} className="px-3 py-1.5 bg-[#1E90FF] text-white text-sm rounded hover:bg-[#3BA0FF] disabled:opacity-50">
        {loading ? "Saving..." : "Save"}
      </button>
      <button type="button" onClick={onCancel} className="px-3 py-1.5 text-sm text-[#666666] hover:text-[#F5F5F5]">
        Cancel
      </button>
    </form>
  );
}
