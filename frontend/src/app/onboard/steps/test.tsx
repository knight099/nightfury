// TODO(onboarding-22a/b): backend endpoint GET /api/agents/{id} (single-agent detail with
// cameras_streaming count) is not yet implemented. UI built ahead of backend; calls will currently 404.
"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

interface AgentDetail {
  id: string;
  cameras_streaming: number;
}

export function TestStep({ agentId }: { agentId: string }) {
  const [status, setStatus] = useState<"waiting" | "ok" | "fail">("waiting");
  const router = useRouter();

  useEffect(() => {
    const t = setInterval(async () => {
      try {
        const r = await api.request<AgentDetail>(`/api/agents/${agentId}`);
        if (r.cameras_streaming > 0) {
          setStatus("ok");
          clearInterval(t);
        }
      } catch {
        // ignore poll errors
      }
    }, 3000);
    const fail = setTimeout(
      () => setStatus((s) => (s === "waiting" ? "fail" : s)),
      60_000
    );
    return () => {
      clearInterval(t);
      clearTimeout(fail);
    };
  }, [agentId]);

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">Testing the stream</h2>
      {status === "waiting" && (
        <p className="text-[#A3A3A3]">Waiting for the first frame from your camera…</p>
      )}
      {status === "ok" && (
        <>
          <p className="text-[#4ADE80]">Frame received. You&apos;re all set.</p>
          <button
            onClick={() => router.push("/dashboard")}
            className="px-6 py-2 bg-[#1E90FF] hover:bg-[#3BA0FF] text-white rounded transition-colors"
          >
            Go to dashboard
          </button>
        </>
      )}
      {status === "fail" && (
        <p className="text-[#EF4444]">
          No frames received in 60s. Check NVR password and try again.
        </p>
      )}
    </div>
  );
}
