"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useAuthStore } from "@/lib/store";
import type { User } from "@/types";
import { Skeleton } from "@/components/ui/Skeleton";

interface Org {
  id: string;
  name: string;
  slug: string;
  plan: string;
  created_at: string;
  deleted_at: string | null;
}

export default function AdminPage() {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<"users" | "orgs">("users");
  const [showDeleted, setShowDeleted] = useState(false);

  const { data: orgs } = useQuery({
    queryKey: ["admin", "orgs", showDeleted],
    queryFn: () => api.adminGetOrgs(showDeleted),
  });

  const { data: users, isLoading: usersLoading } = useQuery({
    queryKey: ["admin", "users", showDeleted],
    queryFn: () => api.adminGetUsers({ include_deleted: showDeleted }),
  });

  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: ["admin"] });
  };

  return (
    <div>
      <h1 className="text-2xl font-bold text-[#F5F5F5] mb-1">Admin Panel</h1>
      <p className="text-xs text-[#666666] mb-6">God mode — full control over all orgs, users, passwords, sessions</p>

      <div className="flex items-center justify-between mb-6">
        <div className="flex gap-2">
          <button
            onClick={() => setTab("users")}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              tab === "users"
                ? "bg-[#1E90FF] text-white"
                : "bg-[#1A1A1A] text-[#A3A3A3] border border-[#2A2A2A] hover:text-[#F5F5F5]"
            }`}
          >
            Users ({users?.length || 0})
          </button>
          <button
            onClick={() => setTab("orgs")}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              tab === "orgs"
                ? "bg-[#1E90FF] text-white"
                : "bg-[#1A1A1A] text-[#A3A3A3] border border-[#2A2A2A] hover:text-[#F5F5F5]"
            }`}
          >
            Organizations ({orgs?.length || 0})
          </button>
        </div>
        <label className="flex items-center gap-2 text-xs text-[#A3A3A3]">
          <input
            type="checkbox"
            checked={showDeleted}
            onChange={(e) => setShowDeleted(e.target.checked)}
            className="rounded"
          />
          Show deleted
        </label>
      </div>

      {tab === "users" && (
        <UsersTab users={users || []} orgs={orgs || []} loading={usersLoading} onMutate={invalidateAll} />
      )}

      {tab === "orgs" && (
        <OrgsTab orgs={orgs || []} onMutate={invalidateAll} />
      )}
    </div>
  );
}

