"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowRight, Check, Copy, Link2, Loader2, Router, Tv2 } from "lucide-react";
import { api } from "@/lib/api";
import { Page, Card, Btn, Field, ErrorBox, BackLink, inputClass } from "@/components/v2/ui";
import { WizardHost } from "@/components/v2/onboarding/WizardHost";
import type { AgentSummary, PairCodeResponse, Site } from "@/types";

type Step = "choice" | "direct" | "pair" | "wait" | "wizard" | "claim" | "done";

const RELAY_URL = process.env.NEXT_PUBLIC_RELAY_URL ?? "https://relay.nightwatch.ai";

/**
 * Connect a camera (V2).
 *
 * Ported from the V1 page. One deliberate change: every path that needs a site
 * now blocks with a link to /app/sites instead of rendering a dead "No sites
 * available" option. A camera cannot exist without a site, and with the V2 flag
 * on there is no legacy route to fall back to — so a silent dead end here means
 * the user simply cannot onboard.
 */
export default function ConnectCameraPageV2() {
  const router = useRouter();
  const [step, setStep] = useState<Step>("choice");
  const [pairCode, setPairCode] = useState<PairCodeResponse | null>(null);
  const [pairStartedAt, setPairStartedAt] = useState<string | null>(null);
  const [agentId, setAgentId] = useState<string | null>(null);
  const [createdCameraId, setCreatedCameraId] = useState<string | null>(null);

  return (
    <Page>
      <BackLink href="/app/cameras" label="Back to cameras" />
      <div className="text-[28px] font-bold tracking-tight mb-6">Connect a camera</div>

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
            setStep("wizard");
          }}
          onLater={() => router.push("/app/cameras")}
        />
      )}

      {step === "wizard" && agentId && <WizardHost agentId={agentId} />}

      {step === "claim" && (
        <ClaimStep
          onDone={(id) => {
            setAgentId(id);
            setStep("wizard");
          }}
        />
      )}

      {step === "done" && <DoneStep cameraId={createdCameraId} />}
    </Page>
  );
}

function ProgressIndicator({ current }: { current: 1 | 2 | 3 }) {
  return (
    <div className="flex items-center gap-3">
      <span className="text-[11.5px] text-[oklch(55%_0.01_265)]">Step {current} of 3</span>
      <div className="flex items-center gap-1.5">
        {[1, 2, 3].map((n) => (
          <span
            key={n}
            className={`h-1.5 w-6 rounded-full ${
              n <= current ? "bg-[oklch(85%_0.16_84)]" : "bg-[oklch(24%_0.02_265)]"
            }`}
          />
        ))}
      </div>
    </div>
  );
}

/**
 * Blocks any step that needs a site until one exists. Returns null while
 * loading so a step never flashes "you have no sites" before the fetch lands.
 */
function useSiteGuard() {
  const { data: sites, isLoading } = useQuery({
    queryKey: ["sites"],
    queryFn: () => api.getSites(),
  });
  return { sites: sites ?? [], isLoading, hasSites: (sites?.length ?? 0) > 0 };
}

