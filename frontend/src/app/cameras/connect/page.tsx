"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowRight, Check, Copy, Link2, Loader2, Router, Tv2 } from "lucide-react";
import { api } from "@/lib/api";
import type { AgentSummary, DiscoveredDevice, PairCodeResponse } from "@/types";

type Step = "choice" | "direct" | "pair" | "wait" | "register" | "claim" | "done";

const RELAY_URL = process.env.NEXT_PUBLIC_RELAY_URL ?? "https://relay.nightwatch.ai";

export default function ConnectCameraPage() {
  const router = useRouter();
  const [step, setStep] = useState<Step>("choice");
  const [pairCode, setPairCode] = useState<PairCodeResponse | null>(null);
  const [pairStartedAt, setPairStartedAt] = useState<string | null>(null);
  const [agentId, setAgentId] = useState<string | null>(null);
  const [createdCameraId, setCreatedCameraId] = useState<string | null>(null);

  return (
    <div className="space-y-6">
      <div className="flex items-baseline gap-3">
        <h1 className="text-xl font-bold">Connect a Camera</h1>
        <Link href="/cameras" className="text-xs text-[#666666] hover:text-[#A3A3A3]">
          back to cameras
        </Link>
      </div>

      {step === "choice" && (
        <ChoiceStep
          onDirectPath={() => setStep("direct")}
          onAgentPath={() => setStep("pair")}
          onDevicePath={() => setStep("claim")}
        />
      )}

      {step === "direct" && (
        <DirectRtspStep
          onDone={(cameraId) => {
            setCreatedCameraId(cameraId);
            setStep("done");
          }}
        />
      )}

      {step === "pair" && (
        <PairStep
          pairCode={pairCode}
          setPairCode={setPairCode}
          onContinue={() => {
            setPairStartedAt(new Date().toISOString());
            setStep("wait");
          }}
        />
      )}

      {step === "wait" && (
        <WaitStep
          pairStartedAt={pairStartedAt}
          onFound={(id) => {
            setAgentId(id);
            setStep("register");
          }}
          onLater={() => router.push("/cameras")}
        />
      )}

      {step === "register" && agentId && (
        <RegisterStep
          agentId={agentId}
          onDone={(cameraId) => {
            setCreatedCameraId(cameraId);
            setStep("done");
          }}
        />
      )}

      {step === "claim" && (
        <ClaimStep
          onDone={(agentId) => {
            setAgentId(agentId);
            setStep("register");
          }}
        />
      )}

      {step === "done" && <DoneStep cameraId={createdCameraId} />}
    </div>
  );
}

function ProgressIndicator({ current }: { current: 1 | 2 | 3 }) {
  return (
    <div className="flex items-center gap-3">
      <span className="text-xs text-[#A3A3A3]">Step {current} of 3</span>
      <div className="flex items-center gap-1.5">
        {[1, 2, 3].map((n) => (
          <span
            key={n}
            className={`h-1.5 w-6 rounded-full ${
              n <= current ? "bg-[#1E90FF]" : "bg-[#2A2A2A]"
            }`}
          />
        ))}
      </div>
    </div>
  );
}

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto max-w-2xl bg-[#111111] border border-[#2A2A2A] rounded-lg p-6 space-y-4">
      {children}
    </div>
  );
}

