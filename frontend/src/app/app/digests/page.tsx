"use client";

import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Skeleton } from "@/components/ui/Skeleton";

export default function DigestsPageV2() {
  const queryClient = useQueryClient();

  const { data: digestsData, isLoading, isError, error } = useQuery({
    queryKey: ["digests"],
    queryFn: () => api.getDigests(),
  });

  const {
    data: prefs,
    isError: prefsError,
    error: prefsErrorObj,
  } = useQuery({
    queryKey: ["digest-preferences"],
    queryFn: () => api.getDigestPreferences(),
  });

  const updatePrefs = useMutation({
    mutationFn: (body: Parameters<typeof api.updateDigestPreferences>[0]) =>
      api.updateDigestPreferences(body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["digest-preferences"] }),
  });

  return (
    <div className="max-w-[1040px] mx-auto px-12 pt-12 pb-20">
      <div className="text-[28px] font-bold tracking-tight mb-6">Digests</div>

      {prefsError ? (
        <div className="mb-8 text-sm text-[oklch(70.4%_0.191_22.216)]">
          {prefsErrorObj instanceof Error
            ? prefsErrorObj.message
            : "Couldn't load your digest schedule."}
        </div>
      ) : prefs ? (
        <div className="mb-8 text-sm">
          <div className="flex gap-6">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={prefs.morning_enabled}
                disabled={updatePrefs.isPending}
                onChange={(e) => updatePrefs.mutate({ ...prefs, morning_enabled: e.target.checked })}
              />
              Morning digest ({prefs.morning_local_time})
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={prefs.evening_enabled}
                disabled={updatePrefs.isPending}
                onChange={(e) => updatePrefs.mutate({ ...prefs, evening_enabled: e.target.checked })}
              />
              Evening digest ({prefs.evening_local_time})
            </label>
          </div>
          {updatePrefs.isError && (
            <div className="mt-2 text-[13px] text-[oklch(70.4%_0.191_22.216)]">
              {updatePrefs.error instanceof Error
                ? `Couldn't save that change: ${updatePrefs.error.message}`
                : "Couldn't save that change."}
            </div>
          )}
        </div>
      ) : null}

      {isLoading ? (
        <Skeleton className="h-96 w-full" />
      ) : isError ? (
        <div className="p-6 text-sm text-center text-[oklch(70.4%_0.191_22.216)] border border-[oklch(70.4%_0.191_22.216)] rounded-[14px] bg-[oklch(18%_0.2_22)]">
          Failed to load digests: {error?.message || "Unknown error"}
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {(digestsData?.items ?? []).length > 0 ? (
            digestsData!.items.map((d) => (
              <Link
                key={d.id}
                href={`/app/digests/${d.id}`}
                className="block bg-[oklch(13%_0.015_265)] border border-[oklch(22%_0.015_265)] rounded-[14px] px-5 py-4"
              >
                <div className="text-sm font-semibold mb-1">{d.payload.headline}</div>
                <div className="text-xs text-[oklch(58%_0.01_265)]">
                  {new Date(d.range_start).toLocaleDateString()} · {d.event_count} events
                </div>
              </Link>
            ))
          ) : (
            <div className="text-sm text-[oklch(55%_0.01_265)]">No digests yet.</div>
          )}
        </div>
      )}
    </div>
  );
}
