"use client";

import { use, useState } from "react";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Skeleton } from "@/components/ui/Skeleton";
import { useAuthStore } from "@/lib/store";

export default function AdminOrgDetailPageV2({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { user } = useAuthStore();
  const queryClient = useQueryClient();
  const [expandedUserId, setExpandedUserId] = useState<string | null>(null);

  const isSuperAdmin = user?.role === "super_admin";

  const { data: orgsHealth, isLoading: healthLoading, isError: healthError } = useQuery({
    queryKey: ["admin", "orgs-health", "include-deleted"],
    queryFn: () => api.adminGetOrgsHealth(true),
    enabled: isSuperAdmin,
  });
  const org = orgsHealth?.find((o) => o.org_id === id);

  const { data: orgUsers, isLoading: usersLoading, isError: usersError, error: usersErrorObj } = useQuery({
    queryKey: ["admin", "users", id],
    queryFn: () => api.adminGetUsers({ org_id: id }),
    enabled: isSuperAdmin,
  });

  const { data: sessions, isLoading: sessionsLoading, isError: sessionsError } = useQuery({
    queryKey: ["admin", "sessions", expandedUserId],
    queryFn: () => api.adminGetUserSessions(expandedUserId!),
    enabled: isSuperAdmin && !!expandedUserId,
  });

  const forceLogout = useMutation({
    mutationFn: (userId: string) => api.adminForceLogout(userId),
    onSuccess: (_data, userId) => {
      if (userId === expandedUserId) {
        queryClient.invalidateQueries({ queryKey: ["admin", "sessions", userId] });
      }
    },
  });

  const deleteOrg = useMutation({
    mutationFn: () => api.adminDeleteOrg(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin", "orgs-health"] }),
  });

  const restoreOrg = useMutation({
    mutationFn: () => api.adminRestoreOrg(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin", "orgs-health"] }),
  });

  const handleDeleteOrg = () => {
    const confirmed = window.confirm(
      `Delete ${org?.name ?? "this org"}? This will also disable every user, camera, site, and alert rule in this org. This can be undone via Restore.`
    );
    if (confirmed) {
      deleteOrg.mutate();
    }
  };

  if (!isSuperAdmin) {
    return (
      <div className="max-w-[1040px] mx-auto px-12 py-12 text-sm text-[oklch(55%_0.01_265)]">
        Not authorized.
      </div>
    );
  }

  return (
    <div className="max-w-[1040px] mx-auto px-12 pt-12 pb-20">
      <Link href="/app/admin" className="text-[13px] text-[oklch(62%_0.01_265)] mb-4 inline-block">
        ← Admin
      </Link>

      {healthLoading ? (
        <Skeleton className="h-24 w-full mb-8" />
      ) : healthError ? (
        <div className="mb-8 text-sm text-[oklch(70.4%_0.191_22.216)]">Couldn&apos;t load org health.</div>
      ) : org ? (
        <div className="mb-8">
          <div className="flex items-center gap-2 mb-1">
            <div className="text-[28px] font-bold tracking-tight">{org.name}</div>
            {org.deleted_at && (
              <div className="text-[11px] font-semibold px-2 py-1 rounded-full bg-[oklch(70.4%_0.191_22.216_/_0.16)] text-[oklch(70.4%_0.191_22.216)]">
                Deleted
              </div>
            )}
          </div>
          {org.deleted_at && (
            <div className="text-[12px] text-[oklch(58%_0.01_265)] mb-1">
              Deleted at {new Date(org.deleted_at).toLocaleString()}
            </div>
          )}
          <div className="text-sm text-[oklch(58%_0.01_265)]">
            {org.camera_count} cameras ({org.cameras_online} online) · {org.events_last_24h} events (24h) ·{" "}
            {org.events_last_7d} events (7d)
          </div>
        </div>
      ) : (
        <div className="mb-8 text-sm text-[oklch(55%_0.01_265)]">Org not found.</div>
      )}

      <div className="flex gap-2 mb-2">
        <button
          onClick={handleDeleteOrg}
          disabled={deleteOrg.isPending}
          className="text-sm font-semibold px-4 py-2 rounded-lg text-[oklch(70.4%_0.191_22.216)] border border-[oklch(70.4%_0.191_22.216)] disabled:opacity-50"
        >
          Delete org
        </button>
        <button
          onClick={() => restoreOrg.mutate()}
          disabled={restoreOrg.isPending}
          className="text-sm font-semibold px-4 py-2 rounded-lg text-[oklch(72%_0.01_265)] border border-[oklch(22%_0.015_265)] disabled:opacity-50"
        >
          Restore org
        </button>
      </div>
      {deleteOrg.isError && (
        <div className="mb-2 text-sm text-[oklch(70.4%_0.191_22.216)]">
          Delete failed: {deleteOrg.error instanceof Error ? deleteOrg.error.message : "unknown error"}. Try again.
        </div>
      )}
      {restoreOrg.isError && (
        <div className="mb-2 text-sm text-[oklch(70.4%_0.191_22.216)]">
          Restore failed: {restoreOrg.error instanceof Error ? restoreOrg.error.message : "unknown error"}. Try again.
        </div>
      )}
      <div className="mb-6" />

      <div className="text-base font-bold mb-3">Team</div>
      {usersLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : usersError ? (
        <div className="text-sm text-[oklch(70.4%_0.191_22.216)]">
          {usersErrorObj instanceof Error ? usersErrorObj.message : "Could not load team."}
        </div>
      ) : (orgUsers ?? []).length > 0 ? (
        <div className="flex flex-col gap-2">
          {orgUsers!.map((u) => (
            <div key={u.id} className="bg-[oklch(13%_0.015_265)] border border-[oklch(22%_0.015_265)] rounded-lg px-4 py-3">
              <div className="flex items-center justify-between text-sm">
                <div>
                  {u.username} · {u.role}
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => setExpandedUserId(expandedUserId === u.id ? null : u.id)}
                    className="text-[12px] text-[oklch(72%_0.01_265)]"
                  >
                    Sessions
                  </button>
                  <button
                    onClick={() => forceLogout.mutate(u.id)}
                    disabled={forceLogout.isPending && forceLogout.variables === u.id}
                    className="text-[12px] text-[oklch(70.4%_0.191_22.216)] disabled:opacity-50"
                  >
                    Force logout
                  </button>
                  {/* Project F (separate plan) adds a "Login as" button here */}
                </div>
              </div>
              {forceLogout.isError && forceLogout.variables === u.id && (
                <div className="mt-2 text-[11px] text-[oklch(70.4%_0.191_22.216)]">
                  Force logout failed: {forceLogout.error instanceof Error ? forceLogout.error.message : "unknown error"}. Try again.
                </div>
              )}
              {expandedUserId === u.id && (
                <div className="mt-2 pt-2 border-t border-[oklch(22%_0.015_265)] text-[11px] text-[oklch(58%_0.01_265)]">
                  {sessionsLoading
                    ? "Loading sessions..."
                    : sessionsError
                      ? "Could not load sessions."
                      : JSON.stringify(sessions)}
                </div>
              )}
            </div>
          ))}
        </div>
      ) : (
        <div className="text-sm text-[oklch(55%_0.01_265)]">No team members yet.</div>
      )}
    </div>
  );
}