function UsersTab({ users, orgs, loading, onMutate }: { users: User[]; orgs: Org[]; loading: boolean; onMutate: () => void }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const startImpersonation = useAuthStore((s) => s.startImpersonation);
  const [showCreate, setShowCreate] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [openSessionsId, setOpenSessionsId] = useState<string | null>(null);
  const [changePasswordId, setChangePasswordId] = useState<string | null>(null);
  const [newPassword, setNewPassword] = useState("");
  const [editForm, setEditForm] = useState({ username: "", name: "", role: "", org_id: "", is_active: true });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.adminDeleteUser(id),
    onSuccess: onMutate,
  });

  const restoreMutation = useMutation({
    mutationFn: (id: string) => api.adminRestoreUser(id),
    onSuccess: onMutate,
  });

  const impersonateMutation = useMutation({
    mutationFn: (id: string) => api.adminImpersonateUser(id),
    onSuccess: ({ token, user: target }) => {
      // Swap identity, then drop every cached query — anything already
      // fetched belongs to the super admin and would leak across the switch.
      startImpersonation(token, target);
      api.setToken(token);
      queryClient.clear();
      router.push("/dashboard");
    },
  });

  const forceLogoutMutation = useMutation({
    mutationFn: (id: string) => api.adminForceLogout(id),
  });

  const changePasswordMutation = useMutation({
    mutationFn: ({ id, password }: { id: string; password: string }) => api.adminChangePassword(id, password),
    onSuccess: () => { setChangePasswordId(null); setNewPassword(""); },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: { username?: string; name?: string; role?: string; is_active?: boolean; org_id?: string } }) =>
      api.adminUpdateUser(id, data),
    onSuccess: () => { setEditingId(null); onMutate(); },
  });

  const startEdit = (u: User) => {
    setEditingId(u.id);
    setEditForm({ username: u.username, name: u.name, role: u.role, org_id: u.org_id || "", is_active: u.is_active });
  };

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-lg font-semibold text-[#F5F5F5]">All Users</h2>
        <button
          onClick={() => setShowCreate(true)}
          className="px-3 py-1.5 bg-[#1E90FF] text-white text-sm rounded-md hover:bg-[#3BA0FF] transition-colors"
        >
          + Create User
        </button>
      </div>

      {loading ? (
        <div className="space-y-2">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-12 rounded-md" />)}</div>
      ) : (
        <div className="space-y-2">
          {users.map((u) => (
            <div key={u.id} className="p-3 bg-[#111111] border border-[#2A2A2A] rounded-lg">
              {editingId === u.id ? (
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    updateMutation.mutate({ id: u.id, data: editForm });
                  }}
                  className="space-y-2"
                >
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    <input
                      type="text"
                      value={editForm.username}
                      onChange={(e) => setEditForm({ ...editForm, username: e.target.value })}
                      placeholder="Username"
                      className="px-2 py-1.5 text-sm bg-[#1F1F1F] border border-[#2A2A2A] rounded text-[#F5F5F5]"
                      required
                    />
                    <input
                      type="text"
                      value={editForm.name}
                      onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                      placeholder="Display name"
                      className="px-2 py-1.5 text-sm bg-[#1F1F1F] border border-[#2A2A2A] rounded text-[#F5F5F5]"
                      required
                    />
                    <select
                      value={editForm.role}
                      onChange={(e) => setEditForm({ ...editForm, role: e.target.value })}
                      className="px-2 py-1.5 text-sm bg-[#1F1F1F] border border-[#2A2A2A] rounded text-[#F5F5F5]"
                    >
                      <option value="viewer">Viewer</option>
                      <option value="operator">Operator</option>
                      <option value="admin">Admin</option>
                      <option value="owner">Owner</option>
                    </select>
                    <select
                      value={editForm.org_id}
                      onChange={(e) => setEditForm({ ...editForm, org_id: e.target.value })}
                      className="px-2 py-1.5 text-sm bg-[#1F1F1F] border border-[#2A2A2A] rounded text-[#F5F5F5]"
                    >
                      <option value="">No org (super admin)</option>
                      {orgs.map((o) => (
                        <option key={o.id} value={o.id}>{o.name}</option>
                      ))}
                    </select>
                  </div>
                  <div className="flex items-center gap-3">
                    <label className="flex items-center gap-2 text-xs text-[#A3A3A3]">
                      <input
                        type="checkbox"
                        checked={editForm.is_active}
                        onChange={(e) => setEditForm({ ...editForm, is_active: e.target.checked })}
                        className="rounded"
                      />
                      Active
                    </label>
                    <button type="submit" className="text-xs px-3 py-1 bg-[#1E90FF] text-white rounded">
                      Save
                    </button>
                    <button type="button" onClick={() => setEditingId(null)} className="text-xs px-3 py-1 text-[#666666] hover:text-[#F5F5F5]">
                      Cancel
                    </button>
                  </div>
                </form>
              ) : (
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3 flex-wrap">
                    <span className="text-sm font-medium text-[#F5F5F5]">{u.name}</span>
                    <span className="text-xs text-[#666666]">@{u.username}</span>
                    <span className={`text-xs px-2 py-0.5 rounded ${
                      u.role === "super_admin" ? "bg-[#EF4444]/20 text-[#EF4444]" :
                      u.role === "owner" ? "bg-[#FBBF24]/20 text-[#FBBF24]" :
                      u.role === "admin" ? "bg-[#F97316]/20 text-[#F97316]" :
                      "bg-[#1E90FF]/20 text-[#1E90FF]"
                    }`}>
                      {u.role}
                    </span>
                    {u.org_id && (
                      <span className="text-xs text-[#666666]">
                        org: {orgs.find(o => o.id === u.org_id)?.name || u.org_id.slice(0, 8)}
                      </span>
                    )}
                    {!u.is_active && (
                      <span className="text-xs px-2 py-0.5 rounded bg-[#666666]/20 text-[#666666]">disabled</span>
                    )}
                    {u.must_change_password && (
                      <span className="text-xs px-2 py-0.5 rounded bg-[#F97316]/20 text-[#F97316]">temp pass</span>
                    )}
                    {u.deleted_at && (
                      <span className="text-xs px-2 py-0.5 rounded bg-[#EF4444]/20 text-[#EF4444]">deleted</span>
                    )}
                  </div>
                  <div className="flex items-center gap-1 flex-shrink-0">
                    {u.deleted_at ? (
                      <button
                        onClick={() => restoreMutation.mutate(u.id)}
                        className="text-xs px-2 py-1 text-[#A3A3A3] hover:text-[#4ADE80] transition-colors"
                      >
                        Restore
                      </button>
                    ) : changePasswordId === u.id ? (
                      <form
                        onSubmit={(e) => {
                          e.preventDefault();
                          changePasswordMutation.mutate({ id: u.id, password: newPassword });
                        }}
                        className="flex gap-1"
                      >
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
                        <button type="button" onClick={() => { setChangePasswordId(null); setNewPassword(""); }} className="text-xs px-1 text-[#666666]">✕</button>
                      </form>
                    ) : (
                      <>
                        <button onClick={() => startEdit(u)} className="text-xs px-2 py-1 text-[#A3A3A3] hover:text-[#1E90FF] transition-colors">
                          Edit
                        </button>
                        <button onClick={() => setChangePasswordId(u.id)} className="text-xs px-2 py-1 text-[#A3A3A3] hover:text-[#1E90FF] transition-colors">
                          Password
                        </button>
                        <button
                          onClick={() => setOpenSessionsId(openSessionsId === u.id ? null : u.id)}
                          className="text-xs px-2 py-1 text-[#A3A3A3] hover:text-[#1E90FF] transition-colors"
                        >
                          Sessions
                        </button>
                        <button onClick={() => forceLogoutMutation.mutate(u.id)} className="text-xs px-2 py-1 text-[#A3A3A3] hover:text-[#FBBF24] transition-colors">
                          Kick
                        </button>
                        {u.role !== "super_admin" && !u.deleted_at && (
                          <button
                            onClick={() => {
                              if (confirm(`Log in as @${u.username}? You will see exactly what they see until you exit.`)) {
                                impersonateMutation.mutate(u.id);
                              }
                            }}
                            disabled={impersonateMutation.isPending}
                            className="text-xs px-2 py-1 text-[#1E90FF] hover:text-[#3BA0FF] transition-colors disabled:opacity-40"
                          >
                            Login as
                          </button>
                        )}
                        {u.role !== "super_admin" && (
                          <button
                            onClick={() => { if (confirm(`Delete @${u.username}?`)) deleteMutation.mutate(u.id); }}
                            className="text-xs px-2 py-1 text-[#A3A3A3] hover:text-[#EF4444] transition-colors"
                          >
                            Delete
                          </button>
                        )}
                      </>
                    )}
                  </div>
                </div>
              )}
              {openSessionsId === u.id && editingId !== u.id && (
                <SessionsPanel userId={u.id} />
              )}
            </div>
          ))}
        </div>
      )}

      {showCreate && (
        <CreateUserModal
          orgs={orgs}
          onClose={() => setShowCreate(false)}
          onCreated={() => { setShowCreate(false); onMutate(); }}
        />
      )}
    </div>
  );
}

