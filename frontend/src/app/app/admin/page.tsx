"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Skeleton } from "@/components/ui/Skeleton";
import { useAuthStore } from "@/lib/store";

export default function AdminPageV2() {
  const { user } = useAuthStore();
  const [tab, setTab] = useState<"users" | "orgs">("users");

  const { data: orgs, isLoading: orgsLoading, isError: orgsError, error: orgsErrorObj } = useQuery({
    queryKey: ["admin", "orgs"],
    queryFn: () => api.adminGetOrgs(),
    enabled: user?.role === "super_admin",
  });

  const { data: users, isLoading: usersLoading, isError: usersError, error: usersErrorObj } = useQuery({
    queryKey: ["admin", "users"],
    queryFn: () => api.adminGetUsers(),
    enabled: user?.role === "super_admin",
  });

  if (user?.role !== "super_admin") {
    return (
      <div className="max-w-[1040px] mx-auto px-12 py-12 text-sm text-[oklch(55%_0.01_265)]">
        Not authorized.
      </div>
    );
  }

  return (
    <div className="max-w-[1040px] mx-auto px-12 pt-12 pb-20">
      <div className="text-[28px] font-bold tracking-tight mb-6">Admin</div>
      <div className="flex gap-2 mb-6">
        <button
          onClick={() => setTab("users")}
          className={`text-sm font-semibold px-4 py-2 rounded-lg ${
            tab === "users" ? "bg-[oklch(85%_0.16_84)] text-[oklch(18%_0.02_84)]" : "text-[oklch(72%_0.01_265)]"
          }`}
        >
          Users
        </button>
        <button
          onClick={() => setTab("orgs")}
          className={`text-sm font-semibold px-4 py-2 rounded-lg ${
            tab === "orgs" ? "bg-[oklch(85%_0.16_84)] text-[oklch(18%_0.02_84)]" : "text-[oklch(72%_0.01_265)]"
          }`}
        >
          Orgs
        </button>
        <Link
          href="/app/admin/ai"
          className="text-sm font-semibold px-4 py-2 rounded-lg text-[oklch(72%_0.01_265)] hover:text-[oklch(95%_0.005_265)] transition-colors"
        >
          AI usage →
        </Link>
      </div>

      {tab === "users" && (
        <>
          {usersLoading ? (
            <Skeleton className="h-96 w-full" />
          ) : usersError ? (
            <div className="bg-[oklch(18%_0.2_22)] border border-[oklch(70.4%_0.191_22.216)] rounded-lg px-4 py-3 text-sm text-[oklch(70.4%_0.191_22.216)]">
              {usersErrorObj instanceof Error ? usersErrorObj.message : "Could not load users."}
            </div>
          ) : (users ?? []).length > 0 ? (
            <div className="flex flex-col gap-2">
              {(users ?? []).map((u) => (
                <div key={u.id} className="bg-[oklch(13%_0.015_265)] border border-[oklch(22%_0.015_265)] rounded-lg px-4 py-3 text-sm">
                  {u.username} · {u.role}
                </div>
              ))}
            </div>
          ) : (
            <div className="text-sm text-[oklch(55%_0.01_265)]">No users found.</div>
          )}
        </>
      )}

      {tab === "orgs" && (
        <>
          {orgsLoading ? (
            <Skeleton className="h-96 w-full" />
          ) : orgsError ? (
            <div className="bg-[oklch(18%_0.2_22)] border border-[oklch(70.4%_0.191_22.216)] rounded-lg px-4 py-3 text-sm text-[oklch(70.4%_0.191_22.216)]">
              {orgsErrorObj instanceof Error ? orgsErrorObj.message : "Could not load organizations."}
            </div>
          ) : (orgs ?? []).length > 0 ? (
            <div className="flex flex-col gap-2">
              {(orgs ?? []).map((o: { id: string; name: string }) => (
                <div key={o.id} className="bg-[oklch(13%_0.015_265)] border border-[oklch(22%_0.015_265)] rounded-lg px-4 py-3 text-sm">
                  {o.name}
                </div>
              ))}
            </div>
          ) : (
            <div className="text-sm text-[oklch(55%_0.01_265)]">No organizations found.</div>
          )}
        </>
      )}
    </div>
  );
}