function NoSitesBlock() {
  return (
    <Card className="space-y-3">
      <div className="text-[15px] font-semibold">You need a site first</div>
      <p className="text-[13px] text-[oklch(72%_0.01_265)] leading-relaxed">
        Cameras are grouped by site — a location like Home, Office, or Warehouse. Create one and
        come back.
      </p>
      <Link href="/app/sites">
        <Btn variant="primary">Create a site</Btn>
      </Link>
    </Card>
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
  const options = [
    {
      onClick: onDirectPath,
      icon: Link2,
      title: "Direct RTSP",
      body: "Your NVR has a public RTSP URL we can pull from. Best when you already have port-forwarding or a static IP.",
      cta: "Add directly",
      recommended: false,
    },
    {
      onClick: onDevicePath,
      icon: Tv2,
      title: "Nightwatch Device",
      body: "Your device shows a code like NW-4829 on screen. Enter it here to link it instantly — no configuration needed.",
      cta: "Enter code",
      recommended: true,
    },
    {
      onClick: onAgentPath,
      icon: Router,
      title: "DIY Agent",
      body: "Install the agent yourself on a NAS, Pi, or OpenWRT — no port-forwarding needed. You generate a code here and paste it into the agent.",
      cta: "Start pairing",
      recommended: false,
    },
  ];

  return (
    <div>
      <p className="text-[13px] text-[oklch(72%_0.01_265)] mb-4">
        Pick how your camera reaches Nightwatch.
      </p>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {options.map((o) => {
          const Icon = o.icon;
          return (
            <button
              key={o.title}
              onClick={o.onClick}
              className={`relative text-left bg-[oklch(12%_0.015_265)] border rounded-[14px] p-5 space-y-3 transition-colors hover:border-[oklch(85%_0.16_84)] ${
                o.recommended
                  ? "border-[oklch(85%_0.16_84)]/40"
                  : "border-[oklch(22%_0.015_265)]"
              }`}
            >
              {o.recommended && (
                <div className="absolute -top-2.5 left-4 px-2 py-0.5 bg-[oklch(85%_0.16_84)] text-[oklch(18%_0.02_84)] text-[10px] font-bold rounded-full">
                  Recommended
                </div>
              )}
              <div className="flex items-center gap-2 text-[oklch(97%_0.005_265)]">
                <Icon size={18} /> <span className="font-semibold text-[14px]">{o.title}</span>
              </div>
              <p className="text-[12.5px] text-[oklch(72%_0.01_265)] leading-relaxed">{o.body}</p>
              <div className="flex items-center gap-1 text-[11.5px] text-[oklch(85%_0.16_84)]">
                {o.cta} <ArrowRight size={12} />
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function SiteSelect({
  sites,
  siteId,
  setSiteId,
}: {
  sites: Site[];
  siteId: string;
  setSiteId: (v: string) => void;
}) {
  return (
    <Field label="Site">
      <select value={siteId} onChange={(e) => setSiteId(e.target.value)} className={inputClass}>
        {sites.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name}
          </option>
        ))}
      </select>
    </Field>
  );
}

function DirectRtspStep({ onDone }: { onDone: (cameraId: string) => void }) {
  const { sites, isLoading, hasSites } = useSiteGuard();
  const [name, setName] = useState("");
  const [siteId, setSiteId] = useState("");
  const [rtspUrl, setRtspUrl] = useState("");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    if (!siteId && sites.length > 0) setSiteId(sites[0].id);
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

  if (isLoading) return <Card>Loading…</Card>;
  if (!hasSites) return <NoSitesBlock />;

  return (
    <Card className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-[15px] font-semibold">Add direct RTSP camera</h2>
        <ProgressIndicator current={1} />
      </div>
      <p className="text-[13px] text-[oklch(72%_0.01_265)]">
        Use this when your NVR or camera is reachable from the cloud by a public RTSP URL.
      </p>

      <div className="space-y-3">
        <Field label="Camera name">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Front door"
            className={inputClass}
          />
        </Field>

        <SiteSelect sites={sites} siteId={siteId} setSiteId={setSiteId} />

        <Field label="RTSP URL">
          <input
            value={rtspUrl}
            onChange={(e) => setRtspUrl(e.target.value)}
            placeholder="rtsp://user:pass@ip:554/stream"
            className={`${inputClass} font-mono`}
          />
        </Field>
        <p className="text-[11.5px] text-[oklch(55%_0.01_265)] -mt-1">
          This must be reachable from whichever component pulls it.
        </p>

        {errorMsg && <ErrorBox message={errorMsg} />}

        <div className="flex gap-2 pt-1">
          <Btn
            variant="primary"
            onClick={() => mutation.mutate()}
            disabled={!name || !siteId || !rtspUrl || mutation.isPending}
          >
            {mutation.isPending ? "Adding…" : "Add camera"}
          </Btn>
          <Btn onClick={() => window.history.back()}>Back</Btn>
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
      if (
        msg.toLowerCase().includes("rate") ||
        msg.includes("429") ||
        msg.toLowerCase().includes("too many")
      ) {
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
    <Card className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-[15px] font-semibold">Generate pair code</h2>
        <ProgressIndicator current={1} />
      </div>
      <p className="text-[13px] text-[oklch(72%_0.01_265)]">
        Create a one-time code and use it to start the agent on your home device.
      </p>

      {!pairCode || expired ? (
        <div className="space-y-3">
          <Btn variant="primary" onClick={() => mutation.mutate()} disabled={mutation.isPending}>
            {mutation.isPending
              ? "Generating…"
              : expired
                ? "Generate new code"
                : "Generate pair code"}
          </Btn>
          {errorMsg && <ErrorBox message={errorMsg} />}
        </div>
      ) : (
        <div className="space-y-4">
          <div className="bg-[oklch(9%_0.015_265)] border border-[oklch(22%_0.015_265)] rounded-[10px] p-4 text-center space-y-1">
            <div className="font-mono text-3xl tracking-[0.4em] text-[oklch(97%_0.005_265)]">
              {pairCode.code}
            </div>
            <div className="text-[11.5px] text-[oklch(55%_0.01_265)]">
              {countdown ? <>expires in {countdown.label}</> : null}
            </div>
          </div>

          <div className="space-y-2">
            <div className="text-[11.5px] text-[oklch(72%_0.01_265)]">
              Run this on your home device (NAS / Pi / OpenWRT):
            </div>
            <pre className="bg-[oklch(9%_0.015_265)] border border-[oklch(22%_0.015_265)] rounded-md p-3 text-[11.5px] text-[oklch(90%_0.005_265)] overflow-x-auto whitespace-pre">
              {dockerCommand}
            </pre>
            <Btn onClick={handleCopy} className="inline-flex items-center gap-1.5">
              {copied ? <Check size={12} /> : <Copy size={12} />}
              {copied ? "Copied" : "Copy command"}
            </Btn>
          </div>

          <Btn variant="primary" onClick={onContinue}>
            I&apos;ve started the agent — wait for it to connect
          </Btn>
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
    // Only agents that checked in AFTER pairing started count — otherwise an
    // unrelated box that was already online would be adopted as "the one you
    // just paired".
    const matches = data.agents.filter((a: AgentSummary) => {
      if (a.status !== "online") return false;
      const seenAt = a.last_seen_at ?? a.created_at;
      return new Date(seenAt).getTime() >= startMs;
    });
    if (matches.length === 0) return;
    matches.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
    onFound(matches[0].id);
  }, [data, pairStartedAt, onFound]);

  return (
    <Card className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-[15px] font-semibold">Waiting for agent to come online</h2>
        <ProgressIndicator current={2} />
      </div>
      <div className="flex items-center gap-3 py-3">
        <Loader2 size={18} className="animate-spin text-[oklch(85%_0.16_84)]" />
        <div className="text-[13px] text-[oklch(72%_0.01_265)]">
          Listening for your agent… make sure the agent container is running.
        </div>
      </div>
      <Btn onClick={onLater}>I&apos;ll do this later</Btn>
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
    <Card className="space-y-4">
      <h2 className="text-[15px] font-semibold">Enter device code</h2>
      <p className="text-[13px] text-[oklch(72%_0.01_265)]">
        Your device displays a code like{" "}
        <span className="font-mono text-[oklch(97%_0.005_265)]">NW-4829</span> on its screen or
        logs. Enter it below to link it to your account.
      </p>
      <div className="space-y-3">
        <input
          value={formatted}
          onChange={(e) => setCode(e.target.value.replace(/[^0-9nwNW-]/g, ""))}
          placeholder="NW-0000"
          maxLength={7}
          className="w-full px-4 py-3 bg-[oklch(9%_0.015_265)] border border-[oklch(24%_0.02_265)] rounded-[10px] font-mono text-2xl tracking-[0.4em] text-center text-[oklch(97%_0.005_265)] focus:outline-none focus:border-[oklch(85%_0.16_84)] uppercase"
        />
        {errorMsg && <ErrorBox message={errorMsg} />}
        <div className="flex gap-2">
          <Btn
            variant="primary"
            onClick={() => mutation.mutate()}
            disabled={code.replace(/nw-/i, "").length < 4 || mutation.isPending}
            className="inline-flex items-center gap-2"
          >
            {mutation.isPending && <Loader2 size={14} className="animate-spin" />}
            {mutation.isPending ? "Linking…" : "Link device"}
          </Btn>
          <Link href="/app/cameras">
            <Btn>Cancel</Btn>
          </Link>
        </div>
      </div>
      <div className="text-[11.5px] text-[oklch(55%_0.01_265)] border-t border-[oklch(22%_0.015_265)] pt-3">
        The code is shown on your device&apos;s display or in its startup logs. It expires after
        10 minutes — restart the device to get a new one.
      </div>
    </Card>
  );
}

function DoneStep({ cameraId }: { cameraId: string | null }) {
  const router = useRouter();
  useEffect(() => {
    const t = setTimeout(() => {
      router.push(cameraId ? `/app/cameras/${cameraId}` : "/app/cameras");
    }, 1500);
    return () => clearTimeout(t);
  }, [cameraId, router]);

  return (
    <Card>
      <div className="flex flex-col items-center gap-3 py-6">
        <div className="h-12 w-12 rounded-full bg-[oklch(85%_0.16_84)]/15 border border-[oklch(85%_0.16_84)] flex items-center justify-center">
          <Check size={24} className="text-[oklch(85%_0.16_84)]" />
        </div>
        <div className="text-[13px] text-[oklch(97%_0.005_265)]">
          Camera connected. Taking you there…
        </div>
      </div>
    </Card>
  );
}
