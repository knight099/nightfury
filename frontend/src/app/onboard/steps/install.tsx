"use client";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

export function InstallStep({ onNext }: { onNext: () => void }) {
  const cmd = `docker run -d --name nightwatch-agent --restart=always \\
  --net=host \\
  -v nightwatch-agent-data:/var/lib/nightwatch-agent \\
  -e BACKEND_URL=${BACKEND_URL} \\
  ghcr.io/nightwatch/agent:latest`;

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">Install the Nightwatch Agent</h2>
      <p className="text-[#A3A3A3]">
        Run this on a device on the same network as your NVR (NAS / Router with
        Docker / Raspberry Pi):
      </p>
      <pre className="bg-[#0a0a0a] border border-[#2A2A2A] p-4 rounded overflow-x-auto text-sm">
        {cmd}
      </pre>
      <button
        onClick={() => navigator.clipboard.writeText(cmd)}
        className="px-4 py-2 bg-[#1a1a1a] border border-[#2A2A2A] rounded hover:bg-[#222] transition-colors"
      >
        Copy
      </button>
      <p className="text-sm text-[#A3A3A3]">
        Once running, open <code className="bg-[#1a1a1a] px-1 rounded">http://&lt;device-ip&gt;:8765</code> in your browser.
      </p>
      <div>
        <button
          onClick={onNext}
          className="px-6 py-2 bg-[#1E90FF] hover:bg-[#3BA0FF] text-white rounded transition-colors"
        >
          I&apos;ve installed it →
        </button>
      </div>
    </div>
  );
}
