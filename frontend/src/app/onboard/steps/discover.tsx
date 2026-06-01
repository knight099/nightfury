// TODO(onboarding-22a/b): backend endpoints POST /api/agents/{id}/discover and POST /api/agents/{id}/cameras
// are not yet implemented. UI built ahead of backend; calls will currently 404.
"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { BRANDS } from "../lib/brands";

interface Discovered {
  uuid: string;
  name: string;
  xaddr: string;
}

interface DiscoverResponse {
  devices: Discovered[];
}

export function DiscoverStep({
  agentId,
  onNext,
}: {
  agentId: string;
  onNext: () => void;
}) {
  const [found, setFound] = useState<Discovered[] | null>(null);
  const [manual, setManual] = useState(false);

  useEffect(() => {
    api
      .request<DiscoverResponse>(`/api/agents/${agentId}/discover`, {
        method: "POST",
        body: JSON.stringify({}),
      })
      .then((r) => setFound(r.devices))
      .catch(() => setManual(true));
  }, [agentId]);

  if (manual || (found && found.length === 0)) {
    return <ManualEntry agentId={agentId} onNext={onNext} />;
  }
  if (!found) return <p className="text-[#A3A3A3]">Scanning your network for NVRs…</p>;

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">Cameras found</h2>
      {found.map((d) => (
        <CameraEnable key={d.uuid} agentId={agentId} discovered={d} />
      ))}
      <div className="flex gap-3 items-center">
        <button
          onClick={onNext}
          className="px-6 py-2 bg-[#1E90FF] hover:bg-[#3BA0FF] text-white rounded transition-colors"
        >
          Done →
        </button>
        <button
          onClick={() => setManual(true)}
          className="text-sm underline text-[#A3A3A3] hover:text-[#F5F5F5]"
        >
          I don&apos;t see my camera
        </button>
      </div>
    </div>
  );
}

function CameraEnable({
  agentId,
  discovered,
}: {
  agentId: string;
  discovered: Discovered;
}) {
  const [user, setU] = useState("");
  const [pass, setP] = useState("");
  const [name, setN] = useState(discovered.name);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const onEnable = async () => {
    setSaving(true);
    setErr(null);
    try {
      await api.request(`/api/agents/${agentId}/cameras`, {
        method: "POST",
        body: JSON.stringify({
          name,
          onvif_xaddr: discovered.xaddr,
          user,
          pass,
        }),
      });
      setSaved(true);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="border border-[#2A2A2A] bg-[#111111] p-4 rounded space-y-2">
      <input
        value={name}
        onChange={(e) => setN(e.target.value)}
        placeholder="Camera name"
        className="bg-[#1F1F1F] border border-[#2A2A2A] focus:border-[#1E90FF] outline-none p-2 w-full rounded"
      />
      <input
        value={user}
        onChange={(e) => setU(e.target.value)}
        placeholder="NVR username"
        className="bg-[#1F1F1F] border border-[#2A2A2A] focus:border-[#1E90FF] outline-none p-2 w-full rounded"
      />
      <input
        type="password"
        value={pass}
        onChange={(e) => setP(e.target.value)}
        placeholder="NVR password"
        className="bg-[#1F1F1F] border border-[#2A2A2A] focus:border-[#1E90FF] outline-none p-2 w-full rounded"
      />
      <button
        onClick={onEnable}
        disabled={saving || saved}
        className="px-4 py-2 bg-[#1E90FF] hover:bg-[#3BA0FF] disabled:opacity-50 text-white rounded transition-colors"
      >
        {saved ? "Enabled" : saving ? "Enabling…" : "Enable"}
      </button>
      {err && <p className="text-sm text-[#EF4444]">{err}</p>}
    </div>
  );
}

function ManualEntry({
  agentId,
  onNext,
}: {
  agentId: string;
  onNext: () => void;
}) {
  const [brand, setBrand] = useState(BRANDS[0].name);
  const [host, setHost] = useState("");
  const [user, setU] = useState("");
  const [pass, setP] = useState("");
  const [ch, setCh] = useState("1");
  const [name, setN] = useState("Front door");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const tpl = BRANDS.find((b) => b.name === brand)!.template;
  const url = tpl
    .replace("{user}", user)
    .replace("{pass}", pass)
    .replace("{host}", host)
    .replace("{ch}", ch);

  const onSave = async () => {
    setSaving(true);
    setErr(null);
    try {
      await api.request(`/api/agents/${agentId}/cameras`, {
        method: "POST",
        body: JSON.stringify({ name, rtsp_url: url }),
      });
      onNext();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-3">
      <h2 className="text-xl font-semibold">Enter your camera URL</h2>
      <select
        value={brand}
        onChange={(e) => setBrand(e.target.value)}
        className="bg-[#1F1F1F] border border-[#2A2A2A] focus:border-[#1E90FF] outline-none p-2 w-full rounded"
      >
        {BRANDS.map((b) => (
          <option key={b.name}>{b.name}</option>
        ))}
      </select>
      <input
        value={name}
        onChange={(e) => setN(e.target.value)}
        placeholder="Camera name"
        className="bg-[#1F1F1F] border border-[#2A2A2A] focus:border-[#1E90FF] outline-none p-2 w-full rounded"
      />
      <input
        value={host}
        onChange={(e) => setHost(e.target.value)}
        placeholder="NVR IP (e.g. 192.168.1.50)"
        className="bg-[#1F1F1F] border border-[#2A2A2A] focus:border-[#1E90FF] outline-none p-2 w-full rounded"
      />
      <input
        value={user}
        onChange={(e) => setU(e.target.value)}
        placeholder="username"
        className="bg-[#1F1F1F] border border-[#2A2A2A] focus:border-[#1E90FF] outline-none p-2 w-full rounded"
      />
      <input
        type="password"
        value={pass}
        onChange={(e) => setP(e.target.value)}
        placeholder="password"
        className="bg-[#1F1F1F] border border-[#2A2A2A] focus:border-[#1E90FF] outline-none p-2 w-full rounded"
      />
      <input
        value={ch}
        onChange={(e) => setCh(e.target.value)}
        placeholder="channel"
        className="bg-[#1F1F1F] border border-[#2A2A2A] focus:border-[#1E90FF] outline-none p-2 w-full rounded"
      />
      <pre className="text-xs text-[#A3A3A3] break-all whitespace-pre-wrap">{url}</pre>
      <button
        onClick={onSave}
        disabled={saving}
        className="px-6 py-2 bg-[#1E90FF] hover:bg-[#3BA0FF] disabled:opacity-50 text-white rounded transition-colors"
      >
        {saving ? "Saving…" : "Save & test"}
      </button>
      {err && <p className="text-sm text-[#EF4444]">{err}</p>}
    </div>
  );
}