function ChoiceStep({
  onDirectPath,
  onAgentPath,
  onDevicePath,
}: {
  onDirectPath: () => void;
  onAgentPath: () => void;
  onDevicePath: () => void;
}) {
  return (
    <div className="mx-auto max-w-3xl">
      <p className="text-sm text-[#A3A3A3] mb-4">
        Pick how your camera reaches Nightwatch.
      </p>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <button
          onClick={onDirectPath}
          className="bg-[#111111] border border-[#2A2A2A] rounded-lg p-6 space-y-3 hover:border-[#1E90FF] transition-colors block"
        >
          <div className="flex items-center gap-2 text-[#F5F5F5]">
            <Link2 size={18} /> <span className="font-medium">Direct RTSP</span>
          </div>
          <p className="text-sm text-[#A3A3A3]">
            Your NVR has a public RTSP URL we can pull from. Best when you already
            have port-forwarding or a static IP.
          </p>
          <div className="flex items-center gap-1 text-xs text-[#1E90FF]">
            Add directly <ArrowRight size={12} />
          </div>
        </button>
        <button
          onClick={onDevicePath}
          className="bg-[#111111] border border-[#1E90FF]/40 rounded-lg p-6 space-y-3 hover:border-[#1E90FF] transition-colors text-left relative"
        >
          <div className="absolute -top-2.5 left-4 px-2 py-0.5 bg-[#1E90FF] text-white text-[10px] font-medium rounded-full">
            Recommended
          </div>
          <div className="flex items-center gap-2 text-[#F5F5F5]">
            <Tv2 size={18} /> <span className="font-medium">Nightwatch Device</span>
          </div>
          <p className="text-sm text-[#A3A3A3]">
            Your device shows a code like <span className="font-mono text-[#F5F5F5]">NW-4829</span> on screen.
            Enter it here to link it instantly — no configuration needed.
          </p>
          <div className="flex items-center gap-1 text-xs text-[#1E90FF]">
            Enter code <ArrowRight size={12} />
          </div>
        </button>
        <button
          onClick={onAgentPath}
          className="bg-[#111111] border border-[#2A2A2A] rounded-lg p-6 space-y-3 hover:border-[#1E90FF] transition-colors text-left"
        >
          <div className="flex items-center gap-2 text-[#F5F5F5]">
            <Router size={18} /> <span className="font-medium">DIY Agent</span>
          </div>
          <p className="text-sm text-[#A3A3A3]">
            Install the agent yourself on a NAS, Pi, or OpenWRT — no port-forwarding
            needed. You generate a code from here, paste it into the agent.
          </p>
          <div className="flex items-center gap-1 text-xs text-[#1E90FF]">
            Start pairing <ArrowRight size={12} />
          </div>
        </button>
      </div>
    </div>
  );
}

