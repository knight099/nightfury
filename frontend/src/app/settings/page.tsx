"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAuthStore } from "@/lib/store";
import type { User } from "@/types";

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const { user } = useAuthStore();
  const isOwner = user?.role === "owner";
  const isSuperAdmin = user?.role === "super_admin";
  const canViewTeam = !!user?.org_id;

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

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-bold text-[#F5F5F5]">Settings</h1>

      {isSuperAdmin && (
        <div className="p-4 bg-[#111111] border border-[#2A2A2A] rounded-lg">
          <p className="text-sm text-[#F5F5F5] mb-1">You are signed in as <span className="text-[#EF4444]">super_admin</span> (no org).</p>
          <p className="text-xs text-[#A3A3A3]">Use the <a href="/admin" className="text-[#1E90FF] hover:underline">Admin Panel</a> to manage all organizations and users across the platform.</p>
        </div>
      )}

      {org && <OrgSection org={org} canEdit={isOwner} />}

      {canViewTeam && team && (
        <TeamSection
          team={team}
          currentUserId={user?.id || ""}
          canManage={isOwner}
          onMutate={() => queryClient.invalidateQueries({ queryKey: ["settings", "team"] })}
        />
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
