"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAuthStore } from "@/lib/store";
import { StatusDot } from "@/components/shared/status-dot";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  Page,
  PageHeader,
  Card,
  Btn,
  EmptyState,
  ErrorBox,
  Pill,
  inputClass,
} from "@/components/v2/ui";
import type { Camera, Site } from "@/types";

/**
 * Sites (V2).
 *
 * Sites are a prerequisite for most of the rest of V2, not a settings detail:
 * Fleet, the video wall, and camera onboarding all start by asking for a site
 * and dead-end without one. In V1 this lived inside the (762-line) settings
 * page; here it gets its own route so a new org can actually get started
 * without leaving the V2 shell.
 */
export default function SitesPageV2() {
  const queryClient = useQueryClient();
  const { user } = useAuthStore();
  const isSuperAdmin = user?.role === "super_admin";
  const canManage = isSuperAdmin || user?.role === "owner" || user?.role === "admin";

  const [showDeleted, setShowDeleted] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [editingSiteId, setEditingSiteId] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const {
    data: sites,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ["sites", { showDeleted }],
    queryFn: () => api.getSites(showDeleted ? { include_deleted: true } : undefined),
  });

  const { data: cameras } = useQuery({
    queryKey: ["cameras"],
    queryFn: () => api.getCameras(),
  });

  // Every mutation invalidates `sites` broadly — Fleet, the wall, setup and
  // camera onboarding all read the same key, and a site created here must
  // show up there without a reload.
  const invalidate = () => {
    setErrorMsg(null);
    queryClient.invalidateQueries({ queryKey: ["sites"] });
    queryClient.invalidateQueries({ queryKey: ["cameras"] });
  };

  const createMutation = useMutation({
    mutationFn: (data: { name: string; address?: string; timezone?: string }) =>
      api.createSite(data),
    onSuccess: () => {
      setShowCreate(false);
      invalidate();
    },
    onError: (e: Error) => setErrorMsg(e.message || "Could not create site."),
  });

  const updateMutation = useMutation({
    mutationFn: ({
      id,
      data,
    }: {
      id: string;
      data: { name?: string; address?: string; timezone?: string };
    }) => api.updateSite(id, data),
    onSuccess: () => {
      setEditingSiteId(null);
      invalidate();
    },
    onError: (e: Error) => setErrorMsg(e.message || "Could not update site."),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.deleteSite(id),
    onSuccess: invalidate,
    onError: (e: Error) => setErrorMsg(e.message || "Could not delete site."),
  });

  const restoreMutation = useMutation({
    mutationFn: (id: string) => api.restoreSite(id),
    onSuccess: invalidate,
    onError: (e: Error) => setErrorMsg(e.message || "Could not restore site."),
  });

  return (
    <Page>
      <PageHeader
        title="Sites"
        subtitle={
          canManage
            ? "Locations like Home, Office, or Warehouse. Cameras are grouped by site, and Fleet, the video wall, and camera setup all work one site at a time."
            : "Locations your cameras are grouped by."
        }
        action={
          canManage ? (
            <Btn
              variant="primary"
              onClick={() => setShowCreate((v) => !v)}
              className="shrink-0"
            >
              {showCreate ? "Close" : "+ New site"}
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

      {showCreate && canManage && (
        <Card className="mb-4">
          <div className="text-[15px] font-semibold mb-3">New site</div>
          <SiteEditor
            mode="create"
            onCancel={() => setShowCreate(false)}
            onSave={(data) => createMutation.mutate(data)}
            loading={createMutation.isPending}
          />
        </Card>
      )}

      {errorMsg && (
        <div className="mb-4">
          <ErrorBox message={errorMsg} />
        </div>
      )}

      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-24 rounded-[14px]" />
          ))}
        </div>
      ) : isError ? (
        <ErrorBox message={`Failed to load sites: ${(error as Error).message}`} />
      ) : !sites?.length ? (
        <EmptyState
          title={canManage ? "No sites yet" : "No sites yet"}
          hint={
            canManage
              ? "Add one so cameras can be organised by location — Fleet, the video wall, and camera setup all need a site to work with."
              : "Ask an admin to add one before cameras can be organised by location."
          }
        />
      ) : (
        <div className="space-y-2">
          {sites.map((site: Site) => (
            <Card key={site.id}>
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
                  <div className="space-y-1.5 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-[14px] font-semibold text-[oklch(97%_0.005_265)]">
                        {site.name}
                      </span>
                      {site.deleted_at && <Pill tone="red">deleted</Pill>}
                    </div>
                    <div className="text-[12px] text-[oklch(55%_0.01_265)]">
                      {site.address || "No address set"} · {site.timezone} · Created{" "}
                      {new Date(site.created_at).toLocaleDateString()}
                    </div>
                    <SiteCameras cameras={(cameras ?? []).filter((c) => c.site_id === site.id)} />
                  </div>
                  <div className="flex gap-1.5 shrink-0">
                    {!canManage ? null : site.deleted_at ? (
                      <Btn
                        onClick={() => restoreMutation.mutate(site.id)}
                        disabled={restoreMutation.isPending}
                      >
                        Restore
                      </Btn>
                    ) : (
                      <>
                        <Btn onClick={() => setEditingSiteId(site.id)}>Edit</Btn>
                        <Btn
                          variant="danger"
                          disabled={deleteMutation.isPending}
                          onClick={() => {
                            if (
                              window.confirm(
                                `Delete site "${site.name}"? Cameras assigned to this site will also be affected.`
                              )
                            ) {
                              deleteMutation.mutate(site.id);
                            }
                          }}
                        >
                          Delete
                        </Btn>
                      </>
                    )}
                  </div>
                </div>
              )}
            </Card>
          ))}
        </div>
      )}
    </Page>
  );
}

function SiteCameras({ cameras }: { cameras: Camera[] }) {
  if (cameras.length === 0) {
    return (
      <div className="text-[11.5px] text-[oklch(42%_0.01_265)]">No cameras at this site yet.</div>
    );
  }
  return (
    <ul className="flex flex-wrap gap-x-3.5 gap-y-1 pt-0.5">
      {cameras.map((c) => (
        <li
          key={c.id}
          className="flex items-center gap-1.5 text-[11.5px] text-[oklch(72%_0.01_265)]"
        >
          <StatusDot status={c.status} />
          <span className="truncate max-w-[180px]">{c.name}</span>
        </li>
      ))}
    </ul>
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
          className={inputClass}
          required
        />
        <input
          value={address}
          onChange={(e) => setAddress(e.target.value)}
          placeholder="Address"
          className={inputClass}
        />
        <input
          value={timezone}
          onChange={(e) => setTimezone(e.target.value)}
          placeholder="Asia/Kolkata"
          className={inputClass}
          required
        />
      </div>
      <div className="flex gap-2">
        <Btn type="submit" variant="primary" disabled={loading}>
          {loading ? "Saving…" : mode === "create" ? "Create site" : "Save"}
        </Btn>
        <Btn type="button" onClick={onCancel}>
          Cancel
        </Btn>
      </div>
    </form>
  );
}