function DirectRtspStep({ onDone }: { onDone: (cameraId: string) => void }) {
  const { data: sites } = useQuery({
    queryKey: ["sites"],
    queryFn: () => api.getSites(),
  });

  const [name, setName] = useState("");
  const [siteId, setSiteId] = useState("");
  const [rtspUrl, setRtspUrl] = useState("");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    if (!siteId && sites && sites.length > 0) {
      setSiteId(sites[0].id);
    }
  }, [sites, siteId]);

  const mutation = useMutation({
    mutationFn: () =>
      api.createCamera({
        name,
        site_id: siteId,
        ingest_mode: "rtsp_pull",
        rtsp_url: rtspUrl,
        enabled_events: ["person", "vehicle", "intrusion"],
        sensitivity: "medium",
      }),
    onSuccess: (data) => onDone(data.camera.id),
    onError: (e: Error) => setErrorMsg(e.message || "Could not add RTSP camera."),
  });

  const disabled = !name || !siteId || !rtspUrl || mutation.isPending;

  return (
    <Card>
      <div className="flex items-center justify-between">
        <h2 className="text-base font-medium">Add direct RTSP camera</h2>
        <ProgressIndicator current={1} />
      </div>
      <p className="text-sm text-[#A3A3A3]">
        Use this when your NVR or camera is reachable from the cloud by a public RTSP URL.
      </p>

      <div className="space-y-3">
        <div className="space-y-1">
          <label className="text-xs text-[#A3A3A3]">Camera name</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Front door"
            className="w-full px-3 py-1.5 bg-[#1F1F1F] border border-[#2A2A2A] rounded-md text-sm focus:border-[#1E90FF] outline-none"
          />
        </div>

        <div className="space-y-1">
          <label className="text-xs text-[#A3A3A3]">Site</label>
          <select
            value={siteId}
            onChange={(e) => setSiteId(e.target.value)}
            className="w-full px-3 py-1.5 bg-[#1F1F1F] border border-[#2A2A2A] rounded-md text-sm focus:border-[#1E90FF] outline-none"
          >
            {(sites || []).map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
            {(!sites || sites.length === 0) && (
              <option value="">No sites available</option>
            )}
          </select>
        </div>

        <div className="space-y-1">
          <label className="text-xs text-[#A3A3A3]">RTSP URL</label>
          <input
            value={rtspUrl}
            onChange={(e) => setRtspUrl(e.target.value)}
            placeholder="rtsp://user:pass@ip:554/stream"
            className="w-full px-3 py-1.5 bg-[#1F1F1F] border border-[#2A2A2A] rounded-md text-sm focus:border-[#1E90FF] outline-none font-mono"
          />
          <div className="text-xs text-[#666666]">
            This should be reachable from the worker or the deployed backend path that pulls it.
          </div>
        </div>

        {errorMsg && (
          <div className="text-xs text-red-400 bg-[#1A1A1A] border border-[#2A2A2A] rounded-md p-2">
            {errorMsg}
          </div>
        )}

        <div className="flex gap-2 pt-2">
          <button
            onClick={() => mutation.mutate()}
            disabled={disabled}
            className="px-3 py-1.5 bg-[#1E90FF] text-white rounded-md text-sm hover:bg-[#3BA0FF] transition-colors disabled:opacity-50"
          >
            {mutation.isPending ? "Adding..." : "Add camera"}
          </button>
          <button
            onClick={() => window.history.back()}
            className="px-3 py-1.5 bg-[#1A1A1A] border border-[#2A2A2A] text-[#A3A3A3] hover:text-[#F5F5F5] rounded-md text-sm transition-colors"
          >
            Back
          </button>
        </div>
      </div>
    </Card>
  );
}

function useCountdown(expiresAt: string | null) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!expiresAt) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [expiresAt]);
  if (!expiresAt) return null;
  const remaining = Math.max(0, new Date(expiresAt).getTime() - now);
  const totalSec = Math.floor(remaining / 1000);
  const mm = String(Math.floor(totalSec / 60)).padStart(2, "0");
  const ss = String(totalSec % 60).padStart(2, "0");
  return { remaining, label: `${mm}:${ss}` };
}