function SessionsPanel({ userId }: { userId: string }) {
  const { data, isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: ["admin", "users", userId, "sessions"],
    queryFn: () => api.adminGetUserSessions(userId),
    enabled: !!userId,
  });

  const sessions = data?.sessions || [];

  const fmt = (v: unknown): string => {
    if (v === null || v === undefined || v === "") return "—";
    if (typeof v === "string") return v;
    if (typeof v === "number") return String(v);
    return "—";
  };

  const fmtTime = (v: unknown): string => {
    const s = fmt(v);
    if (s === "—") return s;
    const d = new Date(s);
    if (isNaN(d.getTime())) return s;
    return d.toLocaleString();
  };

  const truncate = (v: unknown, n: number): string => {
    const s = fmt(v);
    if (s === "—") return s;
    return s.length > n ? s.slice(0, n) + "…" : s;
  };

  const shortId = (v: unknown): string => {
    const s = fmt(v);
    if (s === "—") return s;
    return s.slice(0, 8);
  };

  return (
    <div className="mt-2 bg-[#0D0D0D] border border-[#2A2A2A] rounded p-2">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs text-[#666666] uppercase tracking-wide">Active Sessions</span>
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className="text-xs px-2 py-0.5 text-[#A3A3A3] hover:text-[#1E90FF] transition-colors disabled:opacity-50"
        >
          {isFetching ? "..." : "Refresh"}
        </button>
      </div>
      {isLoading ? (
        <div className="space-y-2">{Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-8 rounded-md" />)}</div>
      ) : isError ? (
        <p className="text-xs text-[#EF4444]">
          {error instanceof Error ? error.message : "Failed to load sessions"}
        </p>
      ) : sessions.length === 0 ? (
        <p className="text-xs text-[#666666]">No active sessions.</p>
      ) : (
        <div className="space-y-1">
          <div className="hidden sm:grid grid-cols-[80px_120px_1fr_160px] gap-2 text-[10px] text-[#666666] uppercase tracking-wide px-1">
            <span>Session</span>
            <span>IP</span>
            <span>User Agent</span>
            <span>Last Active</span>
          </div>
          {sessions.map((s, i) => {
            const sid = s["session_id"] ?? s["id"];
            const lastActive = s["last_active_at"] ?? s["created_at"];
            return (
              <div
                key={(typeof sid === "string" ? sid : "") + i}
                className="grid grid-cols-1 sm:grid-cols-[80px_120px_1fr_160px] gap-2 text-xs text-[#A3A3A3] px-1 py-1 border-t border-[#1A1A1A] sm:border-t-0"
              >
                <span className="font-mono text-[#F5F5F5]">{shortId(sid)}</span>
                <span>{fmt(s["ip"])}</span>
                <span title={typeof s["user_agent"] === "string" ? (s["user_agent"] as string) : undefined}>
                  {truncate(s["user_agent"], 40)}
                </span>
                <span>{fmtTime(lastActive)}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function OrgsTab({ orgs, onMutate }: { orgs: Org[]; onMutate: () => void }) {
  const [showCreate, setShowCreate] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [editPlan, setEditPlan] = useState("");

  const createMutation = useMutation({
    mutationFn: (data: { name: string; plan?: string }) => api.adminCreateOrg(data),
    onSuccess: () => { setShowCreate(false); onMutate(); },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: { name?: string; plan?: string } }) => api.adminUpdateOrg(id, data),
    onSuccess: () => { setEditingId(null); onMutate(); },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.adminDeleteOrg(id),
    onSuccess: onMutate,
  });

  const restoreMutation = useMutation({
    mutationFn: (id: string) => api.adminRestoreOrg(id),
    onSuccess: onMutate,
  });

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-lg font-semibold text-[#F5F5F5]">All Organizations</h2>
        <button
          onClick={() => setShowCreate(true)}
          className="px-3 py-1.5 bg-[#1E90FF] text-white text-sm rounded-md hover:bg-[#3BA0FF] transition-colors"
        >
          + Create Org
        </button>
      </div>

      {showCreate && (
        <div className="mb-4 p-3 bg-[#111111] border border-[#2A2A2A] rounded-lg">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const form = e.target as HTMLFormElement;
              const name = (form.elements.namedItem("orgName") as HTMLInputElement).value;
              const plan = (form.elements.namedItem("orgPlan") as HTMLSelectElement).value;
              createMutation.mutate({ name, plan });
            }}
            className="flex items-center gap-2"
          >
            <input
              name="orgName"
              type="text"
              placeholder="Organization name"
              className="flex-1 px-3 py-1.5 text-sm bg-[#1F1F1F] border border-[#2A2A2A] rounded text-[#F5F5F5] placeholder-[#666666] focus:outline-none focus:border-[#1E90FF]"
              required
            />
            <select
              name="orgPlan"
              defaultValue="free"
              className="px-3 py-1.5 text-sm bg-[#1F1F1F] border border-[#2A2A2A] rounded text-[#F5F5F5]"
            >
              <option value="free">Free</option>
              <option value="starter">Starter</option>
              <option value="pro">Pro</option>
              <option value="enterprise">Enterprise</option>
            </select>
            <button type="submit" disabled={createMutation.isPending} className="px-3 py-1.5 bg-[#1E90FF] text-white text-sm rounded hover:bg-[#3BA0FF] disabled:opacity-50">
              {createMutation.isPending ? "..." : "Create"}
            </button>
            <button type="button" onClick={() => setShowCreate(false)} className="px-3 py-1.5 text-sm text-[#666666] hover:text-[#F5F5F5]">
              Cancel
            </button>
          </form>
        </div>
      )}

      <div className="space-y-2">
        {orgs.map((org) => (
          <div key={org.id} className="p-3 bg-[#111111] border border-[#2A2A2A] rounded-lg">
            {editingId === org.id ? (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  updateMutation.mutate({ id: org.id, data: { name: editName, plan: editPlan } });
                }}
                className="flex items-center gap-2"
              >
                <input
                  type="text"
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  className="flex-1 px-2 py-1.5 text-sm bg-[#1F1F1F] border border-[#2A2A2A] rounded text-[#F5F5F5]"
                  required
                />
                <select
                  value={editPlan}
                  onChange={(e) => setEditPlan(e.target.value)}
                  className="px-2 py-1.5 text-sm bg-[#1F1F1F] border border-[#2A2A2A] rounded text-[#F5F5F5]"
                >
                  <option value="free">Free</option>
                  <option value="starter">Starter</option>
                  <option value="pro">Pro</option>
                  <option value="enterprise">Enterprise</option>
                </select>
                <button type="submit" className="text-xs px-3 py-1 bg-[#1E90FF] text-white rounded">Save</button>
                <button type="button" onClick={() => setEditingId(null)} className="text-xs px-3 py-1 text-[#666666] hover:text-[#F5F5F5]">Cancel</button>
              </form>
            ) : (
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <span className="text-sm font-medium text-[#F5F5F5]">{org.name}</span>
                  <span className="text-xs text-[#666666]">{org.slug}</span>
                  <span className="text-xs px-2 py-0.5 rounded bg-[#1E90FF]/20 text-[#1E90FF]">{org.plan || "free"}</span>
                  <span className="text-xs text-[#666666]">{new Date(org.created_at).toLocaleDateString()}</span>
                  {org.deleted_at && (
                    <span className="text-xs px-2 py-0.5 rounded bg-[#EF4444]/20 text-[#EF4444]">deleted</span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  {org.deleted_at ? (
                    <button
                      onClick={() => restoreMutation.mutate(org.id)}
                      className="text-xs px-2 py-1 text-[#A3A3A3] hover:text-[#4ADE80] transition-colors"
                    >
                      Restore
                    </button>
                  ) : (
                    <>
                      <button
                        onClick={() => { setEditingId(org.id); setEditName(org.name); setEditPlan(org.plan || "free"); }}
                        className="text-xs px-2 py-1 text-[#A3A3A3] hover:text-[#1E90FF] transition-colors"
                      >
                        Edit
                      </button>
                      <button
                        onClick={() => { if (confirm(`Delete "${org.name}" and ALL its users/cameras/data? This can be restored later from Admin → Show deleted.`)) deleteMutation.mutate(org.id); }}
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
        ))}
        {orgs.length === 0 && <p className="text-sm text-[#666666]">No organizations yet.</p>}
      </div>
    </div>
  );
}

function CreateUserModal({
  orgs,
  onClose,
  onCreated,
}: {
  orgs: Org[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [orgId, setOrgId] = useState(orgs[0]?.id || "");
  const [role, setRole] = useState("viewer");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await api.adminCreateUser({
        username,
        password,
        name,
        org_id: orgId,
        role,
        must_change_password: true,
      });
      onCreated();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to create user");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="w-full max-w-md p-6 bg-[#111111] border border-[#2A2A2A] rounded-lg">
        <h3 className="text-lg font-semibold text-[#F5F5F5] mb-4">Create User</h3>
        <form onSubmit={handleSubmit} className="space-y-3">
          <input
            type="text"
            placeholder="Username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="w-full px-3 py-2 bg-[#1F1F1F] border border-[#2A2A2A] rounded-md text-sm text-[#F5F5F5] placeholder-[#666666] focus:outline-none focus:border-[#1E90FF]"
            required
          />
          <input
            type="text"
            placeholder="Display name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full px-3 py-2 bg-[#1F1F1F] border border-[#2A2A2A] rounded-md text-sm text-[#F5F5F5] placeholder-[#666666] focus:outline-none focus:border-[#1E90FF]"
            required
          />
          <input
            type="text"
            placeholder="One-time password (user must change on login)"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full px-3 py-2 bg-[#1F1F1F] border border-[#2A2A2A] rounded-md text-sm text-[#F5F5F5] placeholder-[#666666] focus:outline-none focus:border-[#1E90FF]"
            required
            minLength={8}
          />
          <select
            value={orgId}
            onChange={(e) => setOrgId(e.target.value)}
            className="w-full px-3 py-2 bg-[#1F1F1F] border border-[#2A2A2A] rounded-md text-sm text-[#F5F5F5] focus:outline-none focus:border-[#1E90FF]"
            required
          >
            <option value="" disabled>Select organization</option>
            {orgs.map((o) => (
              <option key={o.id} value={o.id}>{o.name}</option>
            ))}
          </select>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value)}
            className="w-full px-3 py-2 bg-[#1F1F1F] border border-[#2A2A2A] rounded-md text-sm text-[#F5F5F5] focus:outline-none focus:border-[#1E90FF]"
          >
            <option value="viewer">Viewer</option>
            <option value="operator">Operator</option>
            <option value="admin">Admin</option>
            <option value="owner">Owner</option>
          </select>

          <p className="text-xs text-[#F97316]">User will be forced to change password on first login.</p>

          {error && <p className="text-sm text-red-400">{error}</p>}

          <div className="flex gap-2 pt-2">
            <button
              type="submit"
              disabled={loading}
              className="flex-1 py-2 bg-[#1E90FF] text-white rounded-md text-sm font-medium hover:bg-[#3BA0FF] disabled:opacity-50 transition-colors"
            >
              {loading ? "..." : "Create User"}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 bg-[#1A1A1A] text-[#A3A3A3] border border-[#2A2A2A] rounded-md text-sm hover:text-[#F5F5F5] transition-colors"
            >
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