function PairStep({
  pairCode,
  setPairCode,
  onContinue,
}: {
  pairCode: PairCodeResponse | null;
  setPairCode: (p: PairCodeResponse) => void;
  onContinue: () => void;
}) {
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const countdown = useCountdown(pairCode?.expires_at ?? null);
  const expired = countdown !== null && countdown.remaining === 0;

  const mutation = useMutation({
    mutationFn: () => api.createPairCode(),
    onSuccess: (data) => {
      setPairCode(data);
      setErrorMsg(null);
    },
    onError: (e: Error) => {
      const msg = e.message || "";
      if (msg.toLowerCase().includes("rate") || msg.includes("429") || msg.toLowerCase().includes("too many")) {
        setErrorMsg("You've requested too many codes. Try again in an hour.");
      } else {
        setErrorMsg(msg || "Could not generate a pair code.");
      }
    },
  });

  const dockerCommand = useMemo(() => {
    const code = pairCode?.code ?? "<the code>";
    return `docker run -d --name nightwatch-agent \\
  --network host \\
  -e PAIR_CODE=${code} \\
  -e RELAY_URL=${RELAY_URL} \\
  nightwatchhq/agent:latest`;
  }, [pairCode]);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(dockerCommand);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <Card>
      <div className="flex items-center justify-between">
        <h2 className="text-base font-medium">Generate pair code</h2>
        <ProgressIndicator current={1} />
      </div>
      <p className="text-sm text-[#A3A3A3]">
        Create a one-time code and use it to start the agent on your home device.
      </p>

      {!pairCode || expired ? (
        <div className="space-y-3">
          <button
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending}
            className="px-3 py-1.5 bg-[#1E90FF] text-white rounded-md text-sm hover:bg-[#3BA0FF] transition-colors disabled:opacity-50"
          >
            {mutation.isPending ? "Generating..." : expired ? "Generate new code" : "Generate pair code"}
          </button>
          {errorMsg && (
            <div className="text-xs text-red-400 bg-[#1A1A1A] border border-[#2A2A2A] rounded-md p-2">
              {errorMsg}
            </div>
          )}
        </div>
      ) : (
        <div className="space-y-4">
          <div className="bg-[#0D0D0D] border border-[#2A2A2A] rounded-lg p-4 text-center space-y-1">
            <div className="font-mono text-3xl tracking-[0.4em] text-[#F5F5F5]">
              {pairCode.code}
            </div>
            <div className="text-xs text-[#A3A3A3]">
              {countdown ? <>expires in {countdown.label}</> : null}
            </div>
          </div>

          <div className="space-y-2">
            <div className="text-xs text-[#A3A3A3]">
              Run this on your home device (NAS / Pi / OpenWRT):
            </div>
            <pre className="bg-[#0D0D0D] border border-[#2A2A2A] rounded-md p-3 text-xs text-[#F5F5F5] overflow-x-auto whitespace-pre">
{dockerCommand}
            </pre>
            <button
              onClick={handleCopy}
              className="flex items-center gap-1.5 px-2.5 py-1 bg-[#1A1A1A] border border-[#2A2A2A] text-[#A3A3A3] hover:text-[#F5F5F5] rounded-md text-xs transition-colors"
            >
              {copied ? <Check size={12} /> : <Copy size={12} />}
              {copied ? "Copied" : "Copy command"}
            </button>
          </div>

          <div className="flex gap-2 pt-2">
            <button
              onClick={onContinue}
              className="px-3 py-1.5 bg-[#1E90FF] text-white rounded-md text-sm hover:bg-[#3BA0FF] transition-colors"
            >
              I&apos;ve started the agent — wait for it to connect
            </button>
          </div>
        </div>
      )}
    </Card>
  );
}

function WaitStep({
  pairStartedAt,
  onFound,
  onLater,
}: {
  pairStartedAt: string | null;
  onFound: (agentId: string) => void;
  onLater: () => void;
}) {
  const { data } = useQuery({
    queryKey: ["agents"],
    queryFn: () => api.listAgents(),
    refetchInterval: 5000,
  });

  useEffect(() => {
    if (!data || !pairStartedAt) return;
    const startMs = new Date(pairStartedAt).getTime();
    const matches = data.agents.filter((a: AgentSummary) => {
      if (a.status !== "online") return false;
      const seenAt = a.last_seen_at ?? a.created_at;
      return new Date(seenAt).getTime() >= startMs;
    });
    if (matches.length === 0) return;
    matches.sort(
      (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    );
    onFound(matches[0].id);
  }, [data, pairStartedAt, onFound]);

  return (
    <Card>
      <div className="flex items-center justify-between">
        <h2 className="text-base font-medium">Waiting for agent to come online</h2>
        <ProgressIndicator current={2} />
      </div>
      <div className="flex items-center gap-3 py-4">
        <Loader2 size={18} className="animate-spin text-[#1E90FF]" />
        <div className="text-sm text-[#A3A3A3]">
          Listening for your agent... Make sure the agent container is running.
        </div>
      </div>
      <div className="flex gap-2">
        <button
          onClick={onLater}
          className="px-3 py-1.5 bg-[#1A1A1A] border border-[#2A2A2A] text-[#A3A3A3] hover:text-[#F5F5F5] rounded-md text-sm transition-colors"
        >
          I&apos;ll do this later
        </button>
      </div>
    </Card>
  );
}

function DiscoveredCameraCard({
  agentId,
  device,
  siteId,
  onDone,
}: {
  agentId: string;
  device: DiscoveredDevice;
  siteId: string;
  onDone: (cameraId: string) => void;
}) {
  const [name, setName] = useState(device.name !== "unknown" ? device.name : "Camera");
  const [user, setUser] = useState("");
  const [pass, setPass] = useState("");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const mutation = useMutation({
    mutationFn: () =>
      api.registerAgentCameraFromOnvif(agentId, {
        name,
        site_id: siteId || undefined,
        onvif_xaddr: device.xaddr,
        user: user || undefined,
        pass: pass || undefined,
      }),
    onSuccess: (data) => {
      if (data.status === "pending") {
        setPending(true);
        return;
      }
      onDone(data.camera_id);
    },
    onError: (e: Error) => setErrorMsg(e.message || "Could not register camera."),
  });

  if (pending) {
    return (
      <div className="border border-[#2A2A2A] bg-[#1A1A1A] rounded-md p-3 text-xs text-[#A3A3A3]">
        Finding {name}&apos;s stream URL — the agent is resolving this
        automatically on your network. You can continue; it&apos;ll be ready
        in a few seconds.
      </div>
    );
  }

  return (
    <div className="border border-[#2A2A2A] bg-[#1A1A1A] rounded-md p-3 space-y-2">
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Camera name"
        className="w-full px-3 py-1.5 bg-[#1F1F1F] border border-[#2A2A2A] rounded-md text-sm focus:border-[#1E90FF] outline-none"
      />
      <div className="text-xs text-[#666666] font-mono break-all">{device.xaddr}</div>
      <div className="flex gap-2">
        <input
          value={user}
          onChange={(e) => setUser(e.target.value)}
          placeholder="NVR username"
          className="flex-1 px-3 py-1.5 bg-[#1F1F1F] border border-[#2A2A2A] rounded-md text-sm focus:border-[#1E90FF] outline-none"
        />
        <input
          type="password"
          value={pass}
          onChange={(e) => setPass(e.target.value)}
          placeholder="NVR password"
          className="flex-1 px-3 py-1.5 bg-[#1F1F1F] border border-[#2A2A2A] rounded-md text-sm focus:border-[#1E90FF] outline-none"
        />
      </div>
      {errorMsg && <div className="text-xs text-red-400">{errorMsg}</div>}
      <button
        onClick={() => mutation.mutate()}
        disabled={!name || mutation.isPending}
        className="px-3 py-1.5 bg-[#1E90FF] text-white rounded-md text-sm hover:bg-[#3BA0FF] transition-colors disabled:opacity-50"
      >
        {mutation.isPending ? "Enabling..." : "Enable"}
      </button>
    </div>
  );
}

function RegisterStep({
  agentId,
  onDone,
}: {
  agentId: string;
  onDone: (cameraId: string) => void;
}) {
  const { data: sites } = useQuery({
    queryKey: ["sites"],
    queryFn: () => api.getSites(),
  });

  const { data: discovered, isLoading: discovering } = useQuery({
    queryKey: ["agent-discover", agentId],
    queryFn: () => api.discoverAgentCameras(agentId),
    refetchInterval: 5000,
  });

  const [name, setName] = useState("");
  const [siteId, setSiteId] = useState<string>("");
  const [rtspUrl, setRtspUrl] = useState("");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [showManual, setShowManual] = useState(false);

  useEffect(() => {
    if (!siteId && sites && sites.length > 0) {
      setSiteId(sites[0].id);
    }
  }, [sites, siteId]);

  const mutation = useMutation({
    mutationFn: () =>
      api.registerAgentCamera(agentId, { name, site_id: siteId, rtsp_url: rtspUrl }),
    onSuccess: (data) => onDone(data.camera_id),
    onError: (e: Error) => setErrorMsg(e.message || "Could not register camera."),
  });

  const disabled = !name || !rtspUrl || mutation.isPending;
  const hasDiscovered = discovered && discovered.devices.length > 0;

  return (
    <Card>
      <div className="flex items-center justify-between">
        <h2 className="text-base font-medium">Add a camera</h2>
        <ProgressIndicator current={3} />
      </div>
      <p className="text-sm text-[#A3A3A3]">
        Tell the agent which camera to pull from over your local network.
      </p>

      {discovering && !discovered && (
        <div className="flex items-center gap-2 text-sm text-[#A3A3A3] py-2">
          <Loader2 size={14} className="animate-spin" />
          Scanning your network for cameras…
        </div>
      )}

      {hasDiscovered && (
        <div className="space-y-2">
          <h3 className="text-sm font-medium">Cameras found on your network</h3>
          {discovered!.devices.map((d) => (
            <DiscoveredCameraCard
              key={d.uuid}
              agentId={agentId}
              device={d}
              siteId={siteId}
              onDone={onDone}
            />
          ))}
        </div>
      )}

      {!hasDiscovered && !discovering && (
        <p className="text-sm text-[#A3A3A3]">
          No cameras found automatically — enter the RTSP URL manually below.
        </p>
      )}

      {hasDiscovered && !showManual && (
        <button
          onClick={() => setShowManual(true)}
          className="text-sm underline text-[#A3A3A3] hover:text-[#F5F5F5]"
        >
          I don&apos;t see my camera — enter manually
        </button>
      )}

      {(showManual || !hasDiscovered) && (
      <div className="space-y-3">
        <div className="space-y-1">
          <label className="text-xs text-[#A3A3A3]">Camera name</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Front door"
            className="w-full px-3 py-1.5 bg-[#1F1F1F] border border-[#2A2A2A] rounded-md text-sm focus:border-[#1E90FF] outline-none"
          />
        </div>

        <div className="space-y-1">
          <label className="text-xs text-[#A3A3A3]">Site</label>
          <select
            value={siteId}
            onChange={(e) => setSiteId(e.target.value)}
            className="w-full px-3 py-1.5 bg-[#1F1F1F] border border-[#2A2A2A] rounded-md text-sm focus:border-[#1E90FF] outline-none"
          >
            {(sites || []).map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
            {(!sites || sites.length === 0) && (
              <option value="">No sites available</option>
            )}
          </select>
        </div>

        <div className="space-y-1">
          <label className="text-xs text-[#A3A3A3]">RTSP URL (on your LAN)</label>
          <input
            value={rtspUrl}
            onChange={(e) => setRtspUrl(e.target.value)}
            placeholder="rtsp://192.168.1.10:554/Streaming/Channels/101"
            className="w-full px-3 py-1.5 bg-[#1F1F1F] border border-[#2A2A2A] rounded-md text-sm focus:border-[#1E90FF] outline-none font-mono"
          />
          <div className="text-xs text-[#666666]">
            Find this in your NVR&apos;s network settings, or check the brand templates below.
          </div>
        </div>

        <details className="bg-[#1A1A1A] border border-[#2A2A2A] rounded-md">
          <summary className="cursor-pointer px-3 py-2 text-xs text-[#A3A3A3] hover:text-[#F5F5F5]">
            Brand templates
          </summary>
          <div className="px-3 pb-3 space-y-2 text-xs">
            <div>
              <div className="text-[#A3A3A3]">CP Plus</div>
              <code className="text-[#1E90FF] break-all">
                rtsp://admin:&lt;password&gt;@&lt;nvr-ip&gt;:554/cam/realmonitor?channel=1&amp;subtype=0
              </code>
            </div>
            <div>
              <div className="text-[#A3A3A3]">Hikvision</div>
              <code className="text-[#1E90FF] break-all">
                rtsp://admin:&lt;password&gt;@&lt;nvr-ip&gt;:554/Streaming/Channels/101
              </code>
            </div>
            <div>
              <div className="text-[#A3A3A3]">Dahua</div>
              <code className="text-[#1E90FF] break-all">
                rtsp://admin:&lt;password&gt;@&lt;nvr-ip&gt;:554/cam/realmonitor?channel=1&amp;subtype=0
              </code>
            </div>
          </div>
        </details>

        {errorMsg && (
          <div className="text-xs text-red-400 bg-[#1A1A1A] border border-[#2A2A2A] rounded-md p-2">
            {errorMsg}
          </div>
        )}

        <div className="flex gap-2 pt-2">
          <button
            onClick={() => mutation.mutate()}
            disabled={disabled}
            className="px-3 py-1.5 bg-[#1E90FF] text-white rounded-md text-sm hover:bg-[#3BA0FF] transition-colors disabled:opacity-50"
          >
            {mutation.isPending ? "Adding..." : "Add camera"}
          </button>
        </div>
      </div>
      )}
    </Card>
  );
}

function ClaimStep({ onDone }: { onDone: (agentId: string) => void }) {
  const [code, setCode] = useState("");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => api.claimDevice(code),
    onSuccess: (data) => onDone(data.agent_id),
    onError: (e: Error) => setErrorMsg(e.message || "Could not link device."),
  });

  const formatted = code
    .toUpperCase()
    .replace(/[^0-9NW-]/g, "")
    .slice(0, 7);

  return (
    <Card>
      <h2 className="text-base font-medium">Enter device code</h2>
      <p className="text-sm text-[#A3A3A3]">
        Your device displays a code like <span className="font-mono text-[#F5F5F5]">NW-4829</span> on its
        screen or logs. Enter it below to link it to your account.
      </p>
      <div className="space-y-3">
        <input
          value={formatted}
          onChange={(e) => setCode(e.target.value.replace(/[^0-9nwNW-]/g, ""))}
          placeholder="NW-0000"
          maxLength={7}
          className="w-full px-4 py-3 bg-[#0D0D0D] border border-[#2A2A2A] rounded-lg font-mono text-2xl tracking-[0.4em] text-center text-[#F5F5F5] focus:outline-none focus:border-[#1E90FF] uppercase"
        />
        {errorMsg && (
          <div className="text-xs text-red-400 bg-[#1A1A1A] border border-[#2A2A2A] rounded-md p-2">
            {errorMsg}
          </div>
        )}
        <div className="flex gap-2">
          <button
            onClick={() => mutation.mutate()}
            disabled={code.replace("NW-", "").replace("nw-", "").length < 4 || mutation.isPending}
            className="px-4 py-2 bg-[#1E90FF] text-white rounded-md text-sm hover:bg-[#3BA0FF] transition-colors disabled:opacity-50 flex items-center gap-2"
          >
            {mutation.isPending && <Loader2 size={14} className="animate-spin" />}
            {mutation.isPending ? "Linking..." : "Link device"}
          </button>
          <Link
            href="/cameras"
            className="px-4 py-2 bg-[#1A1A1A] border border-[#2A2A2A] text-[#A3A3A3] hover:text-[#F5F5F5] rounded-md text-sm transition-colors"
          >
            Cancel
          </Link>
        </div>
      </div>
      <div className="text-xs text-[#666666] border-t border-[#2A2A2A] pt-3">
        The code is shown on your device&apos;s display or in its startup logs.
        It expires after 10 minutes — restart the device to get a new one.
      </div>
    </Card>
  );
}

function DoneStep({ cameraId }: { cameraId: string | null }) {
  const router = useRouter();
  useEffect(() => {
    const t = setTimeout(() => {
      if (cameraId) router.push(`/cameras/${cameraId}`);
      else router.push("/cameras");
    }, 1500);
    return () => clearTimeout(t);
  }, [cameraId, router]);

  return (
    <Card>
      <div className="flex flex-col items-center gap-3 py-6">
        <div className="h-12 w-12 rounded-full bg-[#1E90FF]/15 border border-[#1E90FF] flex items-center justify-center">
          <Check size={24} className="text-[#1E90FF]" />
        </div>
        <div className="text-sm text-[#F5F5F5]">Camera connected. Heading to dashboard...</div>
      </div>
    </Card>
  );
}
